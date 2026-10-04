"""Shared utilities for the Node-stack check layers.

Centralizes:

- JS/TS/JSX/TSX/MJS/CJS source-file discovery (skips ``node_modules``,
  hidden dirs, build output).
- Node built-in module name set.
- ``package.json`` parsing (deps / devDeps / peerDeps / optionalDeps).
- Import-specifier extraction via regex (static, dynamic, require,
  re-export).

Used by ``node_deps_completeness`` and the upcoming Node-AST layers in
Batch C.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Node built-in modules. ``import fs from 'fs'`` is always valid; no
# package.json entry needed. Kept narrow (no third-party-shipped
# polyfills) to avoid masking missing-dep bugs.
NODE_BUILTINS: frozenset[str] = frozenset(
    [
        "assert", "async_hooks", "buffer", "child_process", "cluster",
        "console", "crypto", "dgram", "dns", "events", "fs", "http",
        "http2", "https", "inspector", "module", "net", "os", "path",
        "perf_hooks", "process", "punycode", "querystring", "readline",
        "repl", "stream", "string_decoder", "timers", "tls", "tty",
        "url", "util", "v8", "vm", "worker_threads", "zlib",
    ]
)


# Source-file extensions that participate in dep checking.
NODE_SOURCE_EXTENSIONS: tuple[str, ...] = (
    "*.ts", "*.tsx", "*.js", "*.jsx", "*.mjs", "*.cjs",
)


# Directories we never descend into. `coverage` holds instrumented / report
# output; scanning it produces false positives just like `dist`/`build`.
_SKIP_DIRS: frozenset[str] = frozenset(["node_modules", "dist", "build", "coverage"])


def is_node_source(root: Path, path: Path) -> bool:
    """True if ``path`` is a JS/TS source under ``root`` outside skip dirs."""
    if not path.is_file():
        return False
    if path.suffix.lower() not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        return False
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts)


def find_node_sources(root: Path) -> list[Path]:
    """Return all JS/TS source files in ``root``, skipping deps + build dirs."""
    out: list[Path] = []
    for ext in NODE_SOURCE_EXTENSIONS:
        for p in root.rglob(ext):
            if is_node_source(root, p):
                out.append(p)
    return out


def load_package_json(root: Path) -> dict[str, Any] | None:
    """Parse ``root/package.json``. Returns dict or None if missing/invalid."""
    pkg_path = root / "package.json"
    if not pkg_path.exists():
        return None
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def declared_deps(pkg: dict[str, Any]) -> set[str]:
    """Collect declared package names from all dependency tables."""
    declared: set[str] = set()
    for key in ("dependencies", "devDependencies",
                "peerDependencies", "optionalDependencies"):
        table = pkg.get(key) or {}
        if isinstance(table, dict):
            declared.update(table.keys())
    return declared


# `import { a, b } from 'pkg'` — the from-clause may span newlines, so
# `[\s\S]+?` is used. A bare `import 'pkg'` (side-effect) wouldn't match
# here because the lazy non-empty body would consume across newlines to
# find a later `from` and steal the spec; we detect side-effect imports
# with a separate, simpler regex.
_IMPORT_FROM_RE = re.compile(
    r"""(?:^|[\s\(])import\s+[\s\S]+?\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
# Side-effect-only: `import 'pkg'` (no identifiers, no `from`).
_SIDE_EFFECT_RE = re.compile(
    r"""(?:^|[\s;])import\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)
# Dynamic: `import('pkg')`
_DYNAMIC_RE = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""")
# CommonJS: `require('pkg')`
_REQUIRE_RE = re.compile(r"""\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)""")
# Re-export: `export ... from 'pkg'`
_EXPORT_RE = re.compile(
    r"""(?:^|[\s\(])export\s+[\s\S]+?\s+from\s+['"]([^'"]+)['"]""",
    re.MULTILINE,
)


def extract_import_specifiers(source: str) -> set[str]:
    """Pull every import / require / re-export specifier from ``source``."""
    specs: set[str] = set()
    for pat in (
        _IMPORT_FROM_RE,
        _SIDE_EFFECT_RE,
        _DYNAMIC_RE,
        _REQUIRE_RE,
        _EXPORT_RE,
    ):
        for m in pat.finditer(source):
            specs.add(m.group(1))
    return specs


def package_root_of(spec: str) -> str:
    """Reduce an import spec to the root package name.

    Strips query/hash, then:
    - ``"lodash/fp"`` → ``"lodash"``
    - ``"@scope/pkg/sub"`` → ``"@scope/pkg"``
    - ``"./local"`` / ``"../up"`` / ``"/abs"`` → ``""`` (not a package)
    - ``"node:fs"`` → ``""`` (caller handles builtins)
    - ``""`` if input is empty after cleaning
    """
    spec_clean = spec.split("?", 1)[0].split("#", 1)[0]
    if not spec_clean:
        return ""
    if spec_clean.startswith(("./", "../", "/")):
        return ""
    if spec_clean.startswith("node:"):
        return ""
    if spec_clean.startswith("@"):
        # `@/x` (empty scope) and `@x` (no separator) are LOCAL path aliases
        # from a vite/tsconfig `paths` mapping, NOT npm scoped packages. A real
        # scoped package is always `@scope/name` with a non-empty scope. Without
        # this guard every `@/components` import is flagged as an undeclared
        # dependency, which false-fails essentially any Vite/Next/CRA project.
        if spec_clean.startswith("@/") or "/" not in spec_clean:
            return ""
        parts = spec_clean.split("/", 2)
        return "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
    return spec_clean.split("/", 1)[0]


__all__ = [
    "NODE_BUILTINS",
    "NODE_SOURCE_EXTENSIONS",
    "is_node_source",
    "find_node_sources",
    "load_package_json",
    "declared_deps",
    "extract_import_specifiers",
    "package_root_of",
]
