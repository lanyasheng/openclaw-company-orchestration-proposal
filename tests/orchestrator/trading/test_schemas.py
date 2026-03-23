#!/usr/bin/env python3
"""
tests/orchestrator/trading/test_schemas.py

测试 Paper Trading Schema。

覆盖：
- 基本数据结构创建
- 序列化/反序列化
- execution_mode 隔离验证
"""

import pytest
from datetime import datetime
from pathlib import Path
import sys

# 添加运行时路径（使用绝对路径）
# tests/orchestrator/trading/test_schemas.py -> runtime/orchestrator
RUNTIME_PATH = Path(__file__).resolve().parent.parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(RUNTIME_PATH))

# 验证路径
assert RUNTIME_PATH.exists(), f"Runtime path does not exist: {RUNTIME_PATH}"
assert (RUNTIME_PATH / "trading").exists(), f"Trading module not found: {RUNTIME_PATH / 'trading'}"

from trading.schemas import (
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


class TestExecutionMode:
    """测试执行模式枚举"""
    
    def test_execution_mode_values(self):
        """测试 execution_mode 枚举值"""
        assert ExecutionMode.PAPER.value == "paper"
        assert ExecutionMode.LIVE.value == "live"
    
    def test_execution_mode_from_string(self):
        """测试从字符串创建 execution_mode"""
        assert ExecutionMode("paper") == ExecutionMode.PAPER
        assert ExecutionMode("live") == ExecutionMode.LIVE


class TestSide:
    """测试买卖方向枚举"""
    
    def test_side_values(self):
        """测试 side 枚举值"""
        assert Side.BUY.value == "buy"
        assert Side.SELL.value == "sell"


class TestProposal:
    """测试交易建议单"""
    
    def test_create_proposal(self):
        """测试创建建议单"""
        proposal = Proposal(
            proposal_id="prop_001",
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Technical breakout",
            execution_mode=ExecutionMode.PAPER,
        )
        
        assert proposal.proposal_id == "prop_001"
        assert proposal.symbol == "AAPL"
        assert proposal.side == Side.BUY
        assert proposal.quantity == 100
        assert proposal.suggested_price == 150.0
        assert proposal.execution_mode == ExecutionMode.PAPER
    
    def test_proposal_to_dict(self):
        """测试建议单序列化"""
        proposal = Proposal(
            proposal_id="prop_002",
            symbol="GOOGL",
            side=Side.SELL,
            quantity=50,
            suggested_price=2800.0,
            rationale="Overvalued",
            strategy_id="strategy_001",
            execution_mode=ExecutionMode.PAPER,
        )
        
        data = proposal.to_dict()
        
        assert data["proposal_id"] == "prop_002"
        assert data["symbol"] == "GOOGL"
        assert data["side"] == "sell"
        assert data["quantity"] == 50
        assert data["execution_mode"] == "paper"
        assert data["strategy_id"] == "strategy_001"
    
    def test_proposal_from_dict(self):
        """测试建议单反序列化"""
        data = {
            "proposal_id": "prop_003",
            "symbol": "MSFT",
            "side": "buy",
            "quantity": 200,
            "suggested_price": 300.0,
            "rationale": "Earnings beat",
            "execution_mode": "paper",
        }
        
        proposal = Proposal.from_dict(data)
        
        assert proposal.proposal_id == "prop_003"
        assert proposal.symbol == "MSFT"
        assert proposal.side == Side.BUY
        assert proposal.execution_mode == ExecutionMode.PAPER
    
    def test_proposal_default_execution_mode(self):
        """测试建议单默认 execution_mode 为 paper"""
        proposal = Proposal(
            proposal_id="prop_004",
            symbol="TSLA",
            side=Side.BUY,
            quantity=10,
            suggested_price=200.0,
            rationale="EV growth",
        )
        
        assert proposal.execution_mode == ExecutionMode.PAPER


class TestConfirmation:
    """测试交易确认单"""
    
    def test_create_confirmation(self):
        """测试创建确认单"""
        confirmation = Confirmation(
            confirmation_id="conf_001",
            proposal_id="prop_001",
            confirmed_by="trader_001",
            confirmed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
        )
        
        assert confirmation.confirmation_id == "conf_001"
        assert confirmation.proposal_id == "prop_001"
        assert confirmation.confirmed_by == "trader_001"
        assert confirmation.execution_mode == ExecutionMode.PAPER
    
    def test_confirmation_with_modifications(self):
        """测试带修改的确认单"""
        confirmation = Confirmation(
            confirmation_id="conf_002",
            proposal_id="prop_002",
            confirmed_by="trader_002",
            confirmed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
            modified_quantity=80,
            modified_price=148.0,
            notes="Reduced quantity due to risk limit",
        )
        
        assert confirmation.modified_quantity == 80
        assert confirmation.modified_price == 148.0
        assert confirmation.notes == "Reduced quantity due to risk limit"


class TestExecution:
    """测试交易执行记录"""
    
    def test_create_execution(self):
        """测试创建执行记录"""
        execution = Execution(
            execution_id="exec_001",
            proposal_id="prop_001",
            confirmation_id="conf_001",
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            executed_price=150.5,
            executed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
        )
        
        assert execution.execution_id == "exec_001"
        assert execution.symbol == "AAPL"
        assert execution.executed_price == 150.5
        assert execution.execution_mode == ExecutionMode.PAPER
    
    def test_execution_total_value(self):
        """测试成交总金额计算"""
        execution = Execution(
            execution_id="exec_002",
            proposal_id="prop_002",
            confirmation_id="conf_002",
            symbol="GOOGL",
            side=Side.BUY,
            quantity=50,
            executed_price=2800.0,
            executed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
        )
        
        assert execution.total_value == 50 * 2800.0
    
    def test_execution_total_cost(self):
        """测试总成本计算（含手续费）"""
        execution = Execution(
            execution_id="exec_003",
            proposal_id="prop_003",
            confirmation_id="conf_003",
            symbol="MSFT",
            side=Side.BUY,
            quantity=100,
            executed_price=300.0,
            executed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
            commission=30.0,
        )
        
        assert execution.total_value == 30000.0
        assert execution.total_cost == 30000.0 + 30.0


class TestPosition:
    """测试持仓记录"""
    
    def test_create_position(self):
        """测试创建持仓"""
        position = Position(
            position_id="pos_001",
            symbol="AAPL",
            quantity=100,
            average_cost=150.0,
            current_price=155.0,
            execution_mode=ExecutionMode.PAPER,
            opened_at=iso_now(),
            updated_at=iso_now(),
        )
        
        assert position.symbol == "AAPL"
        assert position.quantity == 100
        assert position.average_cost == 150.0
    
    def test_position_market_value(self):
        """测试市值计算"""
        position = Position(
            position_id="pos_002",
            symbol="GOOGL",
            quantity=50,
            average_cost=2800.0,
            current_price=2850.0,
            execution_mode=ExecutionMode.PAPER,
            opened_at=iso_now(),
            updated_at=iso_now(),
        )
        
        assert position.market_value == 50 * 2850.0
    
    def test_position_unrealized_pnl_long(self):
        """测试多头未实现盈亏计算"""
        position = Position(
            position_id="pos_003",
            symbol="MSFT",
            quantity=100,
            average_cost=300.0,
            current_price=310.0,
            execution_mode=ExecutionMode.PAPER,
            opened_at=iso_now(),
            updated_at=iso_now(),
        )
        
        # 需要调用 update_price 来计算未实现盈亏
        position.update_price(310.0)
        
        # 多头盈亏 = (现价 - 成本) * 数量
        assert position.unrealized_pnl == (310.0 - 300.0) * 100
    
    def test_position_update_price(self):
        """测试更新价格"""
        position = Position(
            position_id="pos_004",
            symbol="TSLA",
            quantity=50,
            average_cost=200.0,
            current_price=200.0,
            execution_mode=ExecutionMode.PAPER,
            opened_at=iso_now(),
            updated_at=iso_now(),
        )
        
        position.update_price(220.0)
        
        assert position.current_price == 220.0
        assert position.unrealized_pnl == (220.0 - 200.0) * 50


class TestJournalEntry:
    """测试交易日志"""
    
    def test_create_journal_entry(self):
        """测试创建交易日志"""
        proposal = Proposal(
            proposal_id="prop_001",
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Technical breakout",
        )
        
        journal = JournalEntry(
            journal_id="journal_001",
            proposal=proposal,
            confirmation=None,
            execution=None,
            position_snapshot=None,
            rationale=proposal.rationale,
            execution_mode=ExecutionMode.PAPER,
            created_at=iso_now(),
            updated_at=iso_now(),
        )
        
        assert journal.journal_id == "journal_001"
        assert journal.proposal.proposal_id == "prop_001"
        assert journal.execution_mode == ExecutionMode.PAPER
    
    def test_journal_to_dict(self):
        """测试交易日志序列化"""
        proposal = Proposal(
            proposal_id="prop_002",
            symbol="GOOGL",
            side=Side.SELL,
            quantity=50,
            suggested_price=2800.0,
            rationale="Overvalued",
        )
        
        journal = JournalEntry(
            journal_id="journal_002",
            proposal=proposal,
            confirmation=None,
            execution=None,
            position_snapshot=None,
            rationale=proposal.rationale,
            execution_mode=ExecutionMode.PAPER,
            created_at=iso_now(),
            updated_at=iso_now(),
            tags=["test", "paper"],
        )
        
        data = journal.to_dict()
        
        assert data["journal_id"] == "journal_002"
        assert data["execution_mode"] == "paper"
        assert "test" in data["tags"]


class TestExecutionModeIsolation:
    """测试 execution_mode 隔离"""
    
    def test_isolated_paper_records(self):
        """测试纯 paper 记录通过隔离检查"""
        paper_proposals = [
            Proposal(
                proposal_id=f"prop_{i}",
                symbol="AAPL",
                side=Side.BUY,
                quantity=100,
                suggested_price=150.0,
                rationale="Test",
                execution_mode=ExecutionMode.PAPER,
            )
            for i in range(3)
        ]
        
        result = validate_execution_mode_isolation(paper_proposals, [])
        
        assert result["isolated"] is True
        assert len(result["issues"]) == 0
        assert result["paper_count"] == 3
    
    def test_isolated_live_records(self):
        """测试纯 live 记录通过隔离检查"""
        live_proposals = [
            Proposal(
                proposal_id=f"prop_{i}",
                symbol="AAPL",
                side=Side.BUY,
                quantity=100,
                suggested_price=150.0,
                rationale="Test",
                execution_mode=ExecutionMode.LIVE,
            )
            for i in range(2)
        ]
        
        result = validate_execution_mode_isolation([], live_proposals)
        
        assert result["isolated"] is True
        assert len(result["issues"]) == 0
    
    def test_mixed_records_fail_isolation(self):
        """测试混合记录未通过隔离检查"""
        paper_proposals = [
            Proposal(
                proposal_id="prop_paper",
                symbol="AAPL",
                side=Side.BUY,
                quantity=100,
                suggested_price=150.0,
                rationale="Test",
                execution_mode=ExecutionMode.PAPER,
            )
        ]
        
        live_proposals = [
            Proposal(
                proposal_id="prop_live",
                symbol="GOOGL",
                side=Side.BUY,
                quantity=50,
                suggested_price=2800.0,
                rationale="Test",
                execution_mode=ExecutionMode.LIVE,
            )
        ]
        
        # Paper 记录中混入 live
        mixed_paper = paper_proposals + live_proposals
        result = validate_execution_mode_isolation(mixed_paper, [])
        
        assert result["isolated"] is False
        assert len(result["issues"]) == 1
        assert "LIVE mode" in result["issues"][0]


class TestUtilityFunctions:
    """测试辅助函数"""
    
    def test_generate_id(self):
        """测试 ID 生成"""
        id1 = generate_id("test")
        id2 = generate_id("test")
        
        assert id1.startswith("test_")
        assert id2.startswith("test_")
        assert id1 != id2  # 唯一性
    
    def test_iso_now(self):
        """测试时间戳生成"""
        timestamp = iso_now()
        
        # 应该是 ISO 格式字符串
        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO 格式包含 T


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
