"""Lightweight schema validation for orchestrator dataclasses.

Uses Python stdlib only. Provides helpers for from_dict() and __post_init__
validation without adding pydantic or marshmallow dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Collection, Dict, List, Optional, Type, Union

logger = logging.getLogger(__name__)

__all__ = [
    "ValidationError",
    "validate_required",
    "validate_types",
    "validate_iso_datetime",
    "validate_enum_value",
]


class ValidationError(ValueError):
    """Raised when schema validation fails. Carries structured error details."""

    def __init__(self, errors: List[str], source: str = ""):
        self.errors = errors
        self.source = source
        super().__init__(f"Validation failed in {source}: {'; '.join(errors)}")


def validate_required(data: dict, fields: List[str]) -> List[str]:
    """Return list of missing required fields."""
    missing: List[str] = []
    for f in fields:
        if f not in data:
            missing.append(f)
        elif data[f] is None:
            missing.append(f)
    return missing


def validate_types(data: dict, type_map: Dict[str, Union[type, tuple]]) -> List[str]:
    """Return list of type mismatch descriptions.

    ``type_map`` maps field names to expected types (single type or tuple).
    Fields absent from *data* are silently skipped (use ``validate_required``
    for presence checks).
    """
    errors: List[str] = []
    for field_name, expected in type_map.items():
        if field_name not in data or data[field_name] is None:
            continue
        value = data[field_name]
        if not isinstance(value, expected):  # type: ignore[arg-type]
            errors.append(
                f"field '{field_name}' expected {_type_label(expected)}, "
                f"got {type(value).__name__}"
            )
    return errors


def validate_iso_datetime(value: str) -> bool:
    """Check if a string is a valid ISO-8601 datetime."""
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def validate_enum_value(
    value: str, allowed: Collection[str], field_name: str
) -> Optional[str]:
    """Return error string if value not in allowed set, else None."""
    if value not in allowed:
        return (
            f"field '{field_name}' value '{value}' not in allowed set "
            f"{sorted(allowed)}"
        )
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _type_label(t: Union[type, tuple]) -> str:
    if isinstance(t, tuple):
        return " | ".join(cls.__name__ for cls in t)
    return t.__name__
