#!/usr/bin/env python3
"""
test_closeout_gate.py — Tests for closeout gate glue

测试 closeout gate glue，确保：
1. 前一批 closeout 未完成时，阻止下一批继续
2. 前一批 push 未执行时，阻止下一批继续
3. 首次运行或 closeout 通过时，允许继续

这是 P0-4 Batch 2 最小 closeout gate glue 的测试覆盖。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from closeout_tracker import (
    CloseoutTracker,
    create_closeout,
    get_closeout,
    check_closeout_gate,
    CloseoutGateResult,
    ContinuationContract,
    CLOSEOUT_DIR,
    _ensure_closeout_dir,
)


@pytest.fixture(autouse=True)
def clean_closeout_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """使用临时 closeout 目录，避免污染真实数据"""
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(tmp_path / "state"))
    # 重新加载模块以使用新的 STATE_DIR
    import importlib
    import closeout_tracker
    importlib.reload(closeout_tracker)
    
    # 更新全局变量
    global CLOSEOUT_DIR, _ensure_closeout_dir, create_closeout, get_closeout, check_closeout_gate
    CLOSEOUT_DIR = tmp_path / "closeouts"
    CLOSEOUT_DIR.mkdir(parents=True, exist_ok=True)
    closeout_tracker.CLOSEOUT_DIR = CLOSEOUT_DIR
    
    yield
    
    # 清理
    import shutil
    if tmp_path.exists():
        shutil.rmtree(tmp_path)


class TestCloseoutGateResult:
    """测试 CloseoutGateResult 数据类"""
    
    def test_to_dict(self):
        result = CloseoutGateResult(
            allowed=True,
            reason="Test passed",
            previous_batch_id="batch_001",
            previous_closeout_status="complete",
            previous_push_status="pushed",
            previous_push_required=True,
        )
        
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["reason"] == "Test passed"
        assert d["previous_batch_id"] == "batch_001"
        assert d["previous_closeout_status"] == "complete"
        assert d["previous_push_status"] == "pushed"
        assert d["previous_push_required"] is True


class TestCheckCloseoutGate:
    """测试 check_closeout_gate 函数"""
    
    def test_first_run_allowed(self):
        """首次运行（无前一批 closeout）应该允许"""
        result = check_closeout_gate(
            batch_id="batch_001",
            scenario="trading_roundtable",
        )
        
        assert result.allowed is True
        assert "first run" in result.reason.lower()
        assert result.previous_batch_id is None
    
    def test_blocked_closeout_prevents_next_batch(self):
        """前一批 closeout blocked 时，阻止下一批"""
        # 创建 blocked closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_fail_blocker_tradability",
            next_step="Resolve blocker",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={
                "packet": {"overall_gate": "FAIL"},
                "roundtable": {"conclusion": "FAIL", "blocker": "tradability"},
            },
        )
        
        # 检查下一批
        result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
        )
        
        assert result.allowed is False
        assert "blocked" in result.reason.lower()
        assert result.previous_batch_id == "batch_001"
        assert result.previous_closeout_status == "blocked"
    
    def test_incomplete_closeout_prevents_next_batch(self):
        """前一批 closeout incomplete 时，阻止下一批"""
        continuation = ContinuationContract(
            stopped_because="follow_up_partial_completed",
            next_step="Complete remaining work",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
        )
        
        # incomplete closeout 应该允许继续（因为 push_required 但 push_status=blocked）
        # 注意：incomplete closeout 的 push_status 是 "blocked"，不是 "pushed"
        assert result.allowed is False
        assert "push" in result.reason.lower()
    
    def test_push_not_executed_prevents_next_batch(self):
        """前一批 push 未执行时，阻止下一批"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 验证 closeout 已创建且 push_required=True, push_status=pending
        closeout = get_closeout("batch_001")
        assert closeout is not None
        assert closeout.push_required is True
        assert closeout.push_status == "pending"
        
        # 检查下一批
        result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
        )
        
        assert result.allowed is False
        assert "push" in result.reason.lower()
        assert result.previous_push_status == "pending"
    
    def test_push_executed_allows_next_batch(self):
        """前一批 push 已执行时，允许下一批"""
        # 手动创建 push_status="pushed" 的 closeout
        _ensure_closeout_dir()
        
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id="batch_001",
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 手动更新 push_status 为 "pushed"
        artifact.push_status = "pushed"
        artifact.write()
        
        # 检查下一批
        result = check_closeout_gate(
            batch_id="batch_002",
            scenario="trading_roundtable",
        )
        
        assert result.allowed is True
        assert result.previous_batch_id == "batch_001"
        assert result.previous_push_status == "pushed"
    
    def test_non_trading_scenario_does_not_require_push(self):
        """非 trading 场景不强制要求 push"""
        continuation = ContinuationContract(
            stopped_because="callback_closed",
            next_step="Review",
            next_owner="main",
        )
        
        create_closeout(
            batch_id="batch_001",
            scenario="channel_roundtable",  # 非 trading
            continuation=continuation,
            has_remaining_work=False,
            metadata={"packet": {}},  # 没有 git commit
        )
        
        # 非 trading 场景，push_required=False
        closeout = get_closeout("batch_001")
        assert closeout.push_required is False
        
        # 检查下一批应该允许
        result = check_closeout_gate(
            batch_id="batch_002",
            scenario="channel_roundtable",
            require_push_complete=False,  # 非 trading 不强制要求 push
        )
        
        assert result.allowed is True
    
    def test_skip_closeout_gate_in_trading_roundtable(self):
        """测试 trading_roundtable 中 skip_closeout_gate 参数"""
        # 这个测试验证 trading_roundtable.py 中的 skip_closeout_gate 参数
        # 实际测试在 test_trading_roundtable_closeout_gate.py 中
        pass


class TestCloseoutGateIntegration:
    """测试 closeout gate 与 trading_roundtable 的集成"""
    
    def test_closeout_gate_result_in_callback_output(self):
        """验证 closeout gate 结果包含在 callback 输出中"""
        # 这个测试需要完整的 trading_roundtable callback 流程
        # 实际测试在 test_trading_roundtable_closeout_gate.py 中
        pass


def run_tests():
    """运行所有测试"""
    import unittest
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestCloseoutGateResult))
    suite.addTests(loader.loadTestsFromTestCase(TestCheckCloseoutGate))
    suite.addTests(loader.loadTestsFromTestCase(TestCloseoutGateIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
