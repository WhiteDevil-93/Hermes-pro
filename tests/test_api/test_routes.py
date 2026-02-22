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

    def test_create_run_rejects_non_http_scheme(self, client):
        response = client.post(
            "/api/v1/runs",
            json={"target_url": "file:///etc/passwd", "extraction_mode": "heuristic"},
        )
        assert response.status_code == 400

    def test_create_run_rejects_private_network_target(self, client):
        response = client.post(
            "/api/v1/runs",
            json={"target_url": "http://127.0.0.1/admin", "extraction_mode": "heuristic"},
        )
        assert response.status_code == 400

    def test_create_run_rejects_ipv6_loopback_target(self, client):
        response = client.post(
            "/api/v1/runs",
            json={"target_url": "http://[::1]/admin", "extraction_mode": "heuristic"},
        )
        assert response.status_code == 400

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


class TestGroundingEndpoint:
    def test_grounding_search_rejects_data_dir_override(self, client, tmp_path, monkeypatch):
        from server.grounding import search_api

        trusted_dir = tmp_path / "trusted"
        run_dir = trusted_dir / "run_1"
        run_dir.mkdir(parents=True)
        (run_dir / "records.jsonl").write_text('{"fields": {"title": {"value": "alpha"}}}\n')

        attacker_dir = tmp_path / "attacker"
        attacker_run = attacker_dir / "run_2"
        attacker_run.mkdir(parents=True)
        (attacker_run / "records.jsonl").write_text('{"fields": {"title": {"value": "omega"}}}\n')

        monkeypatch.setattr(search_api._pipeline_config, "data_dir", trusted_dir)

        response = client.get(
            "/api/v1/grounding/search",
            params={"q": "alpha", "data_dir": str(attacker_dir)},
        )
        assert response.status_code == 400
        assert "data_dir override is disabled" in response.json()["detail"]

    def test_grounding_search_uses_configured_data_dir(self, client, tmp_path, monkeypatch):
        from server.grounding import search_api

        trusted_dir = tmp_path / "trusted"
        run_dir = trusted_dir / "run_1"
        run_dir.mkdir(parents=True)
        (run_dir / "records.jsonl").write_text('{"fields": {"title": {"value": "alpha"}}}\n')

        monkeypatch.setattr(search_api._pipeline_config, "data_dir", trusted_dir)

        response = client.get("/api/v1/grounding/search", params={"q": "alpha"})
        assert response.status_code == 200
        results = response.json()
        assert results
        assert any("alpha" in item.get("snippet", "") for item in results)
