"""Layer #2 — Python function-body completeness.

Detects functions whose body compiles but does nothing — the agent
declared the surface but never wrote the implementation. Pure AST
analysis; no subprocess, no LLM.

Detected stub patterns:

- body is exactly ``pass``
- body is exactly ``...`` (Ellipsis literal)
- body is exactly ``raise NotImplementedError(...)``
- body is just a docstring (no real statements after it)

Excluded from the count:

- Functions decorated with ``@abstractmethod``
- Trivial ``__init__`` bodies that only call ``super().__init__()``
  (a separate check could enforce this; for now we tolerate)

Verdict logic: layer FAILs when

- any "critical" stub is found (functions with names that suggest
  they're entry points: ``main``, ``run``, ``start``, ``serve``,
  ``get``, ``post``, ``put``, ``delete``, ``patch``, ``handle_*``), OR
- the project has ≥4 functions and ≥30% of them are stubs (project
  isn't really implemented).

Otherwise the layer PASSes — 1-2 stubs in a 50-function project is
usually a deliberate placeholder for an edge case.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks._python_helpers import find_python_sources
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

# Function names that suggest "entry point" — if they're stubs, the
# project doesn't actually do anything when run.
_ENTRY_POINT_NAMES: frozenset[str] = frozenset(
    [
        "main", "run", "start", "serve", "create_app",
        "get", "post", "put", "delete", "patch",
    ]
)

_STUB_RATIO_THRESHOLD = 0.3
_MIN_FUNCS_FOR_RATIO_CHECK = 4


@dataclass(frozen=True)
class StubFunction:
    """One function with a stub body."""

    file: str
    line: int
    name: str
    reason: str


def _has_abstractmethod(decorators: list[ast.expr]) -> bool:
    """True if any of the decorators is ``@abstractmethod`` (with or
    without ``abc.`` prefix)."""
    for d in decorators:
        if isinstance(d, ast.Name) and d.id == "abstractmethod":
            return True
        if isinstance(d, ast.Attribute) and d.attr == "abstractmethod":
            return True
    return False


def stub_reason(body: list[ast.stmt]) -> str | None:
    """If ``body`` is a stub, return a label describing why. Else None."""
    if not body:
        return "empty body"

    # Strip a leading docstring before deciding
    real = body
    if (
        isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        real = body[1:]
    if not real:
        return "docstring only, no implementation"

    if len(real) == 1:
        stmt = real[0]
        if isinstance(stmt, ast.Pass):
            return "body is just `pass`"
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        ):
            return "body is just `...`"
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id == "NotImplementedError":
                return "body is `raise NotImplementedError`"
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                return "body is `raise NotImplementedError`"

    return None


def find_stub_functions(root: Path) -> tuple[list[StubFunction], int]:
    """Walk every .py file under ``root`` and identify stub functions.

    Returns (stubs, total_functions). ``@abstractmethod``-decorated
    functions are excluded from both counts.
    """
    py_files = find_python_sources(root)
    stubs: list[StubFunction] = []
    total = 0

    for py in py_files:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"), filename=str(py))
        except (SyntaxError, ValueError):
            continue
        rel = py.relative_to(root).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_abstractmethod(node.decorator_list):
                    continue
                total += 1
                label = stub_reason(node.body)
                if label is not None:
                    stubs.append(StubFunction(rel, node.lineno, node.name, label))

    return stubs, total


def is_critical_stub_name(name: str) -> bool:
    """True if the function name looks like an entry point that mustn't
    be a stub (``main``, ``run``, ``handle_*``, HTTP verbs, ...)."""
    if name in _ENTRY_POINT_NAMES:
        return True
    return name.startswith("handle_")


class PythonCompletenessCheck(CheckLayer):
    """Layer #2 — detect stub function bodies in Python code."""

    NAME = "python_completeness"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("python",)
    DESCRIPTION = (
        "Detect Python functions whose body compiles but does nothing "
        "(pass, ..., raise NotImplementedError, docstring-only)."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        if not ctx.code_path.is_dir():
            return self._skip("code_path is not a directory")
        if not find_python_sources(ctx.code_path):
            return self._skip("No .py files in input")

        stubs, total = find_stub_functions(ctx.code_path)
        critical = [s for s in stubs if is_critical_stub_name(s.name)]
        ratio = (len(stubs) / total) if total else 0.0
        ratio_fail = (
            total >= _MIN_FUNCS_FOR_RATIO_CHECK and ratio >= _STUB_RATIO_THRESHOLD
        )

        if critical or ratio_fail:
            shown = stubs[:20]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(stubs)} stub function(s) of {total} total "
                    f"({int(ratio * 100)}% stub ratio; "
                    f"{len(critical)} critical)"
                ),
                start_time=start,
                details={
                    "stubs_total": len(stubs),
                    "functions_total": total,
                    "stub_ratio": round(ratio, 3),
                    "critical_count": len(critical),
                    "stubs": [
                        {
                            "file": s.file,
                            "line": s.line,
                            "name": s.name,
                            "reason": s.reason,
                        }
                        for s in shown
                    ],
                    "truncated": len(stubs) > 20,
                },
            )

        if stubs:
            return self._result(
                Verdict.passed,
                summary=(
                    f"{len(stubs)} non-critical stub(s) of {total} function(s) "
                    f"({int(ratio * 100)}%, under threshold)"
                ),
                start_time=start,
                details={
                    "stubs_total": len(stubs),
                    "functions_total": total,
                    "stub_ratio": round(ratio, 3),
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"All {total} function bodies have real implementations",
            start_time=start,
            details={"functions_total": total, "stubs_total": 0},
        )


__all__ = [
    "PythonCompletenessCheck",
    "StubFunction",
    "stub_reason",
    "is_critical_stub_name",
    "find_stub_functions",
]
