"""Auth router — login + register endpoints under /api/auth/*."""

from fastapi import APIRouter
from pydantic import BaseModel

# Router declares its OWN prefix.
router = APIRouter(prefix="/api", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/auth/login")
def login(creds: Credentials) -> TokenResponse:
    return TokenResponse(access_token=f"login-token-for-{creds.email}")


@router.post("/auth/register")
def register(creds: Credentials) -> TokenResponse:
    return TokenResponse(access_token=f"register-token-for-{creds.email}")
