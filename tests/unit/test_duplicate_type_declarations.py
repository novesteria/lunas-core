"""Unit tests for ``lunas.checks.duplicate_type_declarations``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.duplicate_type_declarations import (
    DuplicateTypeDeclarationsCheck,
    find_duplicate_type_conflicts,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = DuplicateTypeDeclarationsCheck()
    assert layer.NAME == "duplicate_type_declarations"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_layer_skipped_no_ts(tmp_path):
    layer = DuplicateTypeDeclarationsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_single_declaration_passes(tmp_path):
    (tmp_path / "types.ts").write_text(
        "export interface Coin { id: string; name: string; }\n"
    )
    problems, _ = find_duplicate_type_conflicts(tmp_path)
    assert problems == []


def test_identical_shape_merged_not_flagged(tmp_path):
    """TS interface merging is intentional — same shape in two files is OK."""
    (tmp_path / "a.ts").write_text("interface Coin { id: string; name: string; }\n")
    (tmp_path / "b.ts").write_text("interface Coin { id: string; name: string; }\n")
    problems, _ = find_duplicate_type_conflicts(tmp_path)
    assert problems == []


def test_different_shapes_flagged(tmp_path):
    """Canonical bug: two files declare Coin with different fields."""
    (tmp_path / "types.ts").write_text(
        "export interface Coin { id: string; name: string; symbol: string; price: number; }\n"
    )
    (tmp_path / "Grid.tsx").write_text(
        "interface Coin { name: string; value: number; }\n"
    )
    problems, _ = find_duplicate_type_conflicts(tmp_path)
    assert len(problems) == 1
    assert problems[0]["name"] == "Coin"
    assert problems[0]["distinct_files"] == 2
    assert problems[0]["shape_count"] == 2


def test_type_alias_object_literal(tmp_path):
    """`type X = { … }` should also be matched."""
    (tmp_path / "a.ts").write_text("type User = { id: string; name: string; }\n")
    (tmp_path / "b.ts").write_text("type User = { id: string; }\n")
    problems, _ = find_duplicate_type_conflicts(tmp_path)
    assert len(problems) == 1
    assert problems[0]["name"] == "User"


def test_imported_name_not_flagged(tmp_path):
    """If a file explicitly imports the name, the local re-decl is a
    deliberate shadow — don't flag."""
    (tmp_path / "types.ts").write_text(
        "export interface Coin { id: string; name: string; }\n"
    )
    (tmp_path / "Grid.tsx").write_text(
        "import { Coin } from './types'\n"
        "interface Coin { value: number; }\n"  # local shadow on purpose
    )
    problems, _ = find_duplicate_type_conflicts(tmp_path)
    assert problems == []


def test_layer_full_pass(tmp_path):
    (tmp_path / "types.ts").write_text("interface Foo { x: number; }\n")
    layer = DuplicateTypeDeclarationsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.passed


def test_layer_full_fail(tmp_path):
    (tmp_path / "a.ts").write_text("interface Coin { id: string; name: string; price: number; }\n")
    (tmp_path / "b.ts").write_text("interface Coin { name: string; value: number; }\n")
    layer = DuplicateTypeDeclarationsCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["conflicts"][0]["name"] == "Coin"
