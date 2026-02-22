"""Tests for the FastAPI REST API endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.api import routes
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

class TestCorsConfiguration:
    def test_dev_allows_wildcard_only_with_explicit_toggle(self, monkeypatch):
        monkeypatch.setenv("HERMES_ENV", "development")
        monkeypatch.delenv("HERMES_ALLOWED_ORIGINS", raising=False)
        monkeypatch.setenv("HERMES_DEV_ALLOW_ALL_ORIGINS", "true")

        from server.api.app import _resolve_cors_origins

        assert _resolve_cors_origins() == ["*"]

    def test_dev_defaults_to_no_origins_without_toggle(self, monkeypatch):
        monkeypatch.setenv("HERMES_ENV", "development")
        monkeypatch.delenv("HERMES_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("HERMES_DEV_ALLOW_ALL_ORIGINS", raising=False)

        from server.api.app import _resolve_cors_origins

        assert _resolve_cors_origins() == []

    def test_production_requires_explicit_origins(self, monkeypatch):
        monkeypatch.setenv("HERMES_ENV", "production")
        monkeypatch.delenv("HERMES_ALLOWED_ORIGINS", raising=False)
        monkeypatch.delenv("HERMES_DEV_ALLOW_ALL_ORIGINS", raising=False)

        from server.api.app import _resolve_cors_origins

        with pytest.raises(RuntimeError, match="HERMES_ALLOWED_ORIGINS"):
            _resolve_cors_origins()

    def test_production_accepts_configured_origins(self, monkeypatch):
        monkeypatch.setenv("HERMES_ENV", "production")
        monkeypatch.setenv(
            "HERMES_ALLOWED_ORIGINS",
            "https://ui.example.com, https://admin.example.com",
        )

        from server.api.app import _resolve_cors_origins

        assert _resolve_cors_origins() == [
            "https://ui.example.com",
            "https://admin.example.com",
        ]

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


class TestGroundingEndpoint:
    def test_grounding_search_ignores_data_dir_override(self, client, tmp_path, monkeypatch):
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
        assert response.status_code == 200
        results = response.json()
        assert results
        assert any("alpha" in item.get("snippet", "") for item in results)
        assert all("omega" not in item.get("snippet", "") for item in results)
