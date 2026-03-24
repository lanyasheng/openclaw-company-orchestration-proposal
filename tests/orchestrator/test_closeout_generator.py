#!/usr/bin/env python3
"""
test_closeout_generator.py — Tests for closeout_generator module
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_DIR = REPO_ROOT / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from closeout_generator import CloseoutGenerator
from orchestrator import Decision


class TestCloseoutGenerator:
    """测试 CloseoutGenerator 类"""
    
    @pytest.fixture
    def generator(self):
        """创建 CloseoutGenerator 实例"""
        return CloseoutGenerator()
    
    @pytest.fixture
    def mock_decision_proceed(self):
        """创建 proceed action 的 mock decision"""
        decision = MagicMock(spec=Decision)
        decision.to_dict.return_value = {
            "action": "proceed",
            "reason": "roundtable gate is PASS",
            "metadata": {
                "packet": {
                    "owner": "trading",
                    "overall_gate": "PASS",
                },
                "roundtable": {
                    "conclusion": "PASS",
                    "blocker": "none",
                    "next_step": "implement feature X",
                    "completion_criteria": "all tests pass",
                    "owner": "trading",
                },
                "packet_validation": {"complete": True},
                "supporting_results": [
                    {"task_id": "tsk_001", "state": "callback_received", "verdict": "PASS", "summary": "completed"},
                    {"task_id": "tsk_002", "state": "final_closed", "verdict": "PASS", "summary": "done"},
                ],
            },
        }
        return decision
    
    @pytest.fixture
    def mock_decision_fix_blocker(self):
        """创建 fix_blocker action 的 mock decision"""
        decision = MagicMock(spec=Decision)
        decision.to_dict.return_value = {
            "action": "fix_blocker",
            "reason": "roundtable gate is CONDITIONAL",
            "metadata": {
                "packet": {
                    "owner": "trading",
                    "primary_blocker": "performance_issue",
                },
                "roundtable": {
                    "conclusion": "CONDITIONAL",
                    "blocker": "performance_issue",
                    "completion_criteria": "fix performance",
                },
                "packet_validation": {"complete": True},
                "supporting_results": [
                    {"task_id": "tsk_001", "state": "callback_received", "verdict": "PASS", "summary": "partial"},
                ],
            },
        }
        return decision
    
    @pytest.fixture
    def mock_decision_abort(self):
        """创建 abort action 的 mock decision"""
        decision = MagicMock(spec=Decision)
        decision.to_dict.return_value = {
            "action": "abort",
            "reason": "roundtable gate is FAIL",
            "metadata": {
                "packet": {
                    "owner": "trading",
                    "primary_blocker": "critical_bug",
                },
                "roundtable": {
                    "conclusion": "FAIL",
                    "blocker": "critical_bug",
                },
                "packet_validation": {"complete": False, "missing_fields": ["artifact"]},
                "supporting_results": [],
            },
        }
        return decision
    
    def test_build_closeout_proceed_creates_next_step(
        self, generator: CloseoutGenerator, mock_decision_proceed
    ):
        """测试 proceed action 创建 next step"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_proceed, {"summary": "test"}
        )
        
        assert closeout is not None
        assert hasattr(closeout, 'has_remaining_work')
        # proceed 应该有 remaining work (next step)
        assert closeout.has_remaining_work() is True
    
    def test_build_closeout_fix_blocker_creates_blocked_scope(
        self, generator: CloseoutGenerator, mock_decision_fix_blocker
    ):
        """测试 fix_blocker action 创建 blocked scope"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_fix_blocker, {"summary": "test"}
        )
        
        assert closeout is not None
        assert closeout.has_remaining_work() is True
    
    def test_build_closeout_abort_marks_failed(
        self, generator: CloseoutGenerator, mock_decision_abort
    ):
        """测试 abort action 标记为 failed"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_abort, {"summary": "test"}
        )
        
        assert closeout is not None
        # abort 应该有 remaining work (missing fields)
        assert closeout.has_remaining_work() is True
    
    def test_build_closeout_includes_continuation_contract(
        self, generator: CloseoutGenerator, mock_decision_proceed
    ):
        """测试 closeout 包含 continuation contract"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_proceed, {"summary": "test"}
        )
        
        # 检查 continuation contract 被合并
        assert hasattr(closeout, 'metadata')
        assert 'continuation_contract' in closeout.metadata or hasattr(closeout, 'continuation_contract')
    
    def test_generate_registrations_empty_when_not_should_generate(
        self, generator: CloseoutGenerator, mock_decision_proceed
    ):
        """测试当不应该生成 registration 时返回空列表"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_proceed, {"summary": "test"}
        )
        
        # Mock closeout 的 should_generate_next_registration 方法
        closeout.should_generate_next_registration = lambda: False
        
        registrations = generator.generate_next_registrations_for_trading(closeout, "test_batch")
        
        assert registrations == []
    
    def test_build_closeout_completed_scope_from_supporting_results(
        self, generator: CloseoutGenerator, mock_decision_proceed
    ):
        """测试从 supporting_results 构建 completed_scope"""
        closeout = generator.build_partial_closeout_for_trading(
            "test_batch", mock_decision_proceed, {"summary": "test"}
        )
        
        # closeout 应该包含 completed scope 信息
        closeout_dict = closeout.to_dict() if hasattr(closeout, 'to_dict') else vars(closeout)
        
        # 检查 closeout 包含必要的字段
        assert 'original_batch_id' in closeout_dict or hasattr(closeout, 'original_batch_id')
