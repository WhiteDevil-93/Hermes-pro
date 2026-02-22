"""Tests for the FastAPI REST API endpoints."""

import pytest
from fastapi.testclient import TestClient

from server.api.app import app


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
    def test_list_runs_empty(self, client):
        response = client.get("/api/v1/runs")
        assert response.status_code == 200
        data = response.json()
        assert "active" in data
        assert "completed" in data

    def test_get_nonexistent_run(self, client):
        response = client.get("/api/v1/runs/nonexistent_run_id")
        assert response.status_code == 404

    def test_abort_nonexistent_run(self, client):
        response = client.post("/api/v1/runs/nonexistent_run_id/abort")
        assert response.status_code == 404

    def test_get_signals_nonexistent_run(self, client):
        response = client.get("/api/v1/runs/nonexistent_run_id/signals")
        assert response.status_code == 404

    def test_get_records_nonexistent_run(self, client):
        response = client.get("/api/v1/runs/nonexistent_run_id/records")
        assert response.status_code == 404

    @pytest.mark.skipif(
        not __import__("shutil").which("chromium")
        and not __import__("shutil").which("chromium-browser"),
        reason="Playwright browser not installed — skips in environments without browser binaries",
    )
    def test_create_run_returns_run_id(self, client):
        """Test that the API accepts a valid run request and returns a run_id."""
        response = client.post(
            "/api/v1/runs",
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


class TestGroundingSearchEndpoint:
    def test_rejects_parent_traversal_data_dir(self, client, tmp_path, monkeypatch, caplog):
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        monkeypatch.setenv("HERMES_DATA_DIR", str(base_dir))

        with caplog.at_level("WARNING"):
            response = client.get("/api/v1/grounding/search", params={"q": "sample", "data_dir": "../"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid data_dir"
        assert "Blocked grounding search data_dir outside HERMES_DATA_DIR" in caplog.text

    def test_rejects_absolute_outside_base_data_dir(self, client, tmp_path, monkeypatch, caplog):
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        monkeypatch.setenv("HERMES_DATA_DIR", str(base_dir))

        with caplog.at_level("WARNING"):
            response = client.get(
                "/api/v1/grounding/search",
                params={"q": "sample", "data_dir": str(outside_dir.resolve())},
            )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid data_dir"
        assert "Blocked grounding search data_dir outside HERMES_DATA_DIR" in caplog.text
