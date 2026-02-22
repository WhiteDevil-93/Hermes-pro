"""Service layer for run orchestration and websocket subscriptions."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import HTTPException, WebSocket

from server.api.run_repository import InMemoryRunRepository
from server.conduit.engine import Conduit
from server.telemetry.errors import ErrorCode, emit_structured_error

logger = logging.getLogger(__name__)


class RunService:
    def __init__(self, repository: InMemoryRunRepository) -> None:
        self._repository = repository

    async def create_run(self, conduit: Conduit) -> str:
        run_id = conduit.run_id
        entry = self._repository.create(conduit)

        async def signal_broadcaster(signal: Any) -> None:
            data = signal.model_dump_json()
            disconnected: list[WebSocket] = []
            for ws in entry.websockets:
                try:
                    await ws.send_text(data)
                except Exception as exc:
                    emit_structured_error(
                        logger,
                        code=ErrorCode.API_WEBSOCKET_SEND_FAILED,
                        message=str(exc),
                        suppressed=True,
                        run_id=run_id,
                        phase=conduit.phase.value,
                    )
                    disconnected.append(ws)
            for ws in disconnected:
                if ws in entry.websockets:
                    entry.websockets.remove(ws)

        conduit.signals.subscribe(signal_broadcaster)

        async def run_task() -> None:
            try:
                result = await conduit.run()
                self._repository.complete(run_id, result)
            finally:
                # Keep completed result in repository, only clear task/sockets by complete()
                if self._repository.get(run_id) and self._repository.get(run_id).result is None:
                    self._repository.remove(run_id)

        task = asyncio.create_task(run_task())
        self._repository.set_task(run_id, task)
        return run_id

    def get_status(self, run_id: str) -> dict[str, Any]:
        entry = self._repository.get(run_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        if entry.task is not None:
            return {
                "run_id": run_id,
                "phase": entry.conduit.phase.value,
                "status": "running",
                "signals_count": len(entry.conduit.signals.signals),
            }
        result = entry.result or {}
        return {
            "run_id": run_id,
            "phase": result.get("phase", "UNKNOWN"),
            "status": result.get("status", "unknown"),
            "records_count": result.get("records_count", 0),
            "duration_s": result.get("duration_s", 0),
            "ai_calls": result.get("ai_calls", 0),
            "signals_count": result.get("signals_count", 0),
        }

    def get_active_signals(self, run_id: str) -> list[dict[str, Any]] | None:
        entry = self._repository.get(run_id)
        if entry and entry.task is not None:
            return [s.model_dump() for s in entry.conduit.signals.signals]
        return None

    def list_runs(self) -> dict[str, Any]:
        active: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        for run_id, entry in self._repository.list_entries().items():
            if entry.task is not None:
                active.append(
                    {
                        "run_id": run_id,
                        "phase": entry.conduit.phase.value,
                        "status": "running",
                    }
                )
            elif entry.result is not None:
                completed.append({"run_id": run_id, **entry.result})
        return {"active": active, "completed": completed}

    def abort_run(self, run_id: str) -> None:
        entry = self._repository.get(run_id)
        if entry is None or entry.task is None:
            raise HTTPException(status_code=404, detail=f"Active run {run_id} not found")
        entry.task.cancel()
        self._repository.remove(run_id)

    def add_websocket(self, run_id: str, websocket: WebSocket) -> None:
        entry = self._repository.get(run_id)
        if entry is None:
            return
        entry.websockets.append(websocket)

    def remove_websocket(self, run_id: str, websocket: WebSocket) -> None:
        entry = self._repository.get(run_id)
        if entry is None:
            return
        entry.websockets = [ws for ws in entry.websockets if ws != websocket]

    def get_active_signal_models(self, run_id: str) -> list[Any]:
        entry = self._repository.get(run_id)
        if entry and entry.task is not None:
            return entry.conduit.signals.signals
        return []
