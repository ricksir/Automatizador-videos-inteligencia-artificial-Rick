"""Safe default binding for a locally operated, optionally authenticated API.

This applies to the shipped main.py launcher. Firewall, TLS, API-key
management and direct uvicorn launch configurations remain independent duties.
"""
from __future__ import annotations

import ipaddress


def is_loopback_binding(host: object) -> bool:
    if not isinstance(host, str):
        return False
    candidate = host.strip()
    if candidate.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate.removeprefix("[").removesuffix("]")).is_loopback
    except ValueError:
        return False


def safe_api_bind_host(host: object, api_key: object) -> str:
    """Never bind an unauthenticated API to a non-loopback interface."""
    if not isinstance(api_key, str):
        raise ValueError("API authentication configuration must be a string")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("Invalid API listen host")
    if not api_key and not is_loopback_binding(host):
        return "127.0.0.1"
    return host
