# 13 — npm preinstall + postinstall hooks

**Stack:** node (vanilla)
**Layer:** `npm_install`
**Expected verdict:** PASS (with side-effect-absence check)

## Input

A one-line Node.js script. `package.json` declares two lifecycle
hooks: `preinstall` writes `PWNED.txt` and prints
`SECURITY-LEAK: preinstall executed`; `postinstall` writes
`PWNED-POST.txt`.

## Behaviour

The `npm_install` layer invokes `npm install --ignore-scripts`. The
install completes with exit 0; the `preinstall` and `postinstall`
hooks are bypassed. After the validator runs, `PWNED.txt` and
`PWNED-POST.txt` do not exist in the input directory, and the
`SECURITY-LEAK` line does not appear in stdout.

`expected.json` includes a `side_effect_check.file_must_not_exist`
field — the bench runner verifies the file's absence as part of the
case's success criterion.

## Files

- `brief.json`
- `input/package.json` — declares `preinstall` + `postinstall` hooks
- `input/index.js`
- `expected.json` — includes `side_effect_check` block
