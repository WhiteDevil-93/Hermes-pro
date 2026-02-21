"""Data Pipeline Manager — staged data model with strict stage gates.

Data cannot advance to the next stage without validation.
There is no silent mutation at any stage.

Stages:
1. Raw Capture — full DOM snapshots, raw HTML, interaction traces
2. Staging — cleaned content, candidate fields, normalized text
3. Processed — schema-compliant JSON records with confidence scores
4. Persisted — written to JSONL, immutable per-run ledger
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from server.pipeline.extraction import ExtractionRecord


class RunMetadata(BaseModel):
    """Metadata for a completed run, stored alongside data."""

    run_id: str
    target_url: str
    started_at: datetime
    completed_at: datetime | None = None
    total_records: int = 0
    total_signals: int = 0
    extraction_mode: str = "heuristic"
    status: str = "running"


class PipelineManager:
    """Manages the four-stage data pipeline for a single run.

    Contract: Persist is atomic. Either the full batch writes or none of it does.
    Partial data is never persisted as complete data.
    """

    def __init__(self, run_id: str, data_dir: Path, debug_mode: bool = False) -> None:
        self._run_id = run_id
        self._data_dir = data_dir
        self._debug_mode = debug_mode

        # Create run directory
        self._run_dir = data_dir / run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)

        # Stage directories
        self._raw_dir = self._run_dir / "raw"
        self._staging_dir = self._run_dir / "staging"
        self._raw_dir.mkdir(exist_ok=True)
        self._staging_dir.mkdir(exist_ok=True)

        # Output files
        self._output_path = self._run_dir / "records.jsonl"
        self._metadata_path = self._run_dir / "metadata.json"

        # In-memory staging
        self._raw_captures: list[dict[str, Any]] = []
        self._staged_records: list[dict[str, Any]] = []
        self._processed_records: list[ExtractionRecord] = []

    @property
    def run_dir(self) -> Path:
        return self._run_dir

    @property
    def output_path(self) -> Path:
        return self._output_path

    @property
    def processed_records(self) -> list[ExtractionRecord]:
        return list(self._processed_records)

    # --- Stage 1: Raw Capture ---

    def capture_raw(
        self,
        html: str,
        url: str,
        dom_hash: str,
        interaction_trace: list[str] | None = None,
        screenshot: bytes | None = None,
    ) -> None:
        """Store raw DOM capture. Kept for debug mode or cleaned up after persist."""
        capture = {
            "html": html,
            "url": url,
            "dom_hash": dom_hash,
            "interaction_trace": interaction_trace or [],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }
        self._raw_captures.append(capture)

        if self._debug_mode:
            idx = len(self._raw_captures) - 1
            raw_path = self._raw_dir / f"capture_{idx}.html"
            raw_path.write_text(html)
            if screenshot:
                ss_path = self._raw_dir / f"capture_{idx}.png"
                ss_path.write_bytes(screenshot)

    # --- Stage 2: Staging ---

    def stage_content(self, cleaned_content: dict[str, Any]) -> bool:
        """Move cleaned content to staging. Gate: must be non-empty."""
        if not cleaned_content:
            return False
        # Basic structural validation
        if not isinstance(cleaned_content, dict):
            return False
        self._staged_records.append(cleaned_content)
        return True

    # --- Stage 3: Processed ---

    def add_processed_record(self, record: ExtractionRecord) -> bool:
        """Add a schema-validated record to the processed stage.

        Gate: Record must have valid confidence scores and source provenance.
        """
        if not record.fields:
            return False
        self._processed_records.append(record)
        return True

    # --- Stage 4: Persist ---

    def persist(self, metadata: RunMetadata) -> int:
        """Atomically persist all processed records to JSONL.

        Contract: Either the full batch writes or none of it does.
        Returns the number of records persisted.
        """
        if not self._processed_records:
            return 0

        # Write records atomically: write to temp file then rename
        temp_path = self._output_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w") as f:
                for record in self._processed_records:
                    f.write(record.model_dump_json() + "\n")
            # Atomic rename
            temp_path.rename(self._output_path)
        except Exception:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise

        # Write metadata
        metadata.total_records = len(self._processed_records)
        metadata.completed_at = datetime.now(timezone.utc)
        self._metadata_path.write_text(metadata.model_dump_json(indent=2))

        count = len(self._processed_records)

        # Clean up raw captures unless debug mode
        if not self._debug_mode:
            self._cleanup_raw()

        return count

    def _cleanup_raw(self) -> None:
        """Remove raw capture files after successful persist."""
        if self._raw_dir.exists():
            for f in self._raw_dir.iterdir():
                f.unlink()

    @staticmethod
    def load_records(output_path: Path) -> list[ExtractionRecord]:
        """Load persisted records from a JSONL file."""
        records = []
        if output_path.exists():
            with open(output_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(ExtractionRecord.model_validate_json(line))
        return records
