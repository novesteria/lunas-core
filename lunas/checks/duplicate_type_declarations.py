"""Layer #10 — same `interface X` / `type X` declared with different shapes.

Catches the failure mode where ``types/crypto.ts`` declares
``interface Coin { id, name, symbol, price, … }`` while
``CoinGrid.tsx`` privately declares its own
``interface Coin { name, value }``. Both compile. The consumer pulls
from the wrong file and silently sees partial fields — runtime
``undefined`` at first use.

TS would only catch this via ``TS2300`` if both decls land in the same
scope, but they typically don't (one is in a separate file, never
imported by the other). The static check shines a clean light on the
divergence.

Flag rule:

- Two or more files declare ``interface NAME`` or ``type NAME = { … }``.
- Their member-name sets DIFFER (re-declarations with the same shape
  via TS interface merging are intentionally allowed).
- ``NAME`` is not imported into either file (that would be a deliberate
  shadow; ``tsc`` would catch genuine collisions).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from lunas.checks._ts_helpers import find_ts_sources
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

# Anchor for an `interface X { … }` or `type X = { … }` declaration. We
# only capture the open brace; the body is pulled out with manual brace
# matching so nested generics (`Map<K, V>`) and unions don't break a
# flat regex.
_DECL_ANCHOR = re.compile(
    r"""
    (?:^|\n)\s*
    (?:export\s+)?
    (?P<kind>interface|type)\s+
    (?P<name>[A-Z]\w*)
    (?:\s*<[^>]+>)?              # optional generics
    (?:\s+extends\s+[^{]+)?      # interface extends
    \s*=?\s*                     # `=` for type alias
    \{
    """,
    re.VERBOSE,
)

_MEMBER_RE = re.compile(
    r"""(?:^|;)\s*(?:readonly\s+)?(\w+)\s*[?]?\s*[:(]""",
    re.MULTILINE,
)

_NAMED_IMPORT_BLOB_RE = re.compile(
    r"""import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"][^'"]+['"]""",
    re.MULTILINE,
)


def _find_block_end(src: str, start_brace_idx: int) -> int:
    """Return index just past the matching ``}`` for the ``{`` at
    ``start_brace_idx``. Naive brace-counter — adequate for our anchor
    point, which is past any generic or extends clause.
    """
    depth = 1
    i = start_brace_idx + 1
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i


def _imported_names_in(src: str) -> set[str]:
    """Set of bare names brought in via ``import { … } from``. Used to
    skip duplicate flags on names the file *imports* (deliberate shadow).
    """
    out: set[str] = set()
    for m in _NAMED_IMPORT_BLOB_RE.finditer(src):
        for raw in m.group(1).split(","):
            # `A`, `A as B`, `type A` → take the leftmost bare identifier.
            piece = raw.strip().split(" as ")[0].split(" ")[-1].strip()
            if piece:
                out.add(piece)
    return out


def find_duplicate_type_conflicts(
    root: Path,
) -> tuple[list[dict[str, str | list[str] | int]], int]:
    """Walk ``root`` for duplicate type declarations with different shapes.

    Returns ``(problems, files_scanned)``.
    """
    ts_files = [p for p in find_ts_sources(root) if p.suffix in (".ts", ".tsx")]

    # name -> list of (file_rel, members_tuple)
    decls: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
    imported_per_file: dict[str, set[str]] = {}
    scanned = 0

    for tsf in ts_files:
        try:
            src = tsf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        rel = tsf.relative_to(root).as_posix()

        imported_per_file[rel] = _imported_names_in(src)

        for m in _DECL_ANCHOR.finditer(src):
            name = m.group("name")
            start = m.end() - 1  # at opening `{`
            end = _find_block_end(src, start)
            body = src[start + 1: end - 1]
            members = tuple(sorted(set(_MEMBER_RE.findall(body))))
            if not members:
                continue
            decls.setdefault(name, []).append((rel, members))

    problems: list[dict[str, Any]] = []
    for name, occurrences in decls.items():
        distinct_files = {rel for rel, _ in occurrences}
        if len(distinct_files) < 2:
            continue
        # Group by shape
        shape_groups: dict[tuple[str, ...], list[str]] = {}
        for rel, members in occurrences:
            shape_groups.setdefault(members, []).append(rel)
        if len(shape_groups) < 2:
            continue  # all dups have identical shape (TS interface merge)
        # Deliberate-shadow check
        shadowed = any(
            name in imported_per_file.get(rel, set())
            for rel, _ in occurrences
        )
        if shadowed:
            continue
        problems.append({
            "name": name,
            "distinct_files": len(distinct_files),
            "shape_count": len(shape_groups),
            "shapes": [
                {
                    "fields": list(members[:6]),
                    "more_fields": max(0, len(members) - 6),
                    "files": rels[:3],
                }
                for members, rels in shape_groups.items()
            ],
        })

    return problems, scanned


class DuplicateTypeDeclarationsCheck(CheckLayer):
    """Layer #10 — duplicate ``interface``/``type`` decls with differing shapes."""

    NAME = "duplicate_type_declarations"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "Same `interface X` or `type X = { … }` must not be declared in "
        "multiple files with conflicting member sets. Catches the silent "
        "partial-shape bug that survives tsc when the two decls are in "
        "disjoint scopes."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        ts_files = [p for p in find_ts_sources(root) if p.suffix in (".ts", ".tsx")]
        if not ts_files:
            return self._skip("No TS files in input")

        problems, scanned = find_duplicate_type_conflicts(root)

        if problems:
            shown = problems[:10]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(problems)} type name(s) duplicated with "
                    f"conflicting shapes ({scanned} file(s) scanned)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "conflicts": shown,
                    "truncated": len(problems) > 10,
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"No conflicting type duplicates across {scanned} file(s)",
            start_time=start,
            details={"files_scanned": scanned},
        )


__all__ = [
    "DuplicateTypeDeclarationsCheck",
    "find_duplicate_type_conflicts",
]
