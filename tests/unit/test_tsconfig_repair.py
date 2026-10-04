"""Unit tests for ``lunas.checks._tsconfig_repair``."""

from __future__ import annotations

import json

from lunas.checks._tsconfig_repair import (
    fix_narrow_lib,
    is_degenerate_root,
    repair_root_tsconfig,
    repair_root_tsconfig_file,
)


def test_degenerate_detection():
    assert is_degenerate_root('{ "@/*": ["src/*"] }') is True
    assert is_degenerate_root("") is True
    assert is_degenerate_root('{ "compilerOptions": { "strict": true } }') is False
    assert is_degenerate_root('{ "extends": "./base.json" }') is False


def test_healthy_root_untouched():
    healthy = '{ "compilerOptions": { "target": "ES2020" } }'
    assert repair_root_tsconfig(healthy) is None


def test_degenerate_standalone_rebuild_salvages_paths_and_exclude():
    text = '{ "@/*": ["src/*"], "exclude": ["dist"] }'
    out = repair_root_tsconfig(text)
    assert out is not None
    cfg = json.loads(out)
    assert cfg["compilerOptions"]["target"] == "ES2020"
    assert cfg["compilerOptions"]["paths"] == {"@/*": ["src/*"]}
    assert cfg["compilerOptions"]["baseUrl"] == "."
    assert cfg["exclude"] == ["dist"]
    # A rebuilt standalone config type-checks with modern globals available.
    assert "ES2020" in cfg["compilerOptions"]["lib"]


def test_degenerate_references_rebuild():
    out = repair_root_tsconfig("{}", has_app_ref=True, has_node_ref=True)
    assert out is not None
    cfg = json.loads(out)
    assert cfg["files"] == []
    paths = [r["path"] for r in cfg["references"]]
    assert "./tsconfig.app.json" in paths
    assert "./tsconfig.node.json" in paths


def test_fix_narrow_lib_adds_es2020():
    text = '{ "compilerOptions": { "lib": ["DOM"] } }'
    out = fix_narrow_lib(text)
    assert out is not None
    assert '"ES2020"' in out
    assert "DOM" in out


def test_fix_narrow_lib_leaves_modern_alone():
    text = '{ "compilerOptions": { "lib": ["ES2020", "DOM"] } }'
    assert fix_narrow_lib(text) is None


def test_fix_old_target_bumped():
    out = fix_narrow_lib('{ "compilerOptions": { "target": "es5" } }')
    assert out is not None
    assert "ES2020" in out
    assert '"es5"' not in out


def test_repair_root_file_writes_back(tmp_path):
    (tmp_path / "tsconfig.json").write_text('{ "@/*": ["src/*"] }')
    notes = repair_root_tsconfig_file(tmp_path)
    assert "degenerate root rebuilt" in notes
    cfg = json.loads((tmp_path / "tsconfig.json").read_text())
    assert "compilerOptions" in cfg


def test_repair_root_file_healthy_noop(tmp_path):
    original = '{ "compilerOptions": { "target": "ES2020", "lib": ["ES2020"] } }'
    (tmp_path / "tsconfig.json").write_text(original)
    notes = repair_root_tsconfig_file(tmp_path)
    assert notes == []
    assert (tmp_path / "tsconfig.json").read_text() == original
