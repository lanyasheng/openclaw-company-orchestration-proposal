"""Shared types for the orchestrator core modules.

Canonical definitions of types used across phase_engine, quality_gate,
and fanout_controller. Import from here to avoid duplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class FanOutMode(str, Enum):
    """Fan-out 执行模式"""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    BATCHED = "batched"


class FanInMode(str, Enum):
    """Fan-in 聚合模式"""
    ALL_SUCCESS = "all_success"
    ANY_SUCCESS = "any_success"
    MAJORITY = "majority"
    CUSTOM = "custom"


@dataclass
class GateResult:
    """Quality Gate 检查结果"""
    passed: bool
    gate_name: str
    checks: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "gate_name": self.gate_name,
            "checks": self.checks,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }
