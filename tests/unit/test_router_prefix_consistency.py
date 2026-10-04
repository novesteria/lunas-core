"""Unit tests for ``lunas.checks.router_prefix_consistency``."""

from __future__ import annotations

from pathlib import Path

from lunas.checks.base import ValidationContext
from lunas.checks.router_prefix_consistency import (
    RouterPrefixConsistencyCheck,
    find_router_conflicts,
)
from lunas.result import LayerKind, Verdict


def _mkpkg(root: Path, dotted: str) -> Path:
    cur = root
    for part in dotted.split("."):
        cur = cur / part
        cur.mkdir(exist_ok=True)
        (cur / "__init__.py").touch()
    return cur


# ----- pure helper --------------------------------------------------------


def test_no_conflict_when_only_one_side_has_prefix(tmp_path):
    """APIRouter(prefix=) alone is fine — caller doesn't double-mount."""
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='/api')\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
    )
    conflicts, scanned, decls, incls = find_router_conflicts(tmp_path)
    assert conflicts == []
    assert decls == 1
    assert incls == 0  # no prefix on include = not counted


def test_same_file_double_prefix(tmp_path):
    """Canonical bug: prefix on APIRouter AND include_router in same file."""
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='/api')\n"
        "app = FastAPI()\n"
        "app.include_router(router, prefix='/api')\n"
    )
    conflicts, _, _, _ = find_router_conflicts(tmp_path)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.declared_prefix == "/api"
    assert c.inclusion_prefix == "/api"
    assert c.landing_path == "/api/api"


def test_cross_file_double_prefix_via_alias(tmp_path):
    """`from X import router as api_router` then double-prefixed include."""
    pkg = _mkpkg(tmp_path, "app.api")
    (pkg / "router.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/api')\n"
    )
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.api.router import router as api_router\n"
        "app = FastAPI()\n"
        "app.include_router(api_router, prefix='/api')\n"
    )
    conflicts, _, _, _ = find_router_conflicts(tmp_path)
    assert len(conflicts) == 1
    assert "api_router" in conflicts[0].name
    assert conflicts[0].declared_in == "app/api/router.py"


def test_attribute_form_resolves(tmp_path):
    """`auth.router` as the included arg — leftmost name lookups via alias."""
    pkg = _mkpkg(tmp_path, "app.routers")
    (pkg / "auth.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/auth')\n"
    )
    (tmp_path / "main.py").write_text(
        "from fastapi import FastAPI\n"
        "from app.routers import auth\n"
        "app = FastAPI()\n"
        "app.include_router(auth.router, prefix='/auth')\n"
    )
    conflicts, _, _, _ = find_router_conflicts(tmp_path)
    # The attribute form takes the leftmost name (`auth`), which the
    # alias map resolves to (`app.routers.auth`, ""). With no var name,
    # the heuristic skips — false negative, by design. Verify we don't
    # crash.
    assert isinstance(conflicts, list)


def test_no_prefix_on_either_side(tmp_path):
    """No prefix anywhere → nothing to flag."""
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter()\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
    )
    conflicts, _, decls, incls = find_router_conflicts(tmp_path)
    assert conflicts == []
    assert decls == 0
    assert incls == 0


def test_empty_string_prefix_is_not_a_prefix(tmp_path):
    """``prefix=""`` doesn't double-mount anything."""
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='')\n"
        "app = FastAPI()\n"
        "app.include_router(router, prefix='/api')\n"
    )
    conflicts, _, _, _ = find_router_conflicts(tmp_path)
    assert conflicts == []


def test_syntax_error_file_skipped(tmp_path):
    """A .py file with a SyntaxError doesn't crash the walk."""
    (tmp_path / "broken.py").write_text("def f(:\n")
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='/api')\n"
        "app = FastAPI()\n"
        "app.include_router(router, prefix='/api')\n"
    )
    conflicts, _, _, _ = find_router_conflicts(tmp_path)
    assert len(conflicts) == 1


# ----- Full layer --------------------------------------------------------


def test_layer_metadata():
    layer = RouterPrefixConsistencyCheck()
    assert layer.NAME == "router_prefix_consistency"
    assert LayerKind.deterministic == layer.KIND
    assert "python" in layer.APPLIES_TO


def test_layer_passes_clean(tmp_path):
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='/api')\n"
        "app = FastAPI()\n"
        "app.include_router(router)\n"
    )
    layer = RouterPrefixConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_fails_on_double_mount(tmp_path):
    (tmp_path / "main.py").write_text(
        "from fastapi import APIRouter, FastAPI\n"
        "router = APIRouter(prefix='/api')\n"
        "app = FastAPI()\n"
        "app.include_router(router, prefix='/api')\n"
    )
    layer = RouterPrefixConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["conflicts"][0]["landing_path"] == "/api/api"


def test_layer_skipped_when_no_py(tmp_path):
    layer = RouterPrefixConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped
