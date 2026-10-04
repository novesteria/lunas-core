"""Unit tests for ``lunas.checks.import_case_consistency``."""

from __future__ import annotations

import sys

import pytest

from lunas.checks._ts_helpers import norm_case
from lunas.checks.base import ValidationContext
from lunas.checks.import_case_consistency import (
    ImportCaseConsistencyCheck,
    find_case_mismatches,
)
from lunas.result import LayerKind, Verdict

# ----- norm_case pure --------------------------------------------------


def test_norm_case_collapses_styles():
    assert norm_case("userService") == "userservice"
    assert norm_case("user_service") == "userservice"
    assert norm_case("UserService") == "userservice"
    assert norm_case("USER_SERVICE") == "userservice"
    assert norm_case("user-service") == "userservice"


# ----- Sub-check 1: named-case mismatch ---------------------------------


def test_named_case_mismatch_flagged(tmp_path):
    (tmp_path / "svc.ts").write_text("export const userService = () => {}\n")
    (tmp_path / "main.ts").write_text("import { user_service } from './svc'\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    cases = [p for p in problems if p["kind"] == "named_case"]
    assert len(cases) == 1
    assert cases[0]["imported_name"] == "user_service"
    assert cases[0]["actual_name"] == "userService"


def test_exact_match_not_flagged(tmp_path):
    (tmp_path / "svc.ts").write_text("export const userService = () => {}\n")
    (tmp_path / "main.ts").write_text("import { userService } from './svc'\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    assert all(p["kind"] != "named_case" for p in problems)


# ----- Sub-check 2: path-casing mismatch --------------------------------


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Path-casing sub-check requires case-insensitive filesystem to surface the divergence",
)
def test_path_casing_mismatch_flagged(tmp_path):
    """On Win/macOS, `./Svc` resolves but disk is `svc.ts` → flag."""
    (tmp_path / "svc.ts").write_text("export const x = 1\n")
    (tmp_path / "main.ts").write_text("import { x } from './Svc'\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    assert any(p["kind"] == "path_casing" for p in problems)


# ----- Sub-check 3: Python case mismatch --------------------------------


def test_python_case_mismatch_flagged(tmp_path):
    (tmp_path / "utils.py").write_text("def helper_fn():\n    pass\n")
    (tmp_path / "main.py").write_text("from utils import helperFn\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    py = [p for p in problems if p["kind"] == "named_case_py"]
    assert len(py) == 1
    assert py[0]["imported_name"] == "helperFn"
    assert py[0]["actual_name"] == "helper_fn"


def test_python_exact_match_not_flagged(tmp_path):
    (tmp_path / "utils.py").write_text("def helper_fn():\n    pass\n")
    (tmp_path / "main.py").write_text("from utils import helper_fn\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    assert all(p["kind"] != "named_case_py" for p in problems)


def test_python_missing_name_not_flagged(tmp_path):
    """Name simply doesn't exist (no case-permutation) → layer #11
    territory, not us."""
    (tmp_path / "utils.py").write_text("def actual_thing():\n    pass\n")
    (tmp_path / "main.py").write_text("from utils import totally_unrelated\n")
    problems, _, _ = find_case_mismatches(tmp_path)
    assert problems == []


# ----- Full layer -------------------------------------------------------


def test_layer_metadata():
    layer = ImportCaseConsistencyCheck()
    assert layer.NAME == "import_case_consistency"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO
    assert "python" in layer.APPLIES_TO


def test_layer_skipped_no_files(tmp_path):
    layer = ImportCaseConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_passes_clean(tmp_path):
    (tmp_path / "utils.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "main.py").write_text("from utils import helper\n")
    layer = ImportCaseConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    assert layer.run(ctx).verdict == Verdict.passed


def test_layer_fails_on_mismatch(tmp_path):
    (tmp_path / "svc.ts").write_text("export const userService = () => {}\n")
    (tmp_path / "main.ts").write_text("import { user_service } from './svc'\n")
    layer = ImportCaseConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.failed
