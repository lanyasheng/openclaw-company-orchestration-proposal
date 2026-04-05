#!/usr/bin/env python3
"""
trading/schemas.py — Paper Trading Journal Schema

定义 paper trading 的核心数据结构，用于记录交易建议、确认、执行、持仓等。

核心设计原则：
1. execution_mode 明确区分 'paper' 与 'live'，默认 'paper'
2. 所有记录包含完整的时间戳链，支持回放
3. 与 live 路径严格隔离，避免混淆
"""

from __future__ import annotations

import logging as _logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import json

from core.validation import validate_required, validate_enum_value, ValidationError

_log = _logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """执行模式：严格区分 paper 与 live"""
    PAPER = "paper"
    LIVE = "live"


class OrderStatus(str, Enum):
    """订单状态"""
    PROPOSED = "proposed"       # 建议单已生成
    CONFIRMED = "confirmed"     # 人工确认
    EXECUTED = "executed"       # 模拟/实际成交
    CANCELLED = "cancelled"     # 已取消
    REJECTED = "rejected"       # 已拒绝


class Side(str, Enum):
    """买卖方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class Proposal:
    """
    交易建议单
    
    由策略/信号生成，尚未经过人工确认。
    """
    proposal_id: str
    symbol: str
    side: Side
    quantity: float
    suggested_price: float
    rationale: str                          # 交易理由
    strategy_id: Optional[str] = None       # 策略 ID
    signal_id: Optional[str] = None         # 信号 ID
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        errors: List[str] = []
        for f in ("proposal_id", "symbol", "rationale"):
            val = getattr(self, f, None)
            if not val or (isinstance(val, str) and not val.strip()):
                errors.append(f"{f} is required")
        err = validate_enum_value(
            self.execution_mode.value if isinstance(self.execution_mode, ExecutionMode) else str(self.execution_mode),
            [m.value for m in ExecutionMode],
            "execution_mode",
        )
        if err:
            errors.append(err)
        if errors:
            _log.warning("Proposal validation warnings: %s", errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "suggested_price": self.suggested_price,
            "rationale": self.rationale,
            "strategy_id": self.strategy_id,
            "signal_id": self.signal_id,
            "execution_mode": self.execution_mode.value,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Proposal:
        missing = validate_required(
            data, ["proposal_id", "symbol", "side", "quantity", "suggested_price", "rationale"]
        )
        if missing:
            raise ValidationError(
                [f"missing required field: {f}" for f in missing],
                source="Proposal.from_dict",
            )
        return cls(
            proposal_id=data["proposal_id"],
            symbol=data["symbol"],
            side=Side(data["side"]),
            quantity=data["quantity"],
            suggested_price=data["suggested_price"],
            rationale=data["rationale"],
            strategy_id=data.get("strategy_id"),
            signal_id=data.get("signal_id"),
            execution_mode=ExecutionMode(data.get("execution_mode", "paper")),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Confirmation:
    """
    交易确认
    
    人工确认交易建议，记录确认时间和确认人。
    """
    confirmation_id: str
    proposal_id: str
    confirmed_by: str                       # 确认人
    confirmed_at: str
    execution_mode: ExecutionMode
    notes: Optional[str] = None             # 确认备注
    modified_quantity: Optional[float] = None  # 可调整数量
    modified_price: Optional[float] = None     # 可调整价格
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "proposal_id": self.proposal_id,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
            "execution_mode": self.execution_mode.value,
            "notes": self.notes,
            "modified_quantity": self.modified_quantity,
            "modified_price": self.modified_price,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Confirmation:
        return cls(
            confirmation_id=data["confirmation_id"],
            proposal_id=data["proposal_id"],
            confirmed_by=data["confirmed_by"],
            confirmed_at=data["confirmed_at"],
            execution_mode=ExecutionMode(data.get("execution_mode", "paper")),
            notes=data.get("notes"),
            modified_quantity=data.get("modified_quantity"),
            modified_price=data.get("modified_price"),
        )


@dataclass
class Execution:
    """
    交易执行记录
    
    记录模拟或实际成交情况。
    """
    execution_id: str
    proposal_id: str
    confirmation_id: str
    symbol: str
    side: Side
    quantity: float
    executed_price: float
    executed_at: str
    execution_mode: ExecutionMode
    status: OrderStatus = OrderStatus.EXECUTED
    commission: float = 0.0                 # 手续费
    slippage: float = 0.0                   # 滑点
    venue: Optional[str] = None             # 交易场所（模拟/实际）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        errors: List[str] = []
        for f in ("execution_id", "proposal_id", "confirmation_id", "symbol"):
            val = getattr(self, f, None)
            if not val or (isinstance(val, str) and not val.strip()):
                errors.append(f"{f} is required")
        err = validate_enum_value(
            self.execution_mode.value if isinstance(self.execution_mode, ExecutionMode) else str(self.execution_mode),
            [m.value for m in ExecutionMode],
            "execution_mode",
        )
        if err:
            errors.append(err)
        if errors:
            _log.warning("Execution validation warnings: %s", errors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "proposal_id": self.proposal_id,
            "confirmation_id": self.confirmation_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "executed_price": self.executed_price,
            "executed_at": self.executed_at,
            "execution_mode": self.execution_mode.value,
            "status": self.status.value,
            "commission": self.commission,
            "slippage": self.slippage,
            "venue": self.venue,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Execution:
        return cls(
            execution_id=data["execution_id"],
            proposal_id=data["proposal_id"],
            confirmation_id=data["confirmation_id"],
            symbol=data["symbol"],
            side=Side(data["side"]),
            quantity=data["quantity"],
            executed_price=data["executed_price"],
            executed_at=data["executed_at"],
            execution_mode=ExecutionMode(data.get("execution_mode", "paper")),
            status=OrderStatus(data.get("status", "executed")),
            commission=data.get("commission", 0.0),
            slippage=data.get("slippage", 0.0),
            venue=data.get("venue"),
            metadata=data.get("metadata", {}),
        )
    
    @property
    def total_value(self) -> float:
        """成交总金额"""
        return self.quantity * self.executed_price
    
    @property
    def total_cost(self) -> float:
        """总成本（含手续费）"""
        return self.total_value + self.commission


@dataclass
class Position:
    """
    持仓记录
    
    记录某个标的的当前持仓情况。
    """
    position_id: str
    symbol: str
    quantity: float                         # 当前数量（正数=多头，负数=空头）
    average_cost: float                     # 平均成本
    current_price: float                    # 当前价格
    execution_mode: ExecutionMode
    opened_at: str
    updated_at: str
    realized_pnl: float = 0.0               # 已实现盈亏
    unrealized_pnl: float = 0.0             # 未实现盈亏
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "average_cost": self.average_cost,
            "current_price": self.current_price,
            "execution_mode": self.execution_mode.value,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Position:
        return cls(
            position_id=data["position_id"],
            symbol=data["symbol"],
            quantity=data["quantity"],
            average_cost=data["average_cost"],
            current_price=data["current_price"],
            execution_mode=ExecutionMode(data.get("execution_mode", "paper")),
            opened_at=data["opened_at"],
            updated_at=data["updated_at"],
            realized_pnl=data.get("realized_pnl", 0.0),
            unrealized_pnl=data.get("unrealized_pnl", 0.0),
            metadata=data.get("metadata", {}),
        )
    
    @property
    def market_value(self) -> float:
        """市值"""
        return abs(self.quantity) * self.current_price
    
    @property
    def total_pnl(self) -> float:
        """总盈亏"""
        return self.realized_pnl + self.unrealized_pnl
    
    def update_price(self, price: float) -> None:
        """更新当前价格并重新计算未实现盈亏"""
        self.current_price = price
        self.updated_at = datetime.now(timezone.utc).isoformat()
        if self.quantity != 0:
            if self.quantity > 0:  # 多头
                self.unrealized_pnl = (price - self.average_cost) * self.quantity
            else:  # 空头
                self.unrealized_pnl = (self.average_cost - price) * abs(self.quantity)


@dataclass
class JournalEntry:
    """
    交易日志条目
    
    完整的交易记录，包含从建议到执行的全链路。
    """
    journal_id: str
    proposal: Proposal
    confirmation: Optional[Confirmation]
    execution: Optional[Execution]
    position_snapshot: Optional[Position]
    rationale: str
    execution_mode: ExecutionMode
    created_at: str
    updated_at: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "journal_id": self.journal_id,
            "proposal": self.proposal.to_dict(),
            "confirmation": self.confirmation.to_dict() if self.confirmation else None,
            "execution": self.execution.to_dict() if self.execution else None,
            "position_snapshot": self.position_snapshot.to_dict() if self.position_snapshot else None,
            "rationale": self.rationale,
            "execution_mode": self.execution_mode.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JournalEntry:
        return cls(
            journal_id=data["journal_id"],
            proposal=Proposal.from_dict(data["proposal"]),
            confirmation=Confirmation.from_dict(data["confirmation"]) if data.get("confirmation") else None,
            execution=Execution.from_dict(data["execution"]) if data.get("execution") else None,
            position_snapshot=Position.from_dict(data["position_snapshot"]) if data.get("position_snapshot") else None,
            rationale=data["rationale"],
            execution_mode=ExecutionMode(data.get("execution_mode", "paper")),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


# ============== 辅助函数 ==============

def generate_id(prefix: str) -> str:
    """生成唯一 ID"""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def iso_now() -> str:
    """获取当前 ISO 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def validate_execution_mode_isolation(paper_records: List[Any], live_records: List[Any]) -> Dict[str, Any]:
    """
    验证 paper 与 live 记录严格隔离
    
    返回验证结果，包含任何发现的问题。
    """
    issues = []
    
    # 检查 paper 记录中是否有 live 模式
    for record in paper_records:
        if hasattr(record, 'execution_mode'):
            if record.execution_mode == ExecutionMode.LIVE:
                issues.append(f"Paper record {getattr(record, 'proposal_id', getattr(record, 'journal_id', 'unknown'))} has LIVE mode")
    
    # 检查 live 记录中是否有 paper 模式
    for record in live_records:
        if hasattr(record, 'execution_mode'):
            if record.execution_mode == ExecutionMode.PAPER:
                issues.append(f"Live record {getattr(record, 'proposal_id', getattr(record, 'journal_id', 'unknown'))} has PAPER mode")
    
    return {
        "isolated": len(issues) == 0,
        "issues": issues,
        "paper_count": len(paper_records),
        "live_count": len(live_records),
    }


# Schema 版本
PAPER_TRADING_SCHEMA_VERSION = "paper_trading_v1_0_0"
