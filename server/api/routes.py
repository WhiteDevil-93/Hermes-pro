"""REST API routes for Hermes.

Provides endpoints for:
- Initiating scrape runs
- Monitoring run status
- Viewing results and signals
- Managing configuration
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from server.api.auth import (
    AUTH_REQUIRED_DETAIL,
    extract_principal_from_headers,
    require_authenticated_principal,
)
from server.conduit.engine import Conduit
from server.config.settings import BrowserConfig, HermesConfig, PipelineConfig
from server.signals.types import Signal

router = APIRouter()

_pipeline_config = PipelineConfig()

# In-memory store for active and completed runs
_active_runs: dict[str, Conduit] = {}
_run_tasks: dict[str, asyncio.Task] = {}
_run_results: dict[str, dict[str, Any]] = {}
_run_owners: dict[str, str] = {}
_websocket_connections: dict[str, list[WebSocket]] = {}


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


def _metadata_path_for_run(run_id: str) -> Path:
    return _pipeline_config.data_dir / run_id / "metadata.json"


def _get_run_owner(run_id: str) -> str | None:
    owner = _run_owners.get(run_id)
    if owner:
        return owner

    metadata_path = _metadata_path_for_run(run_id)
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text())
            owner = metadata.get("owner_principal")
            if owner:
                _run_owners[run_id] = owner
            return owner
        except Exception:
            return None

    return None


def _enforce_run_access(run_id: str, principal: str) -> None:
    owner = _get_run_owner(run_id)
    if owner is None:
        return
    if owner != principal:
        raise HTTPException(status_code=403, detail="Forbidden")


# --- Endpoints ---


@router.post("/runs", response_model=RunResponse)
async def create_run(
    request: RunRequest,
    principal: str = Depends(require_authenticated_principal),
) -> RunResponse:
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
        owner_principal=principal,
        browser=BrowserConfig(headless=request.headless),
        pipeline=PipelineConfig(debug_mode=request.debug_mode),
    )

    conduit = Conduit(config)
    run_id = conduit.run_id

    _active_runs[run_id] = conduit
    _run_owners[run_id] = principal

    # Register WebSocket broadcaster
    async def signal_broadcaster(signal: Signal) -> None:
        if run_id in _websocket_connections:
            data = signal.model_dump_json()
            disconnected = []
            for ws in _websocket_connections[run_id]:
                try:
                    await ws.send_text(data)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                _websocket_connections[run_id].remove(ws)

    conduit.signals.subscribe(signal_broadcaster)

    # Launch run as background task
    async def run_task() -> None:
        try:
            result = await conduit.run()
            _run_results[run_id] = result
        finally:
            # Ensure we always clean up per-run state, regardless of success, failure, or cancellation
            _active_runs.pop(run_id, None)
            _run_tasks.pop(run_id, None)
            _websocket_connections.pop(run_id, None)

    task = asyncio.create_task(run_task())
    _run_tasks[run_id] = task

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run initiated for {request.target_url}",
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(
    run_id: str,
    principal: str = Depends(require_authenticated_principal),
) -> RunStatus:
    """Get the current status of a run."""
    _enforce_run_access(run_id, principal)

    # Check active runs
    if run_id in _active_runs:
        conduit = _active_runs[run_id]
        return RunStatus(
            run_id=run_id,
            phase=conduit.phase.value,
            status="running",
            signals_count=len(conduit.signals.signals),
        )

    # Check completed runs
    if run_id in _run_results:
        result = _run_results[run_id]
        return RunStatus(
            run_id=run_id,
            phase=result.get("phase", "UNKNOWN"),
            status=result.get("status", "unknown"),
            records_count=result.get("records_count", 0),
            duration_s=result.get("duration_s", 0),
            ai_calls=result.get("ai_calls", 0),
            signals_count=result.get("signals_count", 0),
        )

    raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.get("/runs/{run_id}/signals")
async def get_run_signals(
    run_id: str,
    principal: str = Depends(require_authenticated_principal),
) -> list[dict[str, Any]]:
    """Get all signals for a run."""
    _enforce_run_access(run_id, principal)

    if run_id in _active_runs:
        return [s.model_dump() for s in _active_runs[run_id].signals.signals]

    # Try to load from ledger
    from server.signals.emitter import SignalEmitter

    data_dir = _pipeline_config.data_dir
    ledger_path = data_dir / run_id / "signals.jsonl"
    if ledger_path.exists():
        signals = SignalEmitter.load_ledger(ledger_path)
        return [s.model_dump() for s in signals]

    raise HTTPException(status_code=404, detail=f"Signals for run {run_id} not found")


@router.get("/runs/{run_id}/records")
async def get_run_records(
    run_id: str,
    principal: str = Depends(require_authenticated_principal),
) -> list[dict[str, Any]]:
    """Get extracted records for a completed run."""
    _enforce_run_access(run_id, principal)

    from server.pipeline.manager import PipelineManager

    data_dir = _pipeline_config.data_dir
    output_path = data_dir / run_id / "records.jsonl"

    if output_path.exists():
        records = PipelineManager.load_records(output_path)
        return [r.model_dump() for r in records]

    raise HTTPException(status_code=404, detail=f"Records for run {run_id} not found")


@router.post("/runs/{run_id}/abort")
async def abort_run(
    run_id: str,
    principal: str = Depends(require_authenticated_principal),
) -> dict[str, str]:
    """Abort an active run."""
    _enforce_run_access(run_id, principal)

    if run_id in _run_tasks:
        task = _run_tasks[run_id]
        task.cancel()
        _active_runs.pop(run_id, None)
        return {"run_id": run_id, "status": "aborted"}

    raise HTTPException(status_code=404, detail=f"Active run {run_id} not found")


@router.get("/runs")
async def list_runs(principal: str = Depends(require_authenticated_principal)) -> dict[str, Any]:
    """List all active and recent completed runs owned by the caller."""
    active = [
        {"run_id": rid, "phase": c.phase.value, "status": "running"}
        for rid, c in _active_runs.items()
        if _get_run_owner(rid) == principal
    ]
    completed = [
        {"run_id": rid, "status": result.get("status", "unknown"), **result}
        for rid, result in _run_results.items()
        if _get_run_owner(rid) == principal
    ]
    return {"active": active, "completed": completed}


# --- WebSocket for real-time Signal streaming ---


@router.websocket("/ws/runs/{run_id}")
async def websocket_signals(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time signal streaming during active runs.

    Clients connect here to receive signals as they are emitted.
    """
    principal = extract_principal_from_headers(websocket)
    if principal is None:
        await websocket.close(code=4401, reason=AUTH_REQUIRED_DETAIL)
        return

    try:
        _enforce_run_access(run_id, principal)
    except HTTPException:
        await websocket.close(code=4403, reason="Forbidden")
        return

    await websocket.accept()

    if run_id not in _websocket_connections:
        _websocket_connections[run_id] = []
    _websocket_connections[run_id].append(websocket)

    try:
        # Send existing signals as initial state
        if run_id in _active_runs:
            for signal in _active_runs[run_id].signals.signals:
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
                except Exception:
                    break
            except WebSocketDisconnect:
                break
    finally:
        if run_id in _websocket_connections:
            _websocket_connections[run_id] = [
                ws for ws in _websocket_connections[run_id] if ws != websocket
            ]
