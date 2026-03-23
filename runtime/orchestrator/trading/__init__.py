#!/usr/bin/env python3
"""
trading/__init__.py — Paper Trading Module

Paper trading 最小业务闭环模块。
"""

from .schemas import (
    ExecutionMode,
    OrderStatus,
    Side,
    Proposal,
    Confirmation,
    Execution,
    Position,
    JournalEntry,
    generate_id,
    iso_now,
    validate_execution_mode_isolation,
    PAPER_TRADING_SCHEMA_VERSION,
)
from .simulation_adapter import PaperSimulationAdapter

__all__ = [
    "ExecutionMode",
    "OrderStatus",
    "Side",
    "Proposal",
    "Confirmation",
    "Execution",
    "Position",
    "JournalEntry",
    "generate_id",
    "iso_now",
    "validate_execution_mode_isolation",
    "PAPER_TRADING_SCHEMA_VERSION",
    "PaperSimulationAdapter",
]
