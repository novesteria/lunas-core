"""Unit tests for ``lunas.checks.tsc``."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from lunas.checks.base import ValidationContext
from lunas.checks.tsc import TscCheck, patch_tsconfig_excludes
from lunas.result import LayerKind, Verdict
from lunas.subprocess_runner import CmdResult


def _ok():
    return CmdResult(returncode=0, stdout="", stderr="",
                     duration_seconds=3.0, timed_out=False)


def _fail():
    return CmdResult(
        returncode=2,
        stdout="src/x.ts:1:5 - error TS2304: Cannot find name 'foo'.",
        stderr="",
        duration_seconds=3.0,
        timed_out=False,
    )


# ----- patch_tsconfig_excludes pure -----------------------------------


def test_patch_adds_test_excludes(tmp_path):
    cfg_path = tmp_path / "tsconfig.json"
    cfg_path.write_text(json.dumps({"compilerOptions": {}}))
    assert patch_tsconfig_excludes(cfg_path) is True
    cfg = json.loads(cfg_path.read_text())
    assert any("__tests__" in e for e in cfg["exclude"])
    assert any("test.tsx" in e for e in cfg["exclude"])


def test_patch_skips_when_test_already_excluded(tmp_path):
    cfg_path = tmp_path / "tsconfig.json"
    cfg_path.write_text(json.dumps({
        "compilerOptions": {},
        "exclude": ["**/*.test.ts"],
    }))
    assert patch_tsconfig_excludes(cfg_path) is False


def test_patch_returns_false_on_invalid_json(tmp_path):
    cfg_path = tmp_path / "tsconfig.json"
    cfg_path.write_text("{ not valid json")
    assert patch_tsconfig_excludes(cfg_path) is False


# ----- Full layer (mocked run_cmd) -------------------------------------


def test_layer_metadata():
    layer = TscCheck()
    assert layer.NAME == "tsc"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_layer_skipped_when_no_tsconfig(tmp_path):
    layer = TscCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_layer_passes_when_tsc_ok(tmp_path):
    (tmp_path / "tsconfig.json").write_text(json.dumps({"compilerOptions": {}}))

    async def mock_run(*a, **kw):
        return _ok()

    layer = TscCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.tsc.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["tsconfig_patched"] is True


def test_layer_fails_when_tsc_errors(tmp_path):
    (tmp_path / "tsconfig.json").write_text(json.dumps({"compilerOptions": {}}))

    async def mock_run(*a, **kw):
        return _fail()

    layer = TscCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.tsc.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert "TS2304" in result.details["stdout_tail"]


def test_layer_fails_when_npx_missing(tmp_path):
    (tmp_path / "tsconfig.json").write_text(json.dumps({"compilerOptions": {}}))

    async def mock_run(*a, **kw):
        raise FileNotFoundError("npx")

    layer = TscCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.tsc.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["error"] == "npx_not_found"
