# Changelog

All notable changes to Lunas (formerly Aegis) are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased]

### Changed
- Renamed Aegis to Lunas everywhere: the Python package `aegis` is now `lunas`,
  `aegis_cli` is `lunas_cli`, the distribution is `lunas-validator`, the bench
  is `lunas-bench`, and the command is `lunas`. The `aegis` command stays as an
  alias for one release, and reports carry both `lunas_version` and the old
  `aegis_version` key for one release.
- The lunas.novesteria.com website (pages, worker, deploy config) no longer
  lives in this repository; this repository is the open-source validator only.

## [Unreleased]

### Added

- Homepage now explains the open-core model: an "Aegis Core" (this repo,
  Apache 2.0, self-hosted) vs. "Aegis" full-engine (managed or self-hosted,
  live behavior probes, RLS/access audit, best-round delivery) comparison,
  so visitors can see what the static layer covers and what the running-app
  layer adds.
- Homepage ships a real "try it" tool on the full-engine card: Google
  sign-in, then upload a `.zip` and get back a live report from the
  full-engine scan service (a separate backend, own auth, own database —
  runs your code in an isolated sandbox, never on our own host).
- Light theme.
- The scan tool moved to its own page (`/scan.html`) with a proper report
  view — verdict banner, pass/fail/skip counts, and collapsible
  failed/passed/skipped sections — instead of a cramped list inside the
  homepage card. The shield mark (from the Team-AI family logo, no
  monogram) is now the site's favicon and header icon.

## [0.1.0] - 2026-07-17

First public release. Apache 2.0.

### Fixed

- **node_deps_completeness / static_imports:** `@/…` and `@x` import
  specifiers are treated as local path aliases (vite/tsconfig `paths`), not
  npm scoped packages, so a project using the `@/` alias no longer false-fails.
- **TS/JS export scraping:** `export type { A, B } from './x'` re-export lists
  are now recognized as exports — a consumer importing those names is no longer
  flagged (named-import consistency) and a case mismatch on them is no longer
  missed (import-case consistency).
- **react_prop_consistency:** props declared after an inline-object-typed prop
  (`config: { … }; onSubmit`) are no longer dropped (balanced-brace body scan);
  components with an index signature (`[key: string]: T`) are treated as
  extensible; identifiers inside `{expr}` JSX attribute values are no longer
  captured as attribute names.
- **python_imports:** a namespace-only local folder (e.g. an Alembic
  `alembic/` migrations dir with no `__init__.py`) that shadows a third-party
  package of the same name is no longer reported as an unresolved local import.
- **static_imports:** design-artifact directories (`design/`, `wireframes/`,
  `mockups/`) are skipped — their intentionally-broken references are not
  product code.
- **All static walkers:** `coverage/` (and, for the CSS walker, `dist/` and
  `build/`) are excluded from file discovery, so compiled/instrumented output
  no longer produces false results.
- **npm_install:** added a final `npm install --ignore-scripts
  --legacy-peer-deps` recovery tier, so an npm 7+ peer-dependency conflict that
  older npm tolerated no longer fails an otherwise-installable project.
- **tsc:** a degenerate root `tsconfig.json` (no `compilerOptions` /
  `references` / `files` / `extends`, e.g. a stray `@/*` paths fragment) is
  rebuilt before type-checking, so `tsc` no longer falls back to ES5 and
  reports phantom `node_modules` errors (TS2468 / TS2583); a `lib` array with
  no ES2015+ member and an `es3`/`es5` `target` are raised to `ES2020`; and the
  test-exclude patch now tolerates trailing prose after the JSON object.
- **feature_coverage:** the layer now judges frontend code only and skips
  cleanly on a non-frontend stack instead of failing; and a semantic-evidence
  rescue flips a judge "missing" verdict back to present when the code
  demonstrably contains the named mechanism (e.g. `AudioContext` for a "beep"
  feature, a `textContent` flip for a mode label) — a stub with only the HTML
  id does not rescue.
- **design_fidelity:** the palette dimension is scored deterministically
  (`round(found / required hex * 10)`) instead of trusting the LLM's variable
  palette number, so the same CSS yields the same palette score across runs;
  a too-harsh LLM palette score is corrected upward without failing the build,
  and only a downward (missing-evidence) correction forces a fail.

### Added

- Initial package layout (`aegis/`, `aegis_cli/`) and `pyproject.toml`
  shipping `aegis-validator` on PyPI.
- Top-level `aegis.validate()` async entry point + `ValidationPipeline`.
- `aegis check` CLI with `--brief`, `--json`, `--no-llm`,
  `--exit-on-fail`, `--verbose`.
- `LLMClient` Protocol with `AnthropicClient` reference implementation;
  Anthropic SDK ships as an optional `[anthropic]` extra.
- `aegis.subprocess_runner.run_cmd` — sandboxed subprocess runner with
  credential env scrub and per-command timeout.
- 21 check layers under `aegis/checks/`, registered in canonical
  execution order:

  - `python_imports`, `python_completeness`, `python_deps_completeness`
  - `router_prefix_consistency`
  - `node_deps_completeness`, `css_completeness`
  - `react_prop_consistency`, `named_import_consistency`,
    `import_case_consistency`, `duplicate_type_declarations`,
    `hook_destructure_consistency`
  - `ast_brace_balance`
  - `static_imports`, `html_js_id_parity`, `interactivity`
  - `js_syntax`, `npm_install`, `tsc`, `pytest`
  - `design_fidelity` (hybrid), `feature_coverage` (hybrid)

- `aegis-bench/` cohort: 20 cases under `cohort/01-` through
  `cohort/20-`, each with `brief.json`, `input/`, `expected.json`,
  and a short technical README. `METHODOLOGY.md` describes case
  structure, run command, and reproducibility rules.
- 299 unit tests under `tests/unit/`.
- GitHub Actions workflow (`.github/workflows/test.yml`) — matrix
  pytest on Ubuntu / macOS / Windows for Python 3.11 + 3.12, plus a
  package-build job that produces wheel + sdist artifacts.
- `docs/LAYER_INDEX.md` — single canonical table of layers sourced
  from the registry.

### Notes

- Cases 16, 17, 18, 19 have been calibrated end-to-end against
  `claude-opus-4-7`. Each `expected.json` records the per-dimension
  scores and override behavior from that run.
- `tools/calibrate_llm_cases.py` re-runs the calibration against the
  current model. `.env` (git-ignored) supplies the API key.

[Unreleased]: https://github.com/novesteria/lunas-core/commits/main
