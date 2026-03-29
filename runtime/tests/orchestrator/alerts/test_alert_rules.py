#!/usr/bin/env python3
"""
test_alert_rules.py — Observability Batch 4: 告警规则测试

测试覆盖：
1. 超时规则
2. 卡住规则
3. 失败规则
4. 完成规则
5. 边界条件
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# 添加 runtime 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from alert_rules import (
    AlertRules,
    TimeoutCheck,
    StuckCheck,
    FailureCheck,
    CompletionCheck,
    check_timeout,
    check_stuck,
    check_failure,
    check_completion,
    _parse_iso_time,
    _iso_now,
)


class TestAlertRulesInit:
    """测试 AlertRules 初始化"""
    
    def test_init_default(self):
        """测试默认初始化"""
        rules = AlertRules()
        
        assert rules.timeout_threshold_minutes == 15
        assert rules.heartbeat_timeout_minutes == 10
    
    def test_init_custom(self):
        """测试自定义初始化"""
        rules = AlertRules(
            timeout_threshold_minutes=30,
            heartbeat_timeout_minutes=20,
        )
        
        assert rules.timeout_threshold_minutes == 30
        assert rules.heartbeat_timeout_minutes == 20


class TestTimeoutCheck:
    """测试超时检查"""
    
    def test_timeout_overdue(self):
        """测试超时情况"""
        rules = AlertRules(timeout_threshold_minutes=15)
        
        # 过去时间的 promised_eta
        past_eta = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_001",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {
                "promised_eta": past_eta,
            },
        }
        
        result = rules.check_timeout(card)
        
        assert result.is_timeout is True
        assert result.overdue_minutes >= 59  # 至少 59 分钟
        assert "Overdue" in result.reason
    
    def test_timeout_not_overdue(self):
        """测试未超时情况"""
        rules = AlertRules(timeout_threshold_minutes=15)
        
        # 未来时间的 promised_eta
        future_eta = (datetime.now() + timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_002",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {
                "promised_eta": future_eta,
            },
        }
        
        result = rules.check_timeout(card)
        
        assert result.is_timeout is False
        assert "Not yet overdue" in result.reason
    
    def test_timeout_missing_eta(self):
        """测试缺失 promised_eta"""
        rules = AlertRules()
        
        card = {
            "task_id": "task_003",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {},
        }
        
        result = rules.check_timeout(card)
        
        assert result.is_timeout is False
        assert "Missing promised_eta" in result.reason
    
    def test_timeout_wrong_stage(self):
        """测试错误 stage 不判超时"""
        rules = AlertRules(timeout_threshold_minutes=15)
        
        past_eta = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_004",
            "stage": "completed",  # 不是 running/dispatch
            "heartbeat": _iso_now(),
            "promise_anchor": {
                "promised_eta": past_eta,
            },
        }
        
        result = rules.check_timeout(card)
        
        assert result.is_timeout is False
        assert "not running/dispatch" in result.reason
    
    def test_timeout_custom_threshold(self):
        """测试自定义超时阈值"""
        rules = AlertRules(timeout_threshold_minutes=15)
        
        # 30 分钟前，超过 15 分钟阈值但未超过 30 分钟自定义阈值
        past_eta = (datetime.now() - timedelta(minutes=20)).isoformat()
        
        card = {
            "task_id": "task_005",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {
                "promised_eta": past_eta,
            },
        }
        
        # 使用默认阈值 (15 分钟) - 应该超时
        result1 = rules.check_timeout(card)
        assert result1.is_timeout is True
        
        # 使用自定义阈值 (30 分钟) - 不应该超时
        result2 = rules.check_timeout(card, timeout_minutes=30)
        assert result2.is_timeout is False


class TestStuckCheck:
    """测试卡住检查"""
    
    def test_stuck_no_heartbeat(self):
        """测试无心跳卡住情况"""
        rules = AlertRules(heartbeat_timeout_minutes=10)
        
        # 1 小时前的心跳
        past_heartbeat = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_006",
            "stage": "running",
            "heartbeat": past_heartbeat,
        }
        
        result = rules.check_stuck(card)
        
        assert result.is_stuck is True
        assert result.no_heartbeat_minutes >= 59
        assert "No heartbeat" in result.reason
    
    def test_stuck_recent_heartbeat(self):
        """测试心跳正常未卡住"""
        rules = AlertRules(heartbeat_timeout_minutes=10)
        
        card = {
            "task_id": "task_007",
            "stage": "running",
            "heartbeat": _iso_now(),
        }
        
        result = rules.check_stuck(card)
        
        assert result.is_stuck is False
        assert "recent" in result.reason
    
    def test_stuck_missing_heartbeat(self):
        """测试缺失心跳"""
        rules = AlertRules()
        
        card = {
            "task_id": "task_008",
            "stage": "running",
            "heartbeat": "",
        }
        
        result = rules.check_stuck(card)
        
        assert result.is_stuck is True
        assert "Missing heartbeat" in result.reason
    
    def test_stuck_wrong_stage(self):
        """测试错误 stage 不判卡住"""
        rules = AlertRules(heartbeat_timeout_minutes=10)
        
        past_heartbeat = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_009",
            "stage": "completed",  # 不是 running/dispatch
            "heartbeat": past_heartbeat,
        }
        
        result = rules.check_stuck(card)
        
        assert result.is_stuck is False
        assert "not running/dispatch" in result.reason


class TestFailureCheck:
    """测试失败检查"""
    
    def test_failure_receipt_failed(self):
        """测试 receipt 状态为 failed"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "failed",
            "receipt_reason": "Test failure",
        }
        
        result = rules.check_failure(receipt)
        
        assert result.is_failed is True
        assert "failed" in result.reason
    
    def test_failure_validator_blocked(self):
        """测试 validator blocked"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "completed",
            "receipt_reason": "Validator blocked: Missing artifact",
        }
        
        result = rules.check_failure(receipt)
        
        assert result.is_failed is True
        assert "Validator blocked" in result.reason
    
    def test_failure_gate_required(self):
        """测试 gate required"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "completed",
            "receipt_reason": "Gate required: Human review needed",
        }
        
        result = rules.check_failure(receipt)
        
        assert result.is_failed is True
        assert "Gate required" in result.reason
    
    def test_failure_not_failed(self):
        """测试未失败情况"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "completed",
            "receipt_reason": "Success",
        }
        
        result = rules.check_failure(receipt)
        
        assert result.is_failed is False


class TestCompletionCheck:
    """测试完成检查"""
    
    def test_completion_receipt_completed(self):
        """测试 receipt 状态为 completed"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "completed",
            "result_summary": "Task completed successfully",
        }
        
        result = rules.check_completion(receipt)
        
        assert result.is_completed is True
        assert "completed" in result.reason
    
    def test_completion_not_completed(self):
        """测试未完成情况"""
        rules = AlertRules()
        
        receipt = {
            "receipt_status": "failed",
            "result_summary": "Task failed",
        }
        
        result = rules.check_completion(receipt)
        
        assert result.is_completed is False


