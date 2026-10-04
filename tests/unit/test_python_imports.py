"""Unit tests for ``lunas.checks.python_imports``."""

from __future__ import annotations

from pathlib import Path

from lunas.checks.base import ValidationContext
from lunas.checks.python_imports import (
    PythonImportsCheck,
    find_unresolved_local_imports,
)
from lunas.result import LayerKind, Verdict


def _make_pkg(root: Path, dotted: str, *, init: bool = True) -> Path:
    """Create a package/module directory tree, return the deepest dir."""
    parts = dotted.split(".")
    cur = root
    for part in parts:
        cur = cur / part
        cur.mkdir(exist_ok=True)
        if init:
            (cur / "__init__.py").touch()
    return cur


def test_layer_metadata():
    layer = PythonImportsCheck()
    assert layer.NAME == "python_imports"
    assert LayerKind.deterministic == layer.KIND
    assert "python" in layer.APPLIES_TO


def test_passes_when_all_local_imports_resolve(tmp_path):
    """`src/main.py` imports `src.models.user`, which exists."""
    src = _make_pkg(tmp_path, "src.models")
    (src / "user.py").write_text("class User: pass")
    main = tmp_path / "src" / "main.py"
    main.write_text("from src.models.user import User\n")

    missing, scanned = find_unresolved_local_imports(tmp_path)
    assert missing == []
    assert scanned >= 1


def test_fails_when_local_import_missing(tmp_path):
    """Canonical bug: `from src.models.user import User` but no user.py."""
    _make_pkg(tmp_path, "src.models")
    main = tmp_path / "src" / "main.py"
    main.write_text("from src.models.user import User\n")

    missing, scanned = find_unresolved_local_imports(tmp_path)
    assert len(missing) == 1
    assert missing[0].module == "src.models.user"
    assert "src/main.py" in missing[0].file


def test_skips_stdlib(tmp_path):
    """`import os` shouldn't be flagged."""
    main = tmp_path / "main.py"
    main.write_text("import os\nimport sys\nimport json\n")

    missing, scanned = find_unresolved_local_imports(tmp_path)
    assert missing == []
    assert scanned == 1


def test_skips_third_party(tmp_path):
    """`import requests` (third-party, no local file) is skipped by THIS
    layer — the deps-completeness layer covers it."""
    main = tmp_path / "main.py"
    main.write_text("import requests\n")

    missing, scanned = find_unresolved_local_imports(tmp_path)
    # 'requests' isn't a local top-level name (no requests/ dir, no requests.py)
    assert missing == []


def test_relative_import_resolves(tmp_path):
    """`from .other import x` resolves against the importing file's package."""
    pkg = _make_pkg(tmp_path, "app")
    (pkg / "other.py").write_text("x = 1\n")
    (pkg / "main.py").write_text("from .other import x\n")

    missing, _ = find_unresolved_local_imports(tmp_path)
    assert missing == []


def test_relative_import_misses(tmp_path):
    """`from .nope import x` when nope.py doesn't exist."""
    pkg = _make_pkg(tmp_path, "app")
    (pkg / "main.py").write_text("from .nope import x\n")

    missing, _ = find_unresolved_local_imports(tmp_path)
    assert len(missing) == 1
    assert "app.nope" in missing[0].module or "nope" in missing[0].statement


def test_layer_skips_when_no_py_files(tmp_path):
    layer = PythonImportsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped


def test_layer_fails_with_details(tmp_path):
    _make_pkg(tmp_path, "src")
    (tmp_path / "src" / "main.py").write_text("from src.missing import thing\n")

    layer = PythonImportsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["files_scanned"] >= 1
    assert len(result.details["missing_imports"]) >= 1


def test_layer_ignores_virtualenv(tmp_path):
    """Files inside venv/ must not be scanned (they're third-party)."""
    src = _make_pkg(tmp_path, "src")
    (src / "main.py").write_text("from src.helper import x\n")
    (src / "helper.py").write_text("x = 1\n")

    venv_pkg = _make_pkg(tmp_path, "venv.fake_lib")
    (venv_pkg / "broken.py").write_text("from nonexistent.module import x\n")

    layer = PythonImportsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
