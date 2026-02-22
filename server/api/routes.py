"""REST API routes for Hermes."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from server.conduit.engine import Conduit
from server.config.settings import APIConfig, BrowserConfig, HermesConfig, PipelineConfig
from server.signals.types import Signal

router = APIRouter()

_pipeline_config = PipelineConfig()
_api_config = APIConfig()

# In-memory store for active and completed runs
_active_runs: dict[str, Conduit] = {}
_run_tasks: dict[str, asyncio.Task] = {}
_run_results: dict[str, dict[str, Any]] = {}
_run_tokens: dict[str, str] = {}
_run_order: list[str] = []
_websocket_connections: dict[str, list[WebSocket]] = {}
_run_summary_ledger = _pipeline_config.data_dir / "run_summaries.jsonl"


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
    run_token: str


class RunStatus(BaseModel):
    """Current status of a run."""

    run_id: str
    phase: str
    status: str
    records_count: int = 0
    duration_s: float = 0
    ai_calls: int = 0
    signals_count: int = 0


def _validate_api_token(auth_header: str | None, x_api_key: str | None) -> None:
    configured_token = _api_config.api_token
    if not configured_token:
        return

    bearer = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        bearer = auth_header[7:].strip()

    supplied = bearer or (x_api_key or "")
    if not secrets.compare_digest(supplied, configured_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")


def _validate_run_token(run_id: str, run_token: str | None) -> None:
    expected = _run_tokens.get(run_id)
    if expected is None:
        return
    if not run_token or not secrets.compare_digest(run_token, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing run token",
        )


def _append_run_summary(summary: dict[str, Any]) -> None:
    _run_summary_ledger.parent.mkdir(parents=True, exist_ok=True)
    with _run_summary_ledger.open("a", encoding="utf-8") as handle:
        import json

        handle.write(json.dumps(summary) + "\n")


def _load_run_summaries() -> dict[str, dict[str, Any]]:
    if not _run_summary_ledger.exists():
        return {}
    import json

    summaries: dict[str, dict[str, Any]] = {}
    with _run_summary_ledger.open(encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            entry = json.loads(payload)
            run_id = entry.get("run_id")
            if run_id:
                summaries[run_id] = entry
    return summaries


def _evict_if_needed() -> None:
    while len(_run_order) > _api_config.run_retention_limit:
        run_id = _run_order.pop(0)
        _run_results.pop(run_id, None)
        _run_tokens.pop(run_id, None)


def require_api_access(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    _validate_api_token(authorization, x_api_key)


@router.post("/runs", response_model=RunResponse)
async def create_run(request: RunRequest, _: None = Depends(require_api_access)) -> RunResponse:
    """Initiate a new scrape run."""
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
    run_id = conduit.run_id
    run_token = secrets.token_urlsafe(24)

    _active_runs[run_id] = conduit
    _run_tokens[run_id] = run_token

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

    async def run_task() -> None:
        try:
            result = await conduit.run()
            result["completed_at"] = datetime.now(timezone.utc).isoformat()
            _run_results[run_id] = result
            _run_order.append(run_id)
            _evict_if_needed()
            _append_run_summary(result)
        finally:
            _active_runs.pop(run_id, None)
            _run_tasks.pop(run_id, None)
            _websocket_connections.pop(run_id, None)

    task = asyncio.create_task(run_task())
    _run_tasks[run_id] = task

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run initiated for {request.target_url}",
        run_token=run_token,
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(
    run_id: str,
    run_token: str | None = Query(default=None),
    _: None = Depends(require_api_access),
) -> RunStatus:
    _validate_run_token(run_id, run_token)

    if run_id in _active_runs:
        conduit = _active_runs[run_id]
        return RunStatus(
            run_id=run_id,
            phase=conduit.phase.value,
            status="running",
            signals_count=len(conduit.signals.signals),
        )

    if run_id in _run_results:
        result = _run_results[run_id]
    else:
        persisted = _load_run_summaries()
        result = persisted.get(run_id)

    if result:
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
    run_token: str | None = Query(default=None),
    _: None = Depends(require_api_access),
) -> list[dict[str, Any]]:
    _validate_run_token(run_id, run_token)

    if run_id in _active_runs:
        return [s.model_dump() for s in _active_runs[run_id].signals.signals]

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
    run_token: str | None = Query(default=None),
    _: None = Depends(require_api_access),
) -> list[dict[str, Any]]:
    _validate_run_token(run_id, run_token)

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
    run_token: str | None = Query(default=None),
    _: None = Depends(require_api_access),
) -> dict[str, str]:
    _validate_run_token(run_id, run_token)

    if run_id in _run_tasks:
        task = _run_tasks[run_id]
        task.cancel()
        _active_runs.pop(run_id, None)
        return {"run_id": run_id, "status": "aborted"}

    raise HTTPException(status_code=404, detail=f"Active run {run_id} not found")


@router.get("/runs")
async def list_runs(_: None = Depends(require_api_access)) -> dict[str, Any]:
    active = [
        {"run_id": rid, "phase": conduit.phase.value, "status": "running"}
        for rid, conduit in _active_runs.items()
    ]
    completed = [
        {"run_id": rid, "status": result.get("status", "unknown"), **result}
        for rid, result in _run_results.items()
    ]
    return {"active": active, "completed": completed}


@router.websocket("/ws/runs/{run_id}")
async def websocket_signals(
    websocket: WebSocket,
    run_id: str,
    run_token: str | None = Query(default=None),
    api_token: str | None = Query(default=None),
) -> None:
    try:
        auth_header = websocket.headers.get("authorization")
        x_api_key = websocket.headers.get("x-api-key")
        _validate_api_token(auth_header, x_api_key or api_token)
        _validate_run_token(run_id, run_token)
    except HTTPException:
        await websocket.close(code=1008)
        return

    await websocket.accept()

    if run_id not in _websocket_connections:
        _websocket_connections[run_id] = []
    _websocket_connections[run_id].append(websocket)

    try:
        if run_id in _active_runs:
            for signal in _active_runs[run_id].signals.signals:
                await websocket.send_text(signal.model_dump_json())

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
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
