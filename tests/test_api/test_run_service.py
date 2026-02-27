"""Tests for RunService lifecycle and retention."""

from __future__ import annotations

import pytest

from server.api.run_service import RunService
from server.config.settings import RetentionConfig


class TestRunServiceRetention:
    def test_eviction_fifo(self):
        """When max_completed_runs is exceeded, oldest runs are evicted."""
        svc = RunService(retention=RetentionConfig(max_completed_runs=2))
        svc._run_results["run_old"] = {"status": "complete"}
        svc._run_results["run_mid"] = {"status": "complete"}
        svc._run_tokens["run_old"] = "token_old"
        svc._run_tokens["run_mid"] = "token_mid"

        svc.complete_run("run_new", {"status": "complete"})

        assert "run_old" not in svc.run_results
        assert "run_old" not in svc.run_tokens
        assert "run_mid" in svc.run_results
        assert "run_new" in svc.run_results

    def test_no_eviction_under_limit(self):
        """Runs are not evicted when under the retention limit."""
        svc = RunService(retention=RetentionConfig(max_completed_runs=10))
        svc.complete_run("run_1", {"status": "complete"})
        svc.complete_run("run_2", {"status": "complete"})

        assert len(svc.run_results) == 2

    def test_get_run_status_not_found(self):
        svc = RunService()
        assert svc.get_run_status("nonexistent") is None

    def test_abort_nonexistent_returns_false(self):
        svc = RunService()
        assert not svc.abort_run("nonexistent")

    def test_complete_run_cleans_up_active(self):
        """Completing a run removes it from active tracking."""
        svc = RunService()
        # Simulate an active run entry
        svc._active_runs["run_x"] = "mock_conduit"  # type: ignore[assignment]
        svc._run_tokens["run_x"] = "token_x"

        svc.complete_run("run_x", {"status": "complete"})

        assert "run_x" not in svc.active_runs
        assert "run_x" in svc.run_results

    def test_default_retention_limit(self):
        """Default retention allows 100 completed runs."""
        svc = RunService()
        assert svc._retention.max_completed_runs == 100
