# 08 — pytest assertion fail

**Stack:** python
**Layer:** `pytest`
**Expected verdict:** FAIL

## Input

A Python helper that computes the future value of a deposit under
weekly compounding. `src/interest.py` defines
`compound_interest(principal, annual_rate, years) -> float`.
`tests/test_interest.py` exercises two reference scenarios computed
from the formula `principal * (1 + annual_rate/52) ** (52 * years)`.

## Bug

`compound_interest` returns simple interest (`principal * rate * years`)
instead of the weekly-compounded value. For `1000 @ 5% for 1 year` the
expected value is `1051.25`; the function returns `50.0`. Both pytest
assertions fail. All static layers pass — the structure is correct;
only the math is wrong.

## Files

- `brief.json`
- `input/requirements.txt`
- `input/src/__init__.py`
- `input/src/interest.py` — wrong formula
- `input/tests/__init__.py`
- `input/tests/test_interest.py`
- `expected.json`
