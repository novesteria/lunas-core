"""Unit tests for ``lunas.checks.npm_install``."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from lunas.checks.base import ValidationContext
from lunas.checks.npm_install import NpmInstallCheck
from lunas.result import LayerKind, Verdict
from lunas.subprocess_runner import CmdResult


def _ok():
    return CmdResult(
        returncode=0, stdout="added 100 packages",
        stderr="", duration_seconds=2.5, timed_out=False,
    )


def _fail(stderr="npm ERR! peer dep conflict"):
    return CmdResult(
        returncode=1, stdout="", stderr=stderr,
        duration_seconds=2.5, timed_out=False,
    )


def _timeout():
    return CmdResult(
        returncode=-1, stdout="", stderr="",
        duration_seconds=300.0, timed_out=True,
    )


def _pkg(tmp_path: Path, deps=None):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "fixture",
        "version": "0.0.0",
        "dependencies": deps or {},
    }))


def test_layer_metadata():
    layer = NpmInstallCheck()
    assert layer.NAME == "npm_install"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_skipped_when_no_package_json(tmp_path):
    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_uses_npm_install_when_no_lockfile(tmp_path):
    _pkg(tmp_path)
    calls = []

    async def mock_run(argv, *, cwd, timeout, env):
        calls.append(argv)
        return _ok()

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    # First call should be `install` (no lockfile)
    assert "install" in calls[0]
    assert "--ignore-scripts" in calls[0]


def test_uses_npm_ci_when_lockfile_present(tmp_path):
    _pkg(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}")
    calls = []

    async def mock_run(argv, *, cwd, timeout, env):
        calls.append(argv)
        return _ok()

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert "ci" in calls[0]


def test_falls_back_to_install_when_ci_fails(tmp_path):
    _pkg(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}")
    seq = [_fail("stale lockfile"), _ok()]

    async def mock_run(argv, *, cwd, timeout, env):
        return seq.pop(0)

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    # tier 2 = `npm install` after `npm ci` (tier 1) failed
    assert result.details["tier"] == 2


def test_recovers_with_legacy_peer_deps(tmp_path):
    # tier 1 (ci) and tier 2 (install) fail on a peer conflict; tier 3
    # (`install --legacy-peer-deps`) recovers — the exact npm-7+ case this
    # third tier was added for.
    _pkg(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}")
    calls = []
    seq = [_fail("stale lock"), _fail("ERESOLVE peer conflict"), _ok()]

    async def mock_run(argv, *, cwd, timeout, env):
        calls.append(argv)
        return seq.pop(0)

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed
    assert result.details["tier"] == 3
    assert "--legacy-peer-deps" in calls[2]


def test_fails_when_all_tiers_fail(tmp_path):
    _pkg(tmp_path)
    (tmp_path / "package-lock.json").write_text("{}")
    seq = [_fail("stale lock"), _fail("peer conflict"), _fail("registry conflict")]

    async def mock_run(argv, *, cwd, timeout, env):
        return seq.pop(0)

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    # the last tier's stderr is surfaced
    assert "registry conflict" in result.details["stderr_tail"]


def test_fails_when_timeout(tmp_path):
    _pkg(tmp_path)

    async def mock_run(*a, **kw):
        return _timeout()

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["timed_out"] is True


def test_fails_when_npm_missing(tmp_path):
    _pkg(tmp_path)

    async def mock_run(*a, **kw):
        raise FileNotFoundError("npm")

    layer = NpmInstallCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    with patch("lunas.checks.npm_install.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["error"] == "npm_not_found"
