#!/usr/bin/env python3
"""
test_human_report_renderer.py — Observability Batch 4: 人话渲染器测试

测试覆盖：
1. 完成汇报渲染
2. 超时告警渲染
3. 失败告警渲染
4. 卡住告警渲染
5. 技术术语翻译
6. 模板自定义
"""

import sys
from pathlib import Path

import pytest

# 添加 runtime 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "orchestrator"))

from human_report_renderer import (
    HumanReportRenderer,
    render_completion,
    render_timeout,
    render_failure,
    render_stuck,
    _format_duration,
    _translate_stage,
)


class TestHumanReportRendererInit:
    """测试 HumanReportRenderer 初始化"""
    
    def test_init_default(self):
        """测试默认初始化"""
        renderer = HumanReportRenderer()
        
        assert renderer.DEFAULT_COMPLETION_TEMPLATE is not None
        assert renderer.DEFAULT_TIMEOUT_TEMPLATE is not None
        assert renderer.DEFAULT_FAILURE_TEMPLATE is not None
        assert renderer.DEFAULT_STUCK_TEMPLATE is not None


class TestCompletionSummary:
    """测试完成汇报渲染"""
    
    def test_render_completion_success(self):
        """测试成功渲染完成汇报"""
        renderer = HumanReportRenderer()
        
        receipt = {
            "receipt_id": "receipt_test_001",
            "source_task_id": "task_test_001",
            "receipt_status": "completed",
            "result_summary": "Task completed successfully. All tests passed.",
            "metadata": {
                "duration_seconds": 1500,
                "exit_code": 0,
                "validation_status": "accepted_completion",
                "report_path": "/tmp/report.md",
            },
        }
        context = {
            "label": "feature-xxx",
            "scenario": "trading_roundtable",
            "executor": "subagent",
            "owner": "trading",
        }
        
        summary = renderer.render_completion_summary(receipt, context)
        
        assert "✅ 任务完成汇报" in summary
        assert "feature-xxx" in summary
        assert "交易圆桌" in summary  # scenario 翻译
        assert "子代理" in summary  # executor 翻译
        assert "25 分钟" in summary  # 1500 秒 = 25 分钟
        assert "验证通过" in summary  # validation_status 翻译
    
    def test_render_completion_with_custom_template(self):
        """测试使用自定义模板"""
        renderer = HumanReportRenderer()
        
        custom_template = """
## 自定义汇报

任务：{task_label}
状态：已完成
摘要：{conclusion}
""".strip()
        
        receipt = {
            "receipt_id": "receipt_test_002",
            "source_task_id": "task_test_002",
            "receipt_status": "completed",
            "result_summary": "Summary",
            "metadata": {
                "duration_seconds": 60,
                "exit_code": 0,
                "validation_status": "accepted_completion",
            },
        }
        context = {"label": "test", "scenario": "custom", "executor": "subagent", "owner": "main"}
        
        summary = renderer.render_completion_summary(receipt, context, template=custom_template)
        
        assert "自定义汇报" in summary
        assert "test" in summary
    
    def test_render_completion_missing_fields(self):
        """测试缺失字段的容错处理"""
        renderer = HumanReportRenderer()
        
        receipt = {
            "receipt_id": "receipt_test_003",
            # 缺少其他字段
        }
        context = {}
        
        summary = renderer.render_completion_summary(receipt, context)
        
        assert "任务完成汇报" in summary
        assert "unknown" in summary or "unnamed" in summary


