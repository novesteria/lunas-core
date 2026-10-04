"""Application entrypoint — assembles the FastAPI app and mounts routers."""

from fastapi import FastAPI

from app.api.auth import router as auth_router

app = FastAPI(title="Auth Service")

# BUG: auth_router was declared with prefix='/api' in app/api/auth.py.
# Mounting it again with prefix='/api' here lands every endpoint at
# /api/api/auth/login and /api/api/auth/register. Every login request
# returns 404. pytest with happy-path mocks would still pass if the
# test code uses the wrong URL; only real HTTP traffic catches it.
app.include_router(auth_router, prefix="/api")
