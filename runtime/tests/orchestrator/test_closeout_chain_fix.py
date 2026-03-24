#!/usr/bin/env python3
"""
test_closeout_chain_fix.py — Tests for closeout chain fix

测试 closeout 链修复，确保：
1. batch 完成后 closeout 状态正确前进
2. push_required 状态显式输出
3. 不会错误放行 auto-dispatch

这是 P0-4 Batch 1 最小可行修复的测试覆盖。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch, MagicMock

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from state_machine import STATE_DIR, create_task, mark_callback_received, TaskState, get_state
from closeout_tracker import CloseoutTracker, create_closeout, get_closeout, check_push_required, ContinuationContract
from partial_continuation import build_partial_closeout, ScopeItem


class TestCloseoutTracker(unittest.TestCase):
    """测试 CloseoutTracker 基本功能"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_batch_id = f"test_batch_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def test_create_closeout_complete(self):
        """测试创建 complete 状态的 closeout"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass_continuation_ready",
            next_step="Proceed to next phase",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            artifacts={"summary_path": "/tmp/test-summary.md"},
            metadata={"packet": {"overall_gate": "PASS"}},
        )
        
        # 验证 closeout 状态
        self.assertEqual(artifact.closeout_status, "complete")
        self.assertTrue(artifact.push_required)  # trading 场景默认需要 push
        self.assertEqual(artifact.push_status, "pending")
        
        # 验证 continuation contract
        self.assertEqual(artifact.continuation_contract.stopped_because, "roundtable_gate_pass_continuation_ready")
        self.assertEqual(artifact.continuation_contract.next_owner, "trading")
        
        # 验证文件已写入
        closeout = get_closeout(self.test_batch_id)
        self.assertIsNotNone(closeout)
        self.assertEqual(closeout.closeout_id, artifact.closeout_id)
    
    def test_create_closeout_incomplete(self):
        """测试创建 incomplete 状态的 closeout"""
        continuation = ContinuationContract(
            stopped_because="follow_up_partial_completed: fix blocker",
            next_step="Resolve blocker before continuation",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,  # 有剩余工作
            artifacts={"summary_path": "/tmp/test-summary.md"},
            metadata={"packet": {"overall_gate": "CONDITIONAL"}},
        )
        
        # 验证 closeout 状态
        self.assertEqual(artifact.closeout_status, "incomplete")
        self.assertTrue(artifact.push_required)  # trading 场景仍然需要 push
        self.assertEqual(artifact.push_status, "blocked")  # 但因为 incomplete 所以 blocked
    
    def test_create_closeout_blocked(self):
        """测试创建 blocked 状态的 closeout"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_fail_blocker_tradability",
            next_step="Resolve tradability blocker",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            artifacts={"summary_path": "/tmp/test-summary.md"},
            metadata={
                "packet": {"overall_gate": "FAIL"},
                "roundtable": {"conclusion": "FAIL", "blocker": "tradability"},
            },
        )
        
        # 验证 closeout 状态
        self.assertEqual(artifact.closeout_status, "blocked")
        self.assertTrue(artifact.push_required)
        self.assertEqual(artifact.push_status, "blocked")
    
    def test_push_required_non_trading_scenario(self):
        """测试非 trading 场景的 push_required 判断"""
        continuation = ContinuationContract(
            stopped_because="callback_closed_full_completion",
            next_step="Review and close",
            next_owner="main",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="channel_roundtable",  # 非 trading 场景
            continuation=continuation,
            has_remaining_work=False,
            artifacts={"summary_path": "/tmp/test-summary.md"},
            metadata={"packet": {}},  # 没有 git commit
        )
        
        # 非 trading 场景且没有 git commit，默认不需要 push
        self.assertFalse(artifact.push_required)
        self.assertEqual(artifact.push_status, "not_required")
    
    def test_check_push_required(self):
        """测试 check_push_required 函数"""
        # 先创建 closeout
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_pass",
            next_step="Proceed",
            next_owner="trading",
        )
        
        create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 检查 push required
        result = check_push_required(self.test_batch_id)
        
        self.assertTrue(result["push_required"])
        self.assertEqual(result["push_status"], "pending")
        self.assertEqual(result["closeout_status"], "complete")
        self.assertIn("closeout_id", result)


