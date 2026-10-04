"""Unit tests for ``lunas.checks.python_completeness``."""

from __future__ import annotations

import ast

from lunas.checks.base import ValidationContext
from lunas.checks.python_completeness import (
    PythonCompletenessCheck,
    find_stub_functions,
    is_critical_stub_name,
    stub_reason,
)
from lunas.result import LayerKind, Verdict


def _stmts(src: str) -> list[ast.stmt]:
    """Parse ``src`` and return the body of its first function/method."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.body
    return tree.body


# ----- stub_reason pure function --------------------------------------


def test_stub_pass():
    assert stub_reason(_stmts("def f(): pass")) == "body is just `pass`"


def test_stub_ellipsis():
    assert stub_reason(_stmts("def f(): ...")) == "body is just `...`"


def test_stub_raise_notimplementederror():
    body = _stmts("def f(): raise NotImplementedError")
    assert stub_reason(body) == "body is `raise NotImplementedError`"


def test_stub_raise_notimplementederror_with_args():
    body = _stmts('def f(): raise NotImplementedError("todo")')
    assert stub_reason(body) == "body is `raise NotImplementedError`"


def test_stub_docstring_only():
    body = _stmts('def f():\n    """only docstring"""')
    assert stub_reason(body) == "docstring only, no implementation"


def test_real_implementation_not_stub():
    body = _stmts("def f():\n    x = 1\n    return x + 1")
    assert stub_reason(body) is None


def test_docstring_plus_real_implementation_not_stub():
    body = _stmts('def f():\n    """doc"""\n    return 42')
    assert stub_reason(body) is None


# ----- is_critical_stub_name ------------------------------------------


def test_critical_main_run_handlers():
    assert is_critical_stub_name("main")
    assert is_critical_stub_name("run")
    assert is_critical_stub_name("start")
    assert is_critical_stub_name("handle_login")
    assert is_critical_stub_name("get")
    assert is_critical_stub_name("post")


def test_non_critical_names():
    assert not is_critical_stub_name("helper")
    assert not is_critical_stub_name("compute_avg")
    assert not is_critical_stub_name("_private_thing")


# ----- find_stub_functions --------------------------------------------


def test_find_stubs_in_tree(tmp_path):
    (tmp_path / "a.py").write_text(
        "def real():\n    return 1\n"
        "def stub():\n    pass\n"
    )
    stubs, total = find_stub_functions(tmp_path)
    assert total == 2
    assert len(stubs) == 1
    assert stubs[0].name == "stub"


def test_abstractmethod_excluded(tmp_path):
    (tmp_path / "x.py").write_text(
        "from abc import abstractmethod\n"
        "class A:\n"
        "    @abstractmethod\n"
        "    def m(self): pass\n"
    )
    stubs, total = find_stub_functions(tmp_path)
    assert stubs == []
    assert total == 0  # abstractmethod excluded from both counts


# ----- Full layer behavior --------------------------------------------


def test_layer_metadata():
    layer = PythonCompletenessCheck()
    assert layer.NAME == "python_completeness"
    assert LayerKind.deterministic == layer.KIND
    assert "python" in layer.APPLIES_TO


def test_layer_passes_clean_code(tmp_path):
    (tmp_path / "app.py").write_text(
        "def hello(name):\n"
        "    return f'hi {name}'\n"
        "def add(a, b):\n"
        "    return a + b\n"
    )
    layer = PythonCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_fails_critical_stub(tmp_path):
    """A 'main' function as a stub is critical, layer FAILs."""
    (tmp_path / "app.py").write_text("def main(): pass\n")
    layer = PythonCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["critical_count"] == 1


def test_layer_passes_few_non_critical_stubs(tmp_path):
    """1 stub in a 10-function project: under threshold, layer passes."""
    body = "\n".join(f"def fn_{i}():\n    return {i}" for i in range(9))
    body += "\ndef helper():\n    pass\n"  # 1 stub of 10 = 10%, under 30% threshold
    (tmp_path / "app.py").write_text(body)
    layer = PythonCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
    assert result.details["stubs_total"] == 1


def test_layer_fails_high_stub_ratio(tmp_path):
    """≥30% stub ratio in ≥4 functions: layer FAILs."""
    body = (
        "def a(): pass\n"
        "def b(): pass\n"
        "def c(): pass\n"
        "def d(): return 1\n"
    )
    (tmp_path / "app.py").write_text(body)
    layer = PythonCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["stub_ratio"] >= 0.3
