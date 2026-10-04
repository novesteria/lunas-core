"""Layer #16 — `node --check` syntax verification, with Python fallback.

Catches syntactically invalid JS that the file-text checks miss:
mismatched template literals, ``await`` outside async functions,
trailing prose appended by a code-generation agent ("Summary of fixes: …"),
chunk-truncated functions that happen to close their braces.

Strategy:

1. Run ``node --check <file>`` per JS file (up to 50 files to keep
   bounded). First failure does not abort; we collect all error
   output for the report.
2. If ``node`` isn't on ``PATH``, fall back to a **pure-Python static
   check** that targets a real-world failure mode: a code-generation
   agent appended a natural-language explanation
   ("Summary of fixes:\\n- …") AFTER the IIFE closing ``})();``. The
   file would crash at runtime with ``SyntaxError: Unexpected token``,
   but ``node --check`` was previously skipped and the broken file
   landed with a green report.

The Python fallback is NON-optional: Python is always available, and a
fail there means a real bug must not be silently green-lit.
"""

from __future__ import annotations

import time
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict
from lunas.subprocess_runner import run_cmd, scrub_env

# Match what node --check accepts (no .ts — those go through tsc).
_JS_EXTS: tuple[str, ...] = (".js", ".mjs", ".cjs")
# How many files to check per run. node --check is one file per
# invocation, so this directly caps wall-clock cost.
_FILE_LIMIT = 50


def _is_js_source(root: Path, p: Path) -> bool:
    if not p.is_file() or p.suffix.lower() not in _JS_EXTS:
        return False
    try:
        rel_parts = p.relative_to(root).parts
    except ValueError:
        return False
    return not any(part.startswith(".") or part == "node_modules" for part in rel_parts)


def find_js_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if _is_js_source(root, p)]


def python_js_fallback(js_files: list[Path], root: Path) -> list[str]:
    """Pure-Python static check: look for trailing prose after the last
    line of recognisable JS code.

    Returns a list of human-readable problem descriptions. Empty list
    means "no contamination found".
    """
    failed: list[str] = []
    code_endings = (";", "}", ")", ",", "{", "]", "*/")
    for js in js_files[:_FILE_LIMIT]:
        try:
            src = js.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            failed.append(
                f"{js.relative_to(root).as_posix()}: read failed "
                f"({type(e).__name__})"
            )
            continue

        lines = src.split("\n")
        tail_idx = len(lines) - 1
        while tail_idx >= 0 and not lines[tail_idx].strip():
            tail_idx -= 1
        if tail_idx < 0:
            continue

        last_code = -1
        for i in range(tail_idx, -1, -1):
            stripped = lines[i].rstrip()
            if not stripped:
                continue
            if stripped.endswith(code_endings):
                last_code = i
                break
            if stripped.lstrip().startswith(("//", "/*", "*")):
                last_code = i
                break
        if last_code < 0:
            continue

        offenders: list[str] = []
        for j in range(last_code + 1, tail_idx + 1):
            ln = lines[j].strip()
            if not ln:
                continue
            is_markdown = (
                ln.startswith(("- ", "* ", "+ ", "## ", "### ", "#### ",
                               "**", "> "))
                or (len(ln) > 2 and ln[0].isdigit() and ln[1:3] in (". ", ") "))
            )
            is_sentence = (
                ln[0].isupper()
                and " " in ln
                and ln.endswith((".", "!", "?", ":"))
                and not ln.startswith((
                    "//", "/*", "function ", "class ",
                    "const ", "let ", "var ", "export ",
                    "import ", "return ", "if ", "for ",
                    "while ", "switch ",
                ))
            )
            if is_markdown or is_sentence:
                offenders.append(f"  L{j + 1}: {ln[:80]}")

        if offenders:
            failed.append(
                f"{js.relative_to(root).as_posix()}: trailing prose after "
                f"last code line (L{last_code + 1}):\n" + "\n".join(offenders)
            )

    return failed


class JsSyntaxCheck(CheckLayer):
    """Layer #16 — `node --check` over every JS file (Python fallback if no node)."""

    NAME = "js_syntax"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("static_html", "node")
    DESCRIPTION = (
        "Run `node --check` on every JS file. When `node` isn't on PATH, "
        "fall back to a Python static check for trailing-prose contamination "
        "(the canonical 'agent appended Markdown after })();' bug)."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        js_files = find_js_files(root)
        if not js_files:
            return self._skip("No JS files in input")

        env = {**scrub_env(), "CI": "true"}
        failed: list[str] = []
        used_fallback = False

        for js in js_files[:_FILE_LIMIT]:
            try:
                result = await run_cmd(
                    ["node", "--check", str(js)],
                    cwd=root,
                    timeout=min(30, ctx.timeout_per_command),
                    env=env,
                )
            except FileNotFoundError:
                # node not on PATH — bail to the Python fallback.
                used_fallback = True
                break
            if result.timed_out:
                failed.append(
                    f"{js.relative_to(root).as_posix()}: timeout"
                )
                continue
            if result.returncode != 0:
                failed.append(
                    f"{js.relative_to(root).as_posix()}: "
                    f"{(result.stderr or result.stdout).strip()[:200]}"
                )

        if used_fallback:
            fallback_failures = python_js_fallback(js_files, root)
            if fallback_failures:
                return self._result(
                    Verdict.failed,
                    summary=(
                        f"node not on PATH — Python fallback found trailing-prose "
                        f"contamination in {len(fallback_failures)} file(s)"
                    ),
                    start_time=start,
                    details={
                        "fallback": True,
                        "file_count": len(js_files),
                        "failures": fallback_failures[:30],
                        "truncated": len(fallback_failures) > 30,
                    },
                )
            return self._result(
                Verdict.passed,
                summary=(
                    f"node not on PATH — Python fallback scanned "
                    f"{len(js_files)} file(s); no trailing-prose contamination"
                ),
                start_time=start,
                details={"fallback": True, "file_count": len(js_files)},
            )

        if failed:
            return self._result(
                Verdict.failed,
                summary=f"{len(failed)} JS file(s) failed `node --check`",
                start_time=start,
                details={
                    "fallback": False,
                    "file_count": len(js_files),
                    "failures": failed[:30],
                    "truncated": len(failed) > 30,
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"node --check passed for {len(js_files)} file(s)",
            start_time=start,
            details={"fallback": False, "file_count": len(js_files)},
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = [
    "JsSyntaxCheck",
    "find_js_files",
    "python_js_fallback",
]
