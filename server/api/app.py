"""FastAPI application entry point for Hermes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.routes import router
from server.config.settings import APIConfig
from server.grounding.search_api import router as grounding_router

app = FastAPI(
    title="Hermes",
    description="Autonomous Web Intelligence Engine",
    version="2.0.0",
)

_api_config = APIConfig()
_allow_credentials = _api_config.cors_allow_credentials and "*" not in _api_config.allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_api_config.allowed_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(grounding_router, prefix="/api/v1/grounding", tags=["grounding"])


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "hermes", "version": "2.0.0"}


def create_app() -> FastAPI:
    """Factory function for creating the FastAPI application."""
    return app
