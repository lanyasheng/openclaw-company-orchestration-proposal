#!/usr/bin/env python3
"""
test_alert_dispatcher.py — Observability Batch 4: 告警调度器测试

测试覆盖：
1. AlertDispatcher 初始化
2. 完成事件告警
3. 超时事件告警
4. 失败事件告警
5. 卡住事件告警
6. 去重逻辑
7. 节流逻辑
8. 审计日志集成
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# 添加 runtime 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

from alert_dispatcher import (
    AlertDispatcher,
    AlertPayload,
    DeliveryResult,
    _generate_dedupe_key,
    _generate_timeout_dedupe_key,
    _iso_now,
)
from alert_audit import AlertAuditLogger


class TestAlertDispatcherInit:
    """测试 AlertDispatcher 初始化"""
    
    def test_init_default(self):
        """测试默认初始化"""
        dispatcher = AlertDispatcher()
        
        assert dispatcher.channel == "file"
        assert dispatcher.dry_run is False
        assert dispatcher.timeout_threshold_minutes == 15
        assert dispatcher.heartbeat_timeout_minutes == 10
    
    def test_init_custom(self):
        """测试自定义初始化"""
        dispatcher = AlertDispatcher(
            channel="discord",
            dry_run=True,
            timeout_threshold_minutes=30,
            heartbeat_timeout_minutes=20,
        )
        
        assert dispatcher.channel == "discord"
        assert dispatcher.dry_run is True
        assert dispatcher.timeout_threshold_minutes == 30
        assert dispatcher.heartbeat_timeout_minutes == 20


class TestCompletionAlert:
    """测试完成事件告警"""
    
    def test_dispatch_completion_success(self, tmp_path):
        """测试成功发送完成告警"""
        dispatcher = AlertDispatcher(channel="file", dry_run=False)
        
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            receipt = {
                "receipt_id": "receipt_test_001",
                "source_task_id": "task_test_001",
                "receipt_status": "completed",
                "result_summary": "Task completed successfully",
            }
            context = {
                "label": "test-feature",
                "scenario": "custom",
                "owner": "main",
            }
            
            payload, result = dispatcher.dispatch_completion_alert(receipt, context)
            
            assert payload is not None
            assert result.status == "sent"
            assert payload.alert_type == "task_completed"
            assert payload.task_id == "task_test_001"
            assert "已完成" in payload.human_message
        finally:
            # 恢复原目录
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir
    
    def test_dispatch_completion_wrong_status(self, tmp_path):
        """测试错误状态不发送告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        receipt = {
            "receipt_id": "receipt_test_002",
            "source_task_id": "task_test_002",
            "receipt_status": "failed",  # 不是 completed
        }
        context = {"label": "test", "scenario": "custom", "owner": "main"}
        
        payload, result = dispatcher.dispatch_completion_alert(receipt, context)
        
        assert payload is None
        assert result.status == "failed"
    
    def test_dispatch_completion_dry_run(self, tmp_path):
        """测试干跑模式"""
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            dispatcher = AlertDispatcher(channel="file", dry_run=True)
            
            receipt = {
                "receipt_id": "receipt_test_003",
                "source_task_id": "task_test_003",
                "receipt_status": "completed",
            }
            context = {"label": "test", "scenario": "custom", "owner": "main"}
            
            payload, result = dispatcher.dispatch_completion_alert(receipt, context)
            
            assert payload is not None
            assert result.status == "dry_run"
        finally:
            # 恢复原始目录
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir


