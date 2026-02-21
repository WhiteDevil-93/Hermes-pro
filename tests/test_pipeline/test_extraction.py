"""Tests for extraction data models and pipeline manager."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.pipeline.extraction import ExtractionRecord, FieldValue, RecordMetadata
from server.pipeline.manager import PipelineManager, RunMetadata


class TestFieldValue:
    def test_valid_confidence(self):
        fv = FieldValue(value="test", confidence=0.8)
        assert fv.confidence == 0.8

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            FieldValue(value="test", confidence=1.5)
        with pytest.raises(Exception):
            FieldValue(value="test", confidence=-0.1)

    def test_null_source_selector(self):
        fv = FieldValue(value="test", confidence=0.5, source_selector=None)
        assert fv.source_selector is None


class TestExtractionRecord:
    def test_basic_record(self):
        record = ExtractionRecord(
            fields={
                "name": FieldValue(value="Aspirin", confidence=1.0, source_selector=".drug-name"),
            },
            metadata=RecordMetadata(
                source_url="https://example.com/drug/aspirin",
                dom_hash="abc123",
                extraction_mode="heuristic",
            ),
        )
        assert record.fields["name"].value == "Aspirin"
        assert record.completeness_score == 1.0
        assert not record.is_partial

    def test_partial_record(self):
        record = ExtractionRecord(
            fields={"name": FieldValue(value="Test", confidence=0.5)},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="def456",
                extraction_mode="ai",
            ),
            is_partial=True,
            completeness_score=0.5,
        )
        assert record.is_partial
        assert record.completeness_score == 0.5

    def test_record_serialization(self):
        record = ExtractionRecord(
            fields={"title": FieldValue(value="Test Page", confidence=0.9)},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="hash123",
                extraction_mode="heuristic",
            ),
        )
        json_str = record.model_dump_json()
        restored = ExtractionRecord.model_validate_json(json_str)
        assert restored.fields["title"].value == "Test Page"


class TestPipelineManager:
    @pytest.fixture
    def pipeline(self, tmp_path):
        return PipelineManager(
            run_id="test_run",
            data_dir=tmp_path,
            debug_mode=False,
        )

    def test_run_dir_created(self, pipeline, tmp_path):
        assert (tmp_path / "test_run").exists()

    def test_capture_raw(self, pipeline):
        pipeline.capture_raw(
            html="<html><body>Test</body></html>",
            url="https://example.com",
            dom_hash="hash123",
        )
        assert len(pipeline._raw_captures) == 1

    def test_stage_content_rejects_empty(self, pipeline):
        assert not pipeline.stage_content({})
        assert not pipeline.stage_content(None)

    def test_stage_content_accepts_valid(self, pipeline):
        assert pipeline.stage_content({"title": "Test", "content": "Body text"})
        assert len(pipeline._staged_records) == 1

    def test_add_processed_record(self, pipeline):
        record = ExtractionRecord(
            fields={"title": FieldValue(value="Test", confidence=0.8)},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="hash",
                extraction_mode="heuristic",
            ),
        )
        assert pipeline.add_processed_record(record)
        assert len(pipeline.processed_records) == 1

    def test_add_processed_record_rejects_empty_fields(self, pipeline):
        record = ExtractionRecord(
            fields={},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="hash",
                extraction_mode="heuristic",
            ),
        )
        assert not pipeline.add_processed_record(record)

    def test_persist_atomic(self, pipeline):
        record = ExtractionRecord(
            fields={"title": FieldValue(value="Persisted", confidence=1.0)},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="hash",
                extraction_mode="heuristic",
            ),
        )
        pipeline.add_processed_record(record)

        metadata = RunMetadata(
            run_id="test_run",
            target_url="https://example.com",
            started_at=datetime.now(timezone.utc),
            status="complete",
        )
        count = pipeline.persist(metadata)
        assert count == 1
        assert pipeline.output_path.exists()

    def test_persist_empty_returns_zero(self, pipeline):
        metadata = RunMetadata(
            run_id="test_run",
            target_url="https://example.com",
            started_at=datetime.now(timezone.utc),
        )
        count = pipeline.persist(metadata)
        assert count == 0

    def test_load_persisted_records(self, pipeline, tmp_path):
        record = ExtractionRecord(
            fields={"name": FieldValue(value="LoadTest", confidence=0.9)},
            metadata=RecordMetadata(
                source_url="https://example.com",
                dom_hash="hash",
                extraction_mode="heuristic",
            ),
        )
        pipeline.add_processed_record(record)
        metadata = RunMetadata(
            run_id="test_run",
            target_url="https://example.com",
            started_at=datetime.now(timezone.utc),
        )
        pipeline.persist(metadata)

        loaded = PipelineManager.load_records(pipeline.output_path)
        assert len(loaded) == 1
        assert loaded[0].fields["name"].value == "LoadTest"
