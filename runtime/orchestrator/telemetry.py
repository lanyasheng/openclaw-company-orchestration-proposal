#!/usr/bin/env python3
"""
telemetry.py — Orchestration Telemetry / SLA Metrics (Minimal Implementation)

目标：提供最小核心可观测输出，不做完整看板。

核心指标：
1. Validator blocked rate: validator 拦截率统计
2. Auto-continue decision stats: 自动续批决策统计
3. Closeout latency: closeout 延迟统计（可选）
4. Per-lane execution stats: 各 lane 执行统计（可选）

这是 P0-6 Batch F 的最小实现：
- 指标落盘到 JSON 文件
- 支持追加写入和读取
- 提供简单的聚合统计
- 文档明确指标如何使用

设计原则：
- 最小核心，不做完整看板
- 优先落到真实文件/模块和测试
- 不影响现有逻辑，只添加可观测输出
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

__all__ = [
    "TELEMETRY_VERSION",
    "ValidatorMetrics",
    "AutoContinueMetrics",
    "TelemetryRecorder",
    "get_validator_stats",
    "get_auto_continue_stats",
    "TELEMETRY_DIR",
]

TELEMETRY_VERSION = "telemetry_v1"

# Telemetry 存储目录
TELEMETRY_DIR = Path(
    os.environ.get(
        "OPENCLAW_TELEMETRY_DIR",
        Path.home() / ".openclaw" / "shared-context" / "telemetry",
    )
)


def _ensure_telemetry_dir():
    """确保 telemetry 目录存在"""
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _iso_now() -> str:
    """返回 ISO-8601 时间戳"""
    return datetime.now().isoformat()


def _validator_metrics_file() -> Path:
    """返回 validator metrics 文件路径"""
    return TELEMETRY_DIR / "validator_metrics.jsonl"


def _auto_continue_metrics_file() -> Path:
    """返回 auto-continue metrics 文件路径"""
    return TELEMETRY_DIR / "auto_continue_metrics.jsonl"


@dataclass
class ValidatorMetrics:
    """
    Validator 指标记录
    
    核心字段：
    - timestamp: 时间戳
    - audit_id: 审计 ID
    - status: 验证状态 (accepted_completion / blocked_completion / gate_required / validator_error)
    - reason: 验证原因/规则 ID
    - score: Through 分数
    - label: 任务标签
    - metadata: 额外元数据
    """
    timestamp: str
    audit_id: str
    status: str
    reason: str
    score: int
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "telemetry_version": TELEMETRY_VERSION,
            "timestamp": self.timestamp,
            "audit_id": self.audit_id,
            "status": self.status,
            "reason": self.reason,
            "score": self.score,
            "label": self.label,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_validation_result(cls, validation_result: Dict[str, Any]) -> "ValidatorMetrics":
        """从 validation result 创建 metrics"""
        return cls(
            timestamp=validation_result.get("timestamp", _iso_now()),
            audit_id=validation_result.get("audit_id", ""),
            status=validation_result.get("status", "unknown"),
            reason=validation_result.get("reason", ""),
            score=validation_result.get("score", 0),
            label=validation_result.get("label", ""),
            metadata=validation_result.get("metadata", {}),
        )


@dataclass
class AutoContinueMetrics:
    """
    Auto-Continue 决策指标记录
    
    核心字段：
    - timestamp: 时间戳
    - receipt_id: Receipt ID
    - decision: 决策结果 (continue_allowed / continue_blocked / gate_required)
    - reason: 决策原因
    - writer_conflict: 是否存在 writer 冲突
    - batch_id: Batch ID（如果适用）
    - metadata: 额外元数据
    """
    timestamp: str
    receipt_id: str
    decision: str
    reason: str
    writer_conflict: bool = False
    batch_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "telemetry_version": TELEMETRY_VERSION,
            "timestamp": self.timestamp,
            "receipt_id": self.receipt_id,
            "decision": self.decision,
            "reason": self.reason,
            "writer_conflict": self.writer_conflict,
            "batch_id": self.batch_id,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_auto_continue_decision(cls, decision_result: Dict[str, Any], receipt_id: str) -> "AutoContinueMetrics":
        """从 auto-continue decision 创建 metrics"""
        return cls(
            timestamp=_iso_now(),
            receipt_id=receipt_id,
            decision=decision_result.get("decision", "unknown"),
            reason=decision_result.get("reason", ""),
            writer_conflict=decision_result.get("writer_conflict", False),
            batch_id=decision_result.get("batch_id", ""),
            metadata=decision_result.get("metadata", {}),
        )


class TelemetryRecorder:
    """
    Telemetry 记录器
    
    提供：
    - record_validator_metric(): 记录 validator 指标
    - record_auto_continue_metric(): 记录 auto-continue 指标
    - get_validator_stats(): 获取 validator 统计
    - get_auto_continue_stats(): 获取 auto-continue 统计
    """
    
    def __init__(self):
        _ensure_telemetry_dir()
    
    def record_validator_metric(self, metric: ValidatorMetrics):
        """
        记录 validator 指标
        
        Args:
            metric: ValidatorMetrics 记录
        """
        metrics_file = _validator_metrics_file()
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric.to_dict()) + "\n")
    
    def record_auto_continue_metric(self, metric: AutoContinueMetrics):
        """
        记录 auto-continue 指标
        
        Args:
            metric: AutoContinueMetrics 记录
        """
        metrics_file = _auto_continue_metrics_file()
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(metric.to_dict()) + "\n")
    
    def get_validator_stats(
        self,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """
        获取 validator 统计
        
        Args:
            limit: 最大读取记录数
        
        Returns:
            统计字典，包含：
            - total: 总记录数
            - accepted_count: 接受数量
            - blocked_count: 拦截数量
            - gate_count: Gate 数量
            - error_count: 错误数量
            - blocked_rate: 拦截率 (blocked / total)
            - by_reason: 按原因分组统计
            - by_label: 按标签分组统计
        """
        metrics_file = _validator_metrics_file()
        if not metrics_file.exists():
            return {
                "total": 0,
                "accepted_count": 0,
                "blocked_count": 0,
                "gate_count": 0,
                "error_count": 0,
                "blocked_rate": 0.0,
                "by_reason": {},
                "by_label": {},
            }
        
        records = []
        with open(metrics_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                
                if len(records) >= limit:
                    break
        
        # 统计
        total = len(records)
        accepted_count = sum(1 for r in records if r.get("status") == "accepted_completion")
        blocked_count = sum(1 for r in records if r.get("status") == "blocked_completion")
        gate_count = sum(1 for r in records if r.get("status") == "gate_required")
        error_count = sum(1 for r in records if r.get("status") == "validator_error")
        
        blocked_rate = blocked_count / total if total > 0 else 0.0
        
        # 按原因分组
        by_reason: Dict[str, int] = {}
        for r in records:
            reason = r.get("reason", "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1
        
        # 按标签分组
        by_label: Dict[str, int] = {}
        for r in records:
            label = r.get("label", "unknown")
            by_label[label] = by_label.get(label, 0) + 1
        
        return {
            "total": total,
            "accepted_count": accepted_count,
            "blocked_count": blocked_count,
            "gate_count": gate_count,
            "error_count": error_count,
            "blocked_rate": blocked_rate,
            "by_reason": by_reason,
            "by_label": by_label,
            "records": records,
        }
    
    def get_auto_continue_stats(
        self,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """
        获取 auto-continue 统计
        
        Args:
            limit: 最大读取记录数
        
        Returns:
            统计字典，包含：
            - total: 总记录数
            - continue_allowed_count: 允许续批数量
            - continue_blocked_count: 阻止续批数量
            - gate_required_count: Gate 数量
            - writer_conflict_count: Writer 冲突数量
            - continue_rate: 续批率 (continue_allowed / total)
            - by_reason: 按原因分组统计
            - by_batch: 按 batch 分组统计
        """
        metrics_file = _auto_continue_metrics_file()
        if not metrics_file.exists():
            return {
                "total": 0,
                "continue_allowed_count": 0,
                "continue_blocked_count": 0,
                "gate_required_count": 0,
                "writer_conflict_count": 0,
                "continue_rate": 0.0,
                "by_reason": {},
                "by_batch": {},
            }
        
        records = []
        with open(metrics_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
                
                if len(records) >= limit:
                    break
        
        # 统计
        total = len(records)
        continue_allowed_count = sum(1 for r in records if r.get("decision") == "continue_allowed")
        continue_blocked_count = sum(1 for r in records if r.get("decision") == "continue_blocked")
        gate_required_count = sum(1 for r in records if r.get("decision") == "gate_required")
        writer_conflict_count = sum(1 for r in records if r.get("writer_conflict") is True)
        
        continue_rate = continue_allowed_count / total if total > 0 else 0.0
        
        # 按原因分组
        by_reason: Dict[str, int] = {}
        for r in records:
            reason = r.get("reason", "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1
        
        # 按 batch 分组
        by_batch: Dict[str, int] = {}
        for r in records:
            batch_id = r.get("batch_id", "unknown")
            by_batch[batch_id] = by_batch.get(batch_id, 0) + 1
        
        return {
            "total": total,
            "continue_allowed_count": continue_allowed_count,
            "continue_blocked_count": continue_blocked_count,
            "gate_required_count": gate_required_count,
            "writer_conflict_count": writer_conflict_count,
            "continue_rate": continue_rate,
            "by_reason": by_reason,
            "by_batch": by_batch,
            "records": records,
        }


# 便捷函数
_recorder = TelemetryRecorder()


def record_validator_metric(metric: ValidatorMetrics):
    """便捷函数：记录 validator 指标"""
    _recorder.record_validator_metric(metric)


def record_auto_continue_metric(metric: AutoContinueMetrics):
    """便捷函数：记录 auto-continue 指标"""
    _recorder.record_auto_continue_metric(metric)


def get_validator_stats(limit: int = 1000) -> Dict[str, Any]:
    """便捷函数：获取 validator 统计"""
    return _recorder.get_validator_stats(limit)


def get_auto_continue_stats(limit: int = 1000) -> Dict[str, Any]:
    """便捷函数：获取 auto-continue 统计"""
    return _recorder.get_auto_continue_stats(limit)


def get_telemetry_summary() -> Dict[str, Any]:
    """
    获取 telemetry 摘要
    
    Returns:
        包含所有指标摘要的字典
    """
    return {
        "telemetry_version": TELEMETRY_VERSION,
        "timestamp": _iso_now(),
        "validator": get_validator_stats(limit=100),
        "auto_continue": get_auto_continue_stats(limit=100),
    }


# CLI 入口
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python telemetry.py summary")
        print("  python telemetry.py validator [--limit <limit>]")
        print("  python telemetry.py auto-continue [--limit <limit>]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "summary":
        summary = get_telemetry_summary()
        print(json.dumps(summary, indent=2))
    
    elif cmd == "validator":
        limit = 1000
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])
        
        stats = get_validator_stats(limit)
        print(json.dumps(stats, indent=2))
    
    elif cmd == "auto-continue":
        limit = 1000
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])
        
        stats = get_auto_continue_stats(limit)
        print(json.dumps(stats, indent=2))
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
