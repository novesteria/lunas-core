# 17 — density / spacing-rhythm violation

**Stack:** static_html
**Layer:** `design_fidelity` (hybrid — LLM-judge dependent)
**Expected verdict:** FAIL (LLM-driven; no deterministic override)

> This case has no deterministic override path — the palette is
> correct, the required fonts (`Playfair Display` + `Source Sans 3`)
> are imported and used, and the `editorial` philosophy has no
> forbidden-pattern entries. The LLM judge is the only check that
> fires; the calibrated verdict is captured in `expected.json`.

## Input

A magazine-style landing page. `brief.json` sets `density: spacious`
and `spacing_scale: spacious`, with notes describing "generous
whitespace, slow reading rhythm, vertical breathing room".
`input/styles.css` honors the palette and the fonts but uses
0.25–0.5rem paddings, gaps, and margins throughout.

## Bug

The LLM judge reads the brief + CSS together and scores the
`density_motion` dimension low — the spacing rhythm reads as a SaaS
dashboard rather than an editorial landing. The dimension scoring
below `_MIN_DIMENSION_SCORE = 3` triggers a weak-dimension FAIL even
when overall score sits near the pass threshold.

## Files

- `brief.json` — `density: spacious`, editorial philosophy
- `input/index.html`
- `input/styles.css` — palette + fonts correct, paddings 0.25–0.5rem
- `expected.json` — includes documented LLM expectations + override block
