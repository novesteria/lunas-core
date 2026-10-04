"""Layer #3 — Python third-party dependency declaration coverage.

Catches the *runtime* failure mode where pip install succeeds, the
import statement parses, but at first use the module raises
ImportError because a *transitive* dependency wasn't declared.

Canonical example: agent imports ``pydantic`` and uses ``EmailStr``,
but doesn't add ``email-validator`` to ``requirements.txt``. pip
install succeeds (pydantic itself installs fine), the file compiles
(EmailStr is a name in pydantic), pytest may pass if nothing uses
that schema — but when the FastAPI app boots and validates a schema
with EmailStr, it raises ImportError.

Strategy:

1. Parse ``requirements.txt`` and/or ``pyproject.toml`` for declared
   package names (lowercased, normalized).
2. Walk every .py file, AST-collect import statements.
3. For each top-level module name imported, check:

   - stdlib → skip
   - matches a local top-level package → skip (the
     ``python_imports`` layer handles those)
   - declared in requirements/pyproject (with name-alias normalization,
     e.g. ``PIL`` → ``pillow``, ``yaml`` → ``pyyaml``) → skip
   - otherwise → MISSING

4. Special-case Pydantic ``EmailStr`` text-search: if any file
   references ``EmailStr`` and ``email-validator`` isn't declared,
   add a synthetic missing entry.
"""

from __future__ import annotations

import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks._python_helpers import (
    STDLIB_NAMES,
    find_local_top_names,
    find_python_sources,
)
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

# Common import-name → pkg-name aliases. Limited to the painful ones.
_PKG_ALIASES: dict[str, str] = {
    "pil": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "jose": "python-jose",
    "jwt": "pyjwt",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "magic": "python-magic",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "OpenSSL": "pyopenssl",
}

# Transitive deps that ship with common frameworks. When fastapi is
# declared, starlette + anyio + h11 are implicit; we don't flag them.
_TRANSITIVE_DEPS_FOR: dict[str, frozenset[str]] = {
    "fastapi": frozenset([
        "starlette", "anyio", "sniffio", "h11", "httptools",
        "typing_extensions", "typing-extensions", "idna",
        "click", "iniconfig", "pluggy",
    ]),
    "django": frozenset(["sqlparse", "asgiref", "tzdata"]),
    "flask": frozenset(["werkzeug", "jinja2", "markupsafe", "itsdangerous", "click", "blinker"]),
    "requests": frozenset(["urllib3", "certifi", "charset_normalizer", "idna"]),
    "httpx": frozenset(["httpcore", "anyio", "sniffio", "certifi", "h11", "idna"]),
    "pydantic": frozenset(["typing_extensions", "typing-extensions", "annotated-types"]),
}


@dataclass(frozen=True)
class DeclaredDeps:
    """Parsed dependency declarations from a project."""

    names: frozenset[str]
    """All declared package names, lowercased, dash-normalized."""

    has_requirements: bool
    has_pyproject: bool


def _parse_requirements_txt(path: Path) -> set[str]:
    """Extract package names from a requirements.txt file."""
    declared: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            # Strip version markers + extras: 'pkg==1.0', 'pkg[extra]>=1.0'
            name = re.split(r"[<>=!\[~;\s]", line, maxsplit=1)[0].strip().lower()
            if name:
                declared.add(name)
    except OSError:
        pass
    return declared


def _parse_pyproject_toml(path: Path) -> set[str]:
    """Extract package names from a pyproject.toml file via regex.

    We use regex rather than a TOML parser because we want zero
    dependencies and we don't need perfect parsing — false positives
    here are tolerable (we'd just under-flag a missing dep).
    """
    declared: set[str] = set()
    try:
        blob = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return declared

    # Poetry: [tool.poetry.dependencies] table with `pkg = "version"` lines
    for m in re.finditer(r'(?m)^["\']?([\w\-]+)["\']?\s*=\s*["\']', blob):
        declared.add(m.group(1).lower())

    # Quoted entries (also poetry / some PEP 621)
    for m in re.finditer(r'"([\w\-]+)\s*[<>=!~\[].*?"', blob):
        declared.add(m.group(1).lower())

    # PEP 621: dependencies = ["pkg", "pkg2>=1.0"]
    # Split on BOTH commas and newlines so we cover one-line and multi-line forms.
    for m in re.finditer(r"dependencies\s*=\s*\[([\s\S]*?)\]", blob):
        for part in re.split(r"[,\n]", m.group(1)):
            cleaned = part.strip().strip('"').strip("'")
            name = re.split(r"[<>=!\[~;\s]", cleaned, maxsplit=1)[0].strip().lower()
            if name and name.replace("-", "").replace("_", "").isalnum():
                declared.add(name)

    return declared