class TestTimeoutAlert:
    """测试超时告警渲染"""
    
    def test_render_timeout_success(self):
        """测试成功渲染超时告警"""
        renderer = HumanReportRenderer()
        
        card = {
            "task_id": "task_test_004",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "promise_anchor": {
                "promised_eta": "2026-03-29T11:00:00",
            },
            "metadata": {"label": "bug-fix"},
            "scenario": "coding_issue",
            "owner": "main",
        }
        
        alert = renderer.render_timeout_alert(card, timeout_minutes=15, overdue_minutes=30)
        
        assert "⚠️ 任务超时告警" in alert
        assert "bug-fix" in alert
        assert "超时" in alert
        assert "30 分钟" in alert
        assert "15 分钟" in alert
        assert "编码问题" in alert  # scenario 翻译
    
    def test_render_timeout_severity(self):
        """测试超时告警严重程度"""
        renderer = HumanReportRenderer()
        
        card = {
            "task_id": "task_test_005",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "promise_anchor": {"promised_eta": "2026-03-29T11:00:00"},
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = renderer.render_timeout_alert(card, timeout_minutes=15, overdue_minutes=60)
        
        assert "60 分钟" in alert
        assert "警告" in alert or "⚠️" in alert


class TestFailureAlert:
    """测试失败告警渲染"""
    
    def test_render_failure_success(self):
        """测试成功渲染失败告警"""
        renderer = HumanReportRenderer()
        
        receipt = {
            "receipt_id": "receipt_test_006",
            "source_task_id": "task_test_006",
            "receipt_status": "failed",
            "receipt_reason": "Validator blocked: Missing required artifact",
        }
        context = {
            "label": "feature-failed",
            "scenario": "trading_roundtable",
            "executor": "subagent",
            "owner": "trading",
        }
        
        alert = renderer.render_failure_alert(receipt, context)
        
        assert "❌ 任务失败告警" in alert
        assert "feature-failed" in alert
        assert "Validator blocked" in alert or "验证器" in alert
    
    def test_render_failure_long_reason(self):
        """测试长失败原因的截断"""
        renderer = HumanReportRenderer()
        
        long_reason = "A" * 300  # 300 字符
        
        receipt = {
            "receipt_id": "receipt_test_007",
            "source_task_id": "task_test_007",
            "receipt_status": "failed",
            "receipt_reason": long_reason,
        }
        context = {"label": "test", "scenario": "custom", "executor": "subagent", "owner": "main"}
        
        alert = renderer.render_failure_alert(receipt, context)
        
        # 应该被截断
        assert len(alert) < 1000


class TestStuckAlert:
    """测试卡住告警渲染"""
    
    def test_render_stuck_success(self):
        """测试成功渲染卡住告警"""
        renderer = HumanReportRenderer()
        
        card = {
            "task_id": "task_test_008",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "metadata": {"label": "stuck-task"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = renderer.render_stuck_alert(card, no_heartbeat_minutes=60)
        
        assert "🚨 任务卡住告警" in alert
        assert "stuck-task" in alert
        assert "60 分钟" in alert
        assert "卡住" in alert
    
    def test_render_stuck_critical(self):
        """测试卡住告警严重程度"""
        renderer = HumanReportRenderer()
        
        card = {
            "task_id": "task_test_009",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = renderer.render_stuck_alert(card, no_heartbeat_minutes=120)
        
        assert "🚨" in alert  # 严重告警 emoji
        assert "120 分钟" in alert


class TestDurationFormatting:
    """测试时长格式化"""
    
    def test_format_duration_seconds(self):
        """测试秒级时长"""
        assert _format_duration(30) == "30 秒"
        assert _format_duration(59) == "59 秒"
    
    def test_format_duration_minutes(self):
        """测试分钟级时长"""
        assert _format_duration(60) == "1 分钟"
        assert _format_duration(300) == "5 分钟"
        assert _format_duration(3599) == "59 分钟"
    
    def test_format_duration_hours(self):
        """测试小时级时长"""
        assert _format_duration(3600) == "1 小时 0 分钟"
        assert _format_duration(7200) == "2 小时 0 分钟"
        assert _format_duration(7500) == "2 小时 5 分钟"


class TestStageTranslation:
    """测试阶段翻译"""
    
    def test_translate_stage(self):
        """测试阶段翻译"""
        assert _translate_stage("planning") == "规划中"
        assert _translate_stage("dispatch") == "调度中"
        assert _translate_stage("running") == "执行中"
        assert _translate_stage("completed") == "已完成"
        assert _translate_stage("failed") == "失败"
        assert _translate_stage("cancelled") == "已取消"
        assert _translate_stage("unknown") == "unknown"  # 未知阶段保持原样


class TestConvenienceFunctions:
    """测试便捷函数"""
    
    def test_render_completion_function(self):
        """测试 render_completion 便捷函数"""
        receipt = {
            "receipt_id": "receipt_test_010",
            "source_task_id": "task_test_010",
            "receipt_status": "completed",
            "result_summary": "Test summary",
            "metadata": {
                "duration_seconds": 120,
                "exit_code": 0,
                "validation_status": "accepted_completion",
            },
        }
        context = {"label": "test", "scenario": "custom", "executor": "subagent", "owner": "main"}
        
        summary = render_completion(receipt, context)
        
        assert "任务完成汇报" in summary
    
    def test_render_timeout_function(self):
        """测试 render_timeout 便捷函数"""
        card = {
            "task_id": "task_test_011",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "promise_anchor": {"promised_eta": "2026-03-29T11:00:00"},
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = render_timeout(card, timeout_minutes=15, overdue_minutes=30)
        
        assert "超时告警" in alert
    
    def test_render_failure_function(self):
        """测试 render_failure 便捷函数"""
        receipt = {
            "receipt_id": "receipt_test_012",
            "source_task_id": "task_test_012",
            "receipt_status": "failed",
            "receipt_reason": "Test failure",
        }
        context = {"label": "test", "scenario": "custom", "executor": "subagent", "owner": "main"}
        
        alert = render_failure(receipt, context)
        
        assert "失败告警" in alert
    
    def test_render_stuck_function(self):
        """测试 render_stuck 便捷函数"""
        card = {
            "task_id": "task_test_013",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = render_stuck(card, no_heartbeat_minutes=30)
        
        assert "卡住告警" in alert


class TestReportStructure:
    """测试汇报结构（三层：结论/证据/动作）"""
    
    def test_completion_has_three_layers(self):
        """测试完成汇报有三层结构"""
        renderer = HumanReportRenderer()
        
        receipt = {
            "receipt_id": "receipt_test_014",
            "source_task_id": "task_test_014",
            "receipt_status": "completed",
            "result_summary": "Summary",
            "metadata": {
                "duration_seconds": 60,
                "exit_code": 0,
                "validation_status": "accepted_completion",
            },
        }
        context = {"label": "test", "scenario": "custom", "executor": "subagent", "owner": "main"}
        
        summary = renderer.render_completion_summary(receipt, context)
        
        # 检查三层结构
        assert "结论" in summary or "###" in summary
        assert "证据" in summary or "###" in summary
        assert "动作" in summary or "###" in summary
    
    def test_alert_has_three_layers(self):
        """测试告警有三层结构"""
        renderer = HumanReportRenderer()
        
        card = {
            "task_id": "task_test_015",
            "stage": "running",
            "heartbeat": "2026-03-29T10:00:00",
            "promise_anchor": {"promised_eta": "2026-03-29T11:00:00"},
            "metadata": {"label": "test"},
            "scenario": "custom",
            "owner": "main",
        }
        
        alert = renderer.render_timeout_alert(card, timeout_minutes=15, overdue_minutes=30)
        
        # 检查三层结构
        assert "结论" in alert or "###" in alert
        assert "证据" in alert or "###" in alert
        assert "动作" in alert or "###" in alert


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
