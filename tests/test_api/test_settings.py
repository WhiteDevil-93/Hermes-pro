"""Tests for API-related settings validation."""

import pytest

from server.config.settings import APIConfig


def test_api_config_default_origins():
    cfg = APIConfig()
    assert cfg.allowed_origins


def test_api_config_rejects_wildcard_origin():
    with pytest.raises(ValueError):
        APIConfig(allowed_origins=["*"])


def test_api_config_rejects_invalid_origin_url():
    with pytest.raises(ValueError):
        APIConfig(allowed_origins=["localhost:3000"])


def test_api_config_rejects_non_positive_retention():
    with pytest.raises(ValueError):
        APIConfig(run_retention_limit=0)
