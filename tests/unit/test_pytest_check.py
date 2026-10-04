"""Unit tests for ``lunas.checks.pytest_check``."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from lunas.checks.base import ValidationContext
from lunas.checks.pytest_check import PytestCheck, has_pytest_inputs
from lunas.result import LayerKind, Verdict
from lunas.subprocess_runner import CmdResult

# ----- has_pytest_inputs pure -----------------------------------------


def test_no_inputs(tmp_path):
    (tmp_path / "main.py").write_text("def f(): pass")
    assert has_pytest_inputs(tmp_path) is False


def test_detects_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_one(): pass")
    assert has_pytest_inputs(tmp_path) is True


def test_detects_top_level_test_file(tmp_path):
    (tmp_path / "test_helper.py").write_text("def test_x(): pass")
    assert has_pytest_inputs(tmp_path) is True


def test_detects_underscore_test_suffix(tmp_path):
    (tmp_path / "helpers_test.py").write_text("def test_x(): pass")
    assert has_pytest_inputs(tmp_path) is True


def test_detects_pyproject_pytest_section(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nminversion = \"7.0\"\n"
    )
    assert has_pytest_inputs(tmp_path) is True


def test_detects_pytest_ini(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nminversion = 7\n")
    assert has_pytest_inputs(tmp_path) is True


def test_ignores_test_files_in_venv(tmp_path):
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "test_thirdparty.py").write_text("def test_x(): pass")
    assert has_pytest_inputs(tmp_path) is False


# ----- Full layer (mocked run_cmd) ------------------------------------


def _ok():
    return CmdResult(returncode=0, stdout="3 passed in 0.2s",
                     stderr="", duration_seconds=0.2, timed_out=False)


def _fail():
    return CmdResult(
        returncode=1,
        stdout="FAILED tests/test_x.py::test_one - AssertionError",
        stderr="",
        duration_seconds=0.5, timed_out=False,
    )


def _no_tests():
    return CmdResult(returncode=5, stdout="no tests ran", stderr="",
                     duration_seconds=0.1, timed_out=False)


def _timeout():
    return CmdResult(returncode=-1, stdout="", stderr="",
                     duration_seconds=300.0, timed_out=True)


def test_layer_metadata():
    layer = PytestCheck()
    assert layer.NAME == "pytest"
    assert LayerKind.deterministic == layer.KIND
    assert "python" in layer.APPLIES_TO


def test_skipped_when_no_test_inputs(tmp_path):
    (tmp_path / "main.py").write_text("def f(): pass")
    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    assert asyncio.run(layer.run_async(ctx)).verdict == Verdict.skipped


def test_passes_on_zero_exit(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(): pass")

    async def mock_run(*a, **kw):
        return _ok()

    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    with patch("lunas.checks.pytest_check.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.passed


def test_fails_on_nonzero(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(): assert False")

    async def mock_run(*a, **kw):
        return _fail()

    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    with patch("lunas.checks.pytest_check.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert "AssertionError" in result.details["stdout_tail"]


def test_skipped_when_pytest_exit_5(tmp_path):
    """pytest exit 5 = no tests collected → skip, not fail."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("# empty\n")

    async def mock_run(*a, **kw):
        return _no_tests()

    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    with patch("lunas.checks.pytest_check.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.skipped


def test_fails_on_timeout(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(): pass")

    async def mock_run(*a, **kw):
        return _timeout()

    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    with patch("lunas.checks.pytest_check.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["timed_out"] is True


def test_fails_when_python_missing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a(): pass")

    async def mock_run(*a, **kw):
        raise FileNotFoundError("python")

    layer = PytestCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    with patch("lunas.checks.pytest_check.run_cmd", side_effect=mock_run):
        result = asyncio.run(layer.run_async(ctx))
    assert result.verdict == Verdict.failed
    assert result.details["error"] == "python_not_found"
