"""Layer #18 — `npx tsc --noEmit` must pass when `tsconfig.json` exists.

The whole point of TypeScript is type checking. If a generated React/TS
project doesn't type-check, this is a hard failure, not a
green pass.

Strategy:

1. Skip cleanly when no ``tsconfig.json`` is present (vanilla JS,
   pre-init scaffold, etc.).
2. Patch ``tsconfig.json``'s ``exclude`` list to keep ``**/__tests__/**``
   and ``*.test.*`` / ``*.spec.*`` out of the production type check.
   Without this patch, test files using ``jest``/``vitest`` globals
   would fail with ``Cannot find name 'describe'`` even when the
   production code itself is fine.
3. Run ``npx tsc --noEmit`` via the sandboxed runner. Non-zero exit
   means the project does not type-check; fail with the stderr tail.
4. ``--noEmit`` is non-negotiable — we don't want type-checking to
   write artifacts into the user's directory.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from lunas.checks._tsconfig_repair import repair_root_tsconfig_file
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict
from lunas.subprocess_runner import run_cmd, scrub_env


def _npx_argv0() -> str:
    import platform
    return "npx.cmd" if platform.system() == "Windows" else "npx"


_TEST_EXCLUDES: tuple[str, ...] = (
    "**/__tests__/**",
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.ts",
    "**/*.spec.tsx",
)


def patch_tsconfig_excludes(tsconfig_path: Path) -> bool:
    """Add ``**/__tests__/**`` and ``*.test.*`` / ``*.spec.*`` patterns
    to ``tsconfig.json``'s ``exclude`` list if not already present.

    Returns ``True`` if the file was modified, ``False`` if no patch
    was needed or parsing failed. Failures are silent — the caller
    proceeds to run tsc regardless.
    """
    try:
        text = tsconfig_path.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        # `raw_decode` tolerates trailing prose after the JSON object (agent
        # output sometimes appends a note); a plain `json.loads` would raise
        # "Extra data" and skip the patch, shipping the malformed config.
        cfg, _ = json.JSONDecoder().raw_decode(text.lstrip())
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(cfg, dict):
        return False

    exclude = cfg.get("exclude") or []
    if not isinstance(exclude, list):
        return False
    if any("test" in e.lower() for e in exclude if isinstance(e, str)):
        return False

    cfg["exclude"] = list(exclude) + list(_TEST_EXCLUDES)
    try:
        tsconfig_path.write_text(
            json.dumps(cfg, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


class TscCheck(CheckLayer):
    """Layer #18 — `tsc --noEmit` type check (skip when no tsconfig.json)."""

    NAME = "tsc"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "Run `npx tsc --noEmit` when `tsconfig.json` exists. Patches "
        "the config to exclude test files (jest/vitest globals would "
        "otherwise fail the production type check)."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        tsconfig = root / "tsconfig.json"
        if not tsconfig.exists():
            return self._skip("No tsconfig.json at root")

        # Normalize a degenerate/pre-ES2015 config BEFORE running tsc, so a
        # phantom failure (TS2468 Promise, node_modules TS2583) from an unusable
        # config isn't reported as the user's type error. Then patch excludes.
        repaired = repair_root_tsconfig_file(root)
        patched = patch_tsconfig_excludes(tsconfig)
        npx = _npx_argv0()

        try:
            result = await run_cmd(
                [npx, "tsc", "--noEmit"],
                cwd=root,
                timeout=ctx.timeout_per_command,
                env={**scrub_env(), "CI": "true"},
            )
        except FileNotFoundError:
            return self._result(
                Verdict.failed,
                summary="`npx` not on PATH — cannot run tsc",
                start_time=start,
                details={"error": "npx_not_found", "tsconfig_patched": patched},
            )

        if result.timed_out:
            return self._result(
                Verdict.failed,
                summary="tsc type check timed out",
                start_time=start,
                details={
                    "tsconfig_patched": patched,
                    "timed_out": True,
                    "stdout_tail": result.stdout.strip()[-1000:],
                },
            )

        if result.returncode == 0:
            return self._result(
                Verdict.passed,
                summary="tsc --noEmit passed",
                start_time=start,
                details={
                    "tsconfig_patched": patched,
                    "tsconfig_repaired": repaired,
                    "duration_seconds": result.duration_seconds,
                },
            )

        return self._result(
            Verdict.failed,
            summary=f"tsc --noEmit failed (exit {result.returncode})",
            start_time=start,
            details={
                "tsconfig_patched": patched,
                "tsconfig_repaired": repaired,
                "exit_code": result.returncode,
                "stdout_tail": result.stdout.strip()[-2000:],
                "stderr_tail": result.stderr.strip()[-500:],
            },
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = ["TscCheck", "patch_tsconfig_excludes"]
