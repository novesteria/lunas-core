"""Deterministic tsconfig normalizations run before ``tsc``.

Two repairs applied to the root ``tsconfig.json`` so a config that would make
``tsc`` die on an unrelated error (not the user's type bug) does not produce a
misleading failure:

1. Degenerate root rebuild — a root ``tsconfig.json`` with none of
   ``compilerOptions`` / ``references`` / ``files`` / ``extends`` does nothing.
   ``tsc`` then falls back to ES5 defaults and reports phantom errors such as
   "Cannot find global value 'Promise'" (TS2468) and Map/Set errors (TS2583)
   raised inside ``node_modules`` ``.d.ts`` files. Rebuild it as a
   solution-style root when a sibling ``tsconfig.app.json`` /
   ``tsconfig.node.json`` exists, else as a complete vite-react config.
   Recognizable fragments are preserved: a stray ``@/*`` paths entry at root
   level moves under ``compilerOptions.paths``; ``exclude`` is kept.
2. Narrow lib / stale target — a ``lib`` array with no ES2015+ member gains
   ``ES2020``; an ``es3``/``es5`` ``target`` bumps to ``ES2020``. Healthy
   configs are left untouched.

The pure functions do no I/O. ``repair_root_tsconfig_file`` is the one wrapper
that reads/writes a single root tsconfig for the tsc layer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_STRUCTURAL_KEYS = ('"compilerOptions"', '"references"', '"files"', '"extends"')

_MODERN_ES = re.compile(r"es(20(1[5-9]|2\d)|next)", re.IGNORECASE)
_LIB_ARRAY = re.compile(r'("lib"\s*:\s*)\[([^\]]*)\]')
_OLD_TARGET = re.compile(r'("target"\s*:\s*")(es[35])(")', re.IGNORECASE)


def is_degenerate_root(text: str) -> bool:
    """True when a root tsconfig has NONE of the keys that make a tsconfig do
    anything (compilerOptions / references / files / extends)."""
    if not (text or "").strip():
        return True
    return not any(k in text for k in _STRUCTURAL_KEYS)


def repair_root_tsconfig(
    text: str, *, has_app_ref: bool = False, has_node_ref: bool = False
) -> str | None:
    """Rebuild a degenerate root tsconfig. Returns the new text, or ``None``
    when the input is healthy (has structural keys) and must be left alone."""
    if not is_degenerate_root(text):
        return None

    # Salvage recognizable fragments from the garbage (usually valid JSON, but
    # never assume).
    exclude = None
    paths = None
    try:
        obj = json.loads(text or "{}")
        if isinstance(obj, dict):
            if isinstance(obj.get("exclude"), list):
                exclude = obj["exclude"]
            # A stray alias entry at root level (`"@/*": [...]`) is a paths
            # fragment that belongs under compilerOptions.paths.
            stray = {
                k: v
                for k, v in obj.items()
                if isinstance(v, list) and ("*" in k or k.startswith("@"))
            }
            if stray:
                paths = stray
    except Exception:
        pass

    if has_app_ref or has_node_ref:
        # Solution-style root: real compilerOptions live in the referenced
        # projects; the root only wires them together for `tsc -b`.
        out: dict[str, Any] = {"files": []}
        refs = []
        if has_app_ref:
            refs.append({"path": "./tsconfig.app.json"})
        if has_node_ref:
            refs.append({"path": "./tsconfig.node.json"})
        out["references"] = refs
        if exclude:
            out["exclude"] = exclude
        return json.dumps(out, indent=2) + "\n"

    # Standalone: a complete, sane vite-react config.
    comp: dict[str, Any] = {
        "target": "ES2020",
        "useDefineForClassFields": True,
        "lib": ["ES2020", "DOM", "DOM.Iterable"],
        "module": "ESNext",
        "skipLibCheck": True,
        "moduleResolution": "bundler",
        "resolveJsonModule": True,
        "isolatedModules": True,
        "noEmit": True,
        "jsx": "react-jsx",
        "strict": True,
    }
    if paths:
        comp["baseUrl"] = "."
        comp["paths"] = paths
    out = {"compilerOptions": comp, "include": ["src"]}
    if exclude:
        out["exclude"] = exclude
    return json.dumps(out, indent=2) + "\n"


def fix_narrow_lib(text: str) -> str | None:
    """Text-based (tsconfig is jsonc — parse/reserialize would eat comments):
    add ``ES2020`` to a ``lib`` array with no ES2015+ member, bump an
    ``es3``/``es5`` ``target``. Returns new text or ``None`` when healthy."""
    new = text or ""

    def _lib_sub(m: re.Match[str]) -> str:
        members = m.group(2)
        if _MODERN_ES.search(members):
            return m.group(0)
        if members.strip():
            return f'{m.group(1)}["ES2020", {members.strip()}]'
        return f'{m.group(1)}["ES2020"]'

    new = _LIB_ARRAY.sub(_lib_sub, new)
    new = _OLD_TARGET.sub(r"\g<1>ES2020\g<3>", new)
    return new if new != (text or "") else None


def repair_root_tsconfig_file(root: Path) -> list[str]:
    """Read ``root/tsconfig.json``, apply both repairs (checking for sibling
    ``tsconfig.app.json`` / ``tsconfig.node.json`` for the references case),
    and write it back if anything changed. Returns notes (empty when nothing
    needed fixing)."""
    notes: list[str] = []
    path = root / "tsconfig.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return notes

    new = text
    rebuilt = repair_root_tsconfig(
        new,
        has_app_ref=(root / "tsconfig.app.json").exists(),
        has_node_ref=(root / "tsconfig.node.json").exists(),
    )
    if rebuilt is not None:
        new = rebuilt
        notes.append("degenerate root rebuilt")

    lib_fixed = fix_narrow_lib(new)
    if lib_fixed is not None:
        new = lib_fixed
        notes.append("lib/target raised to ES2020")

    if new != text:
        try:
            path.write_text(new, encoding="utf-8")
        except OSError:
            return []
    return notes


__all__ = [
    "is_degenerate_root",
    "repair_root_tsconfig",
    "fix_narrow_lib",
    "repair_root_tsconfig_file",
]
