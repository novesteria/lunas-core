# 10 — HTML id / JS hook mismatch

**Stack:** static_html
**Layer:** `html_js_id_parity`
**Expected verdict:** FAIL

## Input

A tip-calculator UI: vanilla HTML, JS, CSS. `index.html` declares
`id="theme-switch"` and `id="people-decrement"`. `app.js` calls
`getElementById('theme-toggle')` and `getElementById('decrement-btn')`.

## Bug

Two JS id references have no matching id in any HTML file —
`theme-toggle` and `decrement-btn`. `html_js_id_parity` cross-references
every `getElementById('…')` / `querySelector('#…')` call against every
`id="…"` declaration and flags the two phantom hooks. At runtime the
listeners would attach to `null`; clicks do nothing.

## Files

- `brief.json`
- `input/index.html` — declares `theme-switch` and `people-decrement`
- `input/app.js` — hooks `theme-toggle` and `decrement-btn`
- `input/styles.css`
- `expected.json`
