"""Unit tests for ``lunas.checks.hook_destructure_consistency``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.hook_destructure_consistency import (
    HookDestructureConsistencyCheck,
    _keys_from_object_literal,
    collect_hook_returns,
    find_hook_destructure_problems,
)
from lunas.result import LayerKind, Verdict

# ----- _keys_from_object_literal pure -----------------------------------


def test_simple_keys():
    keys = _keys_from_object_literal("a, b, c")
    assert keys == {"a", "b", "c"}


def test_keys_with_values():
    keys = _keys_from_object_literal("a: 1, b: 2")
    assert keys == {"a", "b"}


def test_spread_returns_none():
    """A spread inside the object means we can't enumerate confidently."""
    assert _keys_from_object_literal("a, b, ...rest") is None


def test_computed_key_returns_none():
    assert _keys_from_object_literal("[foo]: bar") is None


def test_nested_object_ok():
    keys = _keys_from_object_literal("a, b: { x: 1 }, c")
    assert keys == {"a", "b", "c"}


# ----- collect_hook_returns ---------------------------------------------


def test_collects_function_hook(tmp_path):
    (tmp_path / "useThing.ts").write_text(
        "export function useThing() {\n"
        "  const data = 1\n"
        "  return { data, loading: false }\n"
        "}\n"
    )
    hooks = collect_hook_returns(list(tmp_path.glob("*.ts")))
    assert hooks == {"useThing": {"data", "loading"}}


def test_collects_arrow_hook_concise(tmp_path):
    (tmp_path / "useArrow.ts").write_text(
        "export const useArrow = () => ({ a, b })\n"
    )
    hooks = collect_hook_returns(list(tmp_path.glob("*.ts")))
    assert hooks == {"useArrow": {"a", "b"}}


def test_collects_arrow_hook_block(tmp_path):
    (tmp_path / "useBlock.ts").write_text(
        "export const useBlock = () => {\n"
        "  return { x, y, z }\n"
        "}\n"
    )
    hooks = collect_hook_returns(list(tmp_path.glob("*.ts")))
    assert hooks["useBlock"] == {"x", "y", "z"}


def test_unconfident_hook_dropped(tmp_path):
    """Spread in the return → hook is dropped from the audit."""
    (tmp_path / "useSpread.ts").write_text(
        "export function useSpread() { return { a, ...rest } }\n"
    )
    hooks = collect_hook_returns(list(tmp_path.glob("*.ts")))
    assert "useSpread" not in hooks


# ----- find_hook_destructure_problems -----------------------------------


def test_clean_destructure_passes(tmp_path):
    (tmp_path / "hooks.ts").write_text(
        "export function useCoins() { return { coins, isLoading } }\n"
    )
    (tmp_path / "Dashboard.tsx").write_text(
        "import { useCoins } from './hooks'\n"
        "const Dashboard = () => {\n"
        "  const { coins, isLoading } = useCoins()\n"
        "  return null\n"
        "}\n"
    )
    problems, _, audited = find_hook_destructure_problems(tmp_path)
    assert problems == []
    assert audited == 1


def test_drift_flagged(tmp_path):
    (tmp_path / "hooks.ts").write_text(
        "export function useCoins() { return { coins, isLoading } }\n"
    )
    (tmp_path / "Dashboard.tsx").write_text(
        "import { useCoins } from './hooks'\n"
        "const Dashboard = () => {\n"
        "  const { coins, isLoading, lastUpdated } = useCoins()\n"
        "  return null\n"
        "}\n"
    )
    problems, _, _ = find_hook_destructure_problems(tmp_path)
    assert len(problems) == 1
    assert problems[0]["hook"] == "useCoins"
    assert "lastUpdated" in problems[0]["missing"]


def test_consumer_only_subset_passes(tmp_path):
    """Consumer using a subset of return fields is fine."""
    (tmp_path / "hooks.ts").write_text(
        "export function useThing() { return { a, b, c } }\n"
    )
    (tmp_path / "use.ts").write_text(
        "import { useThing } from './hooks'\n"
        "const { a } = useThing()\n"
    )
    problems, _, _ = find_hook_destructure_problems(tmp_path)
    assert problems == []


# ----- Full layer ------------------------------------------------------


def test_layer_metadata():
    layer = HookDestructureConsistencyCheck()
    assert layer.NAME == "hook_destructure_consistency"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_layer_skipped_no_ts(tmp_path):
    layer = HookDestructureConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_skipped_when_no_hooks(tmp_path):
    (tmp_path / "plain.ts").write_text("export const x = 1\n")
    layer = HookDestructureConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_layer_full_fail(tmp_path):
    (tmp_path / "hooks.ts").write_text(
        "export function useThing() { return { a, b } }\n"
    )
    (tmp_path / "main.tsx").write_text(
        "import { useThing } from './hooks'\n"
        "const C = () => {\n"
        "  const { a, b, missing } = useThing()\n"
        "  return null\n"
        "}\n"
    )
    layer = HookDestructureConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["hooks_audited"] == 1
