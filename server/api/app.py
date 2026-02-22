"""FastAPI application entry point for Hermes."""

from __future__ import annotations

import os
from typing import Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.routes import router
from server.grounding.search_api import router as grounding_router

_DEVELOPMENT_ENVIRONMENTS: Final[set[str]] = {"dev", "development", "local"}


def _is_truthy_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_cors_origins() -> list[str]:
    environment = os.getenv("HERMES_ENV", "development").strip().lower()
    origins_raw = os.getenv("HERMES_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
    allow_all_in_dev = _is_truthy_env(os.getenv("HERMES_DEV_ALLOW_ALL_ORIGINS", ""))

    if origins:
        return origins

    if environment in _DEVELOPMENT_ENVIRONMENTS and allow_all_in_dev:
        return ["*"]

    if environment not in _DEVELOPMENT_ENVIRONMENTS:
        raise RuntimeError(
            "Production CORS configuration error: HERMES_ALLOWED_ORIGINS must be set "
            "to a comma-separated list of trusted origins when HERMES_ENV is not "
            "development/local/dev."
        )

    return []


def create_app() -> FastAPI:
    """Factory function for creating the FastAPI application."""
    cors_origins = _resolve_cors_origins()
    cors_credentials = (
        _is_truthy_env(os.getenv("HERMES_CORS_ALLOW_CREDENTIALS", ""))
        and "*" not in cors_origins
    )

    app = FastAPI(
        title="Hermes",
        description="Autonomous Web Intelligence Engine",
        version="2.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=cors_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")
    app.include_router(grounding_router, prefix="/api/v1/grounding", tags=["grounding"])

    return app


app = create_app()


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "hermes", "version": "2.0.0"}
