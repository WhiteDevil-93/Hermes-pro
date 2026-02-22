"""Authentication helpers for API routes and WebSockets."""

from __future__ import annotations

from fastapi import HTTPException, Request, WebSocket


AUTH_REQUIRED_DETAIL = "Authentication required"


def extract_principal_from_headers(headers: dict[str, str] | Request | WebSocket) -> str | None:
    """Extract authenticated principal from request/websocket headers."""
    if hasattr(headers, "headers"):
        header_map = headers.headers
    else:
        header_map = headers

    auth_header = header_map.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ").strip()
        if token:
            return token

    fallback = header_map.get("x-hermes-principal", "").strip()
    return fallback or None


def require_authenticated_principal(request: Request) -> str:
    """FastAPI dependency enforcing authenticated requests."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail=AUTH_REQUIRED_DETAIL)
    return principal
