# 09 — node deps missing

**Stack:** node (vanilla ESM script)
**Layer:** `node_deps_completeness`
**Expected verdict:** FAIL

## Input

A small Node.js script: `src/fetch.js` imports `axios` and uses
`date-fns` for timestamp formatting. `package.json` declares
`dependencies: {}`.

## Bug

`node_deps_completeness` walks every JS source, extracts every
bare-specifier import, and reports imports not declared in any
`dependencies` / `devDependencies` / `peerDependencies` /
`optionalDependencies` table. Both `axios` and `date-fns` surface as
missing.

`npm install` itself passes (an empty deps object is valid) and
`js_syntax` passes (the file is valid JavaScript). The runtime would
fail with `ERR_MODULE_NOT_FOUND` once the script ran.

## Files

- `brief.json`
- `input/package.json` — empty dependencies
- `input/src/fetch.js` — imports `axios` and `date-fns`
- `expected.json`
