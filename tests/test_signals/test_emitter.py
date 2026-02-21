"""Tests for the Signal emitter system."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from server.signals.emitter import SignalEmitter
from server.signals.types import Signal, SignalType


@pytest.fixture
def tmp_ledger(tmp_path):
    return tmp_path / "test_run" / "signals.jsonl"


@pytest.fixture
def emitter(tmp_ledger):
    return SignalEmitter(run_id="test_run_001", ledger_path=tmp_ledger)


class TestSignalEmitter:
    """Test signal emission, persistence, and broadcasting."""

    @pytest.mark.asyncio
    async def test_emit_creates_signal(self, emitter):
        signal = await emitter.emit(SignalType.PHASE_TRANSITION, {"from": "INIT", "to": "NAVIGATE"})
        assert signal.sequence == 1
        assert signal.signal_type == SignalType.PHASE_TRANSITION
        assert signal.run_id == "test_run_001"
        assert signal.payload["from"] == "INIT"

    @pytest.mark.asyncio
    async def test_monotonic_sequence(self, emitter):
        s1 = await emitter.emit(SignalType.PHASE_TRANSITION)
        s2 = await emitter.emit(SignalType.ACTION_EXECUTED)
        s3 = await emitter.emit(SignalType.EXTRACTION_COMPLETE)
        assert s1.sequence == 1
        assert s2.sequence == 2
        assert s3.sequence == 3

    @pytest.mark.asyncio
    async def test_signals_are_immutable(self, emitter):
        signal = await emitter.emit(SignalType.PHASE_TRANSITION, {"key": "value"})
        with pytest.raises(Exception):
            signal.payload = {"modified": True}

    @pytest.mark.asyncio
    async def test_signals_persisted_to_ledger(self, emitter, tmp_ledger):
        await emitter.emit(SignalType.PHASE_TRANSITION, {"from": "INIT", "to": "NAVIGATE"})
        await emitter.emit(SignalType.RUN_COMPLETE, {"total_records": 5})

        assert tmp_ledger.exists()
        lines = tmp_ledger.read_text().strip().split("\n")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_load_ledger(self, emitter, tmp_ledger):
        await emitter.emit(SignalType.PHASE_TRANSITION, {"from": "INIT", "to": "NAVIGATE"})
        await emitter.emit(SignalType.RUN_COMPLETE, {"total_records": 5})

        loaded = SignalEmitter.load_ledger(tmp_ledger)
        assert len(loaded) == 2
        assert loaded[0].signal_type == SignalType.PHASE_TRANSITION
        assert loaded[1].signal_type == SignalType.RUN_COMPLETE

    @pytest.mark.asyncio
    async def test_subscriber_receives_signals(self, emitter):
        received = []

        def on_signal(signal):
            received.append(signal)

        emitter.subscribe(on_signal)
        await emitter.emit(SignalType.PHASE_TRANSITION)
        await emitter.emit(SignalType.ACTION_EXECUTED)

        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe(self, emitter):
        received = []

        def on_signal(signal):
            received.append(signal)

        emitter.subscribe(on_signal)
        await emitter.emit(SignalType.PHASE_TRANSITION)

        emitter.unsubscribe(on_signal)
        await emitter.emit(SignalType.ACTION_EXECUTED)

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_subscriber_error_does_not_break_emission(self, emitter):
        def bad_subscriber(signal):
            raise RuntimeError("Subscriber failure")

        emitter.subscribe(bad_subscriber)

        # Should not raise
        signal = await emitter.emit(SignalType.PHASE_TRANSITION)
        assert signal.sequence == 1

    @pytest.mark.asyncio
    async def test_signals_property_returns_copy(self, emitter):
        await emitter.emit(SignalType.PHASE_TRANSITION)
        signals = emitter.signals
        assert len(signals) == 1
        signals.clear()
        assert len(emitter.signals) == 1  # Original not affected

    @pytest.mark.asyncio
    async def test_emit_phase_transition_convenience(self, emitter):
        signal = await emitter.emit_phase_transition("INIT", "NAVIGATE", {"reason": "start"})
        assert signal.signal_type == SignalType.PHASE_TRANSITION
        assert signal.payload["from_phase"] == "INIT"
        assert signal.payload["to_phase"] == "NAVIGATE"
        assert signal.payload["reason"] == "start"

    @pytest.mark.asyncio
    async def test_emit_run_complete_convenience(self, emitter):
        signal = await emitter.emit_run_complete(
            total_records=10, total_duration_s=45.2, ai_calls_count=3
        )
        assert signal.signal_type == SignalType.RUN_COMPLETE
        assert signal.payload["total_records"] == 10
        assert signal.payload["total_duration_s"] == 45.2

    @pytest.mark.asyncio
    async def test_emit_run_failed_convenience(self, emitter):
        signal = await emitter.emit_run_failed(
            failure_reason="Timeout", phase_at_failure="NAVIGATE", attempts_made=3
        )
        assert signal.signal_type == SignalType.RUN_FAILED
        assert signal.payload["failure_reason"] == "Timeout"
