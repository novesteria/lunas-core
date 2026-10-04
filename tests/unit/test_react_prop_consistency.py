"""Unit tests for ``lunas.checks.react_prop_consistency``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.react_prop_consistency import (
    ReactPropConsistencyCheck,
    collect_component_props,
)
from lunas.result import LayerKind, Verdict


def test_layer_metadata():
    layer = ReactPropConsistencyCheck()
    assert layer.NAME == "react_prop_consistency"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_collects_interface_props(tmp_path):
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { title: string; subtitle?: string; }\n"
        "export const Card = (p: CardProps) => <div>{p.title}</div>\n"
    )
    components, extensible = collect_component_props(
        list(tmp_path.glob("*.tsx"))
    )
    assert components == {"Card": {"title", "subtitle"}}
    assert extensible == set()


def test_collects_type_alias_props(tmp_path):
    (tmp_path / "Btn.tsx").write_text(
        "type BtnProps = { label: string; onClick: () => void; }\n"
    )
    components, extensible = collect_component_props(
        list(tmp_path.glob("*.tsx"))
    )
    assert components == {"Btn": {"label", "onClick"}}


def test_extends_marks_extensible(tmp_path):
    (tmp_path / "X.tsx").write_text(
        "interface XProps extends HTMLAttributes<HTMLDivElement> {\n"
        "  custom: string;\n"
        "}\n"
    )
    components, extensible = collect_component_props(
        list(tmp_path.glob("*.tsx"))
    )
    # The decl_re also captures the body, but extension_re separately
    # marks the component extensible — strict check should skip it.
    assert "X" in extensible


def test_passes_clean_jsx_usage(tmp_path):
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { title: string; }\n"
        "const Card = (p: CardProps) => <div>{p.title}</div>\n"
        "const Page = () => <Card title=\"hi\" />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_fails_on_undeclared_prop(tmp_path):
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { coin: string; }\n"
        "const Card = (p: CardProps) => <div>{p.coin}</div>\n"
        "const Page = () => <Card crypto=\"BTC\" />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    problem = result.details["problems"][0]
    assert problem["component"] == "Card"
    assert "crypto" in problem["undeclared"]


def test_extensible_component_not_flagged(tmp_path):
    (tmp_path / "X.tsx").write_text(
        "interface XProps extends HTMLAttributes<HTMLDivElement> {}\n"
        "const X = (p: XProps) => <div {...p} />\n"
        "const P = () => <X anything=\"goes\" />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict in (Verdict.skipped, Verdict.passed)


def test_builtin_attrs_ignored(tmp_path):
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { title: string; }\n"
        "const Card = (p: CardProps) => <div>{p.title}</div>\n"
        "const P = () => <Card title=\"x\" className=\"c\" onClick={() => 0} />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_html_element_not_flagged(tmp_path):
    """``<div data-foo>`` is not a registered component — never flag."""
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { title: string; }\n"
        "const Card = (p: CardProps) => <div>{p.title}</div>\n"
        "const P = () => <div anything=\"goes\" />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_skipped_no_tsx(tmp_path):
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    assert layer.run(ctx).verdict == Verdict.skipped


def test_spread_props_disables_check(tmp_path):
    (tmp_path / "Card.tsx").write_text(
        "interface CardProps { title: string; }\n"
        "const Card = (p: CardProps) => <div>{p.title}</div>\n"
        "const P = (rest) => <Card title=\"x\" {...rest} />\n"
    )
    layer = ReactPropConsistencyCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    # spread → conservative skip → no problems found
    assert result.verdict == Verdict.passed
