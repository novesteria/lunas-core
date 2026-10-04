"""Layer #8 — named imports must match exports in the target module.

Static-import resolution (Layer #1 / Layer #13) verifies that the file
imported exists. This layer goes one level deeper: for relative imports
of named members, the named identifiers must actually be exported from
that file.

Canonical bug: one file declares ``export interface CryptoAsset`` while
a peer file does ``import { Cryptocurrency } from './types/crypto'`` —
the file resolves, the import statement is syntactically fine, but
the name doesn't exist there.

Conservative — only flags when:

- The import is from a relative path (``./``, ``../``, ``/``).
- The target resolves to a single ``.ts/.tsx/.js/.jsx/.mjs`` file.
- The named identifier has no ``export`` declaration in that file.
- The target does not ``export * from`` something else (a wildcard
  re-export chain is too broad to verify precisely).
- The imported name is not ``default``.
"""

from __future__ import annotations

import time
from pathlib import Path

from lunas.checks._ts_helpers import (
    NAMED_IMPORT_RE,
    NAMED_REEXPORT_RE,
    WILDCARD_EXPORT_MARKER,
    collect_exports,
    find_ts_sources,
    parse_import_names,
    resolve_relative_spec,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict


def find_named_import_problems(
    root: Path,
) -> tuple[list[dict[str, str | list[str]]], int]:
    """Walk ``root`` and return (problems, files_scanned).

    Each problem dict has keys: ``file``, ``imported_name``, ``spec``,
    ``target``, ``target_exports`` (up to 5).
    """
    sources = find_ts_sources(root)
    if not sources:
        return [], 0

    exports_cache: dict[Path, set[str]] = {}

    def _exports(target: Path) -> set[str]:
        if target in exports_cache:
            return exports_cache[target]
        try:
            src = target.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            exports_cache[target] = set()
            return set()
        names = collect_exports(src)
        exports_cache[target] = names
        return names

    problems: list[dict[str, str | list[str]]] = []
    scanned = 0

    for src_file in sources:
        try:
            text = src_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        rel = src_file.relative_to(root).as_posix()

        for pat in (NAMED_IMPORT_RE, NAMED_REEXPORT_RE):
            for m in pat.finditer(text):
                names_blob = m.group(1)
                spec = m.group(2)
                if not (spec.startswith(".") or spec.startswith("/")):
                    continue
                target = resolve_relative_spec(src_file, spec, root)
                if target is None:
                    continue
                target_exports = _exports(target)
                if WILDCARD_EXPORT_MARKER in target_exports:
                    continue
                imported = parse_import_names(names_blob)
                for name in imported:
                    if name in target_exports:
                        continue
                    try:
                        tgt_rel = target.relative_to(root).as_posix()
                    except ValueError:
                        tgt_rel = str(target)
                    problems.append({
                        "file": rel,
                        "imported_name": name,
                        "spec": spec,
                        "target": tgt_rel,
                        "target_exports": sorted(
                            target_exports - {WILDCARD_EXPORT_MARKER}
                        )[:5],
                    })

    return problems, scanned


class NamedImportConsistencyCheck(CheckLayer):
    """Layer #8 — named imports from relative paths must resolve."""

    NAME = "named_import_consistency"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "When `import { X } from './foo'`, the target ./foo must actually "
        "export X. Catches the silent typo where one file declares "
        "`CryptoAsset` and a peer file imports `{ Cryptocurrency }`."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        if not find_ts_sources(root):
            return self._skip("No TS/JS files in input")

        problems, scanned = find_named_import_problems(root)

        if problems:
            shown = problems[:20]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(problems)} import(s) reference identifiers the "
                    f"target module does not export "
                    f"({scanned} file(s) scanned)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "problems": shown,
                    "truncated": len(problems) > 20,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All named imports across {scanned} file(s) "
                f"match the target module exports"
            ),
            start_time=start,
            details={"files_scanned": scanned},
        )


__all__ = [
    "NamedImportConsistencyCheck",
    "find_named_import_problems",
]
