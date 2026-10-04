# 11 — FastAPI router prefix double-mount

**Stack:** python (FastAPI)
**Layer:** `router_prefix_consistency`
**Expected verdict:** FAIL

## Input

A FastAPI auth service split across two files. `app/api/auth.py`
declares `router = APIRouter(prefix="/api")` and defines
`POST /auth/login` + `POST /auth/register` on it. `main.py` then does
`app.include_router(auth_router, prefix="/api")`.

## Bug

The prefix is mounted twice: once on `APIRouter(prefix=)` and again on
`include_router(prefix=)`. Endpoints land at `/api/api/auth/login` and
`/api/api/auth/register`; every real client returns 404. The AST cross-
reference layer walks `APIRouter` declarations and `include_router`
calls through each file's import-alias map and flags the conflict with
the resulting landing path.

## Files

- `brief.json`
- `input/requirements.txt`
- `input/app/__init__.py`
- `input/app/api/__init__.py`
- `input/app/api/auth.py` — declares `APIRouter(prefix="/api")`
- `input/main.py` — calls `include_router(..., prefix="/api")`
- `expected.json`
