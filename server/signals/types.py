"""Signal type definitions for the Hermes observability system."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    """All signal types emitted by the Hermes system."""

    PHASE_TRANSITION = "PHASE_TRANSITION"
    OBSTRUCTION_DETECTED = "OBSTRUCTION_DETECTED"
    AI_INVOKED = "AI_INVOKED"
    AI_RESPONDED = "AI_RESPONDED"
    AI_REJECTED = "AI_REJECTED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    EXTRACTION_COMPLETE = "EXTRACTION_COMPLETE"
    RETRY_ATTEMPT = "RETRY_ATTEMPT"
    RUN_COMPLETE = "RUN_COMPLETE"
    RUN_FAILED = "RUN_FAILED"


class Signal(BaseModel):
    """An immutable signal emitted during a Hermes run.

    Every state change, decision, and outcome produces a Signal.
    Signals are append-only and cannot be modified after emission.
    """

    sequence: int = Field(description="Monotonic sequence number within the run")
    signal_type: SignalType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}
