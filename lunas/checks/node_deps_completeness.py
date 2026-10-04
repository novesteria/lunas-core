"""Layer #5 — every bare-specifier JS/TS import must be in package.json.

Catches the same failure mode as Python's deps-completeness layer, but
for Node: an agent writes ``import axios from 'axios'`` and never adds
``"axios"`` to ``package.json``. ``tsc`` and ``vite build`` would
eventually catch it, but those require ``npm install`` to finish —
slow, network-dependent, and can fail for unrelated reasons. This
static check runs in milliseconds.

Skip-clean cases:

- No ``package.json`` at the root (not a Node project).
- No JS/TS source files in the input.

Honors:

- Node built-ins (``fs``, ``path``, ``crypto``, …) — never need a dep.
- The ``node:`` protocol prefix (``import fs from 'node:fs'``).
- ``@types/X`` as a stand-in for type-only imports of ``X`` (the
  runtime package is usually a peer of the type defs).
- Scoped packages (``@scope/pkg``) — package name is first two
  path segments.
- Subpath imports (``lodash/fp``, ``@scope/pkg/util``) — only the
  root package needs to be declared.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks._node_helpers import (
    NODE_BUILTINS,
    declared_deps,
    extract_import_specifiers,
    find_node_sources,
    load_package_json,
    package_root_of,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict


@dataclass(frozen=True)
class UndeclaredNodeDep:
    """A package imported but never declared in package.json."""

    package: str
    """Root package name (e.g. ``"axios"`` or ``"@scope/pkg"``)."""

    files: tuple[str, ...]
    """Relative file paths that import it."""


def find_undeclared_node_deps(
    root: Path,
    *,
    declared: set[str] | None = None,
) -> tuple[list[UndeclaredNodeDep], int]:
    """Return packages imported but not declared, plus files-scanned count.

    Caller supplies ``declared`` to share state across layers; if
    omitted, we parse ``package.json`` ourselves. Returns an empty list
    when there's no ``package.json`` (the layer would skip in that case;
    callers using this helper directly are responsible for the skip).
    """
    if declared is None:
        pkg = load_package_json(root)
        declared = declared_deps(pkg) if pkg else set()

    sources = find_node_sources(root)
    missing: dict[str, list[str]] = {}
    scanned = 0

    for src in sources:
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        rel = src.relative_to(root).as_posix()

        specs = extract_import_specifiers(text)
        for spec in specs:
            pkg_name = package_root_of(spec)
            if not pkg_name:
                continue
            first = pkg_name.split("/", 1)[0]
            if first in NODE_BUILTINS:
                continue
            if pkg_name in declared:
                continue
            if f"@types/{pkg_name}" in declared:
                continue
            missing.setdefault(pkg_name, []).append(rel)

    out = [
        UndeclaredNodeDep(package=name, files=tuple(files))
        for name, files in sorted(missing.items())
    ]
    return out, scanned


class NodeDepsCompletenessCheck(CheckLayer):
    """Layer #5 — bare-specifier Node imports must be declared."""

    NAME = "node_deps_completeness"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "Every bare-specifier JS/TS import must be declared in "
        "package.json (deps/devDeps/peerDeps/optionalDeps). Catches "
        "the canonical 'import axios but never added it to package.json' bug."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        pkg = load_package_json(root)
        if pkg is None:
            if (root / "package.json").exists():
                # File exists but parsing failed — that's a real failure,
                # not a skip. Node tooling won't run against a malformed
                # package.json either.
                return self._result(
                    Verdict.failed,
                    summary="package.json exists but is not valid JSON",
                    start_time=start,
                    details={"package_json_valid": False},
                )
            return self._skip("No package.json at root")

        sources = find_node_sources(root)
        if not sources:
            return self._skip("No JS/TS source files")

        declared = declared_deps(pkg)
        missing, scanned = find_undeclared_node_deps(root, declared=declared)

        if missing:
            shown = missing[:30]
            details_missing = [
                {
                    "package": entry.package,
                    "imported_in": entry.files[0],
                    "occurrences": len(entry.files),
                }
                for entry in shown
            ]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(missing)} package(s) imported but not declared "
                    f"across {scanned} file(s)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "declared_count": len(declared),
                    "missing": details_missing,
                    "truncated": len(missing) > 30,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All imports across {scanned} file(s) resolve to declared deps "
                f"({len(declared)} declarations)"
            ),
            start_time=start,
            details={
                "files_scanned": scanned,
                "declared_count": len(declared),
            },
        )


__all__ = [
    "NodeDepsCompletenessCheck",
    "UndeclaredNodeDep",
    "find_undeclared_node_deps",
]
