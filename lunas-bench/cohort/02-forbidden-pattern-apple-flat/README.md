# 02 — forbidden CSS pattern under apple-flat

**Stack:** static_html
**Layer:** `design_fidelity` (hybrid — LLM judge + deterministic override)
**Expected verdict:** FAIL (override fires)

## Input

The brief sets `philosophy: apple-flat`. The apple-flat preset bans
the following CSS patterns: `linear-gradient`, `box-shadow: 0 0 *`,
`backdrop-filter`, `text-shadow`.

The generated CSS uses all four — a gradient hero, glow shadows on
cards, a blurred header backdrop, and glowing headings.

## Bug

`design_fidelity`'s deterministic override checks every philosophy
listed in `_PHILOSOPHY_FORBIDDEN_PATTERNS`. For `apple-flat`, it
greps the code blob for each forbidden regex. Any single match caps
the `philosophy` dimension at 4/10 and sets `forced_fail`.

The match runs regardless of how the LLM judge scores the dimension
— the override has the final word.

## Files

- `brief.json` — apple-flat philosophy
- `input/index.html`
- `input/styles.css` — gradient + box-shadow + backdrop-filter + text-shadow
- `expected.json` — passed=false, philosophy capped at 4, override expected
