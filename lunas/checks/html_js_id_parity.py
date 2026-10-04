"""Layer #14 — every #id the JS hooks into must exist in the HTML.

Catches the canonical vanilla-JS bug where the HTML and JS were
generated independently and picked different identifiers:

    <!-- index.html -->
    <button id="theme-switch">…</button>

    // app.js
    document.getElementById('theme-toggle').addEventListener(…)

Both files individually parse fine. ``getElementById`` returns
``null``. The button does nothing. The page renders, the user clicks,
nothing happens — and there's no clear error to grep for.

This layer flags every JS id reference (``getElementById('X')`` or
``querySelector('#X')``) that has no matching ``id="X"`` in any HTML
file. We deliberately do **not** flag the reverse direction (HTML
ids that the JS doesn't touch) because static elements (headings,
labels, anchor targets) commonly carry ids for CSS or fragment links
without needing JS.

Skip-clean when:

- There are no HTML files or no JS files (need both for parity).
- The JS uses no ``#id`` selectors at all (class/tag-based only).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_HTML_ID_RE = re.compile(r"""\bid\s*=\s*["']([A-Za-z][\w:.\-]*)["']""")
_GETBYID_RE = re.compile(
    r"""getElementById\s*\(\s*["']([A-Za-z][\w:.\-]*)["']"""
)
# `querySelector('#x')`, `querySelectorAll('.foo #x')`. The id token is
# anchored on the `#` immediately after the open quote OR any descendant
# combinator. We grab the first id token in the selector.
_QSEL_ID_RE = re.compile(
    r"""querySelector(?:All)?\s*\(\s*["'][^"']*?#([A-Za-z][\w:.\-]*)"""
)


def _is_static_html_source(root: Path, path: Path, exts: tuple[str, ...]) -> bool:
    if not path.is_file() or path.suffix.lower() not in exts:
        return False
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(part.startswith(".") or part == "node_modules" for part in rel_parts)


def _find_files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    return [p for p in root.rglob("*") if _is_static_html_source(root, p, exts)]


def collect_html_ids(html_files: list[Path]) -> set[str]:
    ids: set[str] = set()
    for h in html_files:
        try:
            text = h.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ids.update(_HTML_ID_RE.findall(text))
    return ids


def collect_js_id_refs(js_files: list[Path]) -> set[str]:
    refs: set[str] = set()
    for j in js_files:
        try:
            src = j.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        refs.update(_GETBYID_RE.findall(src))
        refs.update(_QSEL_ID_RE.findall(src))
    return refs


def collect_js_id_refs_with_provenance(
    root: Path, js_files: list[Path]
) -> dict[str, set[str]]:
    """Return a mapping ``{id: {rel_path, ...}}``.

    Differs from ``collect_js_id_refs`` only in that it records WHICH
    JS file referenced each id. Used by failure reporting + dispatch
    so a violation in ``tests/smoke.test.js`` is reported against the
    test file, while one in ``app.js`` is reported against the app file.
    """
    out: dict[str, set[str]] = {}
    for j in js_files:
        try:
            src = j.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        try:
            rel = j.relative_to(root).as_posix()
        except ValueError:
            rel = j.name
        local = set(_GETBYID_RE.findall(src)) | set(_QSEL_ID_RE.findall(src))
        for rid in local:
            out.setdefault(rid, set()).add(rel)
    return out


_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "__test__"}
_TEST_FILE_SUFFIXES = (
    ".test.js", ".test.mjs", ".test.cjs",
    ".test.jsx", ".test.tsx",
    ".spec.js", ".spec.mjs", ".spec.cjs",
    ".spec.jsx", ".spec.tsx",
)


def looks_like_test_file(rel_path: str) -> bool:
    """True for JS files written by a test/QA tooling convention.

    Recognizes ``tests/``, ``__tests__/``, ``spec/`` directories and
    ``*.test.*`` / ``*.spec.*`` suffixes (Jest, Mocha, Cypress).
    """
    parts = rel_path.replace("\\", "/").split("/")
    if any(p in _TEST_DIR_NAMES for p in parts):
        return True
    name = parts[-1]
    return any(name.endswith(s) for s in _TEST_FILE_SUFFIXES)


class HtmlJsIdParityCheck(CheckLayer):
    """Layer #14 — JS id references must exist in some HTML file."""

    NAME = "html_js_id_parity"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("static_html", "node")
    DESCRIPTION = (
        "Every #id the JS hooks into via getElementById / querySelector "
        "must exist in at least one HTML file. Catches the canonical "
        "'querySelector returns null, handler attached to phantom node' bug."
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

        html_ids = collect_html_ids(html_files)
        js_id_to_files = collect_js_id_refs_with_provenance(root, js_files)
        js_refs = set(js_id_to_files.keys())

        if not js_refs:
            return self._skip("JS uses no #id selectors (class/tag-based)")

        missing = sorted(js_refs - html_ids)
        if missing:
            # Bucket each missing id by the file that referenced it.
            # Consumers use these buckets to route fix-it work to
            # whoever owns the offending file.
            violating_test_files: dict[str, list[str]] = {}
            violating_app_files: dict[str, list[str]] = {}
            for mid in missing:
                for fpath in sorted(js_id_to_files.get(mid, set())):
                    bucket = (
                        violating_test_files
                        if looks_like_test_file(fpath)
                        else violating_app_files
                    )
                    bucket.setdefault(fpath, []).append(mid)
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(missing)} JS id reference(s) have no matching "
                    f"id in any HTML file"
                ),
                start_time=start,
                details={
                    "missing_ids": missing[:30],
                    "truncated_missing": len(missing) > 30,
                    "html_ids_sample": sorted(html_ids)[:25],
                    "html_files": len(html_files),
                    "js_files": len(js_files),
                    "violating_app_files": {
                        k: sorted(set(v)) for k, v in violating_app_files.items()
                    },
                    "violating_test_files": {
                        k: sorted(set(v)) for k, v in violating_test_files.items()
                    },
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All {len(js_refs)} JS id reference(s) match HTML id declarations"
            ),
            start_time=start,
            details={
                "html_ids_count": len(html_ids),
                "js_refs_count": len(js_refs),
                "html_files": len(html_files),
                "js_files": len(js_files),
            },
        )


__all__ = [
    "HtmlJsIdParityCheck",
    "collect_html_ids",
    "collect_js_id_refs",
    "collect_js_id_refs_with_provenance",
    "looks_like_test_file",
]
