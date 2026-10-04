# 19 — missing dark-mode toggle

**Stack:** static_html
**Layer:** `feature_coverage` (hybrid; deterministic override expected)
**Expected verdict:** FAIL (`design_fidelity` + `feature_coverage` both fail)

## Input

A small note-taking single-page app. `brief.json` lists three
features: write a note, render the list, light/dark mode toggle.
`input/styles.css` ships a charcoal-by-default palette via generic
custom properties (`--surface-1`, `--text-1`); the strings `light`,
`dark`, `toggle`, and `mode` do not appear in any input file.

## Bug

The toggle feature is absent — no toggle button in the markup, no
swap handler in the JS, no `light`/`dark` styling switch. Stage 1 of
`feature_coverage` flags the feature: keyword markers absent. If the
LLM looks at the dark palette and labels the feature `present`, the
cross-validation step requires the LLM's evidence to point at a
concrete code symbol the scanner can locate; prose evidence ("dark
theme via CSS variables") fails the rescue path and the feature stays
missing. `override_fired = true`.

## Files

- `brief.json` — lists `light/dark mode toggle` as feature #3
- `input/index.html` — composer + list, no toggle button
- `input/app.js` — composer handlers, no theme handler
- `input/styles.css` — charcoal palette via `--surface-1` etc.
- `expected.json` — includes Stage 1 finding + override expectation
