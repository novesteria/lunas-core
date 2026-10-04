"""Layer #4 — FastAPI router prefix double-mount detection.

Catches the failure mode where an ``APIRouter`` is declared with a
``prefix=`` *and* included with another ``prefix=`` on
``app.include_router()`` — every endpoint then lands at
``{outer}{inner}/...`` and every request 404s.

Canonical example:

    # app/api/router.py
    router = APIRouter(prefix="/api")

    # main.py
    from app.api.router import router as api_router
    app.include_router(api_router, prefix="/api")
    # → endpoints land at /api/api/...

pip install passes. The file compiles. Tests that hit the router via
its registered path may pass. The bug only surfaces at HTTP runtime
when the live URL is wrong.

Strategy:

1. **Pass 1** (AST walk): for each ``X = APIRouter(prefix="P")`` with
   non-empty ``P``, record ``(file, X) → P``. Also record every
   ``from M import V [as A]`` so we know what local names mean.
2. **Pass 2** (same walk): for every
   ``something.include_router(<expr>, prefix="Q")`` with non-empty
   ``Q``, resolve ``<expr>``'s root name through the file's alias
   map back to ``(origin_file, origin_var)``. If that pair has a
   declared prefix in step 1, flag the conflict.

Heuristic intentionally narrow — false positives only occur when an
unrelated module declares a same-named prefixed router, which is rare.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks._python_helpers import find_python_sources
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict


@dataclass(frozen=True)
class RouterConflict:
    """A FastAPI router with prefix on both APIRouter() and include_router()."""

    incl_file: str
    """Relative path of the file that calls include_router()."""

    lineno: int
    """Line number of the include_router() call."""

    name: str
    """Local name (and origin if resolved cross-file) of the router."""

    declared_prefix: str
    """The prefix from APIRouter(prefix=...)."""

    inclusion_prefix: str
    """The prefix from include_router(..., prefix=...)."""

    declared_in: str
    """Relative path of the file declaring the APIRouter."""

    @property
    def landing_path(self) -> str:
        """Where endpoints actually land (the double-prefixed path)."""
        return f"{self.inclusion_prefix}{self.declared_prefix}"


def _str_const(node: ast.AST) -> str:
    """Return the string value of an ``ast.Constant``, else empty string."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _build_module_index(root: Path, py_files: list[Path]) -> dict[str, str]:
    """Map dotted module path → relative file path.

    ``a/b/c.py`` becomes ``"a.b.c"``; ``a/b/__init__.py`` becomes
    ``"a.b"``. Used to resolve ``from M import V`` back to the file
    that defines ``V``.
    """
    module_to_file: dict[str, str] = {}
    for py in py_files:
        rel_parts = py.relative_to(root).with_suffix("").parts
        if rel_parts and rel_parts[-1] == "__init__":
            dotted = ".".join(rel_parts[:-1])
        else:
            dotted = ".".join(rel_parts)
        if dotted:
            module_to_file[dotted] = py.relative_to(root).as_posix()
    return module_to_file


def _resolve_module_to_rel(module_path: str, module_index: dict[str, str]) -> str:
    """Resolve a dotted module name to a relative file path.

    Falls back to parent packages (so ``app.api.deep.thing`` finds
    ``app/api/deep/__init__.py`` if ``thing`` lives there).
    """
    if module_path in module_index:
        return module_index[module_path]
    parts = module_path.split(".")
    while parts:
        parts.pop()
        cand = ".".join(parts)
        if cand in module_index:
            return module_index[cand]
    return ""


