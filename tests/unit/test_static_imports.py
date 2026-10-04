"""Unit tests for ``lunas.checks.static_imports``."""

from __future__ import annotations

import json

from lunas.checks.base import ValidationContext
from lunas.checks.static_imports import (
    StaticImportsCheck,
    find_unresolved_static_imports,
    load_ts_aliases,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = StaticImportsCheck()
    assert layer.NAME == "static_imports"
    assert LayerKind.deterministic == layer.KIND


def test_resolve_relative_js(tmp_path):
    (tmp_path / "calc.js").write_text("export const x = 1;")
    (tmp_path / "app.js").write_text("import { x } from './calc.js';")
    missing, scanned = find_unresolved_static_imports(tmp_path)
    assert missing == []
    assert scanned == 2


def test_missing_relative_flagged(tmp_path):
    """Canonical bug: `import './calc.js'` but calc.js doesn't exist."""
    (tmp_path / "app.js").write_text("import { x } from './calc.js';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert len(missing) == 1
    assert missing[0]["spec"] == "./calc.js"


def test_extension_less_resolution(tmp_path):
    """`import './calc'` should try .js extension."""
    (tmp_path / "calc.js").write_text("export const x = 1;")
    (tmp_path / "app.js").write_text("import { x } from './calc';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_skips_bare_specifier(tmp_path):
    """`from 'react'` is bare — Layer #8 covers it."""
    (tmp_path / "app.jsx").write_text("import React from 'react';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_skips_external_urls(tmp_path):
    (tmp_path / "p.html").write_text(
        '<script src="https://cdn.example.com/lib.js"></script>'
        '<link rel="stylesheet" href="//fonts.googleapis.com/x">'
    )
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_html_script_src_resolves(tmp_path):
    (tmp_path / "app.js").write_text("console.log('hi')")
    (tmp_path / "p.html").write_text('<script src="app.js"></script>')
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_html_script_src_missing(tmp_path):
    (tmp_path / "p.html").write_text('<script src="missing.js"></script>')
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert any(m["spec"] == "missing.js" for m in missing)


def test_html_stylesheet_resolves(tmp_path):
    (tmp_path / "styles.css").write_text("body {}")
    (tmp_path / "p.html").write_text(
        '<link rel="stylesheet" href="styles.css">'
    )
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_html_stylesheet_missing(tmp_path):
    (tmp_path / "p.html").write_text(
        '<link rel="stylesheet" href="missing.css">'
    )
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert any(m["spec"] == "missing.css" for m in missing)


def test_tsconfig_alias_resolves(tmp_path):
    """`@/foo` resolves to `src/foo.ts` when tsconfig.json declares it."""
    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "baseUrl": ".",
            "paths": {"@/*": ["src/*"]},
        }
    }))
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.ts").write_text("export const x = 1;")
    (src / "main.ts").write_text("import { x } from '@/foo';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []


def test_tsconfig_alias_missing(tmp_path):
    """`@/missing` should be flagged when alias resolves but file missing."""
    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}
    }))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.ts").write_text("import { x } from '@/missing';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert any("@/missing" in m["spec"] for m in missing)


def test_load_ts_aliases_returns_empty_when_no_tsconfig(tmp_path):
    aliases, base = load_ts_aliases(tmp_path)
    assert aliases == []


def test_layer_skipped_no_sources(tmp_path):
    layer = StaticImportsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_full_fail(tmp_path):
    (tmp_path / "app.js").write_text("import { x } from './nonexistent.js';")
    layer = StaticImportsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["static_html"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert len(result.details["missing"]) == 1


def test_query_hash_stripped(tmp_path):
    """`./calc.js?v=1` should be resolved as `./calc.js`."""
    (tmp_path / "calc.js").write_text("export const x = 1;")
    (tmp_path / "app.js").write_text("import { x } from './calc.js?v=1';")
    missing, _ = find_unresolved_static_imports(tmp_path)
    assert missing == []
