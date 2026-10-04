"""Unit tests for ``lunas.checks.named_import_consistency``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.named_import_consistency import (
    NamedImportConsistencyCheck,
    find_named_import_problems,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = NamedImportConsistencyCheck()
    assert layer.NAME == "named_import_consistency"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_layer_skipped_no_ts(tmp_path):
    layer = NamedImportConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_imported_name_exists_passes(tmp_path):
    (tmp_path / "types.ts").write_text("export interface CryptoAsset { id: string }\n")
    (tmp_path / "main.ts").write_text(
        "import { CryptoAsset } from './types'\nconst x: CryptoAsset = { id: 'a' }\n"
    )
    problems, scanned = find_named_import_problems(tmp_path)
    assert problems == []
    assert scanned == 2


def test_typo_in_imported_name_fails(tmp_path):
    """Canonical bug: target exports `CryptoAsset`, consumer imports `Cryptocurrency`."""
    (tmp_path / "types.ts").write_text("export interface CryptoAsset { id: string }\n")
    (tmp_path / "main.ts").write_text(
        "import { Cryptocurrency } from './types'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert len(problems) == 1
    assert problems[0]["imported_name"] == "Cryptocurrency"
    assert problems[0]["target"] == "types.ts"


def test_bare_specifier_skipped(tmp_path):
    """`from 'react'` (bare) is skipped — that's #8 territory."""
    (tmp_path / "main.tsx").write_text(
        "import { useState, NonExistent } from 'react'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert problems == []


def test_wildcard_reexport_skipped(tmp_path):
    """A target that does `export * from` is too broad to verify."""
    (tmp_path / "barrel.ts").write_text("export * from './internal'\n")
    (tmp_path / "main.ts").write_text(
        "import { AnyName } from './barrel'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert problems == []


def test_type_import_recognised(tmp_path):
    """`import { type X }` should be checked the same as `import { X }`."""
    (tmp_path / "types.ts").write_text("export type Foo = string\n")
    (tmp_path / "main.ts").write_text(
        "import { type Bar } from './types'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert len(problems) == 1
    assert problems[0]["imported_name"] == "Bar"


def test_export_function_recognised(tmp_path):
    (tmp_path / "utils.ts").write_text("export function helper() {}\n")
    (tmp_path / "main.ts").write_text(
        "import { helper } from './utils'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert problems == []


def test_named_reexport_chain_verified(tmp_path):
    """`export { X } from './foo'` re-export — target must export X."""
    (tmp_path / "src.ts").write_text("export const real = 1\n")
    (tmp_path / "barrel.ts").write_text(
        "export { missing } from './src'\n"
    )
    problems, _ = find_named_import_problems(tmp_path)
    assert any(p["imported_name"] == "missing" for p in problems)


def test_layer_full_passes(tmp_path):
    (tmp_path / "types.ts").write_text("export interface User { id: string }\n")
    (tmp_path / "app.ts").write_text("import { User } from './types'\n")
    layer = NamedImportConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.passed


def test_layer_full_fails(tmp_path):
    (tmp_path / "types.ts").write_text("export interface Foo { x: number }\n")
    (tmp_path / "app.ts").write_text("import { Bar } from './types'\n")
    layer = NamedImportConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["problems"][0]["imported_name"] == "Bar"
