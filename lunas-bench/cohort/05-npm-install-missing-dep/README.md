# 05 — npm install missing dep

**Stack:** node (React 18 + Vite)
**Layer:** `npm_install`
**Expected verdict:** FAIL

## Input

A React todo app. `package.json` declares `"react": "99.0.0"` — a
version that does not exist on the npm registry. The JS source itself
is clean.

## Bug

`npm install --ignore-scripts` exits non-zero with `ERESOLVE`: the
requested `react@"99.0.0"` cannot satisfy `react-dom@18.x`'s peer
dependency. The install never completes, so layers downstream of
`npm_install` are skipped.

## Files

- `brief.json`
- `input/package.json` — declares the missing version
- `input/index.html`
- `input/src/index.jsx`
- `input/src/App.jsx`
- `expected.json`
