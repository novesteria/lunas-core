# Lunas Validator — Layer Index

This is the canonical list of every layer Lunas runs, in pipeline
execution order. The registry source is
[`lunas/checks/__init__.py`](../lunas/checks/__init__.py).

## Summary

| Kind | Count |
|---|---|
| Deterministic | 19 |
| Hybrid (LLM + deterministic override) | 2 |
| **Total** | **21** |

## Numbering

Before the checks run, the pipeline performs three preparatory stages
(stack detection, code-path materialisation, environment setup). They
are not check layers and are not counted. The 21 check layers are
numbered #1 to #21 below.

## Layers

| # | Name | Kind | Applies to | Source |
|---|---|---|---|---|
| 1 | `python_imports` | deterministic | python | [`lunas/checks/python_imports.py`](../lunas/checks/python_imports.py) |
| 2 | `python_completeness` | deterministic | python | [`lunas/checks/python_completeness.py`](../lunas/checks/python_completeness.py) |
| 3 | `python_deps_completeness` | deterministic | python | [`lunas/checks/python_deps_completeness.py`](../lunas/checks/python_deps_completeness.py) |
| 4 | `router_prefix_consistency` | deterministic | python | [`lunas/checks/router_prefix_consistency.py`](../lunas/checks/router_prefix_consistency.py) |
| 5 | `node_deps_completeness` | deterministic | node | [`lunas/checks/node_deps_completeness.py`](../lunas/checks/node_deps_completeness.py) |
| 6 | `css_completeness` | deterministic | node, static_html | [`lunas/checks/css_completeness.py`](../lunas/checks/css_completeness.py) |
| 7 | `react_prop_consistency` | deterministic | node | [`lunas/checks/react_prop_consistency.py`](../lunas/checks/react_prop_consistency.py) |
| 8 | `named_import_consistency` | deterministic | node | [`lunas/checks/named_import_consistency.py`](../lunas/checks/named_import_consistency.py) |
| 9 | `import_case_consistency` | deterministic | node, python | [`lunas/checks/import_case_consistency.py`](../lunas/checks/import_case_consistency.py) |
| 10 | `duplicate_type_declarations` | deterministic | node | [`lunas/checks/duplicate_type_declarations.py`](../lunas/checks/duplicate_type_declarations.py) |
| 11 | `hook_destructure_consistency` | deterministic | node | [`lunas/checks/hook_destructure_consistency.py`](../lunas/checks/hook_destructure_consistency.py) |
| 12 | `ast_brace_balance` | deterministic | node, static_html | [`lunas/checks/brace_balance.py`](../lunas/checks/brace_balance.py) |
| 13 | `static_imports` | deterministic | node, static_html | [`lunas/checks/static_imports.py`](../lunas/checks/static_imports.py) |
| 14 | `html_js_id_parity` | deterministic | static_html, node | [`lunas/checks/html_js_id_parity.py`](../lunas/checks/html_js_id_parity.py) |
| 15 | `interactivity` | deterministic | static_html, node | [`lunas/checks/interactivity.py`](../lunas/checks/interactivity.py) |
| 16 | `js_syntax` | deterministic | static_html, node | [`lunas/checks/js_syntax.py`](../lunas/checks/js_syntax.py) |
| 17 | `npm_install` | deterministic | node | [`lunas/checks/npm_install.py`](../lunas/checks/npm_install.py) |
| 18 | `tsc` | deterministic | node | [`lunas/checks/tsc.py`](../lunas/checks/tsc.py) |
| 19 | `pytest` | deterministic | python | [`lunas/checks/pytest_check.py`](../lunas/checks/pytest_check.py) |
| 20 | `design_fidelity` | hybrid | static_html, node, python | [`lunas/checks/design_fidelity.py`](../lunas/checks/design_fidelity.py) |
| 21 | `feature_coverage` | hybrid | static_html, node, python | [`lunas/checks/feature_coverage.py`](../lunas/checks/feature_coverage.py) |

## Pluggable LLM client

Layers #20 and #21 invoke an `LLMClient` (see
[`lunas/llm_client.py`](../lunas/llm_client.py)). Lunas ships an
`AnthropicClient` against the Anthropic SDK; the `LLMClient` Protocol
allows alternative backends. When no client is configured (or
`--no-llm` is passed), these layers skip cleanly.

## Layer ordering

The pipeline runs layers in the order declared in
`lunas/checks/__init__.py:LAYERS`. Structural layers (AST, balance)
run first; subprocess layers (`npm_install`, `tsc`, `pytest`) follow;
hybrid LLM layers run last. A failure does not short-circuit the
pipeline — every applicable layer reports its own verdict and the
final pass/fail is the conjunction.
