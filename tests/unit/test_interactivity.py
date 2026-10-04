"""Unit tests for ``lunas.checks.interactivity``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.interactivity import (
    InteractivityCheck,
    count_inline_html_handlers,
    count_interactive_html,
    count_js_bindings,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = InteractivityCheck()
    assert layer.NAME == "interactivity"
    assert LayerKind.deterministic == layer.KIND


def test_counts_buttons(tmp_path):
    (tmp_path / "p.html").write_text("<button>A</button><button>B</button>")
    assert count_interactive_html([tmp_path / "p.html"]) == 2


def test_excludes_hidden_input(tmp_path):
    (tmp_path / "p.html").write_text(
        '<input type="text" /><input type="hidden" name="csrf">'
    )
    # 2 hits for <input, 1 hit for type="hidden" → net 1
    assert count_interactive_html([tmp_path / "p.html"]) == 1


def test_counts_js_bindings(tmp_path):
    (tmp_path / "a.js").write_text(
        "btn.addEventListener('click', f);"
        "el.onclick = g;"
        "document.addEventListener('DOMContentLoaded', init);"
    )
    # addEventListener (2 hits) + .onclick (1 hit) + DOMContentLoaded (1 hit) = 4
    assert count_js_bindings([tmp_path / "a.js"]) == 4


def test_inline_handlers(tmp_path):
    (tmp_path / "p.html").write_text(
        '<button onclick="go()">A</button>'
        '<form onsubmit="save()"></form>'
    )
    assert count_inline_html_handlers([tmp_path / "p.html"]) == 2


def test_layer_skipped_no_html_js_pair(tmp_path):
    (tmp_path / "only.html").write_text("<button>A</button>")
    layer = InteractivityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_skipped_no_interactive(tmp_path):
    (tmp_path / "p.html").write_text("<h1>Hello</h1><p>World</p>")
    (tmp_path / "a.js").write_text("console.log('hi')")
    layer = InteractivityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_passes_clean(tmp_path):
    (tmp_path / "p.html").write_text("<button id='go'>Go</button>")
    (tmp_path / "a.js").write_text(
        "document.getElementById('go').addEventListener('click', f);"
    )
    layer = InteractivityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.passed


def test_layer_fails_dead_ui(tmp_path):
    (tmp_path / "p.html").write_text(
        "<button>Click me</button><form><input /></form>"
    )
    (tmp_path / "a.js").write_text("console.log('initialized');")
    layer = InteractivityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["interactive_elements"] >= 2
    assert result.details["js_binding_hits"] == 0


def test_layer_passes_with_inline_handler(tmp_path):
    """Inline `onclick="…"` counts as wiring."""
    (tmp_path / "p.html").write_text(
        "<button onclick='go()'>Go</button>"
    )
    (tmp_path / "a.js").write_text("function go() { console.log('hi'); }")
    layer = InteractivityCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.passed
