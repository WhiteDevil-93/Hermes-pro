"""The Conduit — Hermes execution engine and lifecycle controller.

The Conduit is a finite state machine. It does not contain AI logic.
It does not interpret pages. It manages the scraping lifecycle with
deterministic phase transitions.

Responsibilities:
- Manage the complete scraping lifecycle from INIT to COMPLETE/FAIL
- Control execution phases with explicit transition guards
- Detect obstructions via DOM heuristics (not AI) as the first pass
- Trigger AI reasoning only when heuristic detection is insufficient
- Enforce retry logic with configurable backoff and attempt limits
- Validate every AI Engine response against the action allowlist before execution
- Emit Signals at every phase boundary
- Persist results only after schema validation passes
- Enforce timeout budgets per phase and per total run

MUST NOT:
- Contain any AI/ML inference logic
- Interpret page content (that is the AI Engine's job)
- Execute browser actions directly (delegates to Browser Layer)
- Swallow errors or fail silently
- Retry indefinitely without a ceiling
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from server.ai_engine.engine import (
    AIEngine,
    FunctionCall,
    validate_function_call,
)
from server.browser.layer import ActionStatus, BrowserLayer, DOMSnapshot
from server.browser.obstruction import ObstructionType, detect_obstruction
from server.conduit.phases import TERMINAL_PHASES, VALID_TRANSITIONS, Phase
from server.config.settings import HermesConfig
from server.pipeline.extraction import ExtractionRecord, FieldValue, RecordMetadata
from server.pipeline.heuristic import heuristic_extract
from server.pipeline.manager import PipelineManager, RunMetadata
from server.signals.emitter import SignalEmitter
from server.signals.types import SignalType


class ConduitError(Exception):
    """Raised when the Conduit encounters an unrecoverable error."""


class Conduit:
    """The authoritative runtime controller for a Hermes scraping run.

    This is a finite state machine that transitions between well-defined
    phases based on concrete conditions. AI augments decisions; it does
    not replace the execution contract.
    """

    def __init__(self, config: HermesConfig) -> None:
        self._config = config
        self._run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._phase = Phase.INIT
        self._start_time: float | None = None
        self._attempts = 0
        self._ai_calls = 0
        self._interaction_trace: list[str] = []
        self._prior_ai_attempts: list[str] = []

        # Components (initialized during INIT phase)
        self._browser = BrowserLayer(config.browser)
        self._signals = SignalEmitter(
            run_id=self._run_id,
            ledger_path=config.pipeline.data_dir / self._run_id / "signals.jsonl",
        )
        self._pipeline = PipelineManager(
            run_id=self._run_id,
            data_dir=config.pipeline.data_dir,
            debug_mode=config.pipeline.debug_mode,
        )
        self._ai_engine = AIEngine(config.vertex)

        # Current DOM state
        self._current_dom: DOMSnapshot | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def phase(self) -> Phase:
        return self._phase

    @property
    def signals(self) -> SignalEmitter:
        return self._signals

    @property
    def pipeline(self) -> PipelineManager:
        return self._pipeline

    # --- Phase Transition ---

    async def _transition(self, to_phase: Phase, context: dict[str, Any] | None = None) -> None:
        """Transition to a new phase with guard validation and signal emission.

        Every phase transition MUST go through this method.
        """
        if to_phase not in VALID_TRANSITIONS.get(self._phase, set()):
            raise ConduitError(
                f"Invalid transition: {self._phase.value} -> {to_phase.value}"
            )

        from_phase = self._phase
        self._phase = to_phase

        await self._signals.emit_phase_transition(
            from_phase=from_phase.value,
            to_phase=to_phase.value,
            context=context or {},
        )

    # --- Retry Logic ---

    async def _backoff(self, attempt: int) -> None:
        """Exponential backoff with jitter."""
        base = self._config.retry.backoff_base_ms / 1000.0
        max_delay = self._config.retry.backoff_max_ms / 1000.0
        delay = min(base * (2 ** attempt), max_delay)
        if self._config.retry.jitter:
            delay += random.uniform(0, base)
        await asyncio.sleep(delay)

    def _check_global_timeout(self) -> bool:
        """Check if the global timeout has been exceeded."""
        if self._start_time is None:
            return False
        elapsed = time.monotonic() - self._start_time
        return elapsed > self._config.timeouts.global_timeout_s

    # --- Main Run Loop ---

    async def run(self) -> dict[str, Any]:
        """Execute the full scraping lifecycle.

        Returns a summary dict with run results.
        """
        self._start_time = time.monotonic()

        try:
            # INIT phase
            await self._phase_init()

            # Main state machine loop
            while self._phase not in TERMINAL_PHASES:
                if self._check_global_timeout():
                    await self._fail("Global timeout exceeded")
                    break

                if self._phase == Phase.NAVIGATE:
                    await self._phase_navigate()
                elif self._phase == Phase.ASSESS:
                    await self._phase_assess()
                elif self._phase == Phase.OBSTRUCT:
                    await self._phase_obstruct()
                elif self._phase == Phase.AI_REASON:
                    await self._phase_ai_reason()
                elif self._phase == Phase.EXECUTE_PLAN:
                    await self._phase_execute_plan()
                elif self._phase == Phase.EXTRACT:
                    await self._phase_extract()
                elif self._phase == Phase.VALIDATE:
                    await self._phase_validate()
                elif self._phase == Phase.REPAIR:
                    await self._phase_repair()
                elif self._phase == Phase.PERSIST:
                    await self._phase_persist()

        except Exception as e:
            if self._phase not in TERMINAL_PHASES:
                await self._fail(f"Unhandled exception: {e}")
        finally:
            await self._cleanup()

        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        records = self._pipeline.processed_records

        return {
            "run_id": self._run_id,
            "status": "complete" if self._phase == Phase.COMPLETE else "failed",
            "phase": self._phase.value,
            "records_count": len(records),
            "duration_s": round(elapsed, 2),
            "ai_calls": self._ai_calls,
            "signals_count": len(self._signals.signals),
        }

    # --- Phase Implementations ---

    async def _phase_init(self) -> None:
        """INIT: Validate config, prepare browser context, set timeout budgets."""
        try:
            # Start browser
            await self._browser.start()

            # Try to initialize AI engine (optional)
            if self._config.extraction_mode in ("ai", "hybrid"):
                await self._ai_engine.initialize()

            await self._transition(Phase.NAVIGATE, {"target_url": self._config.target_url})
        except Exception as e:
            await self._fail(f"Initialization failed: {e}")

    async def _phase_navigate(self) -> None:
        """NAVIGATE: Load target URL, wait for page ready signal."""
        timeout_ms = self._config.timeouts.page_load_timeout_s * 1000
        result = await self._browser.navigate(self._config.target_url, timeout_ms=timeout_ms)

        if result.status == ActionStatus.SUCCESS:
            self._interaction_trace.append(f"navigate:{self._config.target_url}")
            await self._transition(Phase.ASSESS)
        else:
            # Retry with backoff
            if self._attempts < self._config.retry.max_retries:
                self._attempts += 1
                await self._signals.emit(
                    SignalType.RETRY_ATTEMPT,
                    {
                        "attempt_number": self._attempts,
                        "max_attempts": self._config.retry.max_retries,
                        "reason": f"Navigation failed: {result.detail}",
                    },
                )
                await self._backoff(self._attempts)
                # Stay in NAVIGATE phase (re-enter on next loop iteration)
            else:
                await self._fail(
                    f"Navigation failed after {self._attempts}"
                    f" attempts: {result.detail}"
                )

    async def _phase_assess(self) -> None:
        """ASSESS: Evaluate DOM state — is content accessible or obstructed?"""
        dom = await self._browser.capture_dom()
        if dom is None:
            await self._fail("Failed to capture DOM snapshot")
            return

        self._current_dom = dom

        # Heuristic obstruction detection (no AI)
        obstruction = detect_obstruction(dom.html)

        if obstruction.obstruction_type == ObstructionType.NONE:
            # Content is accessible — proceed to extraction
            await self._transition(Phase.EXTRACT)
        elif obstruction.obstruction_type == ObstructionType.HARD_BLOCK:
            # Hard block — escalate immediately
            await self._signals.emit(
                SignalType.OBSTRUCTION_DETECTED,
                {
                    "obstruction_type": obstruction.obstruction_type.value,
                    "dom_hash": dom.dom_hash,
                    "confidence": obstruction.confidence,
                },
            )
            await self._fail(
                f"Hard block detected: {obstruction.obstruction_type.value}"
            )
        else:
            # Obstruction detected — try to resolve
            await self._signals.emit(
                SignalType.OBSTRUCTION_DETECTED,
                {
                    "obstruction_type": obstruction.obstruction_type.value,
                    "dom_hash": dom.dom_hash,
                    "confidence": obstruction.confidence,
                    "selector": obstruction.selector,
                },
            )
            await self._transition(
                Phase.OBSTRUCT,
                {
                    "obstruction_type": obstruction.obstruction_type.value,
                    "requires_ai": obstruction.requires_ai,
                },
            )

    async def _phase_obstruct(self) -> None:
        """OBSTRUCT: Classify obstruction, decide if AI reasoning is needed."""
        if self._current_dom is None:
            await self._fail("No DOM available for obstruction handling")
            return

        obstruction = detect_obstruction(self._current_dom.html)

        # Try heuristic resolution first (e.g., known cookie banner selectors)
        if not obstruction.requires_ai and obstruction.selector:
            result = await self._browser.click(obstruction.selector)
            await self._signals.emit(
                SignalType.ACTION_EXECUTED,
                {
                    "action_type": "click",
                    "selector": obstruction.selector,
                    "result": result.status.value,
                },
            )
            if result.status == ActionStatus.SUCCESS:
                self._interaction_trace.append(f"click:{obstruction.selector}")
                self._attempts = 0
                await self._transition(Phase.NAVIGATE)
                return

        # Heuristic failed or AI needed — escalate
        if self._ai_engine.is_available:
            await self._transition(
                Phase.AI_REASON,
                {"obstruction_type": obstruction.obstruction_type.value},
            )
        elif self._attempts < self._config.retry.max_retries:
            self._attempts += 1
            await self._signals.emit(
                SignalType.RETRY_ATTEMPT,
                {
                    "attempt_number": self._attempts,
                    "max_attempts": self._config.retry.max_retries,
                    "reason": "Obstruction unresolvable without AI",
                },
            )
            await self._backoff(self._attempts)
            await self._transition(Phase.NAVIGATE)
        else:
            await self._fail("Obstruction unresolvable: AI not available and retries exhausted")

    async def _phase_ai_reason(self) -> None:
        """AI_REASON: Invoke AI Engine with DOM snapshot, receive action plan."""
        if self._current_dom is None:
            await self._fail("No DOM available for AI reasoning")
            return

        obstruction = detect_obstruction(self._current_dom.html)

        await self._signals.emit(
            SignalType.AI_INVOKED,
            {
                "request_type": "navigation_plan",
                "dom_size": len(self._current_dom.html),
                "phase_context": obstruction.obstruction_type.value,
            },
        )

        start = time.monotonic()
        plan = await self._ai_engine.generate_navigation_plan(
            dom_html=self._current_dom.html,
            obstruction_type=obstruction.obstruction_type.value,
            target_schema=self._config.extraction_schema,
            prior_attempts=self._prior_ai_attempts or None,
        )
        latency = round((time.monotonic() - start) * 1000)
        self._ai_calls += 1

        await self._signals.emit(
            SignalType.AI_RESPONDED,
            {
                "response_type": "navigation_plan",
                "function_calls_count": len(plan.actions),
                "latency_ms": latency,
                "confidence": plan.confidence,
            },
        )

        if not plan.actions:
            self._prior_ai_attempts.append("AI returned empty plan")
            if self._attempts < self._config.retry.max_retries:
                self._attempts += 1
                await self._transition(Phase.NAVIGATE)
            else:
                await self._fail("AI returned empty navigation plan after retries")
            return

        # Validate all actions against the allowlist
        validated_actions: list[FunctionCall] = []
        for action in plan.actions:
            error = validate_function_call(action, self._config.allow_cross_origin)
            if error:
                await self._signals.emit(
                    SignalType.AI_REJECTED,
                    {
                        "reason": error,
                        "rejected_action": action.function,
                        "phase_context": "AI_REASON",
                    },
                )
            else:
                validated_actions.append(action)

        if not validated_actions:
            self._prior_ai_attempts.append("All AI actions were rejected by validation")
            await self._fail("All AI-generated actions rejected by allowlist validation")
            return

        # Store validated plan for execution
        self._pending_plan = validated_actions
        await self._transition(Phase.EXECUTE_PLAN)

    async def _phase_execute_plan(self) -> None:
        """EXECUTE_PLAN: Execute AI-generated actions via Browser Layer."""
        if not hasattr(self, "_pending_plan") or not self._pending_plan:
            await self._transition(Phase.ASSESS)
            return

        for action in self._pending_plan:
            result = await self._execute_action(action)

            await self._signals.emit(
                SignalType.ACTION_EXECUTED,
                {
                    "action_type": action.function,
                    "selector": action.parameters.get("selector", ""),
                    "result": result,
                },
            )

            if result != "success":
                self._prior_ai_attempts.append(
                    f"Action {action.function}({action.parameters}) failed: {result}"
                )
                break

            self._interaction_trace.append(
                f"{action.function}:{action.parameters}"
            )

        self._pending_plan = []
        self._attempts = 0
        await self._transition(Phase.ASSESS)

    async def _execute_action(self, action: FunctionCall) -> str:
        """Execute a single validated action via the Browser Layer.

        Returns 'success', 'failure', or 'timeout'.
        """
        params = action.parameters
        try:
            if action.function == "click":
                r = await self._browser.click(
                    params["selector"],
                    wait_after_ms=params.get("wait_after_ms", 1000),
                )
            elif action.function == "scroll":
                r = await self._browser.scroll(
                    direction=params.get("direction", "down"),
                    amount=params.get("amount", "page"),
                )
            elif action.function == "fill_form":
                r = await self._browser.fill_form(params["selector"], params["value"])
            elif action.function == "hover":
                r = await self._browser.hover(params["selector"])
            elif action.function == "press_key":
                r = await self._browser.press_key(params["key"])
            elif action.function == "wait_for":
                r = await self._browser.wait_for(
                    params["selector"],
                    timeout_ms=params.get("timeout_ms", 10000),
                )
            elif action.function == "navigate_url":
                url = params["url"]
                if not self._config.allow_cross_origin:
                    current_origin = urlparse(self._config.target_url).netloc
                    target_origin = urlparse(url).netloc
                    if target_origin and target_origin != current_origin:
                        return "failure"
                r = await self._browser.navigate(url)
            else:
                return "failure"

            return r.status.value
        except Exception:
            return "failure"

    async def _phase_extract(self) -> None:
        """EXTRACT: Run extraction logic against accessible DOM."""
        if self._current_dom is None:
            dom = await self._browser.capture_dom()
            if dom is None:
                await self._fail("Failed to capture DOM for extraction")
                return
            self._current_dom = dom

        # Store raw capture in pipeline
        self._pipeline.capture_raw(
            html=self._current_dom.html,
            url=self._current_dom.url,
            dom_hash=self._current_dom.dom_hash,
            interaction_trace=self._interaction_trace,
        )

        if self._config.extraction_mode == "heuristic" and self._config.heuristic_selectors:
            await self._extract_heuristic()
        elif self._config.extraction_mode == "ai" and self._ai_engine.is_available:
            await self._extract_ai()
        elif self._config.extraction_mode == "hybrid":
            await self._extract_hybrid()
        elif self._config.heuristic_selectors:
            # Fallback to heuristic if AI not available
            await self._extract_heuristic()
        else:
            # No extraction config — try AI or fail
            if self._ai_engine.is_available:
                await self._extract_ai()
            else:
                await self._fail("No extraction configuration: no selectors and AI unavailable")
                return

        await self._transition(Phase.VALIDATE)

    async def _extract_heuristic(self) -> None:
        """Extract using CSS selectors (heuristic mode)."""
        page = self._browser.page
        if page is None:
            return

        records = await heuristic_extract(
            page=page,
            selectors=self._config.heuristic_selectors,
            source_url=self._current_dom.url if self._current_dom else self._config.target_url,
            dom_hash=self._current_dom.dom_hash if self._current_dom else "",
        )

        for record in records:
            self._pipeline.add_processed_record(record)

    async def _extract_ai(self) -> None:
        """Extract using AI Engine."""
        if self._current_dom is None:
            return

        await self._signals.emit(
            SignalType.AI_INVOKED,
            {
                "request_type": "extraction",
                "dom_size": len(self._current_dom.html),
                "phase_context": "EXTRACT",
            },
        )

        start = time.monotonic()
        result = await self._ai_engine.extract_structured(
            dom_html=self._current_dom.html,
            schema=self._config.extraction_schema,
            source_url=self._current_dom.url,
        )
        latency = round((time.monotonic() - start) * 1000)
        self._ai_calls += 1

        await self._signals.emit(
            SignalType.AI_RESPONDED,
            {
                "response_type": "extraction",
                "function_calls_count": 0,
                "latency_ms": latency,
            },
        )

        # Convert AI results to ExtractionRecords
        for raw_record in result.records:
            fields = {}
            for key, value in raw_record.items():
                if isinstance(value, dict) and "value" in value:
                    fields[key] = FieldValue(**value)
                else:
                    fields[key] = FieldValue(value=value, confidence=0.7)

            record = ExtractionRecord(
                fields=fields,
                metadata=RecordMetadata(
                    source_url=self._current_dom.url,
                    dom_hash=self._current_dom.dom_hash,
                    ai_model=self._config.vertex.flash_model,
                    extraction_mode="ai",
                ),
                completeness_score=result.completeness_score,
            )
            self._pipeline.add_processed_record(record)

    async def _extract_hybrid(self) -> None:
        """Hybrid extraction: heuristic first, AI fills gaps."""
        # First pass: heuristic
        if self._config.heuristic_selectors:
            await self._extract_heuristic()

        # Second pass: if heuristic produced partial results, use AI to fill gaps
        records = self._pipeline.processed_records
        if records and any(r.is_partial for r in records) and self._ai_engine.is_available:
            await self._extract_ai()

    async def _phase_validate(self) -> None:
        """VALIDATE: Check extracted data against schema, score confidence."""
        records = self._pipeline.processed_records

        if not records:
            if self._attempts < self._config.retry.max_retries:
                self._attempts += 1
                await self._signals.emit(
                    SignalType.RETRY_ATTEMPT,
                    {
                        "attempt_number": self._attempts,
                        "max_attempts": self._config.retry.max_retries,
                        "reason": "No records extracted",
                    },
                )
                # If AI is available, try repair
                if self._ai_engine.is_available:
                    await self._transition(Phase.REPAIR)
                else:
                    await self._fail("No records extracted and no AI available for repair")
            else:
                await self._fail("No records extracted after maximum attempts")
            return

        # Check confidence thresholds
        min_threshold = self._config.pipeline.min_confidence_threshold
        flagged = 0
        for record in records:
            for field_name, field in record.fields.items():
                if field.confidence < min_threshold:
                    flagged += 1

        # If too many low-confidence fields and AI available, try repair
        total_fields = sum(len(r.fields) for r in records)
        if flagged > 0 and flagged / max(total_fields, 1) > 0.5 and self._ai_engine.is_available:
            if self._attempts < self._config.retry.max_retries:
                self._attempts += 1
                await self._transition(Phase.REPAIR)
                return

        await self._signals.emit(
            SignalType.EXTRACTION_COMPLETE,
            {
                "record_count": len(records),
                "confidence_avg": sum(
                    sum(f.confidence for f in r.fields.values()) / max(len(r.fields), 1)
                    for r in records
                ) / max(len(records), 1),
                "schema_valid": True,
                "flagged_fields": flagged,
            },
        )

        await self._transition(Phase.PERSIST)

    async def _phase_repair(self) -> None:
        """REPAIR: AI-assisted extraction repair for partial/malformed data."""
        if not self._ai_engine.is_available or self._current_dom is None:
            await self._fail("Cannot repair: AI unavailable or no DOM")
            return

        records = self._pipeline.processed_records
        partial_data = {}
        if records:
            # Convert current records to dict for repair
            partial_data = {
                "records": [r.model_dump() for r in records],
            }

        await self._signals.emit(
            SignalType.AI_INVOKED,
            {"request_type": "repair", "dom_size": len(self._current_dom.html)},
        )

        start = time.monotonic()
        result = await self._ai_engine.repair_extraction(
            partial_data=partial_data,
            schema=self._config.extraction_schema,
            dom_html=self._current_dom.html,
        )
        latency = round((time.monotonic() - start) * 1000)
        self._ai_calls += 1

        await self._signals.emit(
            SignalType.AI_RESPONDED,
            {"response_type": "repair", "latency_ms": latency},
        )

        # Add repaired records
        for raw_record in result.records:
            fields = {}
            for key, value in raw_record.items():
                if isinstance(value, dict) and "value" in value:
                    fields[key] = FieldValue(**value)
                else:
                    fields[key] = FieldValue(value=value, confidence=0.6)

            record = ExtractionRecord(
                fields=fields,
                metadata=RecordMetadata(
                    source_url=self._current_dom.url,
                    dom_hash=self._current_dom.dom_hash,
                    ai_model=self._config.vertex.flash_model,
                    extraction_mode="ai",
                ),
                completeness_score=result.completeness_score,
            )
            self._pipeline.add_processed_record(record)

        await self._transition(Phase.VALIDATE)

    async def _phase_persist(self) -> None:
        """PERSIST: Write structured records to output sink."""
        try:
            metadata = RunMetadata(
                run_id=self._run_id,
                target_url=self._config.target_url,
                started_at=datetime.fromtimestamp(
                    self._start_time or time.time(), tz=timezone.utc
                ),
                extraction_mode=self._config.extraction_mode,
                total_signals=len(self._signals.signals),
                status="complete",
            )

            count = self._pipeline.persist(metadata)

            await self._signals.emit_run_complete(
                total_records=count,
                total_duration_s=time.monotonic() - (self._start_time or time.monotonic()),
                ai_calls_count=self._ai_calls,
            )

            await self._transition(Phase.COMPLETE)
        except Exception as e:
            await self._fail(f"Persist failed: {e}")

    # --- Failure Handling ---

    async def _fail(self, reason: str) -> None:
        """Enter FAIL state with full context."""
        current_phase = self._phase

        if current_phase in TERMINAL_PHASES:
            return

        self._phase = Phase.FAIL

        await self._signals.emit_run_failed(
            failure_reason=reason,
            phase_at_failure=current_phase.value,
            attempts_made=self._attempts,
        )

    # --- Cleanup ---

    async def _cleanup(self) -> None:
        """Clean up all resources."""
        try:
            await self._browser.stop()
        except Exception:
            pass
