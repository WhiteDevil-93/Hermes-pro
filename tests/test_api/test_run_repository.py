"""Tests for run repository retention and hydration behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from server.api.run_repository import RunRepository, RunSummary


def test_hydrates_completed_runs_from_disk(tmp_path):
    run_dir = tmp_path / "run_abc"
    run_dir.mkdir(parents=True)
    (run_dir / "run_summary.json").write_text(
        RunSummary(
            run_id="run_abc",
            phase="COMPLETE",
            status="complete",
            records_count=3,
            updated_at=datetime.now(timezone.utc),
        ).model_dump_json()
    )

    repository = RunRepository(data_dir=tmp_path)

    summary = repository.get_completed("run_abc")
    assert summary is not None
    assert summary.status == "complete"
    assert summary.records_count == 3


def test_ttl_eviction_removes_expired_run_summaries(tmp_path):
    repository = RunRepository(data_dir=tmp_path, ttl_seconds=1)

    old_summary = RunSummary(
        run_id="run_old",
        phase="COMPLETE",
        status="complete",
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    repository._completed_runs[old_summary.run_id] = old_summary
    repository._persist_summary(old_summary)

    repository._evict_completed()

    assert repository.get_completed("run_old") is None
    assert not (tmp_path / "run_old" / "run_summary.json").exists()


def test_count_eviction_keeps_most_recent_runs(tmp_path):
    repository = RunRepository(data_dir=tmp_path, max_completed_runs=2)

    summaries = [
        RunSummary(
            run_id=f"run_{i}",
            phase="COMPLETE",
            status="complete",
            updated_at=datetime.now(timezone.utc) + timedelta(seconds=i),
        )
        for i in range(3)
    ]

    for summary in summaries:
        repository._completed_runs[summary.run_id] = summary
        repository._persist_summary(summary)

    repository._evict_completed()

    assert repository.get_completed("run_0") is None
    assert repository.get_completed("run_1") is not None
    assert repository.get_completed("run_2") is not None
