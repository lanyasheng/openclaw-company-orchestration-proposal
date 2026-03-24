#!/usr/bin/env python3
"""
test_fallback_protocol.py — Tests for P0-4 Fallback Protocol

测试 timeout / error / empty-result fallback 协议，确保：
1. timeout 后 closeout 状态正确
2. empty-result 被判 FAIL（硬拦截，不重试）
3. 不会错误 auto-dispatch
4. retry 逻辑正确（可恢复错误 retry 1 次，不可恢复直接 FAIL）
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add orchestrator to path
ORCHESTRATOR_DIR = Path(__file__).resolve().parents[2] / "runtime" / "orchestrator"
if str(ORCHESTRATOR_DIR) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATOR_DIR))

from fallback_protocol import (
    FallbackProtocol,
    FallbackResult,
    FallbackVerdict,
    FallbackCloseoutStatus,
    check_empty_result,
    determine_retry_eligibility,
    build_fallback_closeout,
    evaluate_fallback,
    FALLBACK_PROTOCOL_VERSION,
)
from partial_continuation import ContinuationContract


class TestEmptyResult(unittest.TestCase):
    """测试 empty-result 检测"""
    
    def test_empty_result_no_artifacts(self):
        """测试没有 artifact 的情况被判为 empty"""
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertTrue(empty_check["is_empty"])
        self.assertIn("Missing critical artifacts", empty_check["reason"])
    
    def test_empty_result_none_input(self):
        """测试 None 输入被判为 empty"""
        empty_check = check_empty_result(None)
        
        self.assertTrue(empty_check["is_empty"])
        self.assertEqual(empty_check["reason"], "task_result is None or empty")
    
    def test_empty_result_empty_dict(self):
        """测试空字典被判为 empty"""
        empty_check = check_empty_result({})
        
        self.assertTrue(empty_check["is_empty"])
    
    def test_not_empty_has_artifact(self):
        """测试有 artifact 不算 empty"""
        task_result = {
            "status": "completed",
            "artifact": {"path": "/tmp/test.md", "exists": True},
            "report": {"summary": "Test report"},
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertFalse(empty_check["is_empty"])
    
    def test_not_empty_has_result(self):
        """测试有实质性 result 不算 empty"""
        task_result = {
            "status": "completed",
            "result": {
                "data": {"key": "value"},
                "summary": "Test completed successfully",
            },
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertFalse(empty_check["is_empty"])
    
    def test_empty_string_artifact(self):
        """测试空字符串 artifact 被判为 missing"""
        task_result = {
            "status": "completed",
            "artifact": "",
            "report": "   ",  # 只有空格
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertTrue(empty_check["is_empty"])
        self.assertIn("artifact", empty_check["missing_artifacts"])
        self.assertIn("report", empty_check["missing_artifacts"])
    
    def test_empty_list_dict_artifact(self):
        """测试空列表/字典 artifact 被判为 missing"""
        task_result = {
            "status": "completed",
            "artifact": [],
            "report": {},
            "test_summary": [],
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertTrue(empty_check["is_empty"])
    
    def test_error_not_empty_result(self):
        """测试有 error 不算 empty-result（是 error 场景）"""
        task_result = {
            "status": "failed",
            "error": "Network error occurred",
            "error_type": "network_error",
        }
        
        empty_check = check_empty_result(task_result)
        
        self.assertFalse(empty_check["is_empty"])
        self.assertIn("Error present", empty_check["reason"])


class TestTimeoutFallback(unittest.TestCase):
    """测试 timeout fallback 逻辑"""
    
    def setUp(self):
        self.protocol = FallbackProtocol()
    
    def test_first_timeout_allows_retry(self):
        """测试首次超时允许 retry 1 次"""
        task_result = {
            "status": "timeout",
            "error": "Task timed out after 3600s",
            "metadata": {"timeout": True},
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "RETRY")
        self.assertTrue(result.retry_eligible)
        self.assertEqual(result.failure_type, "timeout")
        self.assertEqual(result.retry_count, 0)
        self.assertEqual(result.closeout_status, "incomplete")
    
    def test_timeout_after_max_retries_closeout(self):
        """测试超时达到最大重试次数后 closeout"""
        task_result = {
            "status": "timeout",
            "error": "Task timed out after 3600s",
            "metadata": {"timeout": True},
        }
        
        # 已经重试 1 次，再次超时
        result = self.protocol.evaluate(task_result, retry_count=1)
        
        self.assertEqual(result.verdict, "CONDITIONAL")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.failure_type, "timeout")
        self.assertEqual(result.closeout_status, "timeout_closeout")
        self.assertIn("timeout_closeout_after", result.continuation_contract.stopped_because)
    
    def test_timeout_closeout_continuation_contract(self):
        """测试 timeout closeout 的 continuation contract 正确"""
        task_result = {
            "status": "timed_out",
            "metadata": {"timeout": True},
        }
        
        result = self.protocol.evaluate(task_result, retry_count=1)
        
        self.assertIsNotNone(result.continuation_contract)
        self.assertEqual(result.continuation_contract.next_owner, "main")
        self.assertIn("timeout", result.continuation_contract.stopped_because.lower())
        self.assertIn("review", result.continuation_contract.next_step.lower())


class TestErrorFallback(unittest.TestCase):
    """测试 error fallback 逻辑"""
    
    def setUp(self):
        self.protocol = FallbackProtocol()
    
    def test_recoverable_error_allows_retry(self):
        """测试可恢复错误允许 retry"""
        task_result = {
            "status": "failed",
            "error": "Rate limit exceeded",
            "error_type": "rate_limit",
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "RETRY")
        self.assertTrue(result.retry_eligible)
        self.assertEqual(result.failure_type, "error")
        self.assertTrue(result.metadata.get("recoverable"))
    
    def test_irrecoverable_error_direct_fail(self):
        """测试不可恢复错误直接 FAIL，不重试"""
        task_result = {
            "status": "failed",
            "error": "Authentication failed",
            "error_type": "auth_failure",
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.failure_type, "error")
        self.assertEqual(result.closeout_status, "error_closeout")
    
    def test_irrecoverable_error_types(self):
        """测试各种不可恢复错误类型"""
        irrecoverable_types = [
            "auth_failure",
            "permission_denied",
            "invalid_input",
            "configuration_error",
            "tradability_blocker",
            "gate_fail",
        ]
        
        for error_type in irrecoverable_types:
            with self.subTest(error_type=error_type):
                task_result = {
                    "status": "failed",
                    "error": f"Error: {error_type}",
                    "error_type": error_type,
                }
                
                result = self.protocol.evaluate(task_result, retry_count=0)
                
                self.assertEqual(result.verdict, "FAIL")
                self.assertFalse(result.retry_eligible)
                self.assertEqual(result.closeout_status, "error_closeout")
    
    def test_recoverable_error_types(self):
        """测试各种可恢复错误类型"""
        recoverable_types = [
            "network_error",
            "rate_limit",
            "temporary_unavailable",
            "timeout_retryable",
        ]
        
        for error_type in recoverable_types:
            with self.subTest(error_type=error_type):
                task_result = {
                    "status": "failed",
                    "error": f"Error: {error_type}",
                    "error_type": error_type,
                }
                
                result = self.protocol.evaluate(task_result, retry_count=0)
                
                self.assertEqual(result.verdict, "RETRY")
                self.assertTrue(result.retry_eligible)
    
    def test_error_after_max_retries_closeout(self):
        """测试错误达到最大重试次数后 closeout"""
        task_result = {
            "status": "failed",
            "error": "Network error",
            "error_type": "network_error",  # 可恢复类型
        }
        
        # 已经重试 1 次，再次失败
        result = self.protocol.evaluate(task_result, retry_count=1)
        
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.closeout_status, "error_closeout")
        self.assertIn("Max retries exceeded", result.failure_reason)


class TestEmptyResultFallback(unittest.TestCase):
    """测试 empty-result fallback 逻辑（硬拦截）"""
    
    def setUp(self):
        self.protocol = FallbackProtocol()
    
    def test_empty_result_hard_block_fail(self):
        """测试 empty-result 硬拦截为 FAIL，不重试"""
        task_result = {
            "status": "completed",
            "metadata": {},
            # 没有 artifact / report / result
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.retry_eligible)  # 关键：不重试
        self.assertEqual(result.failure_type, "empty-result")
        self.assertEqual(result.closeout_status, "empty_result_closeout")
    
    def test_empty_result_never_retry(self):
        """测试 empty-result 无论 retry_count 多少都不重试"""
        task_result = {
            "status": "completed",
            # 空结果
        }
        
        for retry_count in [0, 1, 2, 5]:
            with self.subTest(retry_count=retry_count):
                result = self.protocol.evaluate(task_result, retry_count=retry_count)
                
                self.assertEqual(result.verdict, "FAIL")
                self.assertFalse(result.retry_eligible)
                self.assertEqual(result.failure_type, "empty-result")
    
    def test_empty_result_continuation_contract(self):
        """测试 empty-result 的 continuation contract 正确"""
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertIsNotNone(result.continuation_contract)
        self.assertIn("empty_result_hard_block", result.continuation_contract.stopped_because)
        self.assertIn("investigate", result.continuation_contract.next_step.lower())
        self.assertEqual(result.continuation_contract.next_owner, "main")


class TestAutoDispatchSafety(unittest.TestCase):
    """测试 fallback 不会错误放行 auto-dispatch"""
    
    def setUp(self):
        self.protocol = FallbackProtocol()
    
    def test_timeout_closeout_does_not_allow_auto_dispatch(self):
        """测试 timeout closeout 不会允许 auto-dispatch"""
        task_result = {
            "status": "timeout",
            "metadata": {"timeout": True},
        }
        
        # 达到最大重试次数
        result = self.protocol.evaluate(task_result, retry_count=1)
        
        self.assertEqual(result.verdict, "CONDITIONAL")
        self.assertEqual(result.closeout_status, "timeout_closeout")
        # CONDITIONAL 状态不应该允许 auto-dispatch
    
    def test_error_closeout_does_not_allow_auto_dispatch(self):
        """测试 error closeout 不会允许 auto-dispatch"""
        task_result = {
            "status": "failed",
            "error": "Auth failed",
            "error_type": "auth_failure",
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "FAIL")
        self.assertEqual(result.closeout_status, "error_closeout")
        # FAIL 状态不应该允许 auto-dispatch
    
    def test_empty_result_closeout_does_not_allow_auto_dispatch(self):
        """测试 empty-result closeout 不会允许 auto-dispatch"""
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "FAIL")
        self.assertEqual(result.closeout_status, "empty_result_closeout")
        # FAIL 状态不应该允许 auto-dispatch
    
    def test_retry_state_does_not_auto_dispatch_without_confirmation(self):
        """测试 retry 状态不会自动 dispatch（需要确认）"""
        task_result = {
            "status": "failed",
            "error": "Rate limit",
            "error_type": "rate_limit",
        }
        
        result = self.protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "RETRY")
        # RETRY 状态需要上层确认，不应该自动 dispatch


class TestFallbackCloseoutBuilder(unittest.TestCase):
    """测试 fallback closeout 构建器"""
    
    def test_build_fallback_closeout_timeout(self):
        """测试构建 timeout closeout"""
        task_result = {
            "status": "timeout",
            "metadata": {"timeout": True},
        }
        
        fallback_result = evaluate_fallback(task_result, retry_count=1)
        closeout = build_fallback_closeout(
            fallback_result=fallback_result,
            batch_id="test_batch_001",
            task_id="test_task_001",
            scenario="trading_roundtable",
        )
        
        self.assertEqual(closeout["closeout_status"], "timeout_closeout")
        self.assertEqual(closeout["batch_id"], "test_batch_001")
        self.assertEqual(closeout["task_id"], "test_task_001")
        self.assertEqual(closeout["scenario"], "trading_roundtable")
        self.assertEqual(closeout["verdict"], "CONDITIONAL")
        self.assertIn("fallback_protocol", closeout["metadata"])
    
    def test_build_fallback_closeout_empty_result(self):
        """测试构建 empty-result closeout"""
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        fallback_result = evaluate_fallback(task_result, retry_count=0)
        closeout = build_fallback_closeout(
            fallback_result=fallback_result,
            batch_id="test_batch_002",
            task_id="test_task_002",
            scenario="channel_roundtable",
        )
        
        self.assertEqual(closeout["closeout_status"], "empty_result_closeout")
        self.assertEqual(closeout["verdict"], "FAIL")
        self.assertEqual(closeout["failure_type"], "empty-result")
    
    def test_build_fallback_closeout_continuation_contract(self):
        """测试 closeout 包含 continuation contract"""
        task_result = {
            "status": "failed",
            "error": "Auth failed",
            "error_type": "auth_failure",
        }
        
        fallback_result = evaluate_fallback(task_result, retry_count=0)
        closeout = build_fallback_closeout(
            fallback_result=fallback_result,
            batch_id="test_batch_003",
            task_id="test_task_003",
            scenario="test_scenario",
        )
        
        self.assertIsNotNone(closeout["continuation_contract"])
        self.assertIn("stopped_because", closeout["continuation_contract"])
        self.assertIn("next_step", closeout["continuation_contract"])
        self.assertIn("next_owner", closeout["continuation_contract"])


class TestRetryEligibility(unittest.TestCase):
    """测试 retry 资格判断"""
    
    def test_max_retries_exceeded(self):
        """测试超过最大重试次数"""
        task_result = {
            "status": "failed",
            "error": "Network error",
        }
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count=1, max_retries=1)
        
        self.assertFalse(eligible)
        self.assertIn("Max retries", reason)
    
    def test_empty_result_not_retryable(self):
        """测试 empty-result 不可重试"""
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count=0)
        
        self.assertFalse(eligible)
        self.assertIn("Empty result", reason)
        self.assertIn("hard block", reason.lower())
    
    def test_irrecoverable_error_not_retryable(self):
        """测试不可恢复错误不可重试"""
        task_result = {
            "status": "failed",
            "error": "Auth failed",
            "error_type": "auth_failure",
        }
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count=0)
        
        self.assertFalse(eligible)
        self.assertIn("Irrecoverable", reason)
    
    def test_recoverable_error_retryable(self):
        """测试可恢复错误可重试"""
        task_result = {
            "status": "failed",
            "error": "Rate limit",
            "error_type": "rate_limit",
        }
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count=0)
        
        self.assertTrue(eligible)
        self.assertIn("Retry eligible", reason)
    
    def test_timeout_retryable(self):
        """测试超时可重试"""
        task_result = {
            "status": "timeout",
            "metadata": {"timeout": True},
        }
        
        eligible, reason = determine_retry_eligibility(task_result, retry_count=0)
        
        self.assertTrue(eligible)


class TestFallbackProtocolIntegration(unittest.TestCase):
    """测试 fallback 协议集成"""
    
    def test_full_timeout_flow(self):
        """测试完整 timeout 流程：首次超时 → retry → 仍超时 → closeout"""
        protocol = FallbackProtocol()
        task_result = {
            "status": "timeout",
            "metadata": {"timeout": True},
        }
        
        # 第一次：允许 retry
        result1 = protocol.evaluate(task_result, retry_count=0)
        self.assertEqual(result1.verdict, "RETRY")
        self.assertTrue(result1.retry_eligible)
        
        # 第二次：closeout
        result2 = protocol.evaluate(task_result, retry_count=1)
        self.assertEqual(result2.verdict, "CONDITIONAL")
        self.assertFalse(result2.retry_eligible)
        self.assertEqual(result2.closeout_status, "timeout_closeout")
    
    def test_full_error_flow_recoverable(self):
        """测试完整可恢复错误流程：失败 → retry → 仍失败 → closeout"""
        protocol = FallbackProtocol()
        task_result = {
            "status": "failed",
            "error": "Rate limit",
            "error_type": "rate_limit",
        }
        
        # 第一次：允许 retry
        result1 = protocol.evaluate(task_result, retry_count=0)
        self.assertEqual(result1.verdict, "RETRY")
        self.assertTrue(result1.retry_eligible)
        
        # 第二次：closeout
        result2 = protocol.evaluate(task_result, retry_count=1)
        self.assertEqual(result2.verdict, "FAIL")
        self.assertFalse(result2.retry_eligible)
        self.assertEqual(result2.closeout_status, "error_closeout")
    
    def test_full_error_flow_irrecoverable(self):
        """测试完整不可恢复错误流程：直接 closeout，不重试"""
        protocol = FallbackProtocol()
        task_result = {
            "status": "failed",
            "error": "Auth failed",
            "error_type": "auth_failure",
        }
        
        # 直接 FAIL，不重试
        result = protocol.evaluate(task_result, retry_count=0)
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.closeout_status, "error_closeout")
    
    def test_full_empty_result_flow(self):
        """测试完整 empty-result 流程：直接硬拦截，不重试"""
        protocol = FallbackProtocol()
        task_result = {
            "status": "completed",
            "metadata": {},
        }
        
        # 直接 FAIL，硬拦截
        result = protocol.evaluate(task_result, retry_count=0)
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.closeout_status, "empty_result_closeout")
    
    def test_success_flow(self):
        """测试成功流程：直接 PASS"""
        protocol = FallbackProtocol()
        task_result = {
            "status": "completed",
            "artifact": {"path": "/tmp/test.md"},
            "report": {"summary": "Success"},
        }
        
        result = protocol.evaluate(task_result, retry_count=0)
        
        self.assertEqual(result.verdict, "PASS")
        self.assertFalse(result.retry_eligible)
        self.assertEqual(result.closeout_status, "complete")
        self.assertEqual(result.failure_type, "none")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试
    suite.addTests(loader.loadTestsFromTestCase(TestEmptyResult))
    suite.addTests(loader.loadTestsFromTestCase(TestTimeoutFallback))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorFallback))
    suite.addTests(loader.loadTestsFromTestCase(TestEmptyResultFallback))
    suite.addTests(loader.loadTestsFromTestCase(TestAutoDispatchSafety))
    suite.addTests(loader.loadTestsFromTestCase(TestFallbackCloseoutBuilder))
    suite.addTests(loader.loadTestsFromTestCase(TestRetryEligibility))
    suite.addTests(loader.loadTestsFromTestCase(TestFallbackProtocolIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
