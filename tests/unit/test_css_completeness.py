"""Unit tests for ``lunas.checks.css_completeness``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.css_completeness import (
    CssCompletenessCheck,
    find_css_stubs,
    is_css_stub,
)
from lunas.result import LayerKind, Verdict

# ----- is_css_stub pure function -------------------------------------------


def test_stub_generated_css_comment():
    assert is_css_stub("/* Generated CSS */")


def test_stub_empty_file():
    assert is_css_stub("")


def test_stub_only_comments():
    assert is_css_stub("/* placeholder */\n/* todo */\n")


def test_real_rule_not_stub():
    assert not is_css_stub("body { margin: 0; }")


def test_tailwind_directive_not_stub():
    assert not is_css_stub("@tailwind base;\n@tailwind utilities;\n")


def test_import_directive_not_stub():
    assert not is_css_stub('@import "./tokens.css";\n')


def test_keyframes_not_stub():
    assert not is_css_stub("@keyframes fade { from { opacity: 0 } }")


def test_custom_properties_not_stub():
    assert not is_css_stub(":root { --primary: #1a3d2e; }")


def test_large_file_never_stub():
    # 250 bytes of "real" content with no rules — still not flagged
    # because it's over the size limit.
    body = "x" * 250
    assert not is_css_stub(body)


# ----- find_css_stubs ------------------------------------------------------


def test_find_stubs_mixed(tmp_path):
    (tmp_path / "stub.css").write_text("/* Generated CSS */")
    (tmp_path / "real.css").write_text("body { color: red; }")
    stubs, scanned = find_css_stubs(tmp_path)
    assert scanned == 2
    assert len(stubs) == 1
    assert stubs[0].path == "stub.css"
    assert stubs[0].raw_size > 0


def test_skips_node_modules(tmp_path):
    (tmp_path / "real.css").write_text("body { color: red; }")
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "leaky.css").write_text("/* stub */")
    stubs, scanned = find_css_stubs(tmp_path)
    assert scanned == 1
    assert stubs == []


# ----- Full layer ----------------------------------------------------------


def test_layer_metadata():
    layer = CssCompletenessCheck()
    assert layer.NAME == "css_completeness"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO
    assert "static_html" in layer.APPLIES_TO


def test_layer_skipped_when_no_css(tmp_path):
    layer = CssCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped


def test_layer_passes_real_css(tmp_path):
    (tmp_path / "app.css").write_text("body { margin: 0; padding: 0; }")
    layer = CssCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_fails_stub_css(tmp_path):
    (tmp_path / "design-system.css").write_text("/* Generated CSS */")
    layer = CssCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["stubs"][0]["path"] == "design-system.css"


def test_layer_passes_tailwind_entry(tmp_path):
    """Small file with only @tailwind directives is legitimate."""
    (tmp_path / "index.css").write_text(
        "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"
    )
    layer = CssCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_passes_tokens_file(tmp_path):
    """Custom-property-only token file is legitimate."""
    (tmp_path / "tokens.css").write_text(
        ":root {\n  --primary: #1a3d2e;\n  --accent: #d4af37;\n}\n"
    )
    layer = CssCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
