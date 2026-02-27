"""Authentication dependencies for the Hermes API.

Supports two modes:
1. Global API token (HERMES_API_TOKEN env var): all requests require Bearer token
2. Per-run token: returned on create_run, grants access to that run's endpoints

When HERMES_API_TOKEN is not set, authentication is disabled (development mode).
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException


def _get_api_token() -> str:
    """Read the API token at call time (supports test overrides)."""
    import os

    return os.getenv("HERMES_API_TOKEN", "")


def _get_bearer_token(authorization: str = Header(default="")) -> str:
    """Extract bearer token from Authorization header."""
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return ""


async def require_api_auth(token: str = Depends(_get_bearer_token)) -> str:
    """Dependency that enforces API token authentication.

    If HERMES_API_TOKEN is not set, auth is disabled (returns empty string).
    """
    api_token = _get_api_token()
    if not api_token:
        return ""  # Auth disabled
    if not secrets.compare_digest(token, api_token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")
    return token


def generate_run_token() -> str:
    """Generate a cryptographically secure per-run token."""
    return secrets.token_urlsafe(32)
