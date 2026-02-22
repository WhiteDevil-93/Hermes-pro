"""REST API routes for Hermes.

Provides endpoints for:
- Initiating scrape runs
- Monitoring run status
- Viewing results and signals
- Managing configuration
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from server.api.run_repository import InMemoryRunRepository
from server.api.run_service import RunService
from server.conduit.engine import Conduit
from server.config.settings import BrowserConfig, HermesConfig, PipelineConfig
from server.telemetry.errors import ErrorCode, emit_structured_error

router = APIRouter()
logger = logging.getLogger(__name__)

_pipeline_config = PipelineConfig()
_run_service = RunService(InMemoryRunRepository())


# --- Request/Response Models ---


class RunRequest(BaseModel):
    """Request to initiate a scrape run."""

    target_url: str
    extraction_schema: dict[str, Any] = Field(default_factory=dict)
    extraction_mode: Literal["heuristic", "ai", "hybrid"] = "heuristic"
    heuristic_selectors: dict[str, str] = Field(default_factory=dict)
    allow_cross_origin: bool = False
    headless: bool = True
    debug_mode: bool = False


class RunResponse(BaseModel):
    """Response after initiating a run."""

    run_id: str
    status: str
    message: str


class RunStatus(BaseModel):
    """Current status of a run."""

    run_id: str
    phase: str
    status: str
    records_count: int = 0
    duration_s: float = 0
    ai_calls: int = 0
    signals_count: int = 0


# --- Endpoints ---


@router.post("/runs", response_model=RunResponse)
async def create_run(request: RunRequest) -> RunResponse:
    """Initiate a new scrape run.

    The run executes asynchronously. Use the returned run_id
    to monitor progress via GET /runs/{run_id} or WebSocket.
    """
    config = HermesConfig(
        target_url=request.target_url,
        extraction_schema=request.extraction_schema,
        extraction_mode=request.extraction_mode,
        heuristic_selectors=request.heuristic_selectors,
        allow_cross_origin=request.allow_cross_origin,
        browser=BrowserConfig(headless=request.headless),
        pipeline=PipelineConfig(debug_mode=request.debug_mode),
    )

    conduit = Conduit(config)
    run_id = await _run_service.create_run(conduit)

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run initiated for {request.target_url}",
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(run_id: str) -> RunStatus:
    """Get the current status of a run."""
    return RunStatus(**_run_service.get_status(run_id))


def _get_data_dir() -> Path:
    """Resolve the data directory from environment or default."""
    return Path(os.getenv("HERMES_DATA_DIR", "./data"))


@router.get("/runs/{run_id}/signals")
async def get_run_signals(run_id: str) -> list[dict[str, Any]]:
    """Get all signals for a run."""
    active_signals = _run_service.get_active_signals(run_id)
    if active_signals is not None:
        return active_signals

    # Try to load from ledger
    from server.signals.emitter import SignalEmitter

    data_dir = _pipeline_config.data_dir
    ledger_path = data_dir / run_id / "signals.jsonl"
    if ledger_path.exists():
        signals = SignalEmitter.load_ledger(ledger_path)
        return [s.model_dump() for s in signals]

    raise HTTPException(status_code=404, detail=f"Signals for run {run_id} not found")


@router.get("/runs/{run_id}/records")
async def get_run_records(run_id: str) -> list[dict[str, Any]]:
    """Get extracted records for a completed run."""
    from server.pipeline.manager import PipelineManager

    data_dir = _pipeline_config.data_dir
    output_path = data_dir / run_id / "records.jsonl"

    if output_path.exists():
        records = PipelineManager.load_records(output_path)
        return [r.model_dump() for r in records]

    raise HTTPException(status_code=404, detail=f"Records for run {run_id} not found")


@router.post("/runs/{run_id}/abort")
async def abort_run(run_id: str) -> dict[str, str]:
    """Abort an active run."""
    _run_service.abort_run(run_id)
    return {"run_id": run_id, "status": "aborted"}


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    """List all active and recent completed runs."""
    return _run_service.list_runs()


# --- WebSocket for real-time Signal streaming ---


@router.websocket("/ws/runs/{run_id}")
async def websocket_signals(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time signal streaming during active runs.

    Clients connect here to receive signals as they are emitted.
    """
    await websocket.accept()

    _run_service.add_websocket(run_id, websocket)

    try:
        # Send existing signals as initial state
        for signal in _run_service.get_active_signal_models(run_id):
            await websocket.send_text(signal.model_dump_json())

        # Keep connection alive until client disconnects or run completes
        while True:
            try:
                # Wait for client messages (ping/pong or control)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send keepalive
                try:
                    await websocket.send_text('{"type":"keepalive"}')
                except Exception as exc:
                    emit_structured_error(
                        logger,
                        code=ErrorCode.API_WEBSOCKET_SEND_FAILED,
                        message=str(exc),
                        suppressed=True,
                        run_id=run_id,
                    )
                    break
            except WebSocketDisconnect:
                break
    finally:
        _run_service.remove_websocket(run_id, websocket)
