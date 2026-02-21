"""Signal emitter — the nervous system of Hermes.

Handles emission, persistence, and streaming of Signals.
A Hermes run without Signals is a broken run.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from server.signals.types import Signal, SignalType


class SignalEmitter:
    """Emits, persists, and broadcasts signals for a single run.

    Signals are:
    - Immutable once emitted
    - Assigned monotonic sequence numbers
    - Persisted to a JSONL ledger in append-only mode
    - Streamed to subscribers (WebSocket clients) in real time
    """

    def __init__(self, run_id: str, ledger_path: Path | None = None) -> None:
        self._run_id = run_id
        self._sequence = 0
        self._ledger_path = ledger_path
        self._subscribers: list[Callable[[Signal], Any]] = []
        self._signals: list[Signal] = []
        self._lock = asyncio.Lock()

        # Ensure ledger directory exists
        if self._ledger_path:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def signals(self) -> list[Signal]:
        """Return all emitted signals (read-only copy)."""
        return list(self._signals)

    def subscribe(self, callback: Callable[[Signal], Any]) -> None:
        """Register a subscriber for real-time signal streaming."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Signal], Any]) -> None:
        """Remove a subscriber."""
        self._subscribers = [s for s in self._subscribers if s is not callback]

    async def emit(self, signal_type: SignalType, payload: dict[str, Any] | None = None) -> Signal:
        """Emit a signal. This is the ONLY way to create signals.

        Every signal gets:
        - A monotonic sequence number
        - A UTC timestamp
        - Persisted to the ledger
        - Broadcast to all subscribers
        """
        async with self._lock:
            self._sequence += 1
            signal = Signal(
                sequence=self._sequence,
                signal_type=signal_type,
                timestamp=datetime.now(timezone.utc),
                run_id=self._run_id,
                payload=payload or {},
            )
            self._signals.append(signal)

        # Persist to ledger (append-only)
        if self._ledger_path:
            await self._persist(signal)

        # Broadcast to subscribers
        await self._broadcast(signal)

        return signal

    async def _persist(self, signal: Signal) -> None:
        """Append signal to the JSONL ledger file."""
        line = signal.model_dump_json() + "\n"
        # Use synchronous write for simplicity; aiofiles for production
        with open(self._ledger_path, "a") as f:
            f.write(line)

    async def _broadcast(self, signal: Signal) -> None:
        """Notify all subscribers of a new signal."""
        for subscriber in self._subscribers:
            try:
                result = subscriber(signal)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Subscribers must not break the emission pipeline
                pass

    async def emit_phase_transition(
        self, from_phase: str, to_phase: str, context: dict[str, Any] | None = None
    ) -> Signal:
        """Convenience: emit a PHASE_TRANSITION signal."""
        return await self.emit(
            SignalType.PHASE_TRANSITION,
            {"from_phase": from_phase, "to_phase": to_phase, **(context or {})},
        )

    async def emit_run_complete(
        self, total_records: int, total_duration_s: float, ai_calls_count: int
    ) -> Signal:
        """Convenience: emit a RUN_COMPLETE signal."""
        return await self.emit(
            SignalType.RUN_COMPLETE,
            {
                "total_records": total_records,
                "total_duration_s": total_duration_s,
                "ai_calls_count": ai_calls_count,
            },
        )

    async def emit_run_failed(
        self, failure_reason: str, phase_at_failure: str, attempts_made: int
    ) -> Signal:
        """Convenience: emit a RUN_FAILED signal."""
        return await self.emit(
            SignalType.RUN_FAILED,
            {
                "failure_reason": failure_reason,
                "phase_at_failure": phase_at_failure,
                "attempts_made": attempts_made,
            },
        )

    @staticmethod
    def load_ledger(ledger_path: Path) -> list[Signal]:
        """Load all signals from a JSONL ledger file."""
        signals = []
        if ledger_path.exists():
            with open(ledger_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        signals.append(Signal.model_validate_json(line))
        return signals
