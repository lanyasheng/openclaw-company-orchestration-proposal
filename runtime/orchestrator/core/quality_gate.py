#!/usr/bin/env python3
"""
quality_gate.py — Quality Gate Evaluator

质量门评估器，用于在 phase 转换或任务完成前进行检查。

核心功能：
- 预定义检查函数（packet completeness, artifact truth, gate consistency）
- 支持组合检查、阻塞条件收集
- 返回结构化 GateResult

这是通用 kernel，不绑定任何业务场景。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Callable, Optional
from pathlib import Path

from core.types import GateResult  # noqa: F811

__all__ = [
    "GateResult",
    "QualityGateEvaluator",
    "QUALITY_GATE_VERSION",
]

QUALITY_GATE_VERSION = "quality_gate_v1"


class QualityGateEvaluator:
    """
    质量门评估器
    
    管理多个质量门检查，支持动态注册检查函数。
    """
    
    def __init__(self):
        self._checks: Dict[str, Callable[[Dict[str, Any]], GateResult]] = {}
        self._context: Dict[str, Any] = {}
    
    def register_check(self, name: str, check_fn: Callable[[Dict[str, Any]], GateResult]):
        """
        注册检查函数
        
        Args:
            name: 检查名称
            check_fn: 检查函数，接收 context 返回 GateResult
        """
        self._checks[name] = check_fn
    
    def unregister_check(self, name: str):
        """注销检查函数"""
        self._checks.pop(name, None)
    
    def set_context(self, key: str, value: Any):
        """设置评估上下文"""
        self._context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """获取评估上下文"""
        return self._context.get(key, default)
    
    def evaluate(self, context: Optional[Dict[str, Any]] = None) -> GateResult:
        """
        执行所有注册的检查，返回聚合结果
        
        Args:
            context: 评估上下文（可选，会合并到内部 context）
        
        Returns:
            GateResult: 聚合检查结果
        """
        eval_context = {**self._context, **(context or {})}
        
        all_checks = []
        all_blockers = []
        all_warnings = []
        any_failed = False
        
        for name, check_fn in self._checks.items():
            try:
                result = check_fn(eval_context)
                all_checks.append({
                    "check": name,
                    "passed": result.passed,
                    "details": result.to_dict() if hasattr(result, 'to_dict') else result,
                })
                if not result.passed:
                    any_failed = True
                    all_blockers.extend(result.blockers)
                all_warnings.extend(result.warnings)
            except Exception as e:
                all_checks.append({
                    "check": name,
                    "passed": False,
                    "error": str(e),
                })
                any_failed = True
                all_blockers.append(f"Check {name} failed: {e}")
        
        return GateResult(
            passed=not any_failed,
            gate_name="composite",
            checks=all_checks,
            blockers=all_blockers,
            warnings=all_warnings,
            metadata={"check_count": len(self._checks)},
        )
    
    def evaluate_single(self, check_name: str, context: Optional[Dict[str, Any]] = None) -> Optional[GateResult]:
        """
        执行单个检查
        
        Args:
            check_name: 检查名称
            context: 评估上下文
        
        Returns:
            GateResult 或 None（如果检查不存在）
        """
        check_fn = self._checks.get(check_name)
        if not check_fn:
            return None
        
        eval_context = {**self._context, **(context or {})}
        return check_fn(eval_context)
    
    def list_checks(self) -> List[str]:
        """列出所有注册的检查"""
        return list(self._checks.keys())


# ============== 预定义检查函数 ==============

def check_packet_completeness(context: Dict[str, Any]) -> GateResult:
    """
    检查 packet 完整性
    
    验证 packet 中所有必需字段是否存在且非空。
    """
    packet = context.get("packet", {})
    required_fields = context.get("required_fields", [])
    
    missing = []
    for field in required_fields:
        if isinstance(field, tuple):
            parent, child = field
            parent_value = packet.get(parent)
            if not isinstance(parent_value, dict) or child not in parent_value:
                missing.append(f"{parent}.{child}")
                continue
            value = parent_value.get(child)
            if value in (None, ""):
                missing.append(f"{parent}.{child}")
        else:
            value = packet.get(field)
            if value in (None, ""):
                missing.append(field)
    
    return GateResult(
        passed=len(missing) == 0,
        gate_name="packet_completeness",
        checks=[{"field": f, "present": f not in missing} for f in required_fields],
        blockers=[f"Missing required field: {f}" for f in missing],
        metadata={"missing_count": len(missing)},
    )


def check_artifact_truth(context: Dict[str, Any]) -> GateResult:
    """
    检查 artifact 真值
    
    验证 artifact/report/test/repro 路径是否存在且有效。
    """
    packet = context.get("packet", {})
    issues = []
    
    artifact = packet.get("artifact") if isinstance(packet.get("artifact"), dict) else {}
    report = packet.get("report") if isinstance(packet.get("report"), dict) else {}
    test_info = packet.get("test") if isinstance(packet.get("test"), dict) else {}
    repro = packet.get("repro") if isinstance(packet.get("repro"), dict) else {}
    
    if artifact.get("exists") is not True:
        issues.append("artifact.exists is not true")
    if report.get("exists") is not True:
        issues.append("report.exists is not true")
    if not test_info.get("commands"):
        issues.append("test.commands is empty")
    if not repro.get("commands"):
        issues.append("repro.commands is empty")
    
    return GateResult(
        passed=len(issues) == 0,
        gate_name="artifact_truth",
        checks=[
            {"component": "artifact", "exists": artifact.get("exists")},
            {"component": "report", "exists": report.get("exists")},
            {"component": "test", "has_commands": bool(test_info.get("commands"))},
            {"component": "repro", "has_commands": bool(repro.get("commands"))},
        ],
        blockers=issues,
        metadata={"issue_count": len(issues)},
    )


def check_gate_consistency(context: Dict[str, Any]) -> GateResult:
    """
    检查 gate 一致性
    
    验证 roundtable 结论与 packet overall_gate / primary_blocker 是否一致。
    """
    packet = context.get("packet", {})
    roundtable = context.get("roundtable", {})
    issues = []
    
    conclusion = str(roundtable.get("conclusion") or "").upper()
    blocker = str(roundtable.get("blocker") or "").lower()
    overall_gate = str(packet.get("overall_gate") or "").upper()
    primary_blocker = str(packet.get("primary_blocker") or "").lower()
    tradability = packet.get("tradability") if isinstance(packet.get("tradability"), dict) else {}
    tradability_verdict = str(tradability.get("scenario_verdict") or "").upper()
    
    if conclusion == "PASS" and overall_gate not in ("", "PASS"):
        issues.append(f"roundtable conclusion PASS but overall_gate={overall_gate or 'N/A'}")
    if blocker == "none" and primary_blocker not in ("", "none"):
        issues.append(f"roundtable blocker none but primary_blocker={primary_blocker}")
    if conclusion == "PASS" and tradability_verdict not in ("", "PASS"):
        issues.append(f"roundtable conclusion PASS but tradability.scenario_verdict={tradability_verdict or 'N/A'}")
    
    return GateResult(
        passed=len(issues) == 0,
        gate_name="gate_consistency",
        checks=[
            {"conclusion": conclusion, "overall_gate": overall_gate},
            {"blocker": blocker, "primary_blocker": primary_blocker},
            {"tradability_verdict": tradability_verdict},
        ],
        blockers=issues,
        metadata={"issue_count": len(issues)},
    )


def check_batch_health(context: Dict[str, Any]) -> GateResult:
    """
    检查 batch 健康状态
    
    验证 batch 中没有 timeout 或 failed 任务。
    """
    analysis = context.get("batch_analysis", {})
    blockers = []
    
    timeout_count = int(analysis.get("timeout") or 0)
    failed_count = int(analysis.get("failed") or 0)
    
    if timeout_count > 0:
        blockers.append(f"Batch has {timeout_count} timeout task(s)")
    if failed_count > 0:
        blockers.append(f"Batch has {failed_count} failed task(s)")
    
    return GateResult(
        passed=timeout_count == 0 and failed_count == 0,
        gate_name="batch_health",
        checks=[
            {"metric": "timeout_count", "value": timeout_count, "expected": 0},
            {"metric": "failed_count", "value": failed_count, "expected": 0},
        ],
        blockers=blockers,
        metadata={"timeout_count": timeout_count, "failed_count": failed_count},
    )


def check_decision_action(context: Dict[str, Any]) -> GateResult:
    """
    检查 decision action 是否允许 auto-dispatch
    
    只有 proceed/retry 才允许 auto-dispatch。
    """
    decision = context.get("decision", {})
    action = decision.get("action", "")
    
    allowed_actions = {"proceed", "retry"}
    is_allowed = action in allowed_actions
    
    return GateResult(
        passed=is_allowed,
        gate_name="decision_action",
        checks=[{"action": action, "allowed": list(allowed_actions)}],
        blockers=[] if is_allowed else [f"Decision action '{action}' is not auto-dispatchable"],
        metadata={"action": action, "allowed_actions": list(allowed_actions)},
    )


# 预定义检查注册表
PREDEFINED_CHECKS = {
    "packet_completeness": check_packet_completeness,
    "artifact_truth": check_artifact_truth,
    "gate_consistency": check_gate_consistency,
    "batch_health": check_batch_health,
    "decision_action": check_decision_action,
}


def create_default_evaluator() -> QualityGateEvaluator:
    """创建带有预定义检查的默认评估器"""
    evaluator = QualityGateEvaluator()
    for name, check_fn in PREDEFINED_CHECKS.items():
        evaluator.register_check(name, check_fn)
    return evaluator
