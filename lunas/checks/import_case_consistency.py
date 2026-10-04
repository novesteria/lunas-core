"""Layer #9 — imports must match exports / file paths in casing.

Complements ``named_import_consistency`` (Layer #8):

- #11 flags when an imported name simply isn't exported anywhere.
- #12 flags when the symbol IS exported but with a different casing
  (``userService`` vs ``user_service``), or when the relative path
  casing differs from the on-disk filename (``./Components/UserCard``
  vs ``./components/UserCard``).

The path-casing failure mode is especially nasty: it works on
case-insensitive filesystems (macOS, Windows default), then breaks on
a Linux deploy. The named-case failure mode silently degrades to a
runtime undefined.

Three sub-checks:

1. **TS/JS named imports** — imported name not exported, but a
   case-permutation IS exported in the target file.
2. **Relative-path casing** — import spec resolves on a case-insensitive
   filesystem but the on-disk filename differs in case.
3. **Python ``from … import …``** — imported name not a top-level name
   in the target module, but a case-permutation is.

Conservative: only fires when a clear case-permutation exists. Wildcard
re-exports (``export * from``) are skipped — too broad to verify.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from lunas.checks._python_helpers import find_python_sources
from lunas.checks._ts_helpers import (
    NAMED_IMPORT_RE,
    WILDCARD_EXPORT_MARKER,
    collect_exports,
    find_ts_sources,
    norm_case,
    parse_import_names,
    resolve_relative_spec,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

# ----- TS/JS path-casing helpers ------------------------------------------


def _list_dir_ci(d: Path, cache: dict[Path, dict[str, list[str]]]) -> dict[str, list[str]]:
    """Case-insensitive directory listing: lowercase-name → real names."""
    if d in cache:
        return cache[d]
    mapping: dict[str, list[str]] = {}
    try:
        for entry in d.iterdir():
            mapping.setdefault(entry.name.lower(), []).append(entry.name)
    except (OSError, FileNotFoundError):
        pass
    cache[d] = mapping
    return mapping


def _path_casing_mismatch(
    from_file: Path,
    spec: str,
    scan_root: Path,
    cache: dict[Path, dict[str, list[str]]],
) -> str | None:
    """Walk each segment of ``spec`` and look for case-only divergences
    between the spec and on-disk reality. Returns a description string
    or None if the spec matches exactly (or can't be resolved).
    """
    if not (spec.startswith(".") or spec.startswith("/")):
        return None
    spec_clean = spec.split("?", 1)[0].split("#", 1)[0]
    current = from_file.parent if spec_clean.startswith(".") else scan_root
    segments = [
        seg for seg in spec_clean.replace("\\", "/").split("/") if seg not in ("", ".")
    ]
    divergences: list[str] = []
    for i, seg in enumerate(segments):
        if seg == "..":
            current = current.parent
            continue
        last_seg = i == len(segments) - 1
        listing = _list_dir_ci(current, cache)

        # Look for an exact-case directory match in this segment.
        # We can't rely on `direct.exists()` alone because Windows/macOS
        # filesystems case-fold and would mask the divergence we're
        # trying to catch.
        if seg in [name for names in listing.values() for name in names]:
            current = current / seg
            continue

        if last_seg:
            # Last segment may be an extension-less reference to a file.
            # Check for an exact-stem hit before falling through.
            matched = False
            for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs"):
                cand_name = seg + ext
                real_names = listing.get(cand_name.lower(), [])
                if cand_name in real_names:
                    current = current / cand_name
                    matched = True
                    break
            if matched:
                continue

        # Case-insensitive lookup.
        disk_names = listing.get(seg.lower(), [])
        if not disk_names and last_seg:
            for real_list in listing.values():
                for real in real_list:
                    stem, _, _ = real.rpartition(".")
                    if stem and stem.lower() == seg.lower() and stem != seg:
                        disk_names = real_list
                        break
                if disk_names:
                    break
        if disk_names:
            actual = disk_names[0]
            if actual != seg and not actual.startswith(seg + "."):
                divergences.append(f"'{seg}' on disk is '{actual}'")
                current = current / actual
                continue
            # Same casing as spec → fine.
            current = current / actual
            continue
        return None
    if divergences:
        return ", ".join(divergences)
    return None


# ----- Python helpers -----------------------------------------------------


def _collect_py_top_names(target: Path) -> set[str]:
    """Top-level function / class / variable names defined in a .py file."""
    names: set[str] = set()
    try:
        src_text = target.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src_text, filename=str(target))
    except (OSError, SyntaxError, ValueError):
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _resolve_py_module(
    from_file: Path,
    mod: str,
    level: int,
    scan_root: Path,
) -> Path | None:
    """Resolve ``from <mod> import …`` to a single .py file."""
    if level > 0:
        rel_parts = list(from_file.relative_to(scan_root).parts[:-1])
        if level - 1 > 0:
            rel_parts = rel_parts[: -(level - 1)] if level - 1 <= len(rel_parts) else []
        target_parts = rel_parts + (mod.split(".") if mod else [])
    else:
        target_parts = mod.split(".") if mod else []
    if not target_parts:
        return None
    base = scan_root
    for part in target_parts:
        base = base / part
    file_form = Path(str(base) + ".py")
    if file_form.is_file():
        return file_form
    init_form = base / "__init__.py"
    if init_form.is_file():
        return init_form
    return None


# ----- Public scan ---------------------------------------------------------


def find_case_mismatches(
    root: Path,
) -> tuple[list[dict[str, str]], int, int]:
    """Walk ``root`` for the three sub-check failure modes.

    Returns ``(problems, ts_scanned, py_scanned)``.
    """
    try:
        scan_root = root.resolve()
    except (OSError, RuntimeError):
        scan_root = root

    problems: list[dict[str, str]] = []
    ts_scanned = 0
    py_scanned = 0

    # ----- TS/JS sub-checks --------------------------------------------
    ts_files = find_ts_sources(scan_root)
    exports_cache: dict[Path, set[str]] = {}
    dir_cache: dict[Path, dict[str, list[str]]] = {}

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

    for src_file in ts_files:
        try:
            text = src_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        ts_scanned += 1
        rel = src_file.relative_to(scan_root).as_posix()

        for m in NAMED_IMPORT_RE.finditer(text):
            names_blob = m.group(1)
            spec = m.group(2)
            if not (spec.startswith(".") or spec.startswith("/")):
                continue

            # Sub-check 2: path-casing
            casing_msg = _path_casing_mismatch(src_file, spec, scan_root, dir_cache)
            if casing_msg:
                problems.append({
                    "kind": "path_casing",
                    "file": rel,
                    "spec": spec,
                    "detail": casing_msg,
                })

            target = resolve_relative_spec(src_file, spec, scan_root)
            if target is None:
                continue
            target_exports = _exports(target)
            if WILDCARD_EXPORT_MARKER in target_exports:
                continue

            exports_ci = {
                norm_case(ex): ex
                for ex in target_exports
                if ex != WILDCARD_EXPORT_MARKER
            }

            imported = parse_import_names(names_blob)

            # Sub-check 1: named-case mismatch
            for name in imported:
                if name in target_exports:
                    continue
                key = norm_case(name)
                if key in exports_ci:
                    try:
                        tgt_rel = target.relative_to(scan_root).as_posix()
                    except ValueError:
                        tgt_rel = str(target)
                    problems.append({
                        "kind": "named_case",
                        "file": rel,
                        "imported_name": name,
                        "spec": spec,
                        "target": tgt_rel,
                        "actual_name": exports_ci[key],
                    })

    # ----- Python sub-check --------------------------------------------
    py_files = find_python_sources(scan_root)
    if py_files:
        py_top_names_cache: dict[Path, set[str]] = {}

        def _top_names(target: Path) -> set[str]:
            if target in py_top_names_cache:
                return py_top_names_cache[target]
            names = _collect_py_top_names(target)
            py_top_names_cache[target] = names
            return names

        for py in py_files:
            try:
                src_text = py.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(src_text, filename=str(py))
            except (OSError, SyntaxError, ValueError):
                continue
            py_scanned += 1
            rel = py.relative_to(scan_root).as_posix()

            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                target = _resolve_py_module(
                    py, node.module or "", node.level or 0, scan_root
                )
                if target is None:
                    continue
                top_names = _top_names(target)
                if not top_names:
                    continue
                top_ci = {norm_case(n): n for n in top_names}
                for alias in node.names:
                    name = alias.name
                    if name == "*" or name in top_names:
                        continue
                    key = norm_case(name)
                    if key in top_ci:
                        try:
                            tgt_rel = target.relative_to(scan_root).as_posix()
                        except ValueError:
                            tgt_rel = str(target)
                        problems.append({
                            "kind": "named_case_py",
                            "file": rel,
                            "imported_name": name,
                            "module": node.module or ".",
                            "target": tgt_rel,
                            "actual_name": top_ci[key],
                        })

    return problems, ts_scanned, py_scanned


class ImportCaseConsistencyCheck(CheckLayer):
    """Layer #9 — imports must match exports / file paths in casing."""

    NAME = "import_case_consistency"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node", "python")
    DESCRIPTION = (
        "Imports must agree with exports and on-disk paths in casing. "
        "Catches snake_case↔camelCase mismatches and the Linux-only "
        "case-sensitive-filesystem path bug."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        ts_files = find_ts_sources(root)
        py_files = find_python_sources(root)
        if not ts_files and not py_files:
            return self._skip("No TS/JS/Py files in input")

        problems, ts_scanned, py_scanned = find_case_mismatches(root)

        if problems:
            shown = problems[:20]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(problems)} import(s) with case mismatch "
                    f"({ts_scanned} TS/JS + {py_scanned} Py file(s) scanned)"
                ),
                start_time=start,
                details={
                    "ts_files_scanned": ts_scanned,
                    "py_files_scanned": py_scanned,
                    "problems": shown,
                    "truncated": len(problems) > 20,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All imports match exported identifier and path casing "
                f"({ts_scanned} TS/JS + {py_scanned} Py file(s) scanned)"
            ),
            start_time=start,
            details={
                "ts_files_scanned": ts_scanned,
                "py_files_scanned": py_scanned,
            },
        )


__all__ = [
    "ImportCaseConsistencyCheck",
    "find_case_mismatches",
]
