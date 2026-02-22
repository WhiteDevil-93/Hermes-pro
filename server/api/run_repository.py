"""Run repository for API lifecycle tracking and retention."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from server.conduit.engine import Conduit
from server.pipeline.manager import RunMetadata


class RunSummary(BaseModel):
    """Persistent summary for a pipeline run."""

    run_id: str
    phase: str
    status: str
    records_count: int = 0
    duration_s: float = 0
    ai_calls: int = 0
    signals_count: int = 0
    target_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunRepository:
    """Repository for active/completed runs with disk-backed summaries."""

    def __init__(
        self,
        data_dir: Path,
        max_completed_runs: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._max_completed_runs = max_completed_runs
        self._ttl_seconds = ttl_seconds

        self._active_runs: dict[str, Conduit] = {}
        self._run_tasks: dict[str, asyncio.Task[Any]] = {}
        self._completed_runs: dict[str, RunSummary] = {}

        self.hydrate_from_disk()

    @staticmethod
    def from_environment(data_dir: Path) -> "RunRepository":
        max_completed_raw = os.getenv("HERMES_MAX_COMPLETED_RUNS", "200").strip()
        ttl_raw = os.getenv("HERMES_RUN_TTL_SECONDS", "604800").strip()

        max_completed = int(max_completed_raw) if max_completed_raw else None
        ttl_seconds = int(ttl_raw) if ttl_raw else None

        return RunRepository(
            data_dir=data_dir,
            max_completed_runs=max_completed,
            ttl_seconds=ttl_seconds,
        )

    def register_active(self, conduit: Conduit) -> str:
        run_id = conduit.run_id
        self._active_runs[run_id] = conduit
        return run_id

    def set_task(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._run_tasks[run_id] = task

    def complete_run(self, run_id: str, result: dict[str, Any], target_url: str | None) -> None:
        summary = RunSummary(
            run_id=run_id,
            phase=result.get("phase", "UNKNOWN"),
            status=result.get("status", "unknown"),
            records_count=result.get("records_count", 0),
            duration_s=result.get("duration_s", 0),
            ai_calls=result.get("ai_calls", 0),
            signals_count=result.get("signals_count", 0),
            target_url=target_url,
            updated_at=datetime.now(timezone.utc),
        )
        self._completed_runs[run_id] = summary
        self._persist_summary(summary)
        self._evict_completed()

    def remove_active(self, run_id: str) -> None:
        self._active_runs.pop(run_id, None)
        self._run_tasks.pop(run_id, None)

    def abort_run(self, run_id: str) -> bool:
        task = self._run_tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        self.remove_active(run_id)
        return True

    def get_active(self, run_id: str) -> Conduit | None:
        return self._active_runs.get(run_id)

    def get_completed(self, run_id: str) -> RunSummary | None:
        return self._completed_runs.get(run_id)

    def has_active(self, run_id: str) -> bool:
        return run_id in self._active_runs

    def list_active(self) -> list[dict[str, Any]]:
        return [
            {"run_id": run_id, "phase": conduit.phase.value, "status": "running"}
            for run_id, conduit in self._active_runs.items()
        ]

    def list_completed(self) -> list[dict[str, Any]]:
        return [
            {"run_id": run_id, **summary.model_dump(mode="json")}
            for run_id, summary in sorted(
                self._completed_runs.items(),
                key=lambda item: item[1].updated_at,
                reverse=True,
            )
        ]

    def hydrate_from_disk(self) -> None:
        self._completed_runs.clear()
        if not self._data_dir.exists():
            return

        for run_dir in self._data_dir.iterdir():
            if not run_dir.is_dir():
                continue
            summary = self._load_summary(run_dir)
            if summary is not None:
                self._completed_runs[summary.run_id] = summary

        self._evict_completed()

    def _load_summary(self, run_dir: Path) -> RunSummary | None:
        summary_path = run_dir / "run_summary.json"
        if summary_path.exists():
            return RunSummary.model_validate_json(summary_path.read_text())

        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            return None

        metadata = RunMetadata.model_validate_json(metadata_path.read_text())
        updated_at = metadata.completed_at or metadata.started_at

        return RunSummary(
            run_id=metadata.run_id,
            phase="COMPLETE" if metadata.status == "complete" else "UNKNOWN",
            status=metadata.status,
            records_count=metadata.total_records,
            signals_count=metadata.total_signals,
            target_url=metadata.target_url,
            created_at=metadata.started_at,
            updated_at=updated_at,
        )

    def _persist_summary(self, summary: RunSummary) -> None:
        run_dir = self._data_dir / summary.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "run_summary.json"
        summary_path.write_text(summary.model_dump_json(indent=2))

    def _evict_completed(self) -> None:
        if not self._completed_runs:
            return

        now = time.time()
        if self._ttl_seconds is not None and self._ttl_seconds >= 0:
            expired = [
                run_id
                for run_id, summary in self._completed_runs.items()
                if now - summary.updated_at.timestamp() > self._ttl_seconds
            ]
            for run_id in expired:
                self._delete_run_summary(run_id)

        if self._max_completed_runs is not None and self._max_completed_runs >= 0:
            sorted_runs = sorted(
                self._completed_runs.items(), key=lambda item: item[1].updated_at, reverse=True
            )
            for run_id, _ in sorted_runs[self._max_completed_runs :]:
                self._delete_run_summary(run_id)

    def _delete_run_summary(self, run_id: str) -> None:
        self._completed_runs.pop(run_id, None)
        summary_path = self._data_dir / run_id / "run_summary.json"
        if summary_path.exists():
            summary_path.unlink()
