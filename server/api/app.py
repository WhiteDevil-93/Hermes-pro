"""FastAPI application entry point for Hermes."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.routes import router
from server.grounding.search_api import router as grounding_router

app = FastAPI(
    title="Hermes",
    description="Autonomous Web Intelligence Engine",
    version="2.0.0",
)

# CORS for WebUI
_cors_origins_raw = os.getenv("HERMES_ALLOWED_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] or ["*"]
_cors_credentials = (
    os.getenv("HERMES_CORS_ALLOW_CREDENTIALS", "").lower() == "true" and "*" not in _cors_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(grounding_router, prefix="/api/v1/grounding", tags=["grounding"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "hermes", "version": "2.0.0"}


def create_app() -> FastAPI:
    """Factory function for creating the FastAPI application."""
    return app
