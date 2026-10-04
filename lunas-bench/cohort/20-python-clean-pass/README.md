# 20 — Python clean pass

**Stack:** python (FastAPI)
**Layer:** none fires
**Expected verdict:** PASS

## Input

A minimal FastAPI service. `app/__init__.py` declares `__version__`;
`app/main.py` defines `GET /health` returning a status / version /
ISO-timestamp dict. `tests/test_health.py` exercises the endpoint via
`fastapi.testclient.TestClient`. `requirements.txt` lists fastapi,
httpx, pytest.

## Behaviour

Every Python-applicable layer runs and passes:

- `python_imports` — `from app import …` resolves.
- `python_completeness` — both function bodies are real implementations.
- `python_deps_completeness` — fastapi, httpx, pytest all declared.
- `router_prefix_consistency` — no prefixed routers / include_router calls.
- `import_case_consistency` — all imported names match the target file's
  top-level names by casing.
- `pytest` — the test passes, exit 0.

Node and static-html layers skip cleanly on stack mismatch.
`design_fidelity` + `feature_coverage` skip when no LLM client is
configured.

## Files

- `brief.json`
- `input/requirements.txt`
- `input/app/__init__.py`
- `input/app/main.py`
- `input/tests/__init__.py`
- `input/tests/test_health.py`
- `expected.json` — passed=true, expected per-layer outcomes
