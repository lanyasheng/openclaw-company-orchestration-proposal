#!/usr/bin/env python3
"""
test_alert_audit.py — Observability Batch 4: 告警审计日志测试

测试覆盖：
1. 审计记录创建
2. 告警事件记录
3. 汇报事件记录
4. 日志查询
5. 任务历史
6. 统计信息
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# 添加 runtime 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

from alert_audit import (
    AlertAuditLogger,
    AlertAuditRecord,
    log_alert,
    log_report,
    query_logs,
    _generate_audit_id,
    _iso_now,
)


class TestAlertAuditRecord:
    """测试 AlertAuditRecord 数据类"""
    
    def test_record_creation(self):
        """测试审计记录创建"""
        record = AlertAuditRecord(
            audit_id="audit_test_001",
            audit_type="alert",
            alert_type="task_timeout",
            task_id="task_test_001",
            timestamp=_iso_now(),
            payload={"test": "payload"},
            delivery_result={"status": "sent"},
        )
        
        assert record.audit_id == "audit_test_001"
        assert record.audit_type == "alert"
        assert record.alert_type == "task_timeout"
        assert record.task_id == "task_test_001"
    
    def test_record_to_dict(self):
        """测试审计记录转字典"""
        record = AlertAuditRecord(
            audit_id="audit_test_002",
            audit_type="report",
            alert_type="task_completed",
            task_id="task_test_002",
            timestamp=_iso_now(),
            payload={"report": "content"},
            delivery_result={"status": "sent"},
        )
        
        data = record.to_dict()
        
        assert data["audit_id"] == "audit_test_002"
        assert data["audit_type"] == "report"
        assert data["payload"]["report"] == "content"
    
    def test_record_from_dict(self):
        """测试字典转审计记录"""
        data = {
            "audit_id": "audit_test_003",
            "audit_type": "alert",
            "alert_type": "task_failed",
            "task_id": "task_test_003",
            "timestamp": _iso_now(),
            "payload": {"error": "message"},
            "delivery_result": {"status": "failed"},
        }
        
        record = AlertAuditRecord.from_dict(data)
        
        assert record.audit_id == "audit_test_003"
        assert record.alert_type == "task_failed"
    
    def test_record_write(self, tmp_path):
        """测试审计记录写入文件"""
        record = AlertAuditRecord(
            audit_id="audit_test_004",
            audit_type="alert",
            alert_type="task_stuck",
            task_id="task_test_004",
            timestamp=_iso_now(),
            payload={"test": "data"},
            delivery_result={"status": "sent"},
        )
        
        audit_file = record.write(tmp_path)
        
        assert audit_file.exists()
        
        # 验证文件内容
        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        assert data["audit_id"] == "audit_test_004"
        assert data["alert_type"] == "task_stuck"
        
        # 验证日志文件
        log_file = tmp_path / f"logs-{_iso_now()[:10]}.jsonl"
        # 日志文件可能因为日期不同而不同，检查是否有日志文件
        log_files = list(tmp_path.glob("logs-*.jsonl"))
        assert len(log_files) > 0


class TestAlertAuditLogger:
    """测试 AlertAuditLogger"""
    
    def test_logger_init(self, tmp_path):
        """测试日志器初始化"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        assert logger.audit_dir == tmp_path
        assert tmp_path.exists()
    
    def test_log_alert(self, tmp_path):
        """测试记录告警事件"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        record = logger.log_alert(
            alert_type="task_timeout",
            task_id="task_test_005",
            alert_id="alert_test_005",
            payload={"timeout": "data"},
            delivery_result={"status": "sent"},
        )
        
        assert record.audit_id.startswith("audit_")
        assert record.audit_type == "alert"
        assert record.alert_type == "task_timeout"
        assert record.task_id == "task_test_005"
        
        # 验证文件存在
        audit_files = list(tmp_path.glob("audit_*.json"))
        assert len(audit_files) > 0
    
    def test_log_report(self, tmp_path):
        """测试记录汇报事件"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        record = logger.log_report(
            task_id="task_test_006",
            alert_id="alert_test_006",
            report_content="Task completed successfully",
            delivery_result={"status": "sent"},
        )
        
        assert record.audit_id.startswith("audit_")
        assert record.audit_type == "report"
        assert record.alert_type == "task_completed"
        assert record.task_id == "task_test_006"
    
    def test_query_logs(self, tmp_path):
        """测试查询日志"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        # 记录多条日志
        logger.log_alert(
            alert_type="task_timeout",
            task_id="task_test_007",
            alert_id="alert_test_007",
            payload={},
            delivery_result={"status": "sent"},
        )
        
        logger.log_alert(
            alert_type="task_failed",
            task_id="task_test_007",
            alert_id="alert_test_008",
            payload={},
            delivery_result={"status": "sent"},
        )
        
        logger.log_alert(
            alert_type="task_timeout",
            task_id="task_test_009",
            alert_id="alert_test_009",
            payload={},
            delivery_result={"status": "sent"},
        )
        
        # 按 task_id 查询
        logs = logger.query_logs(task_id="task_test_007")
        assert len(logs) == 2
        
        # 按 alert_type 查询
        logs = logger.query_logs(alert_type="task_timeout")
        assert len(logs) == 2
        
        # 按 audit_type 查询
        logs = logger.query_logs(audit_type="alert")
        assert len(logs) == 3
    
    def test_query_logs_with_limit(self, tmp_path):
        """测试查询日志带限制"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        # 记录多条日志
        for i in range(10):
            logger.log_alert(
                alert_type="task_timeout",
                task_id=f"task_test_{i:02d}",
                alert_id=f"alert_test_{i:02d}",
                payload={},
                delivery_result={"status": "sent"},
            )
        
        # 限制返回数量
        logs = logger.query_logs(limit=5)
        assert len(logs) == 5
    
    def test_get_task_history(self, tmp_path):
        """测试获取任务历史"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        # 为同一任务记录多条日志
        for i in range(5):
            logger.log_alert(
                alert_type="task_timeout",
                task_id="task_test_history",
                alert_id=f"alert_test_history_{i}",
                payload={},
                delivery_result={"status": "sent"},
            )
        
        history = logger.get_task_history("task_test_history")
        
        assert len(history) == 5
    
    def test_get_stats(self, tmp_path):
        """测试获取统计信息"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        # 记录不同类型的日志
        logger.log_alert(
            alert_type="task_timeout",
            task_id="task_001",
            alert_id="alert_001",
            payload={},
            delivery_result={"status": "sent"},
        )
        
        logger.log_alert(
            alert_type="task_failed",
            task_id="task_002",
            alert_id="alert_002",
            payload={},
            delivery_result={"status": "failed"},
        )
        
        logger.log_report(
            task_id="task_003",
            alert_id="alert_003",
            report_content="Completed",
            delivery_result={"status": "sent"},
        )
        
        stats = logger.get_stats()
        
        assert stats["total_records"] == 3
        assert "task_timeout" in stats["by_type"]
        assert "task_failed" in stats["by_type"]
        assert "task_completed" in stats["by_type"]
        assert stats["by_delivery_status"]["sent"] == 2
        assert stats["by_delivery_status"]["failed"] == 1


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_log_alert_function(self, tmp_path):
        """测试 log_alert 便捷函数"""
        from alert_audit import log_alert
        
        record = log_alert(
            alert_type="task_stuck",
            task_id="task_test_func_001",
            alert_id="alert_test_func_001",
            payload={},
            delivery_result={"status": "sent"},
            audit_dir=tmp_path,
        )
        
        assert record.audit_id.startswith("audit_")
        assert record.alert_type == "task_stuck"
    
    def test_log_report_function(self, tmp_path):
        """测试 log_report 便捷函数"""
        from alert_audit import log_report
        
        record = log_report(
            task_id="task_test_func_002",
            alert_id="alert_test_func_002",
            report_content="Test report",
            delivery_result={"status": "sent"},
            audit_dir=tmp_path,
        )
        
        assert record.audit_id.startswith("audit_")
        assert record.audit_type == "report"
    
    def test_query_logs_function(self, tmp_path):
        """测试 query_logs 便捷函数"""
        from alert_audit import log_alert, query_logs
        
        # 记录日志
        log_alert(
            alert_type="task_timeout",
            task_id="task_test_func_003",
            alert_id="alert_test_func_003",
            payload={},
            delivery_result={"status": "sent"},
            audit_dir=tmp_path,
        )
        
        # 查询日志
        logs = query_logs(task_id="task_test_func_003", audit_dir=tmp_path)
        
        assert len(logs) == 1


