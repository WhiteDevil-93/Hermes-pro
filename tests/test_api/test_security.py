"""Tests for security controls: auth, SSRF, directory traversal."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestAuthentication:
    """Test API token authentication enforcement."""

    def test_no_auth_required_when_env_unset(self):
        """When HERMES_API_TOKEN is not set, all endpoints are accessible."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HERMES_API_TOKEN", None)
            from server.api.app import app

            client = TestClient(app)
            response = client.get("/api/v1/runs")
            assert response.status_code == 200

    def test_auth_required_when_env_set(self):
        """When HERMES_API_TOKEN is set, requests without token get 401."""
        with patch.dict(os.environ, {"HERMES_API_TOKEN": "test-secret-token"}):
            from server.api.app import app

            client = TestClient(app)
            response = client.get("/api/v1/runs")
            assert response.status_code == 401

    def test_auth_succeeds_with_valid_token(self):
        """Requests with valid Bearer token succeed."""
        with patch.dict(os.environ, {"HERMES_API_TOKEN": "test-secret-token"}):
            from server.api.app import app

            client = TestClient(app)
            response = client.get(
                "/api/v1/runs",
                headers={"Authorization": "Bearer test-secret-token"},
            )
            assert response.status_code == 200

    def test_auth_rejects_invalid_token(self):
        """Requests with wrong token get 401."""
        with patch.dict(os.environ, {"HERMES_API_TOKEN": "test-secret-token"}):
            from server.api.app import app

            client = TestClient(app)
            response = client.get(
                "/api/v1/runs",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert response.status_code == 401


class TestURLPolicy:
    """Test SSRF URL validation."""

    def test_rejects_file_scheme(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("file:///etc/passwd", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_javascript_scheme(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("javascript:alert(1)", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_loopback_ipv4(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://127.0.0.1/admin", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_loopback_ipv6(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://[::1]/admin", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_private_10_range(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://10.0.0.1/internal", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_private_172_range(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://172.16.0.1/internal", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_private_192_range(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://192.168.1.1/router", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_localhost(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://localhost:8080/api", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_dot_local(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://myserver.local/api", URLPolicyConfig())
        assert not result.allowed

    def test_rejects_empty_scheme(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("//example.com/page", URLPolicyConfig())
        assert not result.allowed

    def test_allows_public_ip(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        # 93.184.216.34 is example.com's IP — a public IP
        result = validate_target_url("http://93.184.216.34/page", URLPolicyConfig())
        assert result.allowed

    def test_rejects_link_local(self):
        from server.config.settings import URLPolicyConfig
        from server.config.url_policy import validate_target_url

        result = validate_target_url("http://169.254.1.1/metadata", URLPolicyConfig())
        assert not result.allowed


class TestGroundingDataDirLockdown:
    """Test that grounding search API no longer accepts data_dir parameter."""

    def test_search_ignores_data_dir_param(self):
        """The data_dir query parameter must not influence filesystem reads."""
        from server.api.app import app

        client = TestClient(app)
        # Attempt to pass data_dir — should be ignored (not a recognized param)
        response = client.get(
            "/api/v1/grounding/search",
            params={"q": "test", "data_dir": "/etc"},
        )
        assert response.status_code == 200

    def test_search_returns_empty_for_missing_data(self):
        """Search returns empty list when no extraction data exists."""
        from server.api.app import app

        client = TestClient(app)
        response = client.get(
            "/api/v1/grounding/search",
            params={"q": "nonexistent_query_xyz"},
        )
        assert response.status_code == 200
        assert response.json() == []
