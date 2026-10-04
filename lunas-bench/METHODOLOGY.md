# lunas-bench — Methodology

This document defines what a bench case is, how a run reports pass /
fail, and the reproducibility rules every case follows.

## Case structure

Every directory under `cohort/` is one case and contains four files:

| File | Contents |
|---|---|
| `brief.json` | A `DesignDNA` instance (palette, fonts, philosophy, density, motion, tone, features). Loaded with `lunas.design_dna.load_brief`. |
| `input/` | The codebase the validator runs against. Checked in verbatim — never regenerated. |
| `expected.json` | What `lunas check` should report for this input. |
| `README.md` | Short technical note: stack, layer fired, expected verdict, input, bug, files. |

## Running a case

```
python -m lunas_cli check lunas-bench/cohort/<NN>-<slug>/input \
    --brief lunas-bench/cohort/<NN>-<slug>/brief.json \
    --no-llm \
    --json results/<NN>-<slug>.json
```

`--no-llm` skips the LLM-using layers (`design_fidelity`,
`feature_coverage`).

Python cases ship a `requirements.txt`. The cohort runner
(`scripts/run_lunas.py`) creates `input/.venv` from it before the run
(git-ignored) so the `pytest` layer executes against the case's own
dependencies on any machine. Nothing is installed into the validator's
environment. Cases that require LLM evaluation declare
`llm_calibration: "pending"` in `expected.json` until a real-model run
captures the verdict.

## When a case passes

A case passes when the actual `lunas check` output matches the
declared `expected.json` on:

1. **`passed` field** — actual `passed` equals expected `passed`.
2. **`failed_layer`** — if expected names a failing layer, the layer
   with that `NAME` reports `verdict=failed` in the actual output.
3. **Capped dimensions** — for `design_fidelity` cases, every dimension
   expected to be capped at N must be ≤ N in the verdict.
4. **Override fired** — when expected sets
   `deterministic_override_expected: true`, the failing layer reports
   `override_fired: true`.
5. **Side-effect checks** — if `expected.json` contains
   `side_effect_check.file_must_not_exist`, that file must not exist
   in `input/` after the run.

## Adding a case

1. Create `cohort/<NN>-<short-slug>/`.
2. Write `brief.json` (use an existing case as a template).
3. Place the codebase under `input/`. Keep it minimal — one to a
   handful of files is ideal.
4. Run `lunas check` against the input and read the actual output.
5. Write `expected.json` matching what `lunas check` actually
   reported.
6. Write `README.md` following the case template (stack, layer,
   verdict, input, bug, files).

A new case lands when the actual `lunas check` output reproduces
`expected.json` deterministically.

## Reproducibility

- **Deterministic input.** Every `input/` directory is checked in
  verbatim. Cases are not regenerated from an LLM at run time.
- **Pinned LLM versions.** Layers that invoke an LLM pin to a
  specific model ID. Model upgrades produce a new bench run, not a
  silent score change.
- **Public results.** Bench-run output JSON is committed under
  `results/` with a timestamp, the model ID used by the LLM layers,
  the validator version, and the Python/platform of the run.
- **Case + validator evolve together.** When a validator change
  alters a case's verdict, the case's `expected.json` is updated in
  the same commit, with an explanation in the message.

## Disagreements between LLM judge and deterministic override

The hybrid layers (`design_fidelity`, `feature_coverage`) record both
the original LLM verdict and the post-override outcome. When the
override changes the verdict, the layer sets `override_fired: true`
in `details` and the `missing` list contains a string prefixed
`"DETERMINISTIC OVERRIDE: …"`.

A bench run records the override-fire count and the cases where it
fired.
