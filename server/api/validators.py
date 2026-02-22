"""Validation helpers for API request payloads."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from fastapi import HTTPException

from server.config.settings import TargetURLPolicyConfig

_ALLOWED_SCHEMES = {"http", "https"}


def validate_target_url(target_url: str, policy: TargetURLPolicyConfig) -> None:
    """Validate a run target URL against scheme/domain/network policy."""
    parsed = urlparse(target_url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid URL scheme '{parsed.scheme}'. Allowed schemes: http, https.",
        )

    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="target_url must include a hostname.")

    hostname = parsed.hostname.lower().rstrip(".")

    if policy.denied_domains and _domain_matches(hostname, policy.denied_domains):
        raise HTTPException(status_code=400, detail="target_url domain is denied by policy.")

    if policy.allowed_domains and not _domain_matches(hostname, policy.allowed_domains):
        raise HTTPException(status_code=400, detail="target_url domain is not in allowlist.")

    if not policy.block_private_network_targets:
        return

    host_ip = _parse_ip(hostname)
    if host_ip and _is_blocked_ip(host_ip):
        raise HTTPException(status_code=400, detail="target_url points to a blocked internal IP.")


def _parse_ip(hostname: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        return None


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Block any IP address that is not globally routable. This includes private,
    # link-local, loopback, unspecified, multicast, and reserved address ranges.
    return not address.is_global


def _domain_matches(hostname: str, domains: list[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains)
