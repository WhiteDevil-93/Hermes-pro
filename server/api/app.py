"""FastAPI application entry point for Hermes."""

from __future__ import annotations

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("HERMES_ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
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
