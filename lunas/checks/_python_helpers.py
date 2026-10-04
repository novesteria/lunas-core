"""Shared utilities for the Python-stack check layers.

Centralizes:

- Python source-file discovery (skips virtualenvs, ``__pycache__``,
  ``node_modules``, build dirs).
- Stdlib module name set (uses ``sys.stdlib_module_names`` with a
  belt-and-braces fallback for older Python versions, though we
  require 3.11+ which always has the attribute).
- Local top-level package detection.
- Local module resolution (``foo.bar.baz`` → ``foo/bar/baz.py`` or
  ``foo/bar/baz/__init__.py``).

Used by ``python_imports``, ``python_completeness``,
``python_deps_completeness``, and ``router_prefix_consistency``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Directories never to descend into when collecting Python sources.
_SKIP_DIRS: frozenset[str] = frozenset(
    [
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "env",
        ".env",
        "virtualenv",
        "site-packages",
        "dist",
        "build",
        "coverage",
    ]
)


# Stdlib module names. Python 3.11+ always exposes this; the fallback
# is defensive for the unlikely case of a vendored stripped-down build.
STDLIB_NAMES: frozenset[str] = frozenset(
    getattr(sys, "stdlib_module_names", set())
    or {
        "abc", "argparse", "ast", "asyncio", "base64", "binascii",
        "bisect", "builtins", "calendar", "codecs", "collections",
        "concurrent", "contextlib", "copy", "csv", "dataclasses",
        "datetime", "decimal", "email", "enum", "errno", "fnmatch",
        "functools", "gc", "glob", "gzip", "hashlib", "heapq",
        "hmac", "http", "importlib", "inspect", "io", "ipaddress",
        "itertools", "json", "logging", "math", "multiprocessing",
        "operator", "os", "pathlib", "pickle", "platform", "queue",
        "random", "re", "select", "shutil", "signal", "socket",
        "sqlite3", "ssl", "stat", "string", "struct", "subprocess",
        "sys", "tempfile", "textwrap", "threading", "time", "tokenize",
        "traceback", "typing", "unittest", "urllib", "uuid", "warnings",
        "weakref", "xml", "zipfile", "zlib", "__future__",
    }
)


def is_python_source(root: Path, path: Path) -> bool:
    """True if ``path`` is a .py file inside ``root`` and not in a
    skip directory or dotfolder.
    """
    if not path.is_file() or path.suffix != ".py":
        return False
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    return not any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts)


def find_python_sources(root: Path) -> list[Path]:
    """Return all valid Python source files in ``root`` (recursive)."""
    return [p for p in root.rglob("*.py") if is_python_source(root, p)]


def find_local_top_names(root: Path) -> set[str]:
    """Return top-level package / module names that count as 'local'.

    A directory is local if it contains at least one .py file in a
    non-excluded subtree. A top-level .py file's stem is also local.
    """
    names: set[str] = set()
    if not root.is_dir():
        return names
    for child in root.iterdir():
        if not child.exists():
            continue
        rel_parts = child.relative_to(root).parts
        if any(part.startswith(".") or part in _SKIP_DIRS for part in rel_parts):
            continue
        if child.is_dir():
            for inner in child.rglob("*.py"):
                if is_python_source(root, inner):
                    names.add(child.name)
                    break
        elif child.is_file() and child.suffix == ".py":
            names.add(child.stem)
    return names


def resolve_local_module(root: Path, dotted: str) -> Path | None:
    """Resolve a dotted module name to a file path under ``root``.

    Tries:
    - ``a/b/c.py`` (file form)
    - ``a/b/c/__init__.py`` (package form)

    Returns the resolved path or None if neither exists.
    """
    if not dotted:
        return None
    parts = dotted.split(".")
    if not parts:
        return None
    base = root
    for part in parts:
        base = base / part
    file_form = base.with_suffix(".py")
    if file_form.exists():
        return file_form
    pkg_form = base / "__init__.py"
    if pkg_form.exists():
        return pkg_form
    return None


__all__ = [
    "STDLIB_NAMES",
    "is_python_source",
    "find_python_sources",
    "find_local_top_names",
    "resolve_local_module",
]
