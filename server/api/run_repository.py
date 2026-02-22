"""In-memory repository for run lifecycle state."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

if TYPE_CHECKING:
    from server.conduit.engine import Conduit


@dataclass
class RunEntry:
    conduit: "Conduit"
    task: asyncio.Task[None] | None = None
    result: dict[str, Any] | None = None
    websockets: list[WebSocket] = field(default_factory=list)


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._entries: dict[str, RunEntry] = {}

    def create(self, conduit: "Conduit") -> RunEntry:
        entry = RunEntry(conduit=conduit)
        self._entries[conduit.run_id] = entry
        return entry

    def get(self, run_id: str) -> RunEntry | None:
        return self._entries.get(run_id)

    def list_entries(self) -> dict[str, RunEntry]:
        return dict(self._entries)

    def set_task(self, run_id: str, task: asyncio.Task[None]) -> None:
        entry = self._entries[run_id]
        entry.task = task

    def complete(self, run_id: str, result: dict[str, Any]) -> None:
        entry = self._entries[run_id]
        entry.result = result
        entry.task = None
        entry.websockets.clear()

    def remove(self, run_id: str) -> None:
        self._entries.pop(run_id, None)
