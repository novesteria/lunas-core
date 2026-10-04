"""Unit tests for ``lunas.checks.js_syntax``."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from lunas.checks.base import ValidationContext
from lunas.checks.js_syntax import (
    JsSyntaxCheck,
    find_js_files,
    python_js_fallback,
)
from lunas.result import LayerKind, Verdict
from lunas.subprocess_runner import CmdResult


def test_layer_metadata():
    layer = JsSyntaxCheck()
    assert layer.NAME == "js_syntax"
    assert LayerKind.deterministic == layer.KIND


def test_find_js_files_skips_node_modules(tmp_path):
    (tmp_path / "a.js").write_text("//")
    nm = tmp_path / "node_modules" / "lib"
    nm.mkdir(parents=True)
    (nm / "b.js").write_text("//")
    files = find_js_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "a.js"


# ----- python_js_fallback pure -----------------------------------------


def test_fallback_passes_clean_js(tmp_path):
    (tmp_path / "a.js").write_text(
        "(function(){\n"
        "  console.log('hi');\n"
        "})();\n"
    )
    failed = python_js_fallback([tmp_path / "a.js"], tmp_path)
    assert failed == []


def test_fallback_catches_trailing_markdown(tmp_path):
    """Canonical trailing-markdown bug: agent appended markdown after `})();`."""
    (tmp_path / "a.js").write_text(
        "(function(){\n"
        "  console.log('hi');\n"
        "})();\n"
        "\n"
        "Summary of fixes:\n"
        "- Path fix: Updated reference.\n"
        "- **Bold** marker line.\n"
    )
    failed = python_js_fallback([tmp_path / "a.js"], tmp_path)
    assert len(failed) == 1
    assert "trailing prose" in failed[0]


def test_fallback_catches_numbered_list(tmp_path):
    (tmp_path / "a.js").write_text(
        "const x = 1;\n"
        "\n"
        "1. First change.\n"
    )
    failed = python_js_fallback([tmp_path / "a.js"], tmp_path)
    assert len(failed) == 1


def test_fallback_passes_trailing_comment(tmp_path):
    """A trailing `// note` block is fine — it's still code."""
    (tmp_path / "a.js").write_text(
        "const x = 1;\n"
        "// trailing comment about x\n"
    )
    failed = python_js_fallback([tmp_path / "a.js"], tmp_path)
    assert failed == []


# ----- Full layer (with mocked run_cmd) --------------------------------


async def _stub_cmd_ok(*a, **kw):
    return CmdResult(
        returncode=0, stdout="", stderr="",
        duration_seconds=0.01, timed_out=False,
    )


async def _stub_cmd_fail(*a, **kw):
    return CmdResult(
        returncode=1, stdout="",
        stderr="SyntaxError: Unexpected token",
        duration_seconds=0.01, timed_out=False,
    )


async def _stub_cmd_node_missing(*a, **kw):
    raise FileNotFoundError("node")


def test_layer_passes_when_node_check_ok(tmp_path):
    (tmp_path / "a.js").write_text("console.log('ok');\n")
    layer = JsSyntaxCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    with patch("lunas.checks.js_syntax.run_cmd", side_effect=_stub_cmd_ok):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["fallback"] is False


def test_layer_fails_when_node_check_errors(tmp_path):
    (tmp_path / "a.js").write_text("def x(): pass\n")
    layer = JsSyntaxCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    with patch("lunas.checks.js_syntax.run_cmd", side_effect=_stub_cmd_fail):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert "SyntaxError" in result.details["failures"][0]


def test_layer_falls_back_when_node_missing(tmp_path):
    (tmp_path / "a.js").write_text("const x = 1;\n")
    layer = JsSyntaxCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    with patch("lunas.checks.js_syntax.run_cmd", side_effect=_stub_cmd_node_missing):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["fallback"] is True


def test_layer_fallback_fails_on_trailing_prose(tmp_path):
    (tmp_path / "a.js").write_text(
        "const x = 1;\n\nSummary of fixes:\n- Did stuff.\n"
    )
    layer = JsSyntaxCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    with patch("lunas.checks.js_syntax.run_cmd", side_effect=_stub_cmd_node_missing):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["fallback"] is True


def test_layer_skipped_when_no_js(tmp_path):
    layer = JsSyntaxCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.skipped