class TestTimeoutAlert:
    """测试超时事件告警"""
    
    def test_dispatch_timeout_success(self, tmp_path):
        """测试成功发送超时告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            # 过去时间的 promised_eta
            past_eta = (datetime.now() - timedelta(hours=1)).isoformat()
            
            card = {
                "task_id": "task_test_004",
                "stage": "running",
                "heartbeat": _iso_now(),
                "promise_anchor": {
                    "promised_eta": past_eta,
                },
                "metadata": {"label": "test-timeout"},
                "scenario": "custom",
                "owner": "main",
            }
            
            payload, result = dispatcher.dispatch_timeout_alert(card)
            
            assert payload is not None
            assert result.status == "sent"
            assert payload.alert_type == "task_timeout"
            assert payload.severity == "warning"
            assert "超时" in payload.human_message
        finally:
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir
    
    def test_dispatch_timeout_not_overdue(self, tmp_path):
        """测试未超时不发送告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        # 未来时间的 promised_eta
        future_eta = (datetime.now() + timedelta(hours=1)).isoformat()
        
        card = {
            "task_id": "task_test_005",
            "stage": "running",
            "heartbeat": _iso_now(),
            "promise_anchor": {
                "promised_eta": future_eta,
            },
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        payload, result = dispatcher.dispatch_timeout_alert(card)
        
        assert payload is None
        assert result.status == "failed"


class TestFailureAlert:
    """测试失败事件告警"""
    
    def test_dispatch_failure_success(self, tmp_path):
        """测试成功发送失败告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            receipt = {
                "receipt_id": "receipt_test_006",
                "source_task_id": "task_test_006",
                "receipt_status": "failed",
                "receipt_reason": "Test failure reason",
            }
            context = {
                "label": "test-failure",
                "scenario": "custom",
                "owner": "main",
            }
            
            payload, result = dispatcher.dispatch_failure_alert(receipt, context)
            
            assert payload is not None
            assert result.status == "sent"
            assert payload.alert_type == "task_failed"
            assert payload.severity == "error"
            assert "失败" in payload.human_message
        finally:
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir
    
    def test_dispatch_failure_wrong_status(self):
        """测试错误状态不发送告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        receipt = {
            "receipt_id": "receipt_test_007",
            "source_task_id": "task_test_007",
            "receipt_status": "completed",  # 不是 failed
        }
        context = {"label": "test", "scenario": "custom", "owner": "main"}
        
        payload, result = dispatcher.dispatch_failure_alert(receipt, context)
        
        assert payload is None
        assert result.status == "failed"


class TestStuckAlert:
    """测试卡住事件告警"""
    
    def test_dispatch_stuck_success(self, tmp_path):
        """测试成功发送卡住告警"""
        dispatcher = AlertDispatcher(channel="file")
        
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            # 过去时间的 heartbeat
            past_heartbeat = (datetime.now() - timedelta(hours=1)).isoformat()
            
            card = {
                "task_id": "task_test_008",
                "stage": "running",
                "heartbeat": past_heartbeat,
                "metadata": {"label": "test-stuck"},
                "scenario": "custom",
                "owner": "main",
            }
            
            payload, result = dispatcher.dispatch_stuck_alert(card)
            
            assert payload is not None
            assert result.status == "sent"
            assert payload.alert_type == "task_stuck"
            assert payload.severity == "critical"
            assert "卡住" in payload.human_message
        finally:
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir


class TestDeduplication:
    """测试去重逻辑"""
    
    def test_duplicate_completion_alert(self, tmp_path):
        """测试重复完成告警被拦截"""
        dispatcher = AlertDispatcher(channel="file", throttle_window_seconds=3600)
        
        # Mock 目录
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            receipt = {
                "receipt_id": "receipt_test_009",
                "source_task_id": "task_test_009",
                "receipt_status": "completed",
            }
            context = {"label": "test", "scenario": "custom", "owner": "main"}
            
            # 第一次发送
            payload1, result1 = dispatcher.dispatch_completion_alert(receipt, context)
            assert payload1 is not None
            assert result1.status == "sent"
            
            # 第二次发送（应该被去重拦截）
            payload2, result2 = dispatcher.dispatch_completion_alert(receipt, context)
            assert payload2 is None
            assert result2.status == "failed"
            assert "Duplicate" in result2.error
        finally:
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir


class TestAlertPayload:
    """测试 AlertPayload"""
    
    def test_payload_to_dict(self):
        """测试 payload 转字典"""
        payload = AlertPayload(
            alert_id="alert_test",
            alert_type="task_completed",
            task_id="task_test",
            task_label="test-label",
            scenario="custom",
            owner="main",
            severity="info",
            human_message="Test message",
            technical_details={},
            delivery={"channel": "file"},
            dedupe_key="task_test:task_completed",
        )
        
        data = payload.to_dict()
        
        assert data["alert_id"] == "alert_test"
        assert data["alert_type"] == "task_completed"
        assert data["human_message"] == "Test message"
    
    def test_payload_from_dict(self):
        """测试字典转 payload"""
        data = {
            "alert_id": "alert_test",
            "alert_type": "task_completed",
            "task_id": "task_test",
            "task_label": "test-label",
            "scenario": "custom",
            "owner": "main",
            "severity": "info",
            "human_message": "Test message",
            "technical_details": {},
            "delivery": {"channel": "file"},
            "dedupe_key": "task_test:task_completed",
            "timestamp": _iso_now(),
        }
        
        payload = AlertPayload.from_dict(data)
        
        assert payload.alert_id == "alert_test"
        assert payload.alert_type == "task_completed"
        assert payload.human_message == "Test message"


class TestDeliveryResult:
    """测试 DeliveryResult"""
    
    def test_result_to_dict(self):
        """测试结果转字典"""
        result = DeliveryResult(
            status="sent",
            channel="file",
            message_id="/path/to/file",
            metadata={"test": "value"},
        )
        
        data = result.to_dict()
        
        assert data["status"] == "sent"
        assert data["channel"] == "file"
        assert data["message_id"] == "/path/to/file"


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_dispatch_completion_function(self, tmp_path):
        """测试 dispatch_completion 便捷函数"""
        import alert_dispatcher
        import alert_audit
        original_state_dir = alert_dispatcher.ALERT_STATE_DIR
        original_log_dir = alert_dispatcher.ALERT_LOG_DIR
        original_audit_dir = alert_audit.ALERT_AUDIT_DIR
        
        alert_dispatcher.ALERT_STATE_DIR = tmp_path / "state"
        alert_dispatcher.ALERT_LOG_DIR = tmp_path / "logs"
        alert_audit.ALERT_AUDIT_DIR = tmp_path / "audits"
        
        try:
            from alert_dispatcher import dispatch_completion
            
            receipt = {
                "receipt_id": "receipt_test_010",
                "source_task_id": "task_test_010",
                "receipt_status": "completed",
            }
            context = {"label": "test", "scenario": "custom", "owner": "main"}
            
            payload, result = dispatch_completion(receipt, context)
            
            assert payload is not None
            assert result.status == "sent"
        finally:
            alert_dispatcher.ALERT_STATE_DIR = original_state_dir
            alert_dispatcher.ALERT_LOG_DIR = original_log_dir
            alert_audit.ALERT_AUDIT_DIR = original_audit_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
