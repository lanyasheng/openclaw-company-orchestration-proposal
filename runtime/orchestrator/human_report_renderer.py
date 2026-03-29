#!/usr/bin/env python3
"""
human_report_renderer.py — Observability Batch 4: 人话汇报渲染器

目标：将技术性 completion receipt / observability card 翻译为人类可读的汇报/告警。

核心能力：
1. 完成事件摘要：将 receipt 翻译为自然语言汇报
2. 超时事件告警：生成超时告警消息
3. 失败事件告警：生成失败告警消息
4. 卡住事件告警：生成卡住告警消息
5. 技术术语翻译：将技术术语翻译为通俗语言

汇报结构（三层）：
- 结论：一句话总结
- 证据：关键指标和事实
- 动作：建议的后续操作

使用示例：
```python
from human_report_renderer import HumanReportRenderer

renderer = HumanReportRenderer()

# 完成汇报
summary = renderer.render_completion_summary(receipt, task_context)

# 超时告警
alert = renderer.render_timeout_alert(card, timeout_minutes=15, overdue_minutes=30)

# 失败告警
alert = renderer.render_failure_alert(receipt, task_context)
```
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "HumanReportRenderer",
    "ReportTemplate",
    "RENDERER_VERSION",
]

RENDERER_VERSION = "human_report_renderer_v1"

# 汇报模板类型
ReportTemplate = Literal[
    "completion_summary",    # 完成汇报
    "timeout_alert",         # 超时告警
    "failure_alert",         # 失败告警
    "stuck_alert",           # 卡住告警
]


# 技术术语翻译表
TECHNICAL_TERMS_ZH = {
    "receipt_status": "任务状态",
    "completed": "已完成",
    "failed": "失败",
    "missing": "丢失",
    "timeout": "超时",
    "stuck": "卡住",
    "running": "执行中",
    "dispatch": "调度中",
    "callback_received": "回调已接收",
    "closeout": "收尾中",
    "cancelled": "已取消",
    "subagent": "子代理",
    "tmux": "终端会话",
    "browser": "浏览器自动化",
    "message": "消息",
    "cron": "定时任务",
    "manual": "手动",
    "receipt_id": "回执 ID",
    "task_id": "任务 ID",
    "scenario": "场景",
    "owner": "负责人",
    "executor": "执行器",
    "stage": "阶段",
    "heartbeat": "心跳",
    "promised_eta": "承诺完成时间",
    "duration_seconds": "耗时",
    "exit_code": "退出码",
    "validator": "验证器",
    "gate": "关卡",
    "blocked": "被拦截",
    "accepted": "已接受",
}


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _format_duration(seconds: int) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}分钟"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}小时{minutes}分钟"


def _translate_stage(stage: str) -> str:
    """翻译阶段为中文"""
    stage_map = {
        "planning": "规划中",
        "dispatch": "调度中",
        "running": "执行中",
        "callback_received": "回调已接收",
        "closeout": "收尾中",
        "completed": "已完成",
        "failed": "失败",
        "cancelled": "已取消",
        "idle": "空闲",
        "stuck": "卡住",
    }
    return stage_map.get(stage, stage)


def _translate_severity(severity: str) -> str:
    """翻译严重程度为中文"""
    severity_map = {
        "info": "信息",
        "warning": "警告",
        "error": "错误",
        "critical": "严重",
    }
    return severity_map.get(severity, severity)


@dataclass
class HumanReportRenderer:
    """
    人话汇报渲染器
    
    核心方法：
    - render_completion_summary(): 渲染完成汇报
    - render_timeout_alert(): 渲染超时告警
    - render_failure_alert(): 渲染失败告警
    - render_stuck_alert(): 渲染卡住告警
    - translate_technical_terms(): 翻译技术术语
    """
    
    # 默认汇报模板
    DEFAULT_COMPLETION_TEMPLATE = """## ✅ 任务完成汇报

**任务**: {task_label}
**状态**: 已完成
**时间**: {timestamp}

---

### 结论

{conclusion}

### 证据

- **回执 ID**: {receipt_id}
- **任务 ID**: {task_id}
- **场景**: {scenario}
- **执行器**: {executor}
- **耗时**: {duration}
- **退出码**: {exit_code}

### 动作

