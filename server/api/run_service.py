"""Run lifecycle service — owns all in-memory run state.

Centralizes run creation, tracking, abortion, and retention eviction
that was previously scattered across module-level dicts in routes.py.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import OrderedDict
from typing import Any

from server.conduit.engine import Conduit
from server.config.settings import HermesConfig, RetentionConfig

logger = logging.getLogger(__name__)


class RunService:
    """Manages the lifecycle of all Hermes runs.

    Responsibilities:
    - Create, track, and abort runs
    - Manage run ownership tokens
    - Enforce retention limits with FIFO eviction
    - Provide run status queries
    """

    def __init__(self, retention: RetentionConfig | None = None) -> None:
        self._retention = retention or RetentionConfig()
        self._active_runs: dict[str, Conduit] = {}
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._run_results: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._run_tokens: dict[str, str] = {}
        self._websocket_connections: dict[str, list] = {}

    @property
    def active_runs(self) -> dict[str, Conduit]:
        return self._active_runs

    @property
    def run_results(self) -> OrderedDict[str, dict[str, Any]]:
        return self._run_results

    @property
    def run_tokens(self) -> dict[str, str]:
        return self._run_tokens

    @property
    def websocket_connections(self) -> dict[str, list]:
        return self._websocket_connections

    def create_run(self, config: HermesConfig) -> tuple[Conduit, str]:
        """Create a new run, returning the Conduit and run_token."""
        conduit = Conduit(config)
        run_id = conduit.run_id
        run_token = secrets.token_urlsafe(32)

        self._active_runs[run_id] = conduit
        self._run_tokens[run_id] = run_token

        return conduit, run_token

    def register_task(self, run_id: str, task: asyncio.Task) -> None:
        """Register an asyncio task for a run."""
        self._run_tasks[run_id] = task

    def complete_run(self, run_id: str, result: dict[str, Any]) -> None:
        """Mark a run as completed and apply eviction."""
        self._run_results[run_id] = result
        self._active_runs.pop(run_id, None)
        self._run_tasks.pop(run_id, None)
        self._websocket_connections.pop(run_id, None)
        self._evict_completed()

    def _evict_completed(self) -> None:
        """FIFO eviction of oldest completed runs."""
        while len(self._run_results) > self._retention.max_completed_runs:
            evicted_id, _ = self._run_results.popitem(last=False)
            self._run_tokens.pop(evicted_id, None)
            logger.info(
                "Evicted completed run %s (retention limit: %d)",
                evicted_id,
                self._retention.max_completed_runs,
            )

    def abort_run(self, run_id: str) -> bool:
        """Abort an active run. Returns True if found and cancelled."""
        if run_id in self._run_tasks:
            self._run_tasks[run_id].cancel()
            self._active_runs.pop(run_id, None)
            return True
        return False

    def get_run_status(self, run_id: str) -> dict[str, Any] | None:
        """Get status of a run (active or completed). Returns None if not found."""
        if run_id in self._active_runs:
            conduit = self._active_runs[run_id]
            return {
                "run_id": run_id,
                "phase": conduit.phase.value,
                "status": "running",
                "signals_count": len(conduit.signals.signals),
            }
        if run_id in self._run_results:
            return {"run_id": run_id, **self._run_results[run_id]}
        return None
