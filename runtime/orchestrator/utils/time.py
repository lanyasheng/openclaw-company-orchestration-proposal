"""Unified timestamp utilities.

All modules should use iso_now() instead of datetime.now().isoformat()
to ensure consistent UTC timestamps across the codebase.
"""

from __future__ import annotations

from datetime import datetime, timezone


def iso_now() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
