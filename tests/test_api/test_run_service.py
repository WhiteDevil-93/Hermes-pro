"""Tests for run service/repository orchestration."""

from __future__ import annotations

import asyncio

from server.api.run_repository import InMemoryRunRepository
from server.api.run_service import RunService


class _FakeSignals:
    def __init__(self) -> None:
        self.signals: list = []

    def subscribe(self, callback):
        self._subscriber = callback


class _FakeConduit:
    def __init__(self, run_id: str = "run_test") -> None:
        self.run_id = run_id
        self.phase = type("P", (), {"value": "INIT"})()
        self.signals = _FakeSignals()

    async def run(self):
        await asyncio.sleep(0)
        return {
            "run_id": self.run_id,
            "status": "complete",
            "phase": "COMPLETE",
            "records_count": 0,
            "duration_s": 0,
            "ai_calls": 0,
            "signals_count": 0,
        }


def test_create_run_completes_and_lists_in_completed():
    async def _run() -> None:
        service = RunService(InMemoryRunRepository())
        conduit = _FakeConduit()

        run_id = await service.create_run(conduit)
        await asyncio.sleep(0.01)

        status = service.get_status(run_id)
        assert status["status"] == "complete"

        runs = service.list_runs()
        assert runs["active"] == []
        assert len(runs["completed"]) == 1
        assert runs["completed"][0]["run_id"] == run_id

    asyncio.run(_run())
