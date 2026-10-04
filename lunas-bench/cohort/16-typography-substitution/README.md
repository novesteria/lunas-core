# 16 — typography substitution

**Stack:** static_html
**Layer:** `design_fidelity` (hybrid — LLM judge + deterministic override)
**Expected verdict:** FAIL (override fires)

## Input

An editorial blog landing page. `brief.json` requires Lora for
headings + Inter for body. `input/index.html` and `input/styles.css`
honor the palette (every required hex appears) but every
`font-family` declaration uses `system-ui, sans-serif`. The strings
`Lora` and `Inter` do not appear in any input file.

## Bug

`design_fidelity` runs the LLM judge for four dimensions, then
applies a deterministic override:

- Palette hex search — all required hex codes found → no cap.
- Font-family search — `Lora` and `Inter` not found → philosophy
  dimension capped at 4/10.
- `forced_fail = true` because the override fired.

The LLM may score this case high on visual composition; the override
caps philosophy regardless and the case fails.

## Files

- `brief.json` — requires Lora + Inter
- `input/index.html`
- `input/styles.css` — palette hexes correct, `font-family: system-ui`
- `expected.json` — includes `deterministic_check_findings` block
