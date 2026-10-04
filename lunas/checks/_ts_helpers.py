"""TypeScript / JSX-specific helpers shared across Batch C layers.

Built on top of ``_node_helpers``. Adds:

- TS source-file discovery (``.ts``, ``.tsx``, ``.js``, ``.jsx``, ``.mjs``).
- ``export``-declaration scraping (solo decls + ``export { … }`` groups).
- Relative-spec → file resolution (handles ``./x.ts``, ``./x``, ``./dir``
  with ``index.ts`` fallback).
- Named-import / named-reexport regex.
- Case-normalization for snake/camel/Pascal comparisons.

These are imported by ``named_import_consistency``, ``import_case_consistency``,
``duplicate_type_declarations``, and ``hook_destructure_consistency``.
"""

from __future__ import annotations

import re
from pathlib import Path

# File extensions considered TS/JS source for these layers.
TS_JS_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs")

# Extensions tried (in order) when resolving a relative spec without one.
TS_RESOLVE_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs")


# `coverage` holds instrumented / report output; scanning it produces false
# positives just like `dist`/`build`.
_SKIP_DIRS: frozenset[str] = frozenset(["node_modules", "dist", "build", "coverage"])


def find_ts_sources(root: Path) -> list[Path]:
    """Return all .ts/.tsx/.js/.jsx/.mjs files under ``root``, skipping
    hidden dirs and node_modules.
    """
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in TS_JS_EXTENSIONS:
            continue
        try:
            rel_parts = p.relative_to(root).parts
        except ValueError:
            continue
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts):
            continue
        out.append(p)
    return out


def find_tsx_sources(root: Path) -> list[Path]:
    """Return only .tsx / .jsx files under ``root`` (for JSX-aware layers)."""
    return [p for p in find_ts_sources(root) if p.suffix in (".tsx", ".jsx")]


# ----- relative-spec resolution --------------------------------------------


def resolve_relative_spec(
    from_file: Path,
    spec: str,
    scan_root: Path,
) -> Path | None:
    """Resolve a relative import spec to a TS/JS file.

    Tries:
      1. ``base/spec.{ts,tsx,js,jsx,mjs}``
      2. ``base/spec`` (already an extension)
      3. ``base/spec/index.{ts,tsx,js,jsx}``

    ``base`` is ``from_file.parent`` for ``./…`` / ``../…``, else
    ``scan_root``. Returns ``None`` if nothing resolves.
    """
    spec_clean = spec.split("?", 1)[0].split("#", 1)[0]
    base = from_file.parent if spec_clean.startswith(".") else scan_root
    candidate = (base / spec_clean).resolve()

    for ext in (*TS_RESOLVE_EXTENSIONS, ""):
        p = Path(str(candidate) + ext) if ext else candidate
        if p.is_file():
            return p

    if candidate.is_dir():
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            idx = candidate / f"index{ext}"
            if idx.exists():
                return idx
    return None


# ----- export declarations -------------------------------------------------


# Matches:
#   export interface X
#   export type X
#   export class X
#   export function X
#   export const X
#   export let X / var X / enum X / namespace X / async function X
#   export default … (treated as the literal name "default")
#   export { X, Y as Z }
_EXPORT_DECL_RE = re.compile(
    r"""(?:^|\n)\s*export\s+(?:default\s+|\*\s+from|abstract\s+)?(?:"""
    r"""(?:async\s+)?(?:type|interface|class|function|const|let|var|enum|namespace)\s+(\w+)"""
    # `(?:type\s+)?` so `export type { A, B } from './x'` re-export lists are
    # recognized. tsc accepts them and they are real exports; without this the
    # names go uncollected and a consumer importing them gets false-flagged
    # (L11) or a case mismatch goes undetected (L12).
    r"""|(?:type\s+)?\{([^}]+)\}"""
    r""")""",
    re.MULTILINE,
)

_EXPORT_STAR_RE = re.compile(r"""export\s+\*\s+from""")


WILDCARD_EXPORT_MARKER = "__wildcard__"
"""Sentinel returned in ``collect_exports`` when the file does
``export * from`` — too broad to enumerate exactly, so consumers should
skip strict checking against such targets.
"""


def collect_exports(source: str) -> set[str]:
    """Return the set of names ``source`` exports.

    A ``export * from "..."`` results in ``{"__wildcard__"}`` (alongside
    any concrete exports). Callers should treat the presence of
    ``__wildcard__`` as "I cannot enumerate everything; skip strict
    checks against this module".
    """
    names: set[str] = set()
    for m in _EXPORT_DECL_RE.finditer(source):
        solo = m.group(1)
        group = m.group(2)
        if solo:
            names.add(solo)
        if group:
            for piece in group.split(","):
                token = piece.strip().split(" as ")[-1].strip()
                if token and token != "default":
                    names.add(token)
    if _EXPORT_STAR_RE.search(source):
        names.add(WILDCARD_EXPORT_MARKER)
    return names


# ----- import-spec regexes -------------------------------------------------


NAMED_IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
"""Matches ``import { A, B as C, type D } from 'path'`` — group 1 is the
brace-contents blob, group 2 is the spec."""


NAMED_REEXPORT_RE = re.compile(
    r"""export\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
"""Matches ``export { X, Y } from 'path'`` (re-exports)."""


def parse_import_names(brace_blob: str) -> list[str]:
    """Parse the inside of ``import { … }`` into a list of original names.

    Handles ``A``, ``A as B`` (returns ``A``), ``type A`` (returns ``A``),
    skips empties and ``default``.
    """
    out: list[str] = []
    for piece in brace_blob.split(","):
        token = piece.strip()
        if not token:
            continue
        token = re.sub(r"^type\s+", "", token).strip()
        original = token.split(" as ")[0].strip()
        if original and original != "default":
            out.append(original)
    return out


# ----- case normalization --------------------------------------------------


def norm_case(s: str) -> str:
    """Lowercase + strip ``_`` / ``-`` so ``user_service``, ``userService``,
    ``UserService``, ``USER_SERVICE`` all collapse to the same key.

    Used to detect intentional case-permutation mismatches across an
    import boundary without flagging unrelated names.
    """
    return s.replace("_", "").replace("-", "").lower()


__all__ = [
    "TS_JS_EXTENSIONS",
    "TS_RESOLVE_EXTENSIONS",
    "WILDCARD_EXPORT_MARKER",
    "NAMED_IMPORT_RE",
    "NAMED_REEXPORT_RE",
    "find_ts_sources",
    "find_tsx_sources",
    "resolve_relative_spec",
    "collect_exports",
    "parse_import_names",
    "norm_case",
]