class TestGenerateAuditId:
    """测试审计 ID 生成"""
    
    def test_generate_audit_id_format(self):
        """测试审计 ID 格式"""
        audit_id = _generate_audit_id()
        
        assert audit_id.startswith("audit_")
        assert len(audit_id) == len("audit_") + 12  # 12 字符 hex
    
    def test_generate_audit_id_unique(self):
        """测试审计 ID 唯一性"""
        ids = set()
        for _ in range(100):
            ids.add(_generate_audit_id())
        
        assert len(ids) == 100  # 所有 ID 都唯一


class TestAlertAuditIntegration:
    """测试审计日志集成"""
    
    def test_full_workflow(self, tmp_path):
        """测试完整工作流"""
        logger = AlertAuditLogger(audit_dir=tmp_path)
        
        # 1. 记录告警
        alert_record = logger.log_alert(
            alert_type="task_timeout",
            task_id="task_workflow_001",
            alert_id="alert_workflow_001",
            payload={"timeout_minutes": 15, "overdue_minutes": 30},
            delivery_result={"status": "sent", "channel": "file"},
        )
        
        # 2. 记录汇报
        report_record = logger.log_report(
            task_id="task_workflow_002",
            alert_id="alert_workflow_002",
            report_content="Task completed successfully",
            delivery_result={"status": "sent", "channel": "file"},
        )
        
        # 3. 查询验证
        all_logs = logger.query_logs(limit=10)
        assert len(all_logs) == 2
        
        # 4. 获取统计
        stats = logger.get_stats()
        assert stats["total_records"] == 2
        assert "task_timeout" in stats["by_type"]
        assert "task_completed" in stats["by_type"]
        
        # 5. 验证文件存在（排除索引文件）
        audit_files = [f for f in tmp_path.glob("audit_*.json") if f.name != "audit_index.json"]
        assert len(audit_files) == 2
        
        log_files = list(tmp_path.glob("logs-*.jsonl"))
        assert len(log_files) > 0
        
        index_file = tmp_path / "audit_index.json"
        assert index_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