def parse_declared_deps(root: Path) -> DeclaredDeps:
    """Return all dependency names declared in requirements.txt +
    pyproject.toml under ``root``.
    """
    req = root / "requirements.txt"
    pyp = root / "pyproject.toml"

    declared: set[str] = set()
    if req.exists():
        declared.update(_parse_requirements_txt(req))
    if pyp.exists():
        declared.update(_parse_pyproject_toml(pyp))

    # Add transitive deps when their parent framework is declared
    extras: set[str] = set()
    for parent, transitives in _TRANSITIVE_DEPS_FOR.items():
        if parent in declared:
            extras.update(transitives)
    declared.update(extras)

    return DeclaredDeps(
        names=frozenset(declared),
        has_requirements=req.exists(),
        has_pyproject=pyp.exists(),
    )


def _is_declared(top_module: str, declared: DeclaredDeps) -> bool:
    """True if ``top_module`` is declared (with alias + dash/underscore
    normalization)."""
    candidate = _PKG_ALIASES.get(top_module, top_module).lower()
    if candidate in declared.names:
        return True
    if top_module.lower() in declared.names:
        return True
    if candidate.replace("_", "-") in declared.names:
        return True
    return top_module.lower().replace("_", "-") in declared.names


def find_undeclared_deps(
    root: Path,
    declared: DeclaredDeps | None = None,
) -> tuple[dict[str, list[str]], int]:
    """Find top-level modules imported but not declared in
    requirements/pyproject.

    Returns ({pkg_name: [files_that_import_it]}, files_scanned).
    """
    if declared is None:
        declared = parse_declared_deps(root)

    local_top_names = find_local_top_names(root)
    py_files = find_python_sources(root)
    missing: dict[str, list[str]] = {}
    scanned = 0

    for py in py_files:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, ValueError):
            continue
        scanned += 1
        rel = py.relative_to(root).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if not top or top in STDLIB_NAMES or top in local_top_names:
                        continue
                    if not _is_declared(top, declared):
                        pkg = _PKG_ALIASES.get(top, top).lower()
                        missing.setdefault(pkg, []).append(rel)
            elif isinstance(node, ast.ImportFrom):
                if (node.level or 0) > 0 or not node.module:
                    continue
                top = node.module.split(".", 1)[0]
                if top in STDLIB_NAMES or top in local_top_names:
                    continue
                if not _is_declared(top, declared):
                    pkg = _PKG_ALIASES.get(top, top).lower()
                    missing.setdefault(pkg, []).append(rel)

    # Special-case pydantic.EmailStr → requires email-validator
    email_validator_satisfied = any(
        n in declared.names for n in ("email-validator", "email_validator")
    ) or any(
        d.startswith("pydantic[") and "email" in d for d in declared.names
    )
    if not email_validator_satisfied:
        for py in py_files:
            try:
                src = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "EmailStr" in src and "pydantic" in src:
                rel = py.relative_to(root).as_posix()
                missing.setdefault("email-validator", []).append(
                    f"{rel} (pydantic.EmailStr requires email-validator)"
                )
                break

    return missing, scanned


class PythonDepsCompletenessCheck(CheckLayer):
    """Layer #3 — third-party Python imports must be declared."""

    NAME = "python_deps_completeness"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("python",)
    DESCRIPTION = (
        "Every imported third-party Python module must be declared in "
        "requirements.txt or pyproject.toml. Catches the canonical "
        "'pip install succeeds, runtime ImportError' bug."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        declared = parse_declared_deps(root)
        if not declared.has_requirements and not declared.has_pyproject:
            return self._skip("No requirements.txt or pyproject.toml")

        if not find_python_sources(root):
            return self._skip("No .py files in input")

        missing, scanned = find_undeclared_deps(root, declared)

        if missing:
            shown = sorted(missing.keys())[:20]
            details_missing = []
            for pkg in shown:
                files = missing[pkg]
                details_missing.append(
                    {"package": pkg, "imported_in": files[0], "occurrences": len(files)}
                )
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(missing)} undeclared third-party module(s) "
                    f"across {scanned} file(s)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "declared_count": len(declared.names),
                    "missing": details_missing,
                    "truncated": len(missing) > 20,
                },
            )

        return self._result(
            Verdict.passed,
            summary=f"All third-party imports declared ({scanned} files, {len(declared.names)} declarations)",
            start_time=start,
            details={
                "files_scanned": scanned,
                "declared_count": len(declared.names),
            },
        )


__all__ = [
    "PythonDepsCompletenessCheck",
    "DeclaredDeps",
    "parse_declared_deps",
    "find_undeclared_deps",
]
