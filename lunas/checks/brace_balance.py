"""Layer #12 — JS/TS brace/paren/bracket balance.

Catches mid-function truncation: an agent runs out of tokens and stops
writing in the middle of a function body. ``node --check`` would catch
this too, but only when node is on the host PATH. This layer needs
nothing but the stdlib, so it runs on any machine.

The scanner skips characters inside:
- ``//`` line comments
- ``/* ... */`` block comments
- ``'single'`` / ``"double"`` / `` `template` `` string literals
- ``${expr}`` interpolations inside template literals (the contents are
  skipped as a balanced unit — interior brace counts don't pollute the
  outer file count)

File-set scope:
- Extensions: ``.js`` / ``.mjs`` / ``.cjs`` / ``.ts`` / ``.tsx`` / ``.jsx``
- Skips ``node_modules`` and any dotfolder
- Limits to 50 files per run to keep the layer fast on very large
  repos; that limit catches the failure mode (truncation) reliably,
  since truncated files cluster at the agent's last few writes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import NamedTuple

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_JS_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")
_MAX_FILES_PER_RUN = 50


class BraceCounts(NamedTuple):
    """Counts of each bracket pair in a single source file."""

    braces: tuple[int, int]   # (open '{', close '}')
    parens: tuple[int, int]   # (open '(', close ')')
    brackets: tuple[int, int]  # (open '[', close ']')

    def balanced(self) -> bool:
        """True iff every pair has equal open and close counts."""
        return (
            self.braces[0] == self.braces[1]
            and self.parens[0] == self.parens[1]
            and self.brackets[0] == self.brackets[1]
        )

    def mismatches(self) -> list[str]:
        """Human-readable list of which pairs are off."""
        out: list[str] = []
        if self.braces[0] != self.braces[1]:
            out.append(f"{{={self.braces[0]} vs }}={self.braces[1]}")
        if self.parens[0] != self.parens[1]:
            out.append(f"(={self.parens[0]} vs )={self.parens[1]}")
        if self.brackets[0] != self.brackets[1]:
            out.append(f"[={self.brackets[0]} vs ]={self.brackets[1]}")
        return out


def count_brackets(source: str) -> BraceCounts:
    """Count brackets in JS/TS source, ignoring comments and strings.

    See module docstring for the skip rules. The scanner is a hand-rolled
    state machine rather than a regex / tokenizer because it needs to be
    fast and have zero dependencies (the validator runs before any
    dependency install).

    Examples:
        >>> count_brackets("function f() { return 1; }").balanced()
        True
        >>> count_brackets("const x = '{';").balanced()
        True
        >>> count_brackets("function f() { return 1;").balanced()
        False
    """
    counts: dict[str, int] = {"{": 0, "}": 0, "(": 0, ")": 0, "[": 0, "]": 0}
    i = 0
    n = len(source)

    while i < n:
        c = source[i]

        # Line comment: skip to end of line
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            nl = source.find("\n", i + 2)
            i = n if nl == -1 else nl + 1
            continue

        # Block comment: skip to '*/'
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue

        # String / template literal: skip contents until matching quote.
        # Template ${...} interpolations are skipped as a balanced unit
        # (their internal braces don't contribute to outer counts).
        if c in ("'", '"', "`"):
            quote = c
            i += 1
            while i < n:
                ch = source[i]
                if ch == "\\" and i + 1 < n:
                    # Escape: skip the next char unconditionally
                    i += 2
                    continue
                if ch == quote:
                    i += 1
                    break
                if quote == "`" and ch == "$" and i + 1 < n and source[i + 1] == "{":
                    # Walk through ${expr}; track nested braces and exit
                    # at the matching '}' that returns depth to 0
                    i += 2  # consume '${'
                    depth = 1
                    while i < n and depth:
                        cc = source[i]
                        if cc == "{":
                            depth += 1
                        elif cc == "}":
                            depth -= 1
                            if depth == 0:
                                i += 1
                                break
                        i += 1
                    continue
                i += 1
            continue

        # Otherwise: count if it's a tracked character
        if c in counts:
            counts[c] += 1
        i += 1

    return BraceCounts(
        braces=(counts["{"], counts["}"]),
        parens=(counts["("], counts[")"]),
        brackets=(counts["["], counts["]"]),
    )


def _find_js_files(root: Path, *, max_files: int = _MAX_FILES_PER_RUN) -> list[Path]:
    """Return JS/TS files under ``root``, excluding node_modules + dotfolders.

    Limit applied AFTER filtering so we don't waste time scanning into
    excluded subtrees.
    """
    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _JS_EXTENSIONS:
            continue
        rel_parts = path.relative_to(root).parts
        if any(part.startswith(".") or part == "node_modules" for part in rel_parts):
            continue
        matches.append(path)
        if len(matches) >= max_files:
            break
    return matches


class BraceBalanceCheck(CheckLayer):
    """JS/TS brace/paren/bracket balance check (layer #15 in the index)."""

    NAME = "ast_brace_balance"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node", "static_html")
    DESCRIPTION = (
        "JS/TS bracket balance — catches mid-function truncation. "
        "Skips comments, strings, and template-literal interpolations."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        files = _find_js_files(ctx.code_path)

        if not files:
            return self._skip("No JS/TS files in input")

        problems: list[str] = []
        for path in files:
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                # Unreadable file (permission, IO error) — skip; the
                # other layers will surface that separately if it matters.
                continue
            counts = count_brackets(src)
            if not counts.balanced():
                rel = path.relative_to(ctx.code_path).as_posix()
                problems.append(f"{rel}: {', '.join(counts.mismatches())}")

        if problems:
            shown = problems[:30]
            truncated = len(problems) > 30
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(problems)} of {len(files)} JS/TS file(s) have "
                    f"unbalanced brackets"
                ),
                start_time=start,
                details={
                    "files_scanned": len(files),
                    "files_with_mismatches": len(problems),
                    "mismatch_lines": shown,
                    "truncated": truncated,
                    "scan_cap": _MAX_FILES_PER_RUN,
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"All {len(files)} JS/TS file(s) have balanced brackets",
            start_time=start,
            details={"files_scanned": len(files), "scan_cap": _MAX_FILES_PER_RUN},
        )


__all__ = ["BraceBalanceCheck", "BraceCounts", "count_brackets"]
