"""Layer #15 — interactive HTML elements need at least one JS event handler.

Catches the "dead UI" failure mode: the agent generated a page full of
``<button>``s and ``<form>``s, but the accompanying JS never calls
``addEventListener`` or sets any ``onclick`` property. The page
renders, the user clicks, nothing happens. No error message — just
silent failure.

Rule:

1. Count interactive elements (``<button>``, ``<input>``, ``<select>``,
   ``<textarea>``, ``<form>``) across all HTML files. Subtract
   ``<input type="hidden">``.
2. If the count is zero, skip — there's nothing to wire up.
3. Otherwise, look for any binding signal in the JS:
   ``addEventListener``, ``.onclick``, ``.oninput``, ``DOMContentLoaded``,
   etc. Also count inline HTML ``onclick="…"`` / ``onsubmit="…"``.
4. If both counts are nonzero, pass. If the HTML wants interactivity
   and the JS+inline-HTML provide none, fail.

Skip-clean when there are no HTML+JS pairs (Python projects, pure
backends, etc.).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_INTERACTIVE_RE = re.compile(
    r"<(button|input|select|textarea|form)\b", re.IGNORECASE
)
_HIDDEN_INPUT_RE = re.compile(
    r"""<input\b[^>]*\btype\s*=\s*["']hidden["']""", re.IGNORECASE
)
_INLINE_HANDLER_RE = re.compile(
    r"\bon(click|change|input|submit|keydown|keyup|keypress|load)\s*=",
    re.IGNORECASE,
)


# Substrings (not regexes) we look for in JS source to count event-binding
# usages. Kept as plain substrings because they're cheap and any false
# positive is fine — we just want SOME signal that JS does interactivity.
_JS_BINDING_SIGNALS: tuple[str, ...] = (
    "addEventListener",
    ".onclick",
    ".onchange",
    ".oninput",
    ".onsubmit",
    ".onkeydown",
    ".onkeyup",
    ".onkeypress",
    "window.onload",
    "document.onload",
    "DOMContentLoaded",
)


def _is_source(root: Path, path: Path, exts: tuple[str, ...]) -> bool:
    if not path.is_file() or path.suffix.lower() not in exts:
        return False
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(part.startswith(".") or part == "node_modules" for part in rel_parts)


def _find_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    return [p for p in root.rglob("*") if _is_source(root, p, exts)]


def count_interactive_html(html_files: list[Path]) -> int:
    total = 0
    for h in html_files:
        try:
            text = h.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        all_hits = len(_INTERACTIVE_RE.findall(text))
        hidden_hits = len(_HIDDEN_INPUT_RE.findall(text))
        total += max(0, all_hits - hidden_hits)
    return total


def count_js_bindings(js_files: list[Path]) -> int:
    total = 0
    for j in js_files:
        try:
            text = j.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for sig in _JS_BINDING_SIGNALS:
            total += text.count(sig)
    return total


def count_inline_html_handlers(html_files: list[Path]) -> int:
    total = 0
    for h in html_files:
        try:
            text = h.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        total += len(_INLINE_HANDLER_RE.findall(text))
    return total


class InteractivityCheck(CheckLayer):
    """Layer #15 — interactive HTML needs at least one JS event handler."""

    NAME = "interactivity"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("static_html", "node")
    DESCRIPTION = (
        "When the HTML declares interactive elements "
        "(button/input/select/textarea/form), the JS or inline HTML "
        "must provide at least one event handler. Catches the 'page "
        "renders but nothing responds' failure mode."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        html_files = _find_files(root, (".html", ".htm"))
        js_files = _find_files(root, (".js", ".mjs", ".cjs"))
        if not html_files or not js_files:
            return self._skip("No HTML+JS pair in input")

        interactive = count_interactive_html(html_files)
        if interactive == 0:
            return self._skip(
                "HTML has no interactive elements — nothing to wire up"
            )

        js_hits = count_js_bindings(js_files)
        inline_hits = count_inline_html_handlers(html_files)
        total_bindings = js_hits + inline_hits

        if total_bindings == 0:
            return self._result(
                Verdict.failed,
                summary=(
                    f"HTML has {interactive} interactive element(s) but "
                    f"no event handlers found in JS or inline HTML — page "
                    f"will be unresponsive"
                ),
                start_time=start,
                details={
                    "interactive_elements": interactive,
                    "js_binding_hits": js_hits,
                    "inline_html_handler_hits": inline_hits,
                    "html_files": len(html_files),
                    "js_files": len(js_files),
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"{interactive} interactive element(s) in HTML, "
                f"{total_bindings} event binding(s) in JS/HTML"
            ),
            start_time=start,
            details={
                "interactive_elements": interactive,
                "js_binding_hits": js_hits,
                "inline_html_handler_hits": inline_hits,
            },
        )


__all__ = [
    "InteractivityCheck",
    "count_interactive_html",
    "count_js_bindings",
    "count_inline_html_handlers",
]