- ✅ 任务已完成，等待下一步指示
- 📄 查看详细报告：{report_path}
- 🔍 验证结果：{validation_result}
""".strip()

    DEFAULT_TIMEOUT_TEMPLATE = """## ⚠️ 任务超时告警

**任务**: {task_label}
**状态**: 超时
**时间**: {timestamp}

---

### 结论

任务 **{task_label}** 已超过承诺完成时间 **{overdue_minutes}分钟**。

### 证据

- **承诺完成时间**: {promised_eta}
- **当前时间**: {current_time}
- **超时阈值**: {timeout_threshold}分钟
- **已超时**: {overdue_minutes}分钟
- **当前阶段**: {current_stage}
- **最后心跳**: {last_heartbeat}

### 动作

- 🔍 检查任务执行状态
- ⏸️ 考虑是否需要中止或重试
- 📞 联系负责人：{owner}
""".strip()

    DEFAULT_FAILURE_TEMPLATE = """## ❌ 任务失败告警

**任务**: {task_label}
**状态**: 失败
**时间**: {timestamp}

---

### 结论

任务 **{task_label}** 执行失败。

### 证据

- **回执 ID**: {receipt_id}
- **任务 ID**: {task_id}
- **失败原因**: {failure_reason}
- **场景**: {scenario}
- **执行器**: {executor}

### 动作

- 🔍 查看详细错误日志
- 🔄 考虑是否重试
- 📞 联系负责人：{owner}
- 📝 记录教训，避免重复问题
""".strip()

    DEFAULT_STUCK_TEMPLATE = """## 🚨 任务卡住告警

**任务**: {task_label}
**状态**: 卡住
**时间**: {timestamp}

---

### 结论

任务 **{task_label}** 疑似卡住，已超过 **{no_heartbeat_minutes}分钟** 无心跳更新。

### 证据

- **当前阶段**: {current_stage}
- **最后心跳**: {last_heartbeat}
- **无心跳时长**: {no_heartbeat_minutes}分钟
- **场景**: {scenario}

### 动作

