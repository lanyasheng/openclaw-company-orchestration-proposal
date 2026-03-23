#!/usr/bin/env python3
"""
tests/orchestrator/trading/test_simulation_adapter.py

测试 Paper Simulation Adapter。

覆盖：
- validate_proposal
- simulate_execution
- update_position
- generate_journal
- 完整工作流 (smoke path)
- paper/live 隔离
"""

import pytest
import tempfile
import shutil
from pathlib import Path
import sys
import json

# 添加运行时路径（使用绝对路径）
# tests/orchestrator/trading/test_simulation_adapter.py -> runtime/orchestrator
RUNTIME_PATH = Path(__file__).resolve().parent.parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(RUNTIME_PATH))

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
)
from trading.simulation_adapter import (
    PaperSimulationAdapter,
    create_paper_proposal,
)


@pytest.fixture
def adapter():
    """创建测试用 adapter"""
    temp_dir = tempfile.mkdtemp()
    journal_dir = Path(temp_dir) / "journals"
    state_dir = Path(temp_dir) / "state"
    
    adapter = PaperSimulationAdapter(journal_dir=journal_dir, state_dir=state_dir)
    
    yield adapter
    
    # 清理临时目录
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_proposal():
    """创建示例建议单"""
    return Proposal(
        proposal_id="prop_test_001",
        symbol="AAPL",
        side=Side.BUY,
        quantity=100,
        suggested_price=150.0,
        rationale="Technical breakout above resistance",
        strategy_id="strategy_momentum_001",
        execution_mode=ExecutionMode.PAPER,
    )


class TestValidateProposal:
    """测试提案验证"""
    
    def test_valid_proposal(self, adapter, sample_proposal):
        """测试有效提案"""
        result = adapter.validate_proposal(sample_proposal)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["proposal_id"] == "prop_test_001"
    
    def test_invalid_execution_mode(self, adapter):
        """测试无效 execution_mode"""
        proposal = Proposal(
            proposal_id="prop_test_002",
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Test",
            execution_mode=ExecutionMode.LIVE,  # 应该是 PAPER
        )
        
        result = adapter.validate_proposal(proposal)
        
        assert result["valid"] is False
        assert any("execution_mode" in err for err in result["errors"])
    
    def test_invalid_quantity(self, adapter, sample_proposal):
        """测试无效数量"""
        sample_proposal.quantity = 0
        
        result = adapter.validate_proposal(sample_proposal)
        
        assert result["valid"] is False
        assert any("quantity" in err for err in result["errors"])
    
    def test_invalid_price(self, adapter, sample_proposal):
        """测试无效价格"""
        sample_proposal.suggested_price = -10
        
        result = adapter.validate_proposal(sample_proposal)
        
        assert result["valid"] is False
        assert any("price" in err for err in result["errors"])
    
    def test_missing_rationale(self, adapter, sample_proposal):
        """测试缺失理由"""
        sample_proposal.rationale = ""
        
        result = adapter.validate_proposal(sample_proposal)
        
        assert result["valid"] is False
        assert any("rationale" in err for err in result["errors"])
    
    def test_large_quantity_warning(self, adapter, sample_proposal):
        """测试大数量警告"""
        sample_proposal.quantity = 15000
        
        result = adapter.validate_proposal(sample_proposal)
        
        assert result["valid"] is True
        assert any("Large quantity" in warn for warn in result["warnings"])


