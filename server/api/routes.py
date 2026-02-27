"""REST API routes for Hermes.

Provides endpoints for:
- Initiating scrape runs
- Monitoring run status
- Viewing results and signals
- Managing configuration
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from server.api.auth import _get_bearer_token, require_api_auth
from server.api.run_service import RunService
from server.config.settings import BrowserConfig, HermesConfig, PipelineConfig, URLPolicyConfig
from server.config.url_policy import validate_target_url
from server.signals.types import Signal

router = APIRouter()

_pipeline_config = PipelineConfig()
_run_service = RunService()


def _authorize_run_access(run_id: str, token: str) -> None:
    """Check if the given token has access to the specified run.

    Accepts either the global API token or the run-specific token.
    When auth is disabled (no HERMES_API_TOKEN), all access is allowed.
    """
    api_token = os.getenv("HERMES_API_TOKEN", "")
    if not api_token:
        return  # Auth disabled
    if secrets.compare_digest(token, api_token):
        return  # Global admin token
    stored = _run_service.run_tokens.get(run_id, "")
    if stored and secrets.compare_digest(token, stored):
        return  # Valid run token
    raise HTTPException(status_code=403, detail="Insufficient permissions for this run")


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
    run_token: str = ""


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
async def create_run(
    request: RunRequest, _: str = Depends(require_api_auth)
) -> RunResponse:
    """Initiate a new scrape run.

    The run executes asynchronously. Use the returned run_id
    to monitor progress via GET /runs/{run_id} or WebSocket.
    """
    # Validate target URL against SSRF policy
    url_check = validate_target_url(request.target_url, URLPolicyConfig())
    if not url_check.allowed:
        raise HTTPException(
            status_code=400, detail=f"Target URL rejected: {url_check.reason}"
        )

    config = HermesConfig(
        target_url=request.target_url,
        extraction_schema=request.extraction_schema,
        extraction_mode=request.extraction_mode,
        heuristic_selectors=request.heuristic_selectors,
        allow_cross_origin=request.allow_cross_origin,
        browser=BrowserConfig(headless=request.headless),
        pipeline=PipelineConfig(debug_mode=request.debug_mode),
    )

    conduit, run_token = _run_service.create_run(config)
    run_id = conduit.run_id

    # Register WebSocket broadcaster
    async def signal_broadcaster(signal: Signal) -> None:
        conns = _run_service.websocket_connections.get(run_id, [])
        if conns:
            data = signal.model_dump_json()
            disconnected = []
            for ws in conns:
                try:
                    await ws.send_text(data)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                conns.remove(ws)

    conduit.signals.subscribe(signal_broadcaster)

    # Launch run as background task
    async def run_task() -> None:
        try:
            result = await conduit.run()
            _run_service.complete_run(run_id, result)
        except Exception:
            _run_service.complete_run(run_id, {"status": "failed", "phase": "UNKNOWN"})

    task = asyncio.create_task(run_task())
    _run_service.register_task(run_id, task)

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run initiated for {request.target_url}",
        run_token=run_token,
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(
    run_id: str, token: str = Depends(_get_bearer_token)
) -> RunStatus:
    """Get the current status of a run."""
    _authorize_run_access(run_id, token)

    # Check active runs
    if run_id in _run_service.active_runs:
        conduit = _run_service.active_runs[run_id]
        return RunStatus(
            run_id=run_id,
            phase=conduit.phase.value,
            status="running",
            signals_count=len(conduit.signals.signals),
        )

    # Check completed runs
    if run_id in _run_service.run_results:
        result = _run_service.run_results[run_id]
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


def _get_data_dir() -> Path:
    """Resolve the data directory from environment or default."""
    return Path(os.getenv("HERMES_DATA_DIR", "./data"))


@router.get("/runs/{run_id}/signals")
async def get_run_signals(
    run_id: str, token: str = Depends(_get_bearer_token)
) -> list[dict[str, Any]]:
    """Get all signals for a run."""
    _authorize_run_access(run_id, token)

    if run_id in _run_service.active_runs:
        return [s.model_dump() for s in _run_service.active_runs[run_id].signals.signals]

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
    run_id: str, token: str = Depends(_get_bearer_token)
) -> list[dict[str, Any]]:
    """Get extracted records for a completed run."""
    _authorize_run_access(run_id, token)

    from server.pipeline.manager import PipelineManager

    data_dir = _pipeline_config.data_dir
    output_path = data_dir / run_id / "records.jsonl"

    if output_path.exists():
        records = PipelineManager.load_records(output_path)
        return [r.model_dump() for r in records]

    raise HTTPException(status_code=404, detail=f"Records for run {run_id} not found")


@router.post("/runs/{run_id}/abort")
async def abort_run(
    run_id: str, token: str = Depends(_get_bearer_token)
) -> dict[str, str]:
    """Abort an active run."""
    _authorize_run_access(run_id, token)

    if _run_service.abort_run(run_id):
        return {"run_id": run_id, "status": "aborted"}

    raise HTTPException(status_code=404, detail=f"Active run {run_id} not found")


@router.get("/runs")
async def list_runs(_: str = Depends(require_api_auth)) -> dict[str, Any]:
    """List all active and recent completed runs."""
    active = [
        {"run_id": rid, "phase": c.phase.value, "status": "running"}
        for rid, c in _run_service.active_runs.items()
    ]
    completed = [
        {"run_id": rid, "status": result.get("status", "unknown"), **result}
        for rid, result in _run_service.run_results.items()
    ]
    return {"active": active, "completed": completed}


# --- WebSocket for real-time Signal streaming ---


@router.websocket("/ws/runs/{run_id}")
async def websocket_signals(
    websocket: WebSocket, run_id: str, token: str = Query(default="")
) -> None:
    """WebSocket endpoint for real-time signal streaming during active runs.

    Clients connect here to receive signals as they are emitted.
    Pass token as a query parameter for authentication.
    """
    # Validate token before accepting connection
    api_token = os.getenv("HERMES_API_TOKEN", "")
    if api_token:
        stored_run_token = _run_service.run_tokens.get(run_id, "")
        if not (
            secrets.compare_digest(token, api_token)
            or (stored_run_token and secrets.compare_digest(token, stored_run_token))
        ):
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await websocket.accept()

    ws_conns = _run_service.websocket_connections
    if run_id not in ws_conns:
        ws_conns[run_id] = []
    ws_conns[run_id].append(websocket)

    try:
        # Send existing signals as initial state
        if run_id in _run_service.active_runs:
            for signal in _run_service.active_runs[run_id].signals.signals:
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
        if run_id in ws_conns:
            ws_conns[run_id] = [ws for ws in ws_conns[run_id] if ws != websocket]
