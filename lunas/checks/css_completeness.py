"""Layer #6 — CSS files must contain real content, not just a stub comment.

UX/frontend agents that fall back to ``/* Generated CSS */`` when the
LLM response had no CSS block ship a 19-byte file. The README still
says "see design/design-system.css"; users open the file and find
nothing useful. This layer catches the empty placeholder *before* it
gets handed off.

Rule:

A CSS file is a stub when **all** of the following hold:

- < 200 bytes after stripping ``/* … */`` comments.
- No ``{ … }`` rule block.
- No directive among ``@tailwind``, ``@import``, ``@media``,
  ``@keyframes``, ``@font-face``, ``@supports``, ``@layer``,
  ``@charset``.
- No ``:root { --x: … }`` custom-property declaration.

This lets through legitimate small CSS files:

- Tailwind entry files with just ``@tailwind base/components/utilities``.
- Token files using only ``:root { --x: y }`` custom properties.
- Single-rule reset files.

Skip-clean when there are no ``.css`` files at all.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_COMMENT_RE = re.compile(r"/\*[\s\S]*?\*/", re.MULTILINE)
_RULE_RE = re.compile(r"\{[\s\S]*?\}")
_DIRECTIVE_RE = re.compile(
    r"@(tailwind|import|media|keyframes|font-face|supports|layer|charset)\b"
)
_CUSTOM_PROP_RE = re.compile(r":\s*root\s*\{[\s\S]*?--\w+\s*:")


# Stub-detection size ceiling. Below this and lacking any real
# structure, the file is treated as a placeholder.
_STUB_SIZE_LIMIT_BYTES = 200


@dataclass(frozen=True)
class CssStub:
    """A CSS file that looks like a placeholder rather than real styles."""

    path: str
    """Relative file path from the scan root."""

    raw_size: int
    """Raw byte count of the file."""

    stripped_size: int
    """Byte count after stripping ``/* … */`` comments."""


_CSS_SKIP_DIRS: frozenset[str] = frozenset(["node_modules", "dist", "build", "coverage"])


def _find_css_files(scan_root: Path) -> list[Path]:
    """Return all .css files under ``scan_root``, skipping hidden dirs and
    build output. Scanning ``dist``/``build`` would judge minified/compiled CSS
    and ``coverage`` would judge report CSS — both are false-positive sources.
    """
    out: list[Path] = []
    for p in scan_root.rglob("*.css"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(scan_root).parts
        if any(part.startswith(".") or part in _CSS_SKIP_DIRS for part in rel_parts):
            continue
        out.append(p)
    return out


def is_css_stub(source: str) -> bool:
    """Return True if ``source`` looks like a placeholder CSS file.

    Pure function — useful for unit tests and for layers that want to
    flag a single file without walking a tree.
    """
    stripped = _COMMENT_RE.sub("", source).strip()
    if len(stripped) >= _STUB_SIZE_LIMIT_BYTES:
        return False
    if _RULE_RE.search(stripped):
        return False
    if _DIRECTIVE_RE.search(stripped):
        return False
    # custom-prop regex must match the ORIGINAL source so we don't
    # accidentally strip the rule's braces along with comments.
    return not _CUSTOM_PROP_RE.search(source)


def find_css_stubs(root: Path) -> tuple[list[CssStub], int]:
    """Walk ``root`` and return (stubs, files_scanned)."""
    css_files = _find_css_files(root)
    stubs: list[CssStub] = []
    scanned = 0
    for p in css_files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        if is_css_stub(text):
            stripped = _COMMENT_RE.sub("", text).strip()
            stubs.append(CssStub(
                path=p.relative_to(root).as_posix(),
                raw_size=len(text),
                stripped_size=len(stripped),
            ))
    return stubs, scanned


class CssCompletenessCheck(CheckLayer):
    """Layer #6 — CSS files must contain real rules, directives, or
    custom properties."""

    NAME = "css_completeness"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node", "static_html")
    DESCRIPTION = (
        "CSS files must contain real content (a rule, a directive, or "
        "custom properties). Catches the UX-agent failure mode where "
        "the generated file is just a `/* Generated CSS */` placeholder."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        css_files = _find_css_files(root)
        if not css_files:
            return self._skip("No CSS files in input")

        stubs, scanned = find_css_stubs(root)

        if stubs:
            shown = stubs[:30]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(stubs)} CSS file(s) appear to be stub placeholders "
                    f"(of {scanned} scanned)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "stubs": [
                        {
                            "path": s.path,
                            "raw_size": s.raw_size,
                            "stripped_size": s.stripped_size,
                        }
                        for s in shown
                    ],
                    "truncated": len(stubs) > 30,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All {scanned} CSS file(s) contain real rules, directives, "
                f"or custom properties"
            ),
            start_time=start,
            details={"files_scanned": scanned},
        )


__all__ = [
    "CssCompletenessCheck",
    "CssStub",
    "is_css_stub",
    "find_css_stubs",
]
