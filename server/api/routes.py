"""REST API routes for Hermes."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

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


def _is_obviously_private_target(target_url: str) -> bool:
    """Best-effort guard against SSRF to local/private targets.

    This does not resolve DNS; it only validates obvious direct targets.
    """
    try:
        parsed = urlparse(target_url)
    except Exception:
        return True

    if parsed.scheme not in {"http", "https"}:
        return True

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return True

    if hostname in {"localhost", "0", "0.0.0.0", "::", "::1"}:
        return True

    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return True

    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
    )


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
        owner_principal=principal,
        browser=BrowserConfig(headless=request.headless),
        pipeline=PipelineConfig(debug_mode=request.debug_mode),
    )

    conduit = Conduit(config)
    run_id = await _run_service.create_run(conduit)

    return RunResponse(
        run_id=run_id,
        status="started",
        message=f"Run initiated for {request.target_url}",
        run_token=run_token,
    )


@router.get("/runs/{run_id}", response_model=RunStatus)
async def get_run_status(run_id: str) -> RunStatus:
    """Get the current status of a run."""
    return RunStatus(**_run_service.get_status(run_id))


@router.get("/runs/{run_id}/signals")
async def get_run_signals(run_id: str) -> list[dict[str, Any]]:
    """Get all signals for a run."""
    active_signals = _run_service.get_active_signals(run_id)
    if active_signals is not None:
        return active_signals

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
async def abort_run(run_id: str) -> dict[str, str]:
    """Abort an active run."""
    _run_service.abort_run(run_id)
    return {"run_id": run_id, "status": "aborted"}


@router.get("/runs")
async def list_runs() -> dict[str, Any]:
    """List all active and recent completed runs."""
    return _run_service.list_runs()


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

    _run_service.add_websocket(run_id, websocket)

    try:
        # Send existing signals as initial state
        for signal in _run_service.get_active_signal_models(run_id):
            await websocket.send_text(signal.model_dump_json())

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
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
