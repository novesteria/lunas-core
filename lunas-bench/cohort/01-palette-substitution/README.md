# 01 — palette substitution

**Stack:** static_html
**Layer:** `design_fidelity` (hybrid — LLM judge + deterministic override)
**Expected verdict:** FAIL (override fires)

## Input

A page generated against a brief that specifies a forest-green
editorial palette (`primary: #2A5252`, `accent: #B68A3E`, …) plus
Lora / Inter typography. The generated `index.html` + `styles.css`
deliver a clean layout — proper spacing, consistent typography — but
use the generic Tailwind indigo + slate defaults; none of the brief's
hex codes appear in the CSS.

## Bug

`design_fidelity`'s deterministic override searches the code blob for
each required hex (as `#hex`, raw hex, `rgb(…)`, `rgba(…)`). When ≥
half of the required hexes are missing, the `palette` dimension is
capped at 4/10, `forced_fail` is set, and the layer reports FAIL.

The required font search runs the same way: when both `Lora` and
`Inter` are absent, `philosophy` is capped at 4/10 as well.

## Files

- `brief.json` — forest-green palette + Lora + Inter + editorial philosophy
- `input/index.html`
- `input/styles.css` — uses Tailwind indigo/slate, not the brief hexes
- `expected.json` — passed=false, palette capped at 4, override expected
