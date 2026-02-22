"""Unit tests for target URL validator policy behavior."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.api.validators import validate_target_url
from server.config.settings import TargetURLPolicyConfig


def test_allowlist_blocks_non_matching_domain() -> None:
    policy = TargetURLPolicyConfig(allowed_domains=["example.com"])

    with pytest.raises(HTTPException) as exc:
        validate_target_url("https://evil.com", policy)

    assert exc.value.status_code == 400
    assert exc.value.detail == "target_url domain is not in allowlist."


def test_allowlist_allows_subdomain() -> None:
    policy = TargetURLPolicyConfig(allowed_domains=["example.com"])

    validate_target_url("https://docs.example.com", policy)


def test_denylist_blocks_matching_domain() -> None:
    policy = TargetURLPolicyConfig(denied_domains=["example.com"])

    with pytest.raises(HTTPException) as exc:
        validate_target_url("https://api.example.com", policy)

    assert exc.value.status_code == 400
    assert exc.value.detail == "target_url domain is denied by policy."


def test_private_ip_allowed_when_policy_disabled() -> None:
    policy = TargetURLPolicyConfig(block_private_network_targets=False)

    validate_target_url("http://127.0.0.1", policy)
