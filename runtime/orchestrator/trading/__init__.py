"""
trading — Trading Roundtable Adapter and Validators

提供 trading roundtable 的 adapter、schema 和 validator。
"""

from .callback_validator import validate_trading_callback, validate_callback_file, ValidationResult

__all__ = [
    "validate_trading_callback",
    "validate_callback_file",
    "ValidationResult",
]
