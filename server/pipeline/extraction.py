"""Extraction data models — structured records with confidence scores and provenance."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class FieldValue(BaseModel):
    """A single extracted field with confidence and provenance."""

    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source_selector: str | None = None


class RecordMetadata(BaseModel):
    """Provenance metadata for an extraction record."""

    source_url: str
    dom_hash: str
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ai_model: str = ""
    extraction_mode: Literal["heuristic", "ai", "hybrid"] = "heuristic"


class ExtractionRecord(BaseModel):
    """A single structured extraction record.

    Every record has:
    - Named fields with values, confidence scores, and source selectors
    - Metadata with full provenance
    - A completeness score
    - Flag indicating if this is partial data
    """

    fields: dict[str, FieldValue]
    metadata: RecordMetadata
    completeness_score: float = Field(ge=0.0, le=1.0, default=1.0)
    is_partial: bool = False
    duplicate_of: str | None = None
