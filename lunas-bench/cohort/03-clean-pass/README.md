# 03 — clean pass (node baseline)

**Stack:** static_html / node
**Layer:** none fires
**Expected verdict:** PASS

## Input

The brief specifies a forest-green editorial palette + Lora / Inter
fonts + Editorial philosophy. The generated code honours every
brief value: all five hex codes appear in `styles.css`, both fonts
are imported and used, and the layout avoids any forbidden CSS
pattern.

## Behaviour

`design_fidelity` runs the LLM judge over the four dimensions; the
deterministic override finds no missing evidence (palette hex
search hits, font search hits, no forbidden patterns). The verdict
passes the score threshold; no dimension trips the weak-dimension
floor. The case completes with `passed=true` and no override entry
in the `missing` list.

## Files

- `brief.json` — editorial palette + Lora + Inter + Editorial philosophy
- `input/index.html`
- `input/styles.css` — every required hex present, both fonts imported
- `expected.json` — passed=true, no override expected
