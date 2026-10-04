"""Layer #19 — `pytest` must pass for Python stacks that have tests.

For Python projects, running the test suite is the strongest functional
signal we have. A green static-check pass with red pytest output means
the code is type-clean and structurally correct but doesn't actually
*work*.

Strategy:

1. Skip when there are no recognisable test files (no ``tests/`` /
   ``test_*.py`` / ``*_test.py`` at the root and no ``pytest`` markers
   in ``pyproject.toml``).
2. Find the project's Python interpreter:

   - Prefer a venv-style ``./.venv/bin/python`` (Unix) or
     ``./.venv/Scripts/python.exe`` (Windows).
   - Else ``python``, then ``python3`` on PATH; else the interpreter
     running Lunas (``sys.executable``). macOS ships no ``python``.

3. Run ``python -m pytest -q --tb=short --no-header`` from the root.
4. Non-zero exit → fail with the captured output.

Honors ``ctx.timeout_per_command``. ``pytest`` not on PATH → fail
(not skip) when test files exist — the user explicitly asked for a
Python validation and we have something to test.
"""

from __future__ import annotations

import platform
import shutil
import sys
import time
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict
from lunas.subprocess_runner import run_cmd, scrub_env

_TEST_DIR_NAMES: frozenset[str] = frozenset(["tests", "test"])


def _resolve_python(root: Path) -> str:
    """Project venv first; then ``python``/``python3`` on PATH; then ``sys.executable``."""
    is_windows = platform.system() == "Windows"
    venv_dirs = (".venv", "venv")
    rel_python = (
        Path("Scripts") / "python.exe" if is_windows else Path("bin") / "python"
    )
    for venv in venv_dirs:
        cand = root / venv / rel_python
        if cand.exists():
            return str(cand)
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            return found
    return sys.executable


def has_pytest_inputs(root: Path) -> bool:
    """True if the project looks like it contains pytest tests.

    Heuristics:
    - A top-level ``tests/`` or ``test/`` directory containing any .py.
    - At least one ``test_*.py`` or ``*_test.py`` anywhere outside
      virtualenv / build dirs.
    - A ``[tool.pytest.ini_options]`` block in ``pyproject.toml`` or a
      ``pytest.ini`` / ``setup.cfg`` with ``[tool:pytest]``.
    """
    for name in _TEST_DIR_NAMES:
        d = root / name
        if d.is_dir() and any(d.rglob("*.py")):
            return True

    skip_dirs = {"__pycache__", "node_modules", "venv", ".venv", "env", ".env"}
    for p in root.rglob("test_*.py"):
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") or part in skip_dirs for part in rel_parts):
            continue
        return True
    for p in root.rglob("*_test.py"):
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") or part in skip_dirs for part in rel_parts):
            continue
        return True

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            text = pyproject.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if "[tool.pytest" in text:
            return True

    if (root / "pytest.ini").exists():
        return True

    setup_cfg = root / "setup.cfg"
    if setup_cfg.exists():
        try:
            text = setup_cfg.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        if "[tool:pytest]" in text:
            return True

    return False


class PytestCheck(CheckLayer):
    """Layer #19 — `python -m pytest` (skip cleanly when no tests)."""

    NAME = "pytest"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("python",)
    DESCRIPTION = (
        "Run `python -m pytest -q --tb=short --no-header`. Skipped "
        "cleanly when the project has no recognisable test inputs."
    )

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        if not has_pytest_inputs(root):
            return self._skip("No pytest inputs (no tests/ dir or test_*.py)")

        python = _resolve_python(root)
        env = {**scrub_env(), "CI": "true", "PYTHONIOENCODING": "utf-8"}

        try:
            result = await run_cmd(
                [python, "-m", "pytest", "-q", "--tb=short", "--no-header"],
                cwd=root,
                timeout=ctx.timeout_per_command,
                env=env,
            )
        except FileNotFoundError:
            return self._result(
                Verdict.failed,
                summary=f"Python interpreter `{python}` not on PATH",
                start_time=start,
                details={"error": "python_not_found"},
            )

        if result.timed_out:
            return self._result(
                Verdict.failed,
                summary="pytest timed out",
                start_time=start,
                details={
                    "timed_out": True,
                    "stdout_tail": result.stdout.strip()[-2000:],
                },
            )

        # pytest exit codes:
        #   0 = all passed
        #   1 = tests collected but ≥1 failed
        #   2 = test execution interrupted
        #   3 = internal error
        #   4 = pytest command-line usage error
        #   5 = no tests collected
        if result.returncode == 0:
            return self._result(
                Verdict.passed,
                summary="pytest passed",
                start_time=start,
                details={
                    "duration_seconds": result.duration_seconds,
                    "stdout_tail": result.stdout.strip()[-1000:],
                },
            )

        if result.returncode == 5:
            return self._skip(
                "pytest collected no tests (exit code 5)"
            )

        return self._result(
            Verdict.failed,
            summary=f"pytest failed (exit {result.returncode})",
            start_time=start,
            details={
                "exit_code": result.returncode,
                "stdout_tail": result.stdout.strip()[-2000:],
                "stderr_tail": result.stderr.strip()[-500:],
            },
        )

    def run(self, ctx: ValidationContext) -> LayerResult:  # pragma: no cover
        import asyncio
        return asyncio.run(self.run_async(ctx))


__all__ = ["PytestCheck", "has_pytest_inputs"]
