#!/usr/bin/env python3
"""
alert_rules.py — Observability Batch 4: 告警规则

目标：定义超时/失败/完成/卡住事件的判定逻辑。

核心规则：
1. 超时规则：当前时间 - promised_eta > threshold
2. 失败规则：receipt_status = failed
3. 完成规则：receipt_status = completed
4. 卡住规则：heartbeat 超过 threshold 未更新

使用示例：
```python
from alert_rules import AlertRules

rules = AlertRules(timeout_threshold_minutes=15)

# 检查超时
result = rules.check_timeout(card)
if result.is_timeout:
    print(f"Timeout: {result.overdue_minutes} minutes")

# 检查卡住
result = rules.check_stuck(card)
if result.is_stuck:
    print(f"Stuck: {result.no_heartbeat_minutes} minutes")
```
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Literal, Optional

__all__ = [
    "AlertRules",
    "TimeoutCheck",
    "StuckCheck",
    "FailureCheck",
    "CompletionCheck",
    "TimeoutRule",
    "FailureRule",
    "CompletionRule",
    "RULES_VERSION",
]

RULES_VERSION = "alert_rules_v1"


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_time(time_str: str) -> Optional[datetime]:
    """解析 ISO-8601 时间字符串"""
    if not time_str:
        return None
    try:
        # 尝试多种格式
        for fmt in [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ]:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        # 最后尝试 fromisoformat
        return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


@dataclass
class TimeoutCheck:
    """
    超时检查结果
    
    字段：
    - is_timeout: 是否超时
    - reason: 原因
    - timeout_minutes: 超时阈值（分钟）
    - overdue_minutes: 已超时时长（分钟）
    - promised_eta: 承诺完成时间
    - current_time: 当前时间
    """
    is_timeout: bool
    reason: str
    timeout_minutes: int = 0
    overdue_minutes: int = 0
    promised_eta: str = ""
    current_time: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_timeout": self.is_timeout,
            "reason": self.reason,
            "timeout_minutes": self.timeout_minutes,
            "overdue_minutes": self.overdue_minutes,
            "promised_eta": self.promised_eta,
            "current_time": self.current_time,
        }


@dataclass
class StuckCheck:
    """
    卡住检查结果
    
    字段：
    - is_stuck: 是否卡住
    - reason: 原因
    - no_heartbeat_minutes: 无心跳时长（分钟）
    - heartbeat_threshold_minutes: 心跳阈值（分钟）
    - last_heartbeat: 最后心跳时间
    - current_time: 当前时间
    """
    is_stuck: bool
    reason: str
    no_heartbeat_minutes: int = 0
    heartbeat_threshold_minutes: int = 0
    last_heartbeat: str = ""
    current_time: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_stuck": self.is_stuck,
            "reason": self.reason,
            "no_heartbeat_minutes": self.no_heartbeat_minutes,
            "heartbeat_threshold_minutes": self.heartbeat_threshold_minutes,
            "last_heartbeat": self.last_heartbeat,
            "current_time": self.current_time,
        }


@dataclass
class FailureCheck:
    """
    失败检查结果
    
    字段：
    - is_failed: 是否失败
    - reason: 原因
    - receipt_status: Receipt 状态
    - receipt_reason: Receipt 原因
    """
    is_failed: bool
    reason: str
    receipt_status: str = ""
    receipt_reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_failed": self.is_failed,
            "reason": self.reason,
            "receipt_status": self.receipt_status,
            "receipt_reason": self.receipt_reason,
        }


@dataclass
class CompletionCheck:
    """
    完成检查结果
    
    字段：
    - is_completed: 是否完成
    - reason: 原因
    - receipt_status: Receipt 状态
    - result_summary: 结果摘要
    """
    is_completed: bool
    reason: str
    receipt_status: str = ""
    result_summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_completed": self.is_completed,
            "reason": self.reason,
            "receipt_status": self.receipt_status,
            "result_summary": self.result_summary,
        }


# 规则类型别名
TimeoutRule = Literal["promised_eta_exceeded"]
FailureRule = Literal["receipt_failed", "validator_blocked", "gate_failed"]
CompletionRule = Literal["receipt_completed", "validator_accepted"]


class AlertRules:
    """
    告警规则
    
    核心方法：
    - check_timeout(): 检查超时
    - check_stuck(): 检查卡住
    - check_failure(): 检查失败
    - check_completion(): 检查完成
    """
    
    def __init__(
        self,
        timeout_threshold_minutes: int = 15,
        heartbeat_timeout_minutes: int = 10,
    ):
        """
        初始化告警规则
        
        Args:
            timeout_threshold_minutes: 超时阈值（分钟）
            heartbeat_timeout_minutes: 心跳超时阈值（分钟）
        """
        self.timeout_threshold_minutes = timeout_threshold_minutes
        self.heartbeat_timeout_minutes = heartbeat_timeout_minutes
    
    def check_timeout(
        self,
        card: Dict[str, Any],
        timeout_minutes: Optional[int] = None,
    ) -> TimeoutCheck:
        """
        检查任务是否超时
        
        规则：
        1. 当前时间 - promised_eta > threshold
        2. stage 仍为 running/dispatch
        
        Args:
            card: Observability card
            timeout_minutes: 超时阈值（分钟），覆盖实例配置
        
        Returns:
            TimeoutCheck
        """
        threshold = timeout_minutes or self.timeout_threshold_minutes
        current_time = datetime.now()
        
        # 获取 promised_eta
        promise_anchor = card.get("promise_anchor", {})
        promised_eta_str = promise_anchor.get("promised_eta", "")
        
        if not promised_eta_str:
            return TimeoutCheck(
                is_timeout=False,
                reason="Missing promised_eta in card",
                timeout_minutes=threshold,
            )
        
        promised_eta = _parse_iso_time(promised_eta_str)
        if not promised_eta:
            return TimeoutCheck(
                is_timeout=False,
                reason=f"Invalid promised_eta format: {promised_eta_str}",
                timeout_minutes=threshold,
            )
        
        # 检查是否超时（允许 threshold 分钟的宽限期）
        deadline = promised_eta + timedelta(minutes=threshold)
        if current_time <= deadline:
            return TimeoutCheck(
                is_timeout=False,
                reason="Not yet overdue",
                timeout_minutes=threshold,
                promised_eta=promised_eta_str,
                current_time=_iso_now(),
            )
        
        # 计算超时时长
        overdue = current_time - promised_eta
        overdue_minutes = int(overdue.total_seconds() / 60)
        
        # 检查 stage
        stage = card.get("stage", "")
        if stage not in ["running", "dispatch"]:
            return TimeoutCheck(
                is_timeout=False,
                reason=f"Stage is '{stage}', not running/dispatch",
                timeout_minutes=threshold,
                overdue_minutes=overdue_minutes,
                promised_eta=promised_eta_str,
                current_time=_iso_now(),
            )
        
        return TimeoutCheck(
            is_timeout=True,
            reason=f"Overdue by {overdue_minutes} minutes",
            timeout_minutes=threshold,
            overdue_minutes=overdue_minutes,
            promised_eta=promised_eta_str,
            current_time=_iso_now(),
        )
    
    def check_stuck(
        self,
        card: Dict[str, Any],
        heartbeat_minutes: Optional[int] = None,
    ) -> StuckCheck:
        """
        检查任务是否卡住
        
        规则：
        1. heartbeat 超过 threshold 未更新
        2. stage 仍为 running
        
        Args:
            card: Observability card
            heartbeat_minutes: 心跳阈值（分钟），覆盖实例配置
        
        Returns:
            StuckCheck
        """
        threshold = heartbeat_minutes or self.heartbeat_timeout_minutes
        current_time = datetime.now()
        
        # 获取 heartbeat
        heartbeat_str = card.get("heartbeat", "")
        
        if not heartbeat_str:
            return StuckCheck(
                is_stuck=True,
                reason="Missing heartbeat in card",
                heartbeat_threshold_minutes=threshold,
                current_time=_iso_now(),
            )
        
        heartbeat = _parse_iso_time(heartbeat_str)
        if not heartbeat:
            return StuckCheck(
                is_stuck=False,
                reason=f"Invalid heartbeat format: {heartbeat_str}",
                heartbeat_threshold_minutes=threshold,
                last_heartbeat=heartbeat_str,
                current_time=_iso_now(),
            )
        
        # 计算无心跳时长
        no_heartbeat = current_time - heartbeat
        no_heartbeat_minutes = int(no_heartbeat.total_seconds() / 60)
        
        # 检查是否卡住
        if no_heartbeat_minutes < threshold:
            return StuckCheck(
                is_stuck=False,
                reason=f"Heartbeat is recent ({no_heartbeat_minutes} minutes ago)",
                no_heartbeat_minutes=no_heartbeat_minutes,
                heartbeat_threshold_minutes=threshold,
                last_heartbeat=heartbeat_str,
                current_time=_iso_now(),
            )
        
        # 检查 stage
        stage = card.get("stage", "")
        if stage not in ["running", "dispatch"]:
            return StuckCheck(
                is_stuck=False,
                reason=f"Stage is '{stage}', not running/dispatch",
                no_heartbeat_minutes=no_heartbeat_minutes,
                heartbeat_threshold_minutes=threshold,
                last_heartbeat=heartbeat_str,
                current_time=_iso_now(),
            )
        
        return StuckCheck(
            is_stuck=True,
            reason=f"No heartbeat for {no_heartbeat_minutes} minutes",
            no_heartbeat_minutes=no_heartbeat_minutes,
            heartbeat_threshold_minutes=threshold,
            last_heartbeat=heartbeat_str,
            current_time=_iso_now(),
        )
    
    def check_failure(
        self,
        completion_receipt: Dict[str, Any],
    ) -> FailureCheck:
        """
        检查任务是否失败
        
        规则：
        1. receipt_status = failed
        2. 或者 validator blocked
        
        Args:
            completion_receipt: Completion receipt artifact
        
        Returns:
            FailureCheck
        """
        receipt_status = completion_receipt.get("receipt_status", "")
        receipt_reason = completion_receipt.get("receipt_reason", "")
        
        if receipt_status == "failed":
            return FailureCheck(
                is_failed=True,
                reason=f"Receipt status is 'failed': {receipt_reason}",
                receipt_status=receipt_status,
                receipt_reason=receipt_reason,
            )
        
        # 检查 validator blocked
        if "validator blocked" in receipt_reason.lower():
            return FailureCheck(
                is_failed=True,
                reason=f"Validator blocked: {receipt_reason}",
                receipt_status=receipt_status,
                receipt_reason=receipt_reason,
            )
        
        if "gate required" in receipt_reason.lower():
            return FailureCheck(
                is_failed=True,
                reason=f"Gate required: {receipt_reason}",
                receipt_status=receipt_status,
                receipt_reason=receipt_reason,
            )
        
        return FailureCheck(
            is_failed=False,
            reason=f"Receipt status is '{receipt_status}', not failed",
            receipt_status=receipt_status,
            receipt_reason=receipt_reason,
        )
    
    def check_completion(
        self,
        completion_receipt: Dict[str, Any],
    ) -> CompletionCheck:
        """
        检查任务是否完成
        
        规则：
        1. receipt_status = completed
        2. 或者 validator accepted
        
        Args:
            completion_receipt: Completion receipt artifact
        
        Returns:
            CompletionCheck
        """
        receipt_status = completion_receipt.get("receipt_status", "")
        result_summary = completion_receipt.get("result_summary", "")
        
        if receipt_status == "completed":
            return CompletionCheck(
                is_completed=True,
                reason="Receipt status is 'completed'",
                receipt_status=receipt_status,
                result_summary=result_summary,
            )
        
        return CompletionCheck(
            is_completed=False,
            reason=f"Receipt status is '{receipt_status}', not completed",
            receipt_status=receipt_status,
            result_summary=result_summary,
        )


# 便捷函数

def check_timeout(
    card: Dict[str, Any],
    timeout_minutes: int = 15,
) -> TimeoutCheck:
    """便捷函数：检查超时"""
    rules = AlertRules(timeout_threshold_minutes=timeout_minutes)
    return rules.check_timeout(card, timeout_minutes)


def check_stuck(
    card: Dict[str, Any],
    heartbeat_minutes: int = 10,
) -> StuckCheck:
    """便捷函数：检查卡住"""
    rules = AlertRules(heartbeat_timeout_minutes=heartbeat_minutes)
    return rules.check_stuck(card, heartbeat_minutes)


def check_failure(receipt: Dict[str, Any]) -> FailureCheck:
    """便捷函数：检查失败"""
    rules = AlertRules()
    return rules.check_failure(receipt)


def check_completion(receipt: Dict[str, Any]) -> CompletionCheck:
    """便捷函数：检查完成"""
    rules = AlertRules()
    return rules.check_completion(receipt)


if __name__ == "__main__":
    # 简单测试
    print("Alert Rules - Quick Test")
    print("=" * 50)
    
    rules = AlertRules(timeout_threshold_minutes=15, heartbeat_timeout_minutes=10)
    
    # 测试超时检查（超时）
    test_card_timeout = {
        "task_id": "task_001",
        "stage": "running",
        "heartbeat": _iso_now(),
        "promise_anchor": {
            "promised_eta": "2026-03-29T10:00:00",  # 过去时间
        },
    }
    
    result = rules.check_timeout(test_card_timeout)
    print(f"Timeout check: is_timeout={result.is_timeout}, reason={result.reason}")
    
    # 测试超时检查（未超时）
    from datetime import timedelta
    future_eta = (datetime.now() + timedelta(hours=1)).isoformat()
    test_card_not_timeout = {
        "task_id": "task_002",
        "stage": "running",
        "heartbeat": _iso_now(),
        "promise_anchor": {
            "promised_eta": future_eta,  # 未来时间
        },
    }
    
    result = rules.check_timeout(test_card_not_timeout)
    print(f"Timeout check (not overdue): is_timeout={result.is_timeout}, reason={result.reason}")
    
    # 测试卡住检查（卡住）
    test_card_stuck = {
        "task_id": "task_003",
        "stage": "running",
        "heartbeat": "2026-03-29T10:00:00",  # 过去时间
    }
    
    result = rules.check_stuck(test_card_stuck)
    print(f"Stuck check: is_stuck={result.is_stuck}, reason={result.reason}")
    
    # 测试卡住检查（未卡住）
    test_card_not_stuck = {
        "task_id": "task_004",
        "stage": "running",
        "heartbeat": _iso_now(),
    }
    
    result = rules.check_stuck(test_card_not_stuck)
    print(f"Stuck check (not stuck): is_stuck={result.is_stuck}, reason={result.reason}")
    
    # 测试失败检查
    test_receipt_failed = {
        "receipt_status": "failed",
        "receipt_reason": "Test failure",
    }
    
    result = rules.check_failure(test_receipt_failed)
    print(f"Failure check: is_failed={result.is_failed}, reason={result.reason}")
    
    # 测试完成检查
    test_receipt_completed = {
        "receipt_status": "completed",
        "result_summary": "Task completed successfully",
    }
    
    result = rules.check_completion(test_receipt_completed)
    print(f"Completion check: is_completed={result.is_completed}, reason={result.reason}")
    
    print("Test completed!")
