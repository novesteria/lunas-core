"""Layer #17 — `npm install` (or `npm ci`) must succeed.

For Node projects this is the most concrete signal that the
``package.json`` is at least cohesive enough to resolve all deps. If
``npm install`` fails — version conflicts, missing registry packages,
incompatible peer deps — the project cannot ship regardless of how
clean the static checks looked.

Strategy:

1. If ``package-lock.json`` exists, prefer ``npm ci --ignore-scripts``
   (faster, reproducible). Fall back to ``npm install --ignore-scripts``
   if ``npm ci`` exits non-zero.
2. ``--ignore-scripts`` is non-negotiable: an attacker-controlled
   ``preinstall``/``postinstall`` is the entire supply-chain attack
   surface this layer is supposed to neutralize.
3. Long-running by nature; honors ``ctx.timeout_per_command``.
4. Skipped when no ``package.json`` is present (not a Node project).
5. When ``npm`` isn't on PATH, returns a failure (not a skip) — the
   user explicitly asked to validate a Node project.
"""

from __future__ import annotations

import time

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict
from lunas.subprocess_runner import run_cmd, scrub_env


# Windows ships `npm` and `npx` as `.cmd` shims; pick the right one.
def _npm_argv0() -> str:
    import platform
    return "npm.cmd" if platform.system() == "Windows" else "npm"


class NpmInstallCheck(CheckLayer):
    """Layer #17 — `npm ci` (or `npm install`) on the project root."""

    NAME = "npm_install"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "Run `npm ci --ignore-scripts` (or `npm install --ignore-scripts` "
        "as fallback). A non-zero exit means the project cannot "
        "actually be installed; static checks alone are insufficient signal."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")
        if not (root / "package.json").exists():
            return self._skip("No package.json at root")

        npm = _npm_argv0()
        env = {**scrub_env(), "CI": "true"}
        timeout = ctx.timeout_per_command

        has_lock = (root / "package-lock.json").exists()
        # Recovery tiers, tried in order until one exits 0. `--ignore-scripts`
        # on EVERY tier (the supply-chain guard is non-negotiable). The final
        # `--legacy-peer-deps` tier is the last resort: npm 7+ hard-fails on
        # peer-dependency conflicts that older npm only warned about, and
        # agent-generated `package.json` files hit this constantly — without it
        # a resolvable project false-fails install.
        tiers: list[list[str]] = []
        if has_lock:
            tiers.append([npm, "ci", "--ignore-scripts"])
        tiers.append([npm, "install", "--ignore-scripts"])
        tiers.append([npm, "install", "--ignore-scripts", "--legacy-peer-deps"])

        last = None
        for i, argv in enumerate(tiers):
            try:
                last = await run_cmd(argv, cwd=root, timeout=timeout, env=env)
            except FileNotFoundError:
                if i == 0:
                    return self._result(
                        Verdict.failed,
                        summary="`npm` not on PATH — cannot run install",
                        start_time=start,
                        details={"error": "npm_not_found"},
                    )
                break
            if last.returncode == 0 and not last.timed_out:
                return self._result(
                    Verdict.passed,
                    summary=(
                        f"`{' '.join(argv[1:])}` succeeded"
                        + ("" if i == 0 else f" (tier {i + 1})")
                    ),
                    start_time=start,
                    details={
                        "command": argv,
                        "tier": i + 1,
                        "duration_seconds": last.duration_seconds,
                        "stdout_tail": last.stdout.strip()[-500:],
                    },
                )
            if last.timed_out:
                break  # a timeout won't clear on retry — don't burn more budget

        summary = (
            "npm install timed out"
            if last is not None and last.timed_out
            else (
                f"npm install failed (exit {last.returncode})"
                if last is not None
                else "npm install failed"
            )
        )
        return self._result(
            Verdict.failed,
            summary=summary,
            start_time=start,
            details={
                "tiers_tried": [t[1:] for t in tiers],
                "exit_code": last.returncode if last is not None else None,
                "timed_out": last.timed_out if last is not None else None,
                "stderr_tail": last.stderr.strip()[-2000:] if last is not None else "",
                "stdout_tail": last.stdout.strip()[-1000:] if last is not None else "",
            },
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = ["NpmInstallCheck"]
