"""Unit tests for ``lunas.checks.html_js_id_parity``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.html_js_id_parity import (
    HtmlJsIdParityCheck,
    collect_html_ids,
    collect_js_id_refs,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = HtmlJsIdParityCheck()
    assert layer.NAME == "html_js_id_parity"
    assert LayerKind.deterministic == layer.KIND
    assert "static_html" in layer.APPLIES_TO


def test_collect_html_ids(tmp_path):
    (tmp_path / "page.html").write_text(
        "<button id=\"submit\">Go</button>"
        "<div id='theme-switch'></div>"
    )
    ids = collect_html_ids([tmp_path / "page.html"])
    assert ids == {"submit", "theme-switch"}


def test_collect_js_id_refs(tmp_path):
    (tmp_path / "app.js").write_text(
        "document.getElementById('submit');"
        "document.querySelector('#theme-toggle');"
        "document.querySelectorAll('.foo #inner');"
    )
    refs = collect_js_id_refs([tmp_path / "app.js"])
    assert refs == {"submit", "theme-toggle", "inner"}


def test_layer_skipped_no_html(tmp_path):
    (tmp_path / "app.js").write_text("document.getElementById('x')")
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_skipped_no_js(tmp_path):
    (tmp_path / "page.html").write_text("<div id='x'></div>")
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_skipped_no_id_selectors(tmp_path):
    """JS uses no #id selectors → skip."""
    (tmp_path / "page.html").write_text("<button>Go</button>")
    (tmp_path / "app.js").write_text("document.querySelector('.foo');")
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_passes_clean(tmp_path):
    (tmp_path / "page.html").write_text(
        "<button id=\"submit\">Go</button>"
    )
    (tmp_path / "app.js").write_text(
        "document.getElementById('submit').addEventListener('click', () => {});"
    )
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.passed


def test_layer_fails_on_phantom_id(tmp_path):
    """Canonical bug: JS targets `#theme-toggle`, HTML has `#theme-switch`."""
    (tmp_path / "page.html").write_text(
        "<button id=\"theme-switch\">Switch</button>"
    )
    (tmp_path / "app.js").write_text(
        "document.getElementById('theme-toggle').addEventListener('click', f);"
    )
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert "theme-toggle" in result.details["missing_ids"]


def test_query_selector_id_form(tmp_path):
    """`querySelector('#id')` is also tracked."""
    (tmp_path / "page.html").write_text("<div id='real'></div>")
    (tmp_path / "app.js").write_text(
        "const el = document.querySelector('#fake');"
    )
    layer = HtmlJsIdParityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert "fake" in result.details["missing_ids"]
