"""Layer #1 — Python local-import resolution.

Catches the classic backend bug: agent writes ``from src.models.user
import User`` but never creates ``src/models/user.py``. ``compileall``
passes (the importing file's syntax is fine), pytest may pass too if
nothing exercises the import, but the moment the app starts at runtime,
``ImportError``.

Strategy:

1. Walk every Python source file under the project root.
2. AST-parse each. Collect ``Import`` and ``ImportFrom`` nodes.
3. For each module name, decide:

   - stdlib → skip (we trust the stdlib is present)
   - third-party → skip (pip should have installed it; the
     ``python_deps_completeness`` layer covers missing third-party
     declarations)
   - local → resolve via package-style search; report if missing

4. Relative imports (``from .foo import bar``) are resolved against
   the importing file's package path.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks._python_helpers import (
    STDLIB_NAMES,
    find_local_top_names,
    find_python_sources,
    resolve_local_module,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict


@dataclass(frozen=True)
class MissingImport:
    """One unresolved local import."""

    file: str          # path relative to project root
    statement: str     # e.g. "from src.foo import bar"
    module: str        # the dotted name that failed to resolve


def _is_third_party_shadow(root: Path, first: str) -> bool:
    """True if ``first`` names only a namespace-only local folder: a directory
    with Python content but no ``__init__.py`` and no ``first.py`` sibling
    (e.g. an Alembic ``alembic/versions/`` migrations tree). Such a name is NOT
    an importable local package, so ``import first`` resolves to the 3rd-party
    package of the same name and must not be flagged as an unresolved local
    import. (The name lands in ``local_top_names`` purely because the dir
    exists.)"""
    d = root / first
    return (
        d.is_dir()
        and not (d / "__init__.py").exists()
        and not (root / f"{first}.py").exists()
        and any(d.rglob("*.py"))
    )


def find_unresolved_local_imports(
    root: Path,
    *,
    local_top_names: set[str] | None = None,
) -> tuple[list[MissingImport], int]:
    """Find every local import in the project tree that doesn't resolve.

    Args:
        root: Project root directory.
        local_top_names: Pre-computed top-level local names. If None,
            computed from ``root``. Pass an explicit value for tests
            that need a synthetic universe.

    Returns:
        (missing_imports, files_scanned). ``files_scanned`` counts only
        files that AST-parsed successfully — syntax errors are silently
        skipped (a separate layer surfaces them).
    """
    py_files = find_python_sources(root)
    if local_top_names is None:
        local_top_names = find_local_top_names(root)

    missing: list[MissingImport] = []
    scanned = 0

    for py in py_files:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"), filename=str(py))
        except (SyntaxError, ValueError):
            continue
        scanned += 1
        rel = py.relative_to(root).as_posix()

        for node in ast.walk(tree):
            # `import a.b.c`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name
                    first = mod.split(".", 1)[0]
                    if first in STDLIB_NAMES or first not in local_top_names:
                        continue
                    if _is_third_party_shadow(root, first):
                        continue
                    if resolve_local_module(root, mod) is None:
                        # Also try the parent (`from foo.bar import baz`
                        # may mean foo/bar.py exports baz)
                        parent = ".".join(mod.split(".")[:-1])
                        if not parent or resolve_local_module(root, parent) is None:
                            missing.append(MissingImport(rel, f"import {mod}", mod))

            # `from a.b import c` or `from . import x`
            elif isinstance(node, ast.ImportFrom):
                level = node.level or 0
                mod = node.module or ""
                if level > 0:
                    # Relative import — resolve against the file's package.
                    rel_parts = list(py.relative_to(root).parts[:-1])
                    if level - 1 > 0:
                        # `from ..x import y` walks up `level - 1` packages.
                        rel_parts = (
                            rel_parts[: -(level - 1)] if level - 1 <= len(rel_parts) else []
                        )
                    target_parts = rel_parts + ([mod] if mod else [])
                    if target_parts:
                        target_mod = ".".join(target_parts)
                        if resolve_local_module(root, target_mod) is None:
                            # Could still be valid if it's a package dir
                            pkg_dir = root
                            for p in target_parts:
                                pkg_dir = pkg_dir / p
                            if not (pkg_dir / "__init__.py").exists() and not (
                                pkg_dir.with_suffix(".py").exists()
                            ):
                                missing.append(
                                    MissingImport(
                                        rel,
                                        f"from {'.' * level}{mod} import ...",
                                        target_mod,
                                    )
                                )
                else:
                    if not mod:
                        continue
                    first = mod.split(".", 1)[0]
                    if first in STDLIB_NAMES or first not in local_top_names:
                        continue
                    if _is_third_party_shadow(root, first):
                        continue
                    if resolve_local_module(root, mod) is None:
                        missing.append(
                            MissingImport(rel, f"from {mod} import ...", mod)
                        )

    return missing, scanned


class PythonImportsCheck(CheckLayer):
    """Verify every local Python import resolves to a file in the repo."""

    NAME = "python_imports"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("python",)
    DESCRIPTION = (
        "Python local-import resolution — catches `from x.y import z` where "
        "x/y.py was never created."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        if not ctx.code_path.is_dir():
            return self._skip("code_path is not a directory")

        if not find_python_sources(ctx.code_path):
            return self._skip("No .py files in input")

        missing, scanned = find_unresolved_local_imports(ctx.code_path)

        if missing:
            shown = missing[:30]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(missing)} unresolved local import(s) "
                    f"across {scanned} file(s) scanned"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "missing_imports": [
                        {"file": m.file, "statement": m.statement, "module": m.module}
                        for m in shown
                    ],
                    "truncated": len(missing) > 30,
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"All local imports resolve across {scanned} file(s)",
            start_time=start,
            details={"files_scanned": scanned},
        )


__all__ = ["PythonImportsCheck", "MissingImport", "find_unresolved_local_imports"]