class TestSimulateExecution:
    """测试模拟执行"""
    
    def test_basic_execution(self, adapter, sample_proposal):
        """测试基本执行"""
        execution, metadata = adapter.simulate_execution(sample_proposal)
        
        assert execution.execution_id is not None
        assert execution.proposal_id == sample_proposal.proposal_id
        assert execution.symbol == "AAPL"
        assert execution.side == Side.BUY
        assert execution.quantity == 100
        assert execution.execution_mode == ExecutionMode.PAPER
        assert execution.status == OrderStatus.EXECUTED
        assert metadata["simulation"] is True
    
    def test_execution_with_confirmation(self, adapter, sample_proposal):
        """测试带确认的执行"""
        confirmation = Confirmation(
            confirmation_id="conf_test_001",
            proposal_id=sample_proposal.proposal_id,
            confirmed_by="trader_001",
            confirmed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
            modified_quantity=80,
            modified_price=148.0,
        )
        
        execution, metadata = adapter.simulate_execution(
            sample_proposal, confirmation
        )
        
        assert execution.quantity == 80  # 使用修改后的数量
        # 买入时滑点使价格变高，执行价应略高于基准价
        assert execution.executed_price > 148.0
        assert execution.executed_price < 148.1  # 滑点很小
    
    def test_execution_price_slippage(self, adapter, sample_proposal):
        """测试滑点对价格的影响"""
        # 买入：执行价应该高于基准价
        execution_buy, _ = adapter.simulate_execution(sample_proposal)
        assert execution_buy.executed_price > sample_proposal.suggested_price
        
        # 卖出：执行价应该低于基准价
        sell_proposal = Proposal(
            proposal_id="prop_test_sell",
            symbol="AAPL",
            side=Side.SELL,
            quantity=100,
            suggested_price=150.0,
            rationale="Test",
            execution_mode=ExecutionMode.PAPER,
        )
        execution_sell, _ = adapter.simulate_execution(sell_proposal)
        assert execution_sell.executed_price < sample_proposal.suggested_price
    
    def test_execution_commission(self, adapter, sample_proposal):
        """测试手续费计算"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        
        expected_commission = (
            execution.quantity * 
            execution.executed_price * 
            adapter.default_commission_rate
        )
        
        assert abs(execution.commission - expected_commission) < 0.01
    
    def test_invalid_proposal_raises_error(self, adapter):
        """测试无效提案抛出错误"""
        invalid_proposal = Proposal(
            proposal_id="prop_invalid",
            symbol="",  # 缺失 symbol
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Test",
        )
        
        with pytest.raises(ValueError, match="Invalid proposal"):
            adapter.simulate_execution(invalid_proposal)


class TestUpdatePosition:
    """测试持仓更新"""
    
    def test_open_long_position(self, adapter, sample_proposal):
        """测试开多仓"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution)
        
        assert position.symbol == "AAPL"
        assert position.quantity == 100
        assert position.average_cost > 0
        assert position.execution_mode == ExecutionMode.PAPER
    
    def test_increase_long_position(self, adapter, sample_proposal):
        """测试加仓"""
        # 第一次买入
        execution1, _ = adapter.simulate_execution(sample_proposal)
        position1 = adapter.update_position(execution1)
        
        # 第二次买入
        execution2, _ = adapter.simulate_execution(sample_proposal)
        position2 = adapter.update_position(execution2)
        
        assert position2.quantity == 200
        assert position2.average_cost == position1.average_cost  # 价格相同
    
    def test_close_long_position(self, adapter, sample_proposal):
        """测试平仓"""
        # 买入开仓
        execution1, _ = adapter.simulate_execution(sample_proposal)
        position1 = adapter.update_position(execution1)
        
        # 卖出平仓
        sell_proposal = Proposal(
            proposal_id="prop_test_sell",
            symbol="AAPL",
            side=Side.SELL,
            quantity=100,
            suggested_price=155.0,
            rationale="Take profit",
            execution_mode=ExecutionMode.PAPER,
        )
        execution2, _ = adapter.simulate_execution(sell_proposal)
        position2 = adapter.update_position(execution2)
        
        assert position2.quantity == 0
        assert position2.realized_pnl > 0  # 盈利
    
    def test_position_unrealized_pnl(self, adapter, sample_proposal):
        """测试未实现盈亏"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution, current_price=160.0)
        
        # 多头：(现价 - 成本) * 数量
        expected_pnl = (160.0 - position.average_cost) * 100
        assert abs(position.unrealized_pnl - expected_pnl) < 0.01
    
    def test_persist_position(self, adapter, sample_proposal):
        """测试持久化持仓"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution)
        file_path = adapter.persist_position(position)
        
        assert file_path.exists()
        
        # 验证文件内容
        with open(file_path) as f:
            data = json.load(f)
        
        assert data["symbol"] == "AAPL"
        assert data["execution_mode"] == "paper"


class TestGenerateJournal:
    """测试交易日志生成"""
    
    def test_generate_journal(self, adapter, sample_proposal):
        """测试生成交易日志"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution)
        confirmation = Confirmation(
            confirmation_id="conf_test_001",
            proposal_id=sample_proposal.proposal_id,
            confirmed_by="trader_001",
            confirmed_at=iso_now(),
            execution_mode=ExecutionMode.PAPER,
        )
        
        journal = adapter.generate_journal(
            proposal=sample_proposal,
            confirmation=confirmation,
            execution=execution,
            position=position,
            tags=["test", "momentum"],
        )
        
        assert journal.journal_id is not None
        assert journal.proposal.proposal_id == sample_proposal.proposal_id
        assert journal.execution.execution_id == execution.execution_id
        assert journal.execution_mode == ExecutionMode.PAPER
        assert "test" in journal.tags
    
    def test_journal_persistence(self, adapter, sample_proposal):
        """测试日志持久化"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution)
        
        journal = adapter.generate_journal(
            proposal=sample_proposal,
            confirmation=None,
            execution=execution,
            position=position,
        )
        
        journal_path = adapter.journal_dir / f"{journal.journal_id}.json"
        assert journal_path.exists()
    
    def test_get_journal(self, adapter, sample_proposal):
        """测试获取日志"""
        execution, _ = adapter.simulate_execution(sample_proposal)
        position = adapter.update_position(execution)
        
        journal = adapter.generate_journal(
            proposal=sample_proposal,
            confirmation=None,
            execution=execution,
            position=position,
        )
        
        retrieved = adapter.get_journal(journal.journal_id)
        assert retrieved is not None
        assert retrieved.journal_id == journal.journal_id


