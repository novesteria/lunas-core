# 18 — missing CSV export

**Stack:** static_html
**Layer:** `feature_coverage` (hybrid — Stage 1 keyword scan + LLM judge)
**Expected verdict:** FAIL

## Input

A user-list dashboard. `brief.json` lists three features:
1) a user table with name / email / signup-date columns,
2) sort by column header,
3) export the current view to CSV via a download button.
`input/app.js` + `input/index.html` implement (1) and (2) cleanly.

## Bug

The CSV export feature is absent. The strings `export`, `download`,
`csv`, `Blob`, and `text/csv` do not appear in any input file. Stage 1
of `feature_coverage` derives keyword markers from each feature label
(stopword strip + length sort) and flags the export feature: the
markers `export` and `download` have zero hits. Stage 2 (LLM) is
expected to agree; both halves of the hybrid report the same missing
feature.

## Files

- `brief.json` — lists CSV export as feature #3
- `input/index.html` — table only, no export button
- `input/app.js` — sort handlers only, no export logic
- `input/styles.css`
- `expected.json` — includes Stage 1 finding details
