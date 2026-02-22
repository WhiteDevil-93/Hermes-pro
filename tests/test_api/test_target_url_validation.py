"""Target URL validation tests for run creation endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.api.app import app

client = TestClient(app)


def test_rejects_non_http_scheme() -> None:
    response = client.post("/api/v1/runs", json={"target_url": "file:///etc/passwd"})

    assert response.status_code == 400
    assert "Invalid URL scheme" in response.json()["detail"]


def test_rejects_loopback_ipv4_target() -> None:
    response = client.post("/api/v1/runs", json={"target_url": "http://127.0.0.1"})

    assert response.status_code == 400
    assert response.json()["detail"] == "target_url points to a blocked internal IP."


def test_rejects_private_ipv4_target() -> None:
    response = client.post("/api/v1/runs", json={"target_url": "http://10.0.0.8"})

    assert response.status_code == 400
    assert response.json()["detail"] == "target_url points to a blocked internal IP."


def test_rejects_link_local_ipv6_target() -> None:
    response = client.post("/api/v1/runs", json={"target_url": "http://[fe80::1]"})

    assert response.status_code == 400
    assert response.json()["detail"] == "target_url points to a blocked internal IP."
