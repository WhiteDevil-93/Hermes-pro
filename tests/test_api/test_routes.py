"""Tests for the FastAPI REST API endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.api import routes
from server.api.app import app

class _DummyTask:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


@pytest.fixture(autouse=True)
def clear_run_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DATA_DIR", str(tmp_path))
    routes._pipeline_config = routes.PipelineConfig()
    routes._active_runs.clear()
    routes._run_tasks.clear()
    routes._run_results.clear()
    routes._run_owners.clear()
    routes._websocket_connections.clear()


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "hermes"
        assert data["version"] == "2.0.0"


class TestRunEndpoints:
    @staticmethod
    def _auth_headers(principal: str = "alice") -> dict[str, str]:
        return {"Authorization": f"Bearer {principal}"}

    def test_list_runs_requires_auth(self, client):
        response = client.get("/api/v1/runs")
        assert response.status_code == 401

    def test_get_nonexistent_run(self, client):
        response = client.get(
            "/api/v1/runs/nonexistent_run_id",
            headers=self._auth_headers(),
        )
        assert response.status_code == 404

    def test_abort_nonexistent_run(self, client):
        response = client.post(
            "/api/v1/runs/nonexistent_run_id/abort",
            headers=self._auth_headers(),
        )
        assert response.status_code == 404

    def test_get_signals_nonexistent_run(self, client):
        response = client.get(
            "/api/v1/runs/nonexistent_run_id/signals",
            headers=self._auth_headers(),
        )
        assert response.status_code == 404

    def test_get_records_nonexistent_run(self, client):
        response = client.get(
            "/api/v1/runs/nonexistent_run_id/records",
            headers=self._auth_headers(),
        )
        assert response.status_code == 404

    def test_owner_access_enforced_for_status(self, client):
        routes._run_owners["run_owned"] = "alice"
        routes._run_results["run_owned"] = {"phase": "COMPLETE", "status": "complete"}

        response = client.get(
            "/api/v1/runs/run_owned",
            headers=self._auth_headers("bob"),
        )
        assert response.status_code == 403

    def test_owner_access_enforced_for_signals(self, client, tmp_path):
        run_id = "run_owned"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps({"run_id": run_id, "owner_principal": "alice"})
        )
        (run_dir / "signals.jsonl").write_text("")

        response = client.get(
            f"/api/v1/runs/{run_id}/signals",
            headers=self._auth_headers("bob"),
        )
        assert response.status_code == 403

    def test_owner_access_enforced_for_records(self, client, tmp_path):
        run_id = "run_owned"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps({"run_id": run_id, "owner_principal": "alice"})
        )
        (run_dir / "records.jsonl").write_text("")

        response = client.get(
            f"/api/v1/runs/{run_id}/records",
            headers=self._auth_headers("bob"),
        )
        assert response.status_code == 403

    def test_owner_access_enforced_for_abort(self, client):
        routes._run_owners["run_owned"] = "alice"
        routes._run_tasks["run_owned"] = _DummyTask()

        response = client.post(
            "/api/v1/runs/run_owned/abort",
            headers=self._auth_headers("bob"),
        )
        assert response.status_code == 403

    def test_authorized_status_success(self, client):
        routes._run_owners["run_owned"] = "alice"
        routes._run_results["run_owned"] = {
            "phase": "COMPLETE",
            "status": "complete",
            "records_count": 2,
        }

        response = client.get(
            "/api/v1/runs/run_owned",
            headers=self._auth_headers("alice"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "complete"

    def test_authorized_abort_success(self, client):
        routes._run_owners["run_abort"] = "alice"
        routes._run_tasks["run_abort"] = _DummyTask()

        response = client.post(
            "/api/v1/runs/run_abort/abort",
            headers=self._auth_headers("alice"),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "aborted"

    @pytest.mark.skipif(
        not __import__("shutil").which("chromium")
        and not __import__("shutil").which("chromium-browser"),
        reason="Playwright browser not installed — skips in environments without browser binaries",
    )
    def test_create_run_returns_run_id(self, client):
        """Test that the API accepts a valid run request and returns a run_id."""
        response = client.post(
            "/api/v1/runs",
            headers=self._auth_headers(),
            json={
                "target_url": "https://example.com",
                "extraction_mode": "heuristic",
                "heuristic_selectors": {"title": "h1"},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert data["status"] == "started"
        assert data["run_id"].startswith("run_")
