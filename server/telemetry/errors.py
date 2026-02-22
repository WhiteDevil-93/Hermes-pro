"""Structured error telemetry helpers."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Canonical error codes for operational telemetry."""

    AI_INITIALIZATION_FAILED = "AI_INITIALIZATION_FAILED"
    AI_CLASSIFICATION_FAILED = "AI_CLASSIFICATION_FAILED"
    AI_PLAN_GENERATION_FAILED = "AI_PLAN_GENERATION_FAILED"
    AI_EXTRACTION_FAILED = "AI_EXTRACTION_FAILED"
    AI_REPAIR_FAILED = "AI_REPAIR_FAILED"
    SIGNAL_SUBSCRIBER_FAILURE = "SIGNAL_SUBSCRIBER_FAILURE"
    API_WEBSOCKET_SEND_FAILED = "API_WEBSOCKET_SEND_FAILED"
    BROWSER_CLEANUP_FAILED = "BROWSER_CLEANUP_FAILED"
    CONDUIT_ACTION_EXECUTION_FAILED = "CONDUIT_ACTION_EXECUTION_FAILED"


def emit_structured_error(
    logger: logging.Logger,
    *,
    code: ErrorCode,
    message: str,
    suppressed: bool,
    run_id: str | None = None,
    phase: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Emit a structured telemetry event via logging."""
    logger.error(
        "hermes_error",
        extra={
            "error_code": code,
            "error_message": message,
            "suppressed": suppressed,
            "run_id": run_id,
            "phase": phase,
            "details": details or {},
        },
    )