- 🔍 立即检查任务执行状态
- 🛑 考虑中止并重新启动
- 📞 联系负责人：{owner}
- 📋 查看 tmux/session 日志
""".strip()

    def render_completion_summary(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
        template: Optional[str] = None,
    ) -> str:
        """
        渲染完成汇报
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
            template: 可选的汇报模板
        
        Returns:
            人话汇报文本
        """
        # 提取关键信息
        receipt_id = completion_receipt.get("receipt_id", "unknown")
        task_id = completion_receipt.get("source_task_id", "unknown")
        result_summary = completion_receipt.get("result_summary", "无摘要")
        
        task_label = task_context.get("label", "unnamed")
        scenario = task_context.get("scenario", "custom")
        executor = task_context.get("executor", "subagent")
        owner = task_context.get("owner", "main")
        
        # 提取技术指标
        duration_seconds = completion_receipt.get("metadata", {}).get("duration_seconds", 0)
        exit_code = completion_receipt.get("metadata", {}).get("exit_code", 0)
        validation_status = completion_receipt.get("metadata", {}).get("validation_status", "unknown")
        
        # 生成结论
        conclusion = self._generate_completion_conclusion(
            task_label=task_label,
            result_summary=result_summary,
            duration_seconds=duration_seconds,
            exit_code=exit_code,
        )
        
        # 报告路径（如有）
        report_path = completion_receipt.get("metadata", {}).get("report_path", "暂无")
        
        # 使用默认模板或自定义模板
        if template is None:
            template = self.DEFAULT_COMPLETION_TEMPLATE
        
        # 生成汇报
        translation = template.format(
            task_label=task_label,
            timestamp=_iso_now(),
            conclusion=conclusion,
            receipt_id=receipt_id,
            task_id=task_id,
            scenario=self._translate_scenario(scenario),
            executor=self._translate_executor(executor),
            duration=_format_duration(duration_seconds),
            exit_code=exit_code,
            report_path=report_path,
            validation_result=self._translate_validation_status(validation_status),
        )
        
        return translation
    
    def render_timeout_alert(
        self,
        card: Dict[str, Any],
        timeout_minutes: int,
        overdue_minutes: int,
    ) -> str:
        """
        渲染超时告警
        
        Args:
            card: Observability card
            timeout_minutes: 超时阈值（分钟）
            overdue_minutes: 已超时时长（分钟）
        
        Returns:
            人话告警文本
        """
        # 提取关键信息
        task_id = card.get("task_id", "unknown")
        task_label = card.get("metadata", {}).get("label", "unnamed")
        scenario = card.get("scenario", "custom")
        owner = card.get("owner", "main")
        current_stage = card.get("stage", "unknown")
        last_heartbeat = card.get("heartbeat", "未知")
        promised_eta = card.get("promise_anchor", {}).get("promised_eta", "未知")
        
        # 使用默认模板
        template = self.DEFAULT_TIMEOUT_TEMPLATE
        
        # 生成告警
        alert = template.format(
            task_label=task_label,
            timestamp=_iso_now(),
            overdue_minutes=overdue_minutes,
            promised_eta=promised_eta,
            current_time=_iso_now(),
            timeout_threshold=timeout_minutes,
            current_stage=_translate_stage(current_stage),
            last_heartbeat=last_heartbeat,
            owner=owner,
        )
        
        return alert
    
    def render_failure_alert(
        self,
        completion_receipt: Dict[str, Any],
        task_context: Dict[str, Any],
    ) -> str:
        """
        渲染失败告警
        
        Args:
            completion_receipt: Completion receipt artifact
            task_context: 任务上下文
        
        Returns:
            人话告警文本
        """
        # 提取关键信息
        receipt_id = completion_receipt.get("receipt_id", "unknown")
        task_id = completion_receipt.get("source_task_id", "unknown")
        failure_reason = completion_receipt.get("receipt_reason", "未知原因")
        
        task_label = task_context.get("label", "unnamed")
        scenario = task_context.get("scenario", "custom")
        executor = task_context.get("executor", "subagent")
        owner = task_context.get("owner", "main")
        
        # 使用默认模板
        template = self.DEFAULT_FAILURE_TEMPLATE
        
        # 生成告警
        alert = template.format(
            task_label=task_label,
            timestamp=_iso_now(),
            receipt_id=receipt_id,
            task_id=task_id,
            failure_reason=self._truncate_text(failure_reason, 200),
            scenario=self._translate_scenario(scenario),
            executor=self._translate_executor(executor),
            owner=owner,
        )
        
        return alert
    
    def render_stuck_alert(
        self,
        card: Dict[str, Any],
        no_heartbeat_minutes: int,
    ) -> str:
        """
        渲染卡住告警
        
        Args:
            card: Observability card
            no_heartbeat_minutes: 无心跳时长（分钟）
        
        Returns:
            人话告警文本
        """
        # 提取关键信息
        task_id = card.get("task_id", "unknown")
        task_label = card.get("metadata", {}).get("label", "unnamed")
        scenario = card.get("scenario", "custom")
        owner = card.get("owner", "main")
        current_stage = card.get("stage", "unknown")
        last_heartbeat = card.get("heartbeat", "未知")
        
        # 使用默认模板
        template = self.DEFAULT_STUCK_TEMPLATE
        
        # 生成告警
        alert = template.format(
            task_label=task_label,
            timestamp=_iso_now(),
            no_heartbeat_minutes=no_heartbeat_minutes,
            current_stage=_translate_stage(current_stage),
            last_heartbeat=last_heartbeat,
            scenario=self._translate_scenario(scenario),
            owner=owner,
        )
        
        return alert
    
    def translate_technical_terms(self, text: str) -> str:
        """
        翻译技术术语为通俗语言
        
        Args:
            text: 包含技术术语的文本
        
        Returns:
            翻译后的文本
        """
        result = text
        for en, zh in TECHNICAL_TERMS_ZH.items():
            result = result.replace(en, zh)
        return result
    
    def _generate_completion_conclusion(
        self,
        task_label: str,
        result_summary: str,
        duration_seconds: int,
        exit_code: int,
    ) -> str:
        """
        生成完成汇报的结论部分
        
        Args:
            task_label: 任务标签
            result_summary: 结果摘要
            duration_seconds: 耗时（秒）
            exit_code: 退出码
        
        Returns:
            结论文本
        """
        duration_str = _format_duration(duration_seconds)
        
        if exit_code == 0:
            status_emoji = "✅"
            status_text = "成功完成"
        else:
            status_emoji = "⚠️"
            status_text = "完成但有警告"
        
        # 生成结论
        conclusion = f"任务 **{task_label}** 已{status_text}，耗时 {duration_str}。"
        
        # 添加摘要
        if result_summary and result_summary != "无摘要":
            conclusion += f"\n\n{result_summary[:200]}"
        
        return conclusion
    
    def _translate_scenario(self, scenario: str) -> str:
        """翻译场景为中文"""
        scenario_map = {
            "trading_roundtable": "交易圆桌",
            "channel_roundtable": "频道圆桌",
            "coding_issue": "编码问题",
            "workflow_dag": "工作流",
            "custom": "自定义",
        }
        return scenario_map.get(scenario, scenario)
    
    def _translate_executor(self, executor: str) -> str:
        """翻译执行器为中文"""
        executor_map = {
            "subagent": "子代理",
            "tmux": "终端会话",
            "browser": "浏览器",
            "message": "消息",
            "cron": "定时任务",
            "manual": "手动",
        }
        return executor_map.get(executor, executor)
    
    def _translate_validation_status(self, status: str) -> str:
        """翻译验证状态为中文"""
        status_map = {
            "accepted_completion": "验证通过",
            "blocked_completion": "验证拦截",
            "gate_required": "需要人工审查",
            "validator_error": "验证器错误",
            "unknown": "未知",
        }
        return status_map.get(status, status)
    
    def _truncate_text(self, text: str, max_length: int) -> str:
        """截断文本"""
        if len(text) <= max_length:
            return text
        return text[:max_length] + "..."


# 便捷函数

def render_completion(
    receipt: Dict[str, Any],
    context: Dict[str, Any],
    template: Optional[str] = None,
) -> str:
    """便捷函数：渲染完成汇报"""
    renderer = HumanReportRenderer()
    return renderer.render_completion_summary(receipt, context, template)


def render_timeout(
    card: Dict[str, Any],
    timeout_minutes: int,
    overdue_minutes: int,
) -> str:
    """便捷函数：渲染超时告警"""
    renderer = HumanReportRenderer()
    return renderer.render_timeout_alert(card, timeout_minutes, overdue_minutes)


def render_failure(
    receipt: Dict[str, Any],
    context: Dict[str, Any],
) -> str:
    """便捷函数：渲染失败告警"""
    renderer = HumanReportRenderer()
    return renderer.render_failure_alert(receipt, context)


def render_stuck(
    card: Dict[str, Any],
    no_heartbeat_minutes: int,
) -> str:
    """便捷函数：渲染卡住告警"""
    renderer = HumanReportRenderer()
    return renderer.render_stuck_alert(card, no_heartbeat_minutes)


if __name__ == "__main__":
    # 简单测试
    print("Human Report Renderer - Quick Test")
    print("=" * 50)
    
    renderer = HumanReportRenderer()
    
    # 测试完成汇报
    test_receipt = {
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
    test_context = {
        "label": "feature-xxx",
        "scenario": "trading_roundtable",
        "executor": "subagent",
        "owner": "trading",
    }
    
    summary = renderer.render_completion_summary(test_receipt, test_context)
    print("Completion Summary:")
    print(summary)
    print()
    
    # 测试超时告警
    test_card = {
        "task_id": "task_test_002",
        "stage": "running",
        "heartbeat": "2026-03-29T10:00:00",
        "promise_anchor": {
            "promised_eta": "2026-03-29T11:00:00",
        },
        "metadata": {"label": "bug-fix"},
        "scenario": "coding_issue",
        "owner": "main",
    }
    
    alert = renderer.render_timeout_alert(test_card, timeout_minutes=15, overdue_minutes=30)
    print("Timeout Alert:")
    print(alert)
    print()
    
    # 测试失败告警
    test_receipt_failed = {
        "receipt_id": "receipt_test_003",
        "source_task_id": "task_test_003",
        "receipt_status": "failed",
        "receipt_reason": "Validator blocked: Missing required artifact",
    }
    
    alert = renderer.render_failure_alert(test_receipt_failed, test_context)
    print("Failure Alert:")
    print(alert)
    
    print("\nTest completed!")