def find_router_conflicts(root: Path) -> tuple[list[RouterConflict], int, int, int]:
    """Find FastAPI routers double-mounted with a prefix on both sides.

    Returns ``(conflicts, files_scanned, declarations_count, inclusions_count)``.
    """
    py_files = find_python_sources(root)
    if not py_files:
        return [], 0, 0, 0

    module_index = _build_module_index(root, py_files)

    # (file_rel, var_name) -> declared_prefix
    declarations: dict[tuple[str, str], str] = {}
    # file_rel -> {local_name: (origin_module, origin_var)}
    aliases: dict[str, dict[str, tuple[str, str]]] = {}
    # (file_rel, included_local_name, inclusion_prefix, lineno)
    inclusions: list[tuple[str, str, str, int]] = []

    scanned = 0
    for py in py_files:
        try:
            src = py.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(py))
        except (SyntaxError, ValueError, OSError):
            continue
        scanned += 1
        rel = py.relative_to(root).as_posix()
        aliases.setdefault(rel, {})

        for node in ast.walk(tree):
            # Build alias map for this file
            if isinstance(node, ast.ImportFrom) and node.module and (node.level or 0) == 0:
                for alias in node.names:
                    local = alias.asname or alias.name
                    aliases[rel][local] = (node.module, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    aliases[rel][local] = (alias.name, "")

            # Declarations: X = APIRouter(prefix='...')
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                func = call.func
                is_router_ctor = (
                    (isinstance(func, ast.Name) and func.id == "APIRouter")
                    or (isinstance(func, ast.Attribute) and func.attr == "APIRouter")
                )
                if not is_router_ctor:
                    continue
                declared_prefix = ""
                for kw in call.keywords:
                    if kw.arg == "prefix":
                        declared_prefix = _str_const(kw.value)
                        break
                if not declared_prefix:
                    continue
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        declarations[(rel, tgt.id)] = declared_prefix

            # Inclusions: <x>.include_router(<arg0>, prefix='...')
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr != "include_router":
                    continue
                if not node.args:
                    continue
                incl_prefix = ""
                for kw in node.keywords:
                    if kw.arg == "prefix":
                        incl_prefix = _str_const(kw.value)
                        break
                if not incl_prefix:
                    continue
                arg0 = node.args[0]
                if isinstance(arg0, ast.Name):
                    incl_local = arg0.id
                elif isinstance(arg0, ast.Attribute):
                    cur: ast.AST = arg0
                    while isinstance(cur, ast.Attribute):
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        incl_local = cur.id
                    else:
                        continue
                else:
                    continue
                inclusions.append((rel, incl_local, incl_prefix, node.lineno))

    # Cross-reference: every inclusion against declarations
    conflicts: list[RouterConflict] = []
    for incl_file, incl_local, incl_prefix, lineno in inclusions:
        # Same-file declaration first
        if (incl_file, incl_local) in declarations:
            conflicts.append(RouterConflict(
                incl_file=incl_file,
                lineno=lineno,
                name=incl_local,
                declared_prefix=declarations[(incl_file, incl_local)],
                inclusion_prefix=incl_prefix,
                declared_in=incl_file,
            ))
            continue
        # Resolve through this file's alias map
        file_aliases = aliases.get(incl_file, {})
        if incl_local in file_aliases:
            origin_module, origin_var = file_aliases[incl_local]
            if not origin_var:
                # `import M` alone — the include must have been M.something
                # which the Attribute branch normalized; nothing more to do.
                continue
            origin_file = _resolve_module_to_rel(origin_module, module_index)
            if not origin_file:
                continue
            if (origin_file, origin_var) in declarations:
                conflicts.append(RouterConflict(
                    incl_file=incl_file,
                    lineno=lineno,
                    name=f"{incl_local} (={origin_module}.{origin_var})",
                    declared_prefix=declarations[(origin_file, origin_var)],
                    inclusion_prefix=incl_prefix,
                    declared_in=origin_file,
                ))

    return conflicts, scanned, len(declarations), len(inclusions)


class RouterPrefixConsistencyCheck(CheckLayer):
    """Layer #4 — FastAPI router prefix double-mount detection."""

    NAME = "router_prefix_consistency"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("python",)
    DESCRIPTION = (
        "FastAPI routers must not carry a `prefix=` on both APIRouter() "
        "and include_router() — endpoints would land at the doubled path "
        "and every request would 404."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        py_files = find_python_sources(root)
        if not py_files:
            return self._skip("No .py files in input")

        conflicts, scanned, decl_count, incl_count = find_router_conflicts(root)

        if conflicts:
            shown = conflicts[:10]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(conflicts)} FastAPI router(s) double-mounted "
                    f"across {scanned} file(s)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "declarations": decl_count,
                    "inclusions": incl_count,
                    "conflicts": [
                        {
                            "incl_file": c.incl_file,
                            "lineno": c.lineno,
                            "name": c.name,
                            "declared_prefix": c.declared_prefix,
                            "inclusion_prefix": c.inclusion_prefix,
                            "declared_in": c.declared_in,
                            "landing_path": c.landing_path,
                        }
                        for c in shown
                    ],
                    "truncated": len(conflicts) > 10,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"No double-prefixed routers across {scanned} file(s) "
                f"({decl_count} prefixed router(s), {incl_count} include_router call(s))"
            ),
            start_time=start,
            details={
                "files_scanned": scanned,
                "declarations": decl_count,
                "inclusions": incl_count,
            },
        )


__all__ = [
    "RouterPrefixConsistencyCheck",
    "RouterConflict",
    "find_router_conflicts",
]
