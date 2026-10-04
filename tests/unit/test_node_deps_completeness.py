"""Unit tests for ``lunas.checks.node_deps_completeness``."""

from __future__ import annotations

import json
from pathlib import Path

from lunas.checks._node_helpers import (
    extract_import_specifiers,
    package_root_of,
)
from lunas.checks.base import ValidationContext
from lunas.checks.node_deps_completeness import (
    NodeDepsCompletenessCheck,
    find_undeclared_node_deps,
)
from lunas.result import LayerKind, Verdict


def _pkg(root: Path, **deps_by_table: dict[str, str]) -> None:
    """Write a package.json with the given dep tables."""
    body: dict = {"name": "fixture", "version": "0.0.0"}
    body.update(deps_by_table)
    (root / "package.json").write_text(json.dumps(body))


# ----- _node_helpers pure functions ----------------------------------------


def test_package_root_relative_returns_empty():
    assert package_root_of("./local") == ""
    assert package_root_of("../up") == ""
    assert package_root_of("/abs") == ""


def test_package_root_node_protocol():
    assert package_root_of("node:fs") == ""


def test_package_root_scoped():
    assert package_root_of("@scope/pkg") == "@scope/pkg"
    assert package_root_of("@scope/pkg/sub") == "@scope/pkg"


def test_package_root_subpath():
    assert package_root_of("lodash/fp") == "lodash"


def test_package_root_strips_query_hash():
    assert package_root_of("lodash?raw") == "lodash"
    assert package_root_of("lodash#fragment") == "lodash"


def test_extract_imports_picks_up_all_forms():
    src = (
        "import React from 'react'\n"
        "import { x } from 'lodash'\n"
        "import 'side-effect'\n"
        "const a = require('axios')\n"
        "const b = await import('dynamic-pkg')\n"
        "export { z } from 'reexported'\n"
    )
    specs = extract_import_specifiers(src)
    assert {"react", "lodash", "side-effect", "axios", "dynamic-pkg", "reexported"} <= specs


# ----- find_undeclared_node_deps -------------------------------------------


def test_all_declared(tmp_path):
    _pkg(tmp_path, dependencies={"axios": "^1.0.0"})
    (tmp_path / "app.js").write_text("import axios from 'axios'\n")
    missing, scanned = find_undeclared_node_deps(tmp_path)
    assert missing == []
    assert scanned == 1


def test_missing_declared(tmp_path):
    _pkg(tmp_path, dependencies={})
    (tmp_path / "app.js").write_text("import axios from 'axios'\n")
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert len(missing) == 1
    assert missing[0].package == "axios"


def test_node_builtin_not_flagged(tmp_path):
    _pkg(tmp_path, dependencies={})
    (tmp_path / "app.js").write_text(
        "import fs from 'fs'\n"
        "import { readFile } from 'node:fs/promises'\n"
    )
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert missing == []


def test_relative_imports_skipped(tmp_path):
    _pkg(tmp_path, dependencies={})
    (tmp_path / "app.js").write_text(
        "import { helper } from './utils'\n"
        "import { up } from '../shared'\n"
    )
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert missing == []


def test_scoped_package_subpath(tmp_path):
    """``@scope/pkg/sub`` only requires ``@scope/pkg`` to be declared."""
    _pkg(tmp_path, dependencies={"@scope/pkg": "^1.0.0"})
    (tmp_path / "app.js").write_text(
        "import x from '@scope/pkg/util'\n"
    )
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert missing == []


def test_types_package_satisfies_runtime(tmp_path):
    """``@types/lodash`` declared → ``lodash`` import is OK (type-only)."""
    _pkg(tmp_path, devDependencies={"@types/lodash": "^4.0.0"})
    (tmp_path / "app.ts").write_text("import _ from 'lodash'\n")
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert missing == []


def test_node_modules_directory_skipped(tmp_path):
    """A package imported only from inside node_modules/ is not flagged."""
    _pkg(tmp_path, dependencies={"axios": "^1"})
    (tmp_path / "app.js").write_text("import axios from 'axios'\n")
    nm = tmp_path / "node_modules" / "axios"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("import secret from 'leaky-pkg'\n")
    missing, _ = find_undeclared_node_deps(tmp_path)
    assert missing == []


# ----- Full layer ----------------------------------------------------------


def test_layer_metadata():
    layer = NodeDepsCompletenessCheck()
    assert layer.NAME == "node_deps_completeness"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO


def test_layer_skipped_when_no_package_json(tmp_path):
    (tmp_path / "app.js").write_text("import axios from 'axios'\n")
    layer = NodeDepsCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped


def test_layer_fails_on_malformed_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{ not valid json")
    (tmp_path / "app.js").write_text("import axios from 'axios'\n")
    layer = NodeDepsCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert result.details["package_json_valid"] is False


def test_layer_skipped_when_no_sources(tmp_path):
    _pkg(tmp_path, dependencies={"axios": "^1"})
    layer = NodeDepsCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped


def test_layer_fails_on_undeclared(tmp_path):
    _pkg(tmp_path, dependencies={})
    (tmp_path / "app.js").write_text(
        "import axios from 'axios'\n"
        "import _ from 'lodash'\n"
    )
    layer = NodeDepsCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    pkgs = {entry["package"] for entry in result.details["missing"]}
    assert pkgs == {"axios", "lodash"}


def test_layer_passes_when_all_declared(tmp_path):
    _pkg(tmp_path, dependencies={"axios": "^1", "lodash": "^4"})
    (tmp_path / "app.js").write_text(
        "import axios from 'axios'\n"
        "import _ from 'lodash'\n"
    )
    layer = NodeDepsCompletenessCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
    assert result.details["declared_count"] == 2
