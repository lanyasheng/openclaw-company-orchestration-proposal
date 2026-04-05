#!/usr/bin/env python3
"""
trading/simulation_adapter.py — Paper Simulation Adapter

Paper Trading 模拟执行适配器。

核心能力：
- validate_proposal: 验证交易建议单
- simulate_execution: 模拟成交（不接真实券商）
- update_position: 更新持仓
- generate_journal: 生成交易日志

执行语义：
建议单 -> 人工确认数据 -> 模拟成交 -> journal 落盘 -> 持仓更新

风险隔离：
- execution_mode 始终为 'paper'
- 与 live 路径严格区分
- 所有操作可回放
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import asdict

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
)


class PaperSimulationAdapter:
    """
    Paper Trading 模拟执行适配器
    
    实现最小业务闭环：
    1. 验证交易建议
    2. 模拟成交（不接真实券商）
    3. 更新持仓
    4. 生成交易日志
    
    所有操作默认 execution_mode='paper'，与 live 严格隔离。
    """
    
    def __init__(self, journal_dir: Optional[Path] = None, state_dir: Optional[Path] = None):
        """
        初始化适配器
        
        Args:
            journal_dir: 交易日志存储目录
            state_dir: 状态文件存储目录（持仓等）
        """
        self.journal_dir = journal_dir or Path("/tmp/paper_trading/journals")
        self.state_dir = state_dir or Path("/tmp/paper_trading/state")
        self.execution_mode = ExecutionMode.PAPER
        
        # 确保目录存在
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存状态（生产环境应持久化）
        self._positions: Dict[str, Position] = {}  # symbol -> Position
        self._journal_entries: Dict[str, JournalEntry] = {}
        
        # 模拟成交配置
        self.default_commission_rate = 0.001  # 0.1% 手续费
        self.default_slippage_rate = 0.0005   # 0.05% 滑点
    
    def validate_proposal(self, proposal: Proposal) -> Dict[str, Any]:
        """
        验证交易建议单
        
        检查：
        - execution_mode 必须为 paper
        - 数量 > 0
        - 价格 > 0
        - 必填字段完整
        
        Returns:
            {"valid": bool, "errors": List[str], "warnings": List[str]}
        """
        errors = []
        warnings = []
        
        # 强制检查 execution_mode
        if proposal.execution_mode != ExecutionMode.PAPER:
            errors.append(f"execution_mode must be 'paper', got '{proposal.execution_mode.value}'")
        
        # 检查必填字段
        if not proposal.proposal_id:
            errors.append("proposal_id is required")
        if not proposal.symbol:
            errors.append("symbol is required")
        if not proposal.side:
            errors.append("side is required")
        if proposal.quantity <= 0:
            errors.append(f"quantity must be > 0, got {proposal.quantity}")
        if proposal.suggested_price <= 0:
            errors.append(f"suggested_price must be > 0, got {proposal.suggested_price}")
        if not proposal.rationale:
            errors.append("rationale is required")
        
        # 警告检查
        if proposal.quantity > 10000:
            warnings.append(f"Large quantity: {proposal.quantity}")
        if not proposal.strategy_id and not proposal.signal_id:
            warnings.append("No strategy_id or signal_id specified")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "proposal_id": proposal.proposal_id,
        }
    
    def simulate_execution(
        self,
        proposal: Proposal,
        confirmation: Optional[Confirmation] = None,
        market_price: Optional[float] = None,
    ) -> Tuple[Execution, Dict[str, Any]]:
        """
        模拟成交
        
        不接真实券商，仅模拟成交逻辑：
        - 使用市场价或建议价
        - 计算手续费和滑点
        - 生成执行记录
        
        Args:
            proposal: 交易建议单
            confirmation: 确认单（可选）
            market_price: 市场价（可选，默认使用建议价）
        
        Returns:
            (Execution, metadata)
        """
        # 验证 proposal
        validation = self.validate_proposal(proposal)
        if not validation["valid"]:
            raise ValueError(f"Invalid proposal: {validation['errors']}")
        
        # 确定执行价格
        if confirmation and confirmation.modified_price:
            base_price = confirmation.modified_price
        elif market_price:
            base_price = market_price
        else:
            base_price = proposal.suggested_price
        
        # 确定执行数量
        if confirmation and confirmation.modified_quantity:
            quantity = confirmation.modified_quantity
        else:
            quantity = proposal.quantity
        
        # 模拟滑点（对买方加价，对卖方减价）
        slippage = base_price * self.default_slippage_rate
        if proposal.side == Side.BUY:
            executed_price = base_price + slippage
        else:
            executed_price = base_price - slippage
        
        # 计算手续费
        commission = quantity * executed_price * self.default_commission_rate
        
        # 生成执行记录
        execution = Execution(
            execution_id=generate_id("exec"),
            proposal_id=proposal.proposal_id,
            confirmation_id=confirmation.confirmation_id if confirmation else None,
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=quantity,
            executed_price=executed_price,
            executed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
            status=OrderStatus.EXECUTED,
            commission=commission,
            slippage=slippage,
            venue="paper_simulation",
            metadata={
                "suggested_price": proposal.suggested_price,
                "base_price": base_price,
                "commission_rate": self.default_commission_rate,
                "slippage_rate": self.default_slippage_rate,
            },
        )
        
        metadata = {
            "simulation": True,
            "venue": "paper",
            "price_impact": slippage / base_price if base_price > 0 else 0,
            "total_cost": execution.total_cost,
        }
        
        return execution, metadata
    
    def update_position(
        self,
        execution: Execution,
        current_price: Optional[float] = None,
    ) -> Position:
        """
        更新持仓
        
        根据执行记录更新持仓：
        - 买入：增加持仓，重新计算平均成本
        - 卖出：减少持仓，计算已实现盈亏
        
        Args:
            execution: 执行记录
            current_price: 当前价格（用于计算未实现盈亏）
        
        Returns:
            更新后的持仓
        """
        symbol = execution.symbol
        now = iso_now()
        
        # 获取或创建持仓
        if symbol not in self._positions:
            # 新建持仓
            position = Position(
                position_id=generate_id("pos"),
                symbol=symbol,
                quantity=0,
                average_cost=0,
                current_price=current_price or execution.executed_price,
                execution_mode=ExecutionMode.PAPER,
                opened_at=now,
                updated_at=now,
            )
        else:
            position = self._positions[symbol]
        
        # 更新持仓
        old_quantity = position.quantity
        old_avg_cost = position.average_cost
        
        if execution.side == Side.BUY:
            # 买入：增加持仓
            new_quantity = old_quantity + execution.quantity
            if new_quantity > 0:
                # 重新计算平均成本
                total_cost = (old_quantity * old_avg_cost) + execution.total_cost
                position.average_cost = total_cost / new_quantity if new_quantity > 0 else 0
            position.quantity = new_quantity
        else:
            # 卖出：减少持仓
            new_quantity = old_quantity - execution.quantity
            # 计算已实现盈亏
            if old_quantity > 0:
                realized_pnl = (execution.executed_price - old_avg_cost) * min(execution.quantity, old_quantity)
                position.realized_pnl += realized_pnl
            position.quantity = new_quantity
        
        # 更新当前价格
        if current_price:
            position.current_price = current_price
        else:
            position.current_price = execution.executed_price
        
        # 重新计算未实现盈亏
        position.update_price(position.current_price)
        position.updated_at = now
        
        # 保存持仓
        self._positions[symbol] = position
        
        return position
    
    def generate_journal(
        self,
        proposal: Proposal,
        confirmation: Optional[Confirmation],
        execution: Execution,
        position: Position,
        tags: Optional[List[str]] = None,
    ) -> JournalEntry:
        """
        生成交易日志
        
        完整的交易记录，包含从建议到执行的全链路。
        
        Args:
            proposal: 交易建议单
            confirmation: 确认单
            execution: 执行记录
            position: 持仓快照
            tags: 标签
        
        Returns:
            JournalEntry
        """
        journal = JournalEntry(
            journal_id=generate_id("journal"),
            proposal=proposal,
            confirmation=confirmation,
            execution=execution,
            position_snapshot=position,
            rationale=proposal.rationale,
            execution_mode=ExecutionMode.PAPER,
            created_at=iso_now(),
            updated_at=iso_now(),
            tags=tags or [],
            metadata={
                "adapter": "PaperSimulationAdapter",
                "version": "1.0.0",
                "simulation": True,
            },
        )
        
        # 保存日志
        self._journal_entries[journal.journal_id] = journal
        self._persist_journal(journal)
        
        return journal
    
    def _persist_journal(self, journal: JournalEntry) -> Path:
        """持久化交易日志到文件"""
        from utils.io import atomic_write_json
        file_path = self.journal_dir / f"{journal.journal_id}.json"
        atomic_write_json(file_path, journal.to_dict())
        return file_path

    def persist_position(self, position: Position) -> Path:
        """持久化持仓到文件"""
        from utils.io import atomic_write_json
        file_path = self.state_dir / f"position_{position.symbol}.json"
        atomic_write_json(file_path, position.to_dict())
        return file_path
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取某个标的的持仓"""
        return self._positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        return self._positions.copy()
    
    def get_journal(self, journal_id: str) -> Optional[JournalEntry]:
        """获取交易日志"""
        return self._journal_entries.get(journal_id)
    
    def get_journals(self, limit: int = 100) -> List[JournalEntry]:
        """获取最近的交易日志"""
        return list(self._journal_entries.values())[-limit:]
    
    def execute_full_workflow(
        self,
        proposal: Proposal,
        confirmed_by: str,
        market_price: Optional[float] = None,
        current_price: Optional[float] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的工作流
        
        最小 smoke path：
        proposal -> confirmation -> execution -> position -> journal
        
        Args:
            proposal: 交易建议单
            confirmed_by: 确认人
            market_price: 市场价
            current_price: 当前价格（用于持仓估值）
            tags: 标签
        
        Returns:
            完整的工作流结果
        """
        # 1. 验证建议单
        validation = self.validate_proposal(proposal)
        if not validation["valid"]:
            return {
                "success": False,
                "stage": "validation",
                "errors": validation["errors"],
            }
        
        # 2. 生成确认单
        confirmation = Confirmation(
            confirmation_id=generate_id("conf"),
            proposal_id=proposal.proposal_id,
            confirmed_by=confirmed_by,
            confirmed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
        )
        
        # 3. 模拟成交
        execution, exec_metadata = self.simulate_execution(
            proposal=proposal,
            confirmation=confirmation,
            market_price=market_price,
        )
        
        # 4. 更新持仓
        position = self.update_position(
            execution=execution,
            current_price=current_price or execution.executed_price,
        )
        self.persist_position(position)
        
        # 5. 生成交易日志
        journal = self.generate_journal(
            proposal=proposal,
            confirmation=confirmation,
            execution=execution,
            position=position,
            tags=tags,
        )
        
        return {
            "success": True,
            "stage": "completed",
            "proposal_id": proposal.proposal_id,
            "confirmation_id": confirmation.confirmation_id,
            "execution_id": execution.execution_id,
            "journal_id": journal.journal_id,
            "position": {
                "symbol": position.symbol,
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "current_price": position.current_price,
                "unrealized_pnl": position.unrealized_pnl,
            },
            "execution_metadata": exec_metadata,
            "journal_path": str(self.journal_dir / f"{journal.journal_id}.json"),
        }
    
    def clear_state(self) -> None:
        """清除所有状态（用于测试）"""
        self._positions.clear()
        self._journal_entries.clear()


# 便捷函数

def create_paper_proposal(
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    rationale: str,
    strategy_id: Optional[str] = None,
) -> Proposal:
    """
    创建 paper trading 建议单
    
    便捷函数，确保 execution_mode='paper'
    """
    return Proposal(
        proposal_id=generate_id("prop"),
        symbol=symbol,
        side=Side(side.lower()),
        quantity=quantity,
        suggested_price=price,
        rationale=rationale,
        strategy_id=strategy_id,
        execution_mode=ExecutionMode.PAPER,
    )
