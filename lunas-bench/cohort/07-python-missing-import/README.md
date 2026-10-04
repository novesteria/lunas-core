# 07 — python missing import

**Stack:** python (FastAPI)
**Layer:** `pytest`
**Expected verdict:** FAIL

## Input

A FastAPI app with one endpoint that returns the current time after a
1-second wait. `src/api.py` uses `await asyncio.sleep(1)` and
`datetime.now(timezone.utc)`. `tests/test_api.py` exercises the endpoint
via `fastapi.testclient.TestClient`.

## Bug

`src/api.py` calls `asyncio.sleep` and `datetime.now` but neither
`asyncio` nor `datetime` is imported. pytest fails at collection with
`NameError: name 'asyncio' is not defined`. AST parse succeeds (the
syntax is valid) and `python_imports` / `python_deps_completeness`
pass because no missing-import string appears — the bug is name usage
without a corresponding import statement.

## Files

- `brief.json`
- `input/requirements.txt`
- `input/src/__init__.py`
- `input/src/api.py` — uses `asyncio` and `datetime` without importing them
- `input/tests/__init__.py`
- `input/tests/test_api.py`
- `expected.json`
