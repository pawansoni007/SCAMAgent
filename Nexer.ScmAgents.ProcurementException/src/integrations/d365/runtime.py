"""
Shared runtime helpers for D365-backed services.

Centralises the "is D365 configured?" check, a cached OData client instance,
and small value-coercion helpers so individual services don't duplicate this
plumbing. Services use these to add a live-D365 path with a mock fallback.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """True when D365 connection settings are present in the environment."""
    return bool(os.environ.get("D365_ODATA_BASE_URL"))


@lru_cache(maxsize=1)
def get_client():
    """Return a process-wide cached D365 OData client."""
    from integrations.d365.odata_client import D365ODataClient

    return D365ODataClient()


def reset_client_cache() -> None:
    """Drop the cached client (useful in tests or after config changes)."""
    get_client.cache_clear()


def to_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion (D365 returns decimals as numbers or strings)."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_date(value: Any) -> str | None:
    """Normalise an OData datetime ('2026-06-02T00:00:00Z') to an ISO date."""
    if not value or not isinstance(value, str):
        return None
    return value[:10]
