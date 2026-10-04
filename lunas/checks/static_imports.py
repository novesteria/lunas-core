"""Layer #13 — every relative import / script src must resolve on disk.

The canonical vanilla-JS bug:

    // app.js
    import { computeTip } from './calc.js';   // calc.js doesn't exist

The file parses. The browser tries to load ``calc.js``, gets 404,
``computeTip`` is undefined, the app silently breaks.

Same failure mode for HTML:

    <script src="app.js"></script>            <!-- never generated -->
    <link rel="stylesheet" href="styles.css"> <!-- never generated -->

This layer walks every ``.html`` / ``.htm`` / ``.js`` / ``.mjs`` /
``.cjs`` / ``.ts`` / ``.tsx`` / ``.jsx`` file, extracts relative
imports and script/link references, and reports any that don't resolve
to an existing file.

Handles:

- TypeScript path aliases (``@/components/Foo``) by reading
  ``tsconfig.json``'s ``compilerOptions.paths`` + ``baseUrl``.
- Vite-style absolute paths (``/src/main.tsx``) by walking up to the
  served root (closest ancestor with ``index.html`` / ``vite.config`` /
  ``package.json``).
- Bare HTML specs (``<script src="app.js">`` in ``frontend/index.html``)
  resolved against the document's own directory.
- Extension-less imports (``import './calc'`` → tries ``.js``, ``.mjs``,
  ``.cjs``, ``.ts``, ``.tsx``, ``.jsx``).

Skips:

- Full URLs (``http://``, ``//``), inline schemes (``data:``, ``blob:``,
  ``mailto:``, ``tel:``, ``#``).
- Bare JS imports (``react``, ``@scope/pkg``) — those need ``npm install``
  to verify; Layer #5 covers them.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_SOURCE_EXTS: tuple[str, ...] = (
    ".html", ".htm", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
)
_TRY_EXTENSIONS: tuple[str, ...] = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


# JS: `import ... from 'X'` / `import 'X'` / `import('X')` / `require('X')`
_JS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""import\s+(?:[\s\S]+?\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
)

# HTML: <script src="X">, <link rel="stylesheet" href="X">.
_HTML_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"""<script\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<link\b[^>]*\brel\s*=\s*['"]stylesheet['"][^>]*\bhref\s*=\s*['"]([^'"]+)['"]""",
        re.IGNORECASE,
    ),
    re.compile(
        r"""<link\b[^>]*\bhref\s*=\s*['"]([^'"]+)['"][^>]*\brel\s*=\s*['"]stylesheet['"]""",
        re.IGNORECASE,
    ),
)


_EXTERNAL_PREFIXES: tuple[str, ...] = (
    "http://", "https://", "//", "data:", "blob:", "mailto:", "tel:", "#",
)
_HTML_EXTERNAL_PREFIXES: tuple[str, ...] = (
    *_EXTERNAL_PREFIXES, "javascript:",
)


@dataclass(frozen=True)
class TsAlias:
    """A tsconfig path-alias entry: ``"@/*": ["src/*"]`` → prefix +
    list of resolution directories."""

    prefix: str
    """Alias prefix without the trailing ``/*``. ``"@/*"`` → ``"@"``."""

    bases: tuple[Path, ...]
    """Resolved absolute base directories. Each comes from one entry
    of the ``paths`` list, with ``baseUrl`` applied and ``/*`` stripped."""


# Directories that hold design artifacts (wireframes / mockups). Their HTML
# ships intentionally-broken `<link>`/`<script>` refs to a design-system that
# is not on disk, so static-import resolution would false-fail on them. They
# are not product code and must be skipped.
_DESIGN_ARTIFACT_DIRS: frozenset[str] = frozenset(
    ["design", "designs", "wireframe", "wireframes", "mockup", "mockups"]
)
# Also skip build output — scanning compiled/minified HTML in dist/build/coverage
# produces false static-import failures.
_STATIC_SKIP_DIRS: frozenset[str] = frozenset(
    ["node_modules", "dist", "build", "coverage"]
) | _DESIGN_ARTIFACT_DIRS


def _is_source(root: Path, p: Path) -> bool:
    if not p.is_file() or p.suffix not in _SOURCE_EXTS:
        return False
    try:
        rel_parts = p.relative_to(root).parts
    except ValueError:
        return False
    return not any(
        part.startswith(".") or part.lower() in _STATIC_SKIP_DIRS
        for part in rel_parts
    )


def load_ts_aliases(root: Path) -> tuple[list[TsAlias], Path]:
    """Read ``tsconfig.json`` (if any) and return (alias list, base_url).

    Picks the SHALLOWEST tsconfig.json under ``root``. Strips JSON
    comments (``//`` and ``/* */``) and trailing commas before parsing.
    Returns ``([], root)`` if no tsconfig or parsing fails — the layer
    keeps working without aliases.
    """
    tsconfigs = [
        p for p in root.rglob("tsconfig.json")
        if "node_modules" not in p.parts
        and not any(part.startswith(".") for part in p.parts)
    ]
    if not tsconfigs:
        return [], root

    tsconfig = min(tsconfigs, key=lambda p: len(p.parts))
    try:
        text = tsconfig.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], root

    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    try:
        cfg = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return [], root

    co = cfg.get("compilerOptions") or {}
    base_url = co.get("baseUrl") or "."
    ts_base = (tsconfig.parent / base_url).resolve()
    paths = co.get("paths") or {}

    aliases: list[TsAlias] = []
    for alias_pat, resolutions in paths.items():
        if not isinstance(resolutions, list):
            continue
        clean_prefix = alias_pat[:-2] if alias_pat.endswith("/*") else alias_pat
        bases: list[Path] = []
        for r in resolutions:
            if not isinstance(r, str):
                continue
            clean_r = r[:-2] if r.endswith("/*") else r
            bases.append((ts_base / clean_r).resolve())
        if bases:
            aliases.append(TsAlias(prefix=clean_prefix, bases=tuple(bases)))

    return aliases, ts_base