class TestFullWorkflow:
    """测试完整工作流 (Smoke Path)"""
    
    def test_execute_full_workflow(self, adapter, sample_proposal):
        """测试完整工作流"""
        result = adapter.execute_full_workflow(
            proposal=sample_proposal,
            confirmed_by="trader_001",
            market_price=151.0,
            current_price=152.0,
            tags=["smoke_test"],
        )
        
        assert result["success"] is True
        assert result["stage"] == "completed"
        assert "proposal_id" in result
        assert "confirmation_id" in result
        assert "execution_id" in result
        assert "journal_id" in result
        assert "position" in result
        assert result["position"]["symbol"] == "AAPL"
        assert result["position"]["quantity"] == 100
    
    def test_workflow_creates_files(self, adapter, sample_proposal):
        """测试工作流创建文件"""
        result = adapter.execute_full_workflow(
            proposal=sample_proposal,
            confirmed_by="trader_001",
        )
        
        # 检查日志文件
        journal_path = Path(result["journal_path"])
        assert journal_path.exists()
        
        # 检查持仓文件
        position_path = adapter.state_dir / f"position_{sample_proposal.symbol}.json"
        assert position_path.exists()
    
    def test_workflow_invalid_proposal(self, adapter):
        """测试工作流处理无效提案"""
        invalid_proposal = Proposal(
            proposal_id="prop_invalid",
            symbol="",
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Test",
        )
        
        result = adapter.execute_full_workflow(
            proposal=invalid_proposal,
            confirmed_by="trader_001",
        )
        
        assert result["success"] is False
        assert result["stage"] == "validation"
        assert len(result["errors"]) > 0


class TestPaperLiveIsolation:
    """测试 Paper/Live 隔离"""
    
    def test_adapter_always_paper(self, adapter, sample_proposal):
        """测试 adapter 始终使用 paper 模式"""
        assert adapter.execution_mode == ExecutionMode.PAPER
        
        execution, _ = adapter.simulate_execution(sample_proposal)
        assert execution.execution_mode == ExecutionMode.PAPER
    
    def test_create_paper_proposal_helper(self):
        """测试便捷函数创建 paper proposal"""
        proposal = create_paper_proposal(
            symbol="GOOGL",
            side="buy",
            quantity=50,
            price=2800.0,
            rationale="Fundamental value",
            strategy_id="strategy_value_001",
        )
        
        assert proposal.execution_mode == ExecutionMode.PAPER
        assert proposal.symbol == "GOOGL"
        assert proposal.side == Side.BUY
    
    def test_live_mode_proposal_rejected(self, adapter):
        """测试 live 模式提案被拒绝"""
        live_proposal = Proposal(
            proposal_id="prop_live",
            symbol="AAPL",
            side=Side.BUY,
            quantity=100,
            suggested_price=150.0,
            rationale="Test",
            execution_mode=ExecutionMode.LIVE,
        )
        
        result = adapter.validate_proposal(live_proposal)
        
        assert result["valid"] is False
        assert any("execution_mode" in err for err in result["errors"])


class TestPositionManagement:
    """测试持仓管理"""
    
    def test_get_all_positions(self, adapter, sample_proposal):
        """测试获取所有持仓"""
        # 创建多个持仓
        execution1, _ = adapter.simulate_execution(sample_proposal)
        adapter.update_position(execution1)
        
        proposal2 = Proposal(
            proposal_id="prop_test_002",
            symbol="GOOGL",
            side=Side.BUY,
            quantity=50,
            suggested_price=2800.0,
            rationale="Test",
            execution_mode=ExecutionMode.PAPER,
        )
        execution2, _ = adapter.simulate_execution(proposal2)
        adapter.update_position(execution2)
        
        positions = adapter.get_all_positions()
        
        assert len(positions) == 2
        assert "AAPL" in positions
        assert "GOOGL" in positions
    
    def test_get_journals(self, adapter, sample_proposal):
        """测试获取多个日志"""
        # 创建多个日志
        for i in range(5):
            prop = Proposal(
                proposal_id=f"prop_test_{i:03d}",
                symbol="AAPL",
                side=Side.BUY,
                quantity=100,
                suggested_price=150.0 + i,
                rationale=f"Test {i}",
                execution_mode=ExecutionMode.PAPER,
            )
            adapter.execute_full_workflow(prop, confirmed_by="trader_001")
        
        journals = adapter.get_journals(limit=3)
        
        assert len(journals) == 3
    
    def test_clear_state(self, adapter, sample_proposal):
        """测试清除状态"""
        adapter.execute_full_workflow(sample_proposal, confirmed_by="trader_001")
        
        assert len(adapter.get_all_positions()) > 0
        assert len(adapter.get_journals()) > 0
        
        adapter.clear_state()
        
        assert len(adapter.get_all_positions()) == 0
        assert len(adapter.get_journals()) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
