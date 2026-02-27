"""URL validation for SSRF prevention.

Validates target URLs against a configurable policy to prevent
Server-Side Request Forgery attacks. Blocks private IPs, local
hostnames, and non-HTTP schemes.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from server.config.settings import URLPolicyConfig

PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


@dataclass(frozen=True)
class URLValidationResult:
    allowed: bool
    reason: str


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return the matching private network string if addr is private, else None."""
    for network in PRIVATE_NETWORKS:
        if addr in network:
            return str(network)
    return None


def validate_target_url(url: str, policy: URLPolicyConfig) -> URLValidationResult:
    """Validate a URL against the SSRF prevention policy.

    Checks:
    1. Scheme must be in allowed_schemes (default: http, https)
    2. Hostname must not be localhost or .local
    3. Resolved IP must not be in private/reserved ranges
    """
    parsed = urlparse(url)

    # Check scheme
    if parsed.scheme not in policy.allowed_schemes:
        return URLValidationResult(
            allowed=False,
            reason=f"Scheme '{parsed.scheme}' not allowed",
        )

    # Check hostname presence
    hostname = parsed.hostname or ""
    if not hostname:
        return URLValidationResult(allowed=False, reason="No hostname in URL")

    # Check blocked hostnames
    if policy.block_local_hostnames:
        if hostname == "localhost" or hostname.endswith(".local"):
            return URLValidationResult(
                allowed=False,
                reason=f"Hostname '{hostname}' is blocked",
            )

    # Check IP addresses
    if policy.block_private_ips:
        # Try parsing hostname as an IP directly (avoids DNS for literal IPs)
        try:
            addr = ipaddress.ip_address(hostname)
            match = _is_private_ip(addr)
            if match:
                return URLValidationResult(
                    allowed=False,
                    reason=f"IP {addr} is in private range {match}",
                )
            # Valid public IP literal — skip DNS resolution
            return URLValidationResult(allowed=True, reason="OK")
        except ValueError:
            pass  # Not an IP literal, resolve via DNS

        # Resolve hostname and check all resulting IPs
        try:
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                addr = ipaddress.ip_address(info[4][0])
                match = _is_private_ip(addr)
                if match:
                    return URLValidationResult(
                        allowed=False,
                        reason=f"IP {addr} is in private range {match}",
                    )
        except socket.gaierror:
            return URLValidationResult(
                allowed=False,
                reason=f"Cannot resolve hostname '{hostname}'",
            )

    return URLValidationResult(allowed=True, reason="OK")