def _try_candidate(candidate: Path) -> Path | None:
    """If ``candidate`` is a file, return it. Otherwise try appending
    each of ``_TRY_EXTENSIONS`` and the ``index.{ext}`` package form.
    """
    if candidate.exists() and candidate.is_file():
        return candidate
    # Append each extension — `tailwind.config` + `.js` =
    # `tailwind.config.js`. (Path.with_suffix would replace `.config`,
    # which is wrong here.)
    for ext in _TRY_EXTENSIONS:
        p = Path(str(candidate) + ext)
        if p.exists() and p.is_file():
            return p
    if candidate.is_dir():
        for ext in _TRY_EXTENSIONS:
            idx = candidate / f"index{ext}"
            if idx.exists():
                return idx
    return None


def _match_alias(spec: str, aliases: list[TsAlias]) -> tuple[str, tuple[Path, ...]] | None:
    """If ``spec`` matches an alias prefix, return (suffix, bases)."""
    for alias in aliases:
        if not alias.prefix:
            continue
        if spec == alias.prefix or spec.startswith(alias.prefix + "/"):
            suffix = spec[len(alias.prefix):].lstrip("/")
            return (suffix, alias.bases)
    return None


def _resolve_served_root(from_file: Path, project_root: Path) -> Path:
    """Walk up from ``from_file`` to the closest dir with index.html,
    vite.config.*, or package.json. That dir is the served-root for
    absolute ``/path`` specs. Falls back to ``from_file.parent``.
    """
    served = from_file.parent
    cur = from_file.parent
    while True:
        for marker in ("index.html", "vite.config.ts", "vite.config.js", "package.json"):
            if (cur / marker).exists():
                return cur
        if cur == project_root or cur.parent == cur:
            return served
        cur = cur.parent


def resolve_spec(
    from_file: Path,
    spec: str,
    project_root: Path,
    aliases: list[TsAlias],
) -> Path | None:
    """Resolve ``spec`` (relative path, tsconfig alias, or Vite-absolute)
    to an on-disk file. Returns None if nothing matches.

    Caller is responsible for filtering out external URLs and bare
    package specifiers before calling.
    """
    spec_clean = spec.split("?", 1)[0].split("#", 1)[0]

    alias_match = _match_alias(spec_clean, aliases)
    if alias_match is not None:
        suffix, bases = alias_match
        for base in bases:
            candidate = (base / suffix).resolve() if suffix else base
            hit = _try_candidate(candidate)
            if hit:
                return hit
        return None

    if spec_clean.startswith("/"):
        served_root = _resolve_served_root(from_file, project_root)
        candidate = (served_root / spec_clean.lstrip("/")).resolve()
        return _try_candidate(candidate)

    base = from_file.parent
    candidate = (base / spec_clean).resolve()
    return _try_candidate(candidate)


def _is_external_js(spec: str, aliases: list[TsAlias]) -> bool:
    if spec.startswith(_EXTERNAL_PREFIXES):
        return True
    if _match_alias(spec, aliases) is not None:
        return False
    # Bare specifier: node_deps_completeness territory.
    return not spec.startswith((".", "/"))


def find_unresolved_static_imports(
    root: Path,
) -> tuple[list[dict[str, str]], int]:
    """Walk ``root`` and report unresolvable relative imports / script srcs.

    Returns ``(missing, files_scanned)`` where each missing entry has
    keys ``file`` and ``spec``.
    """
    sources = [p for p in root.rglob("*") if _is_source(root, p)]
    if not sources:
        return [], 0

    aliases, _ = load_ts_aliases(root)

    missing: list[dict[str, str]] = []
    scanned = 0

    for src in sources:
        try:
            text = src.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        is_html = src.suffix.lower() in (".html", ".htm")
        patterns = _HTML_PATTERNS if is_html else _JS_PATTERNS

        for pat in patterns:
            for m in pat.finditer(text):
                spec = m.group(1).strip()
                if not spec:
                    continue
                if is_html:
                    if spec.startswith(_HTML_EXTERNAL_PREFIXES):
                        continue
                else:
                    if _is_external_js(spec, aliases):
                        continue
                resolved = resolve_spec(src, spec, root, aliases)
                if resolved is None:
                    missing.append({
                        "file": src.relative_to(root).as_posix(),
                        "spec": spec,
                    })

    return missing, scanned


class StaticImportsCheck(CheckLayer):
    """Layer #13 — relative imports and script/link refs must exist on disk."""

    NAME = "static_imports"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("static_html", "node")
    DESCRIPTION = (
        "Every relative `import`/`require`, `<script src=…>`, and "
        "stylesheet `<link href=…>` must resolve to a file on disk. "
        "Handles tsconfig path aliases and Vite-style absolute paths."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        sources = [p for p in root.rglob("*") if _is_source(root, p)]
        if not sources:
            return self._skip("No HTML/JS/TS files in input")

        missing, scanned = find_unresolved_static_imports(root)

        if missing:
            shown = missing[:30]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(missing)} relative import(s) / static reference(s) "
                    f"do not resolve ({scanned} file(s) scanned)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "missing": shown,
                    "truncated": len(missing) > 30,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"All relative imports / script srcs resolve "
                f"({scanned} file(s) scanned)"
            ),
            start_time=start,
            details={"files_scanned": scanned},
        )


__all__ = [
    "StaticImportsCheck",
    "TsAlias",
    "load_ts_aliases",
    "resolve_spec",
    "find_unresolved_static_imports",
]
