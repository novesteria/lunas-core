"""Check-layer registry.

Each module under ``lunas.checks.*`` contributes one or more
``CheckLayer`` subclasses. The pipeline imports the registry to know
which layers to run for a given stack and the order to run them in.

Layer execution order matters: structural checks (AST, imports) run
before semantic checks (build, test), which run before judgment checks
(design fidelity, feature coverage).
"""

from __future__ import annotations

from lunas.checks.base import CheckLayer
from lunas.checks.brace_balance import BraceBalanceCheck
from lunas.checks.css_completeness import CssCompletenessCheck
from lunas.checks.design_fidelity import DesignFidelityCheck
from lunas.checks.duplicate_type_declarations import DuplicateTypeDeclarationsCheck
from lunas.checks.feature_coverage import FeatureCoverageCheck
from lunas.checks.hook_destructure_consistency import HookDestructureConsistencyCheck
from lunas.checks.html_js_id_parity import HtmlJsIdParityCheck
from lunas.checks.import_case_consistency import ImportCaseConsistencyCheck
from lunas.checks.interactivity import InteractivityCheck
from lunas.checks.js_syntax import JsSyntaxCheck
from lunas.checks.named_import_consistency import NamedImportConsistencyCheck
from lunas.checks.node_deps_completeness import NodeDepsCompletenessCheck
from lunas.checks.npm_install import NpmInstallCheck
from lunas.checks.pytest_check import PytestCheck
from lunas.checks.python_completeness import PythonCompletenessCheck
from lunas.checks.python_deps_completeness import PythonDepsCompletenessCheck
from lunas.checks.python_imports import PythonImportsCheck
from lunas.checks.react_prop_consistency import ReactPropConsistencyCheck
from lunas.checks.router_prefix_consistency import RouterPrefixConsistencyCheck
from lunas.checks.static_imports import StaticImportsCheck
from lunas.checks.tsc import TscCheck

# Layers are registered in canonical execution order. The numeric
# comments correspond to the entries in docs/LAYER_INDEX.md.
LAYERS: list[type[CheckLayer]] = [
    # ---- structural / AST layers ----
    PythonImportsCheck,                  # #1
    PythonCompletenessCheck,             # #2
    PythonDepsCompletenessCheck,         # #3
    RouterPrefixConsistencyCheck,        # #4
    NodeDepsCompletenessCheck,           # #5
    CssCompletenessCheck,                # #6
    ReactPropConsistencyCheck,           # #7
    NamedImportConsistencyCheck,         # #8
    ImportCaseConsistencyCheck,          # #9
    DuplicateTypeDeclarationsCheck,      # #10
    HookDestructureConsistencyCheck,     # #11
    BraceBalanceCheck,                   # #12
    StaticImportsCheck,                  # #13
    HtmlJsIdParityCheck,                 # #14
    InteractivityCheck,                  # #15
    # ---- subprocess layers ----
    JsSyntaxCheck,                       # #16
    NpmInstallCheck,                     # #17
    TscCheck,                            # #18
    PytestCheck,                         # #19
    # ---- LLM-judge / hybrid layers ----
    DesignFidelityCheck,                 # #20
    FeatureCoverageCheck,                # #21
]


def all_layers() -> list[type[CheckLayer]]:
    """Return the canonical layer list in execution order."""
    return list(LAYERS)


__all__ = ["LAYERS", "all_layers", "CheckLayer"]
