"""Hermes configuration settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class VertexConfig(BaseModel):
    """Vertex AI configuration."""

    project_id: str = Field(default_factory=lambda: os.getenv("VERTEX_PROJECT_ID", ""))
    location: str = Field(default_factory=lambda: os.getenv("VERTEX_LOCATION", "us-central1"))
    credentials_path: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    )
    flash_model: str = "gemini-2.5-flash"
    pro_model: str = "gemini-2.5-pro"


class RetryConfig(BaseModel):
    """Retry and backoff configuration."""

    max_retries: int = 3
    backoff_base_ms: int = 1000
    backoff_max_ms: int = 30000
    jitter: bool = True


class TimeoutConfig(BaseModel):
    """Timeout budgets per phase and global."""

    global_timeout_s: int = 300
    page_load_timeout_s: int = 30
    interaction_timeout_s: int = 10
    ai_timeout_s: int = 60
    extraction_timeout_s: int = 60


class BrowserConfig(BaseModel):
    """Browser layer configuration."""

    headless: bool = True
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: str | None = None
    locale: str = "en-US"


class PipelineConfig(BaseModel):
    """Data pipeline configuration."""

    data_dir: Path = Field(default_factory=lambda: Path(os.getenv("HERMES_DATA_DIR", "./data")))
    debug_mode: bool = False
    min_confidence_threshold: float = 0.5


class HermesConfig(BaseModel):
    """Root configuration for a Hermes run."""

    target_url: str
    extraction_schema: dict = Field(default_factory=dict)
    vertex: VertexConfig = Field(default_factory=VertexConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    max_concurrent_runs: int = Field(
        default_factory=lambda: int(os.getenv("HERMES_MAX_CONCURRENT_RUNS", "1"))
    )
    extraction_mode: Literal["heuristic", "ai", "hybrid"] = "heuristic"
    allow_cross_origin: bool = False
    heuristic_selectors: dict[str, str] = Field(default_factory=dict)
    log_level: str = Field(default_factory=lambda: os.getenv("HERMES_LOG_LEVEL", "INFO"))