class TestCloseoutChainIntegration(unittest.TestCase):
    """测试 closeout 链与 state machine 的集成"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_batch_id = f"test_batch_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.test_task_ids = [f"tsk_test_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}" for i in range(3)]
        
        # 创建测试任务
        for task_id in self.test_task_ids:
            create_task(task_id, batch_id=self.test_batch_id)
    
    def test_closeout_after_batch_complete(self):
        """测试 batch 完成后 closeout 状态前进"""
        # 模拟 batch 完成：所有任务进入终态
        for task_id in self.test_task_ids:
            mark_callback_received(task_id, {"verdict": "PASS"})
        
        # 验证 batch 已完成
        from state_machine import is_batch_complete
        self.assertTrue(is_batch_complete(self.test_batch_id))
        
        # 创建 closeout
        continuation = ContinuationContract(
            stopped_because="batch_completed_all_tasks_passed",
            next_step="Review batch results and proceed",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=False,
            artifacts={
                "summary_path": f"/tmp/batch-{self.test_batch_id}-summary.md",
                "decision_path": f"/tmp/decision-{self.test_batch_id}.json",
                "dispatch_path": f"/tmp/dispatch-{self.test_batch_id}.json",
            },
            metadata={
                "packet": {"overall_gate": "PASS"},
                "roundtable": {"conclusion": "PASS", "blocker": "none"},
            },
        )
        
        # 验证 closeout 状态
        self.assertEqual(artifact.closeout_status, "complete")
        self.assertTrue(artifact.push_required)
        
        # 验证可以从 state machine 查询到 closeout
        closeout = get_closeout(self.test_batch_id)
        self.assertIsNotNone(closeout)
        self.assertEqual(closeout.batch_id, self.test_batch_id)
    
    def test_closeout_preserves_continuation_contract(self):
        """测试 closeout 正确保存 continuation contract"""
        continuation = ContinuationContract(
            stopped_because="test_stopped_because",
            next_step="test_next_step",
            next_owner="test_owner",
            metadata={"test_key": "test_value"},
        )
        
        create_closeout(
            batch_id=self.test_batch_id,
            scenario="test_scenario",
            continuation=continuation,
            has_remaining_work=False,
        )
        
        # 读取并验证
        closeout = get_closeout(self.test_batch_id)
        self.assertIsNotNone(closeout)
        
        cc = closeout.continuation_contract
        self.assertEqual(cc.stopped_because, "test_stopped_because")
        self.assertEqual(cc.next_step, "test_next_step")
        self.assertEqual(cc.next_owner, "test_owner")
        self.assertEqual(cc.metadata.get("test_key"), "test_value")


class TestCloseoutAutoDispatchSafety(unittest.TestCase):
    """测试 closeout 不会错误放行 auto-dispatch"""
    
    def setUp(self):
        """设置测试环境"""
        self.test_batch_id = f"test_batch_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    def test_blocked_closeout_does_not_allow_auto_dispatch(self):
        """测试 blocked closeout 不会允许 auto-dispatch"""
        continuation = ContinuationContract(
            stopped_because="roundtable_gate_fail_blocker_tradability",
            next_step="Resolve blocker first",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={
                "packet": {"overall_gate": "FAIL"},
                "roundtable": {"conclusion": "FAIL", "blocker": "tradability"},
            },
        )
        
        # 验证 closeout 状态
        self.assertEqual(artifact.closeout_status, "blocked")
        self.assertEqual(artifact.push_status, "blocked")
        
        # blocked 状态下不应该允许 auto-dispatch
        # （这里通过 closeout_status 间接验证，实际 auto-dispatch 控制由 dispatch_planner 负责）
        self.assertIn(artifact.closeout_status, {"blocked", "incomplete"})
    
    def test_incomplete_closeout_does_not_allow_auto_dispatch(self):
        """测试 incomplete closeout 不会允许 auto-dispatch"""
        continuation = ContinuationContract(
            stopped_because="follow_up_partial_completed",
            next_step="Complete remaining work",
            next_owner="trading",
        )
        
        artifact = create_closeout(
            batch_id=self.test_batch_id,
            scenario="trading_roundtable",
            continuation=continuation,
            has_remaining_work=True,
            metadata={
                "packet": {"overall_gate": "PASS"},  # PASS 但有 remaining work
                "roundtable": {"conclusion": "PASS", "blocker": "none"},
            },
        )
        
        # 验证 closeout 状态（有 remaining work -> incomplete）
        self.assertEqual(artifact.closeout_status, "incomplete")
        self.assertEqual(artifact.push_status, "blocked")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试
    suite.addTests(loader.loadTestsFromTestCase(TestCloseoutTracker))
    suite.addTests(loader.loadTestsFromTestCase(TestCloseoutChainIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestCloseoutAutoDispatchSafety))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
