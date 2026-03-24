#!/usr/bin/env python3
"""
decision_builder.py — Decision Building for Trading Roundtable

负责从 payload 构建 decision，包含 empty-result 检查等逻辑。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from adapters.trading import TradingAdapter, ADAPTER_NAME, SCENARIO
from orchestrator import Decision

# 初始化适配器
_adapter = TradingAdapter()


def _check_empty_result(packet: Dict[str, Any]) -> Optional[str]:
    """
    C2: 检查是否为 empty-result
    
    Empty result 定义：
    - 无 artifact path/exists
    - 无 report path/exists
    - 无 test commands/summary
    - 无 repro commands
    
    Returns:
        如果是 empty result，返回原因字符串；否则返回 None
    """
    if not packet:
        return "packet is empty"
    
    # 检查 artifact
    artifact = packet.get("artifact") if isinstance(packet.get("artifact"), dict) else {}
    if not artifact.get("path") or not artifact.get("exists"):
        return "missing artifact truth (path or exists)"
    
    # 检查 report
    report = packet.get("report") if isinstance(packet.get("report"), dict) else {}
    if not report.get("path") or not report.get("exists"):
        return "missing report truth (path or exists)"
    
    # 检查 test
    test_info = packet.get("test") if isinstance(packet.get("test"), dict) else {}
    if not test_info.get("commands") or not test_info.get("summary"):
        return "missing test truth (commands or summary)"
    
    # 检查 repro
    repro = packet.get("repro") if isinstance(packet.get("repro"), dict) else {}
    if not repro.get("commands"):
        return "missing repro truth (commands)"
    
    return None


def build_decision(
    batch_id: str,
    payloads: Dict[str, Any],
    analysis: Dict[str, Any],
    preflight_validation: Optional[Dict[str, Any]] = None,
) -> Decision:
    """
    从 payload 构建 decision
    
    Args:
        batch_id: 批次 ID
        payloads: 从 _extract_payloads 返回的 payload dict
        analysis: batch 分析结果
        preflight_validation: P0-1 前置校验结果（可选）
    
    C2: 强校验逻辑
    - 缺关键 packet/roundtable 字段时，不允许 completed/PASS 混过去
    - empty-result（无 artifact/report/test summary）时硬拦截
    - 输出明确 blocked/error 状态，而不是静默接受
    """
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    
    # 使用适配器验证 packet（完整验证）
    validation = _adapter.validate_packet(packet, roundtable)
    
    # P0-1: 如果有 preflight validation，合并到 validation metadata 中
    if preflight_validation:
        validation["preflight"] = preflight_validation
    
    # ========== C2: Empty-Result Hard Block ==========
    empty_result_blocker = _check_empty_result(packet)
    if empty_result_blocker:
        # Empty result 硬拦截：不允许 completed/PASS 混过去
        validation["complete"] = False
        validation["empty_result_blocked"] = True
        validation["empty_result_reason"] = empty_result_blocker
        if "missing_fields" not in validation:
            validation["missing_fields"] = []
        validation["missing_fields"].append(f"empty_result: {empty_result_blocker}")
    # ========== End C2 ==========
    
    # 确定 action
    conclusion = str(roundtable.get("conclusion") or packet.get("overall_gate") or "FAIL").upper()
    blocker = str(roundtable.get("blocker") or packet.get("primary_blocker") or "implementation_risk")
    next_step = str(roundtable.get("next_step") or "")
    completion_criteria = str(roundtable.get("completion_criteria") or "")

    if not validation["complete"]:
        # C2: 明确区分 empty-result blocker 和普通 missing fields
        if validation.get("empty_result_blocked"):
            action = "fix_blocker"
            reason = f"EMPTY_RESULT_BLOCKED: {validation.get('empty_result_reason', 'empty result detected')}"
        else:
            action = "fix_blocker"
            reason = "phase1 packet or roundtable closure is incomplete"
    elif conclusion == "PASS" and blocker == "none":
        action = "proceed"
        reason = "roundtable gate is PASS and no blocker remains"
    elif conclusion == "CONDITIONAL":
        action = "fix_blocker"
        reason = f"roundtable gate is CONDITIONAL with blocker={blocker}"
    elif conclusion == "FAIL":
        action = "abort"
        reason = f"roundtable gate is FAIL with blocker={blocker}"
    else:
        action = "fix_blocker"
        reason = f"unrecognized trading roundtable conclusion={conclusion}"

    # 构建 next tasks
    recommended_next_tasks: List[Dict[str, Any]] = []
    if action in {"proceed", "fix_blocker"} and next_step:
        recommended_next_tasks.append({
            "type": "trading_roundtable_followup",
            "adapter": ADAPTER_NAME,
            "scenario": SCENARIO,
            "next_step": next_step,
            "completion_criteria": completion_criteria,
            "blocker": blocker,
        })

    return Decision(
        action=action,
        reason=reason,
        next_tasks=recommended_next_tasks,
        metadata={
            "adapter": ADAPTER_NAME,
            "scenario": SCENARIO,
            "packet": packet,
            "roundtable": roundtable,
            "packet_validation": validation,
            "batch_analysis": analysis,
            "supporting_results": payloads["supporting_results"],
        },
    )