class TestTimeoutCheckDataclass:
    """测试 TimeoutCheck 数据类"""
    
    def test_timeout_check_to_dict(self):
        """测试 TimeoutCheck 转字典"""
        check = TimeoutCheck(
            is_timeout=True,
            reason="Test timeout",
            timeout_minutes=15,
            overdue_minutes=30,
            promised_eta="2026-03-29T10:00:00",
            current_time="2026-03-29T11:30:00",
        )
        
        data = check.to_dict()
        
        assert data["is_timeout"] is True
        assert data["overdue_minutes"] == 30
        assert data["timeout_minutes"] == 15


class TestStuckCheckDataclass:
    """测试 StuckCheck 数据类"""
    
    def test_stuck_check_to_dict(self):
        """测试 StuckCheck 转字典"""
        check = StuckCheck(
            is_stuck=True,
            reason="Test stuck",
            no_heartbeat_minutes=60,
            heartbeat_threshold_minutes=10,
            last_heartbeat="2026-03-29T10:00:00",
            current_time="2026-03-29T11:00:00",
        )
        
        data = check.to_dict()
        
        assert data["is_stuck"] is True
        assert data["no_heartbeat_minutes"] == 60


class TestFailureCheckDataclass:
    """测试 FailureCheck 数据类"""
    
    def test_failure_check_to_dict(self):
        """测试 FailureCheck 转字典"""
        check = FailureCheck(
            is_failed=True,
            reason="Test failure",
            receipt_status="failed",
            receipt_reason="Error occurred",
        )
        
        data = check.to_dict()
        
        assert data["is_failed"] is True
        assert data["receipt_status"] == "failed"


class TestCompletionCheckDataclass:
    """测试 CompletionCheck 数据类"""
    
    def test_completion_check_to_dict(self):
        """测试 CompletionCheck 转字典"""
        check = CompletionCheck(
            is_completed=True,
            reason="Test completion",
            receipt_status="completed",
            result_summary="Success",
        )
        
        data = check.to_dict()
        
        assert data["is_completed"] is True
        assert data["receipt_status"] == "completed"


class TestParseIsoTime:
    """测试 ISO 时间解析"""
    
    def test_parse_iso_time_standard(self):
        """测试标准 ISO 格式"""
        time_str = "2026-03-29T15:30:00"
        result = _parse_iso_time(time_str)
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 29
        assert result.hour == 15
        assert result.minute == 30
    
    def test_parse_iso_time_with_microseconds(self):
        """测试带微秒的 ISO 格式"""
        time_str = "2026-03-29T15:30:00.123456"
        result = _parse_iso_time(time_str)
        
        assert result is not None
        assert result.year == 2026
    
    def test_parse_iso_time_empty(self):
        """测试空字符串"""
        result = _parse_iso_time("")
        assert result is None
    
    def test_parse_iso_time_invalid(self):
        """测试无效格式"""
        result = _parse_iso_time("invalid-time")
        assert result is None


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_check_timeout_function(self):
        """测试 check_timeout 便捷函数"""
        past_eta = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_010",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {"promised_eta": past_eta},
        }
        
        result = check_timeout(card, timeout_minutes=15)
        
        assert isinstance(result, TimeoutCheck)
        assert result.is_timeout is True
    
    def test_check_stuck_function(self):
        """测试 check_stuck 便捷函数"""
        past_heartbeat = (datetime.now() - timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_011",
            "stage": "running",
            "heartbeat": past_heartbeat,
        }
        
        result = check_stuck(card, heartbeat_minutes=10)
        
        assert isinstance(result, StuckCheck)
        assert result.is_stuck is True
    
    def test_check_failure_function(self):
        """测试 check_failure 便捷函数"""
        receipt = {
            "receipt_status": "failed",
            "receipt_reason": "Test",
        }
        
        result = check_failure(receipt)
        
        assert isinstance(result, FailureCheck)
        assert result.is_failed is True
    
    def test_check_completion_function(self):
        """测试 check_completion 便捷函数"""
        receipt = {
            "receipt_status": "completed",
            "result_summary": "Success",
        }
        
        result = check_completion(receipt)
        
        assert isinstance(result, CompletionCheck)
        assert result.is_completed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
