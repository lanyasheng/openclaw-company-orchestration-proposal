#!/usr/bin/env python3
"""
Trading roundtable continuation glue.

目标：把现有 state_machine / batch_aggregator / orchestrator 的最小能力，
接到 Trading Phase 1 roundtable continuation 这个具体场景上。

默认策略：safe semi-auto
- 总是持久化 summary / decision / dispatch plan
- 默认只对白名单的 clean PASS continuation 自动续跑，其余仍保持 skipped
- 显式 allow_auto_dispatch 仍优先于默认值
- 即使默认白名单或显式允许自动续跑，仍要求 packet / batch / gate 真值足够干净，避免越过 trading 风险边界
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from batch_aggregator import analyze_batch_results, check_and_summarize_batch
from completion_ack_guard import send_roundtable_completion_ack
from contracts import CANONICAL_CALLBACK_ENVELOPE_VERSION, resolve_orchestration_contract
from orchestrator import Decision, DECISIONS_DIR, DISPATCHES_DIR, _ensure_dirs
from state_machine import (
    STATE_DIR,
    _iso_now,
    get_batch_tasks,
    get_state,
    is_batch_complete,
    mark_callback_received,
    mark_final_closed,
    mark_next_dispatched,
)
from waiting_guard import reconcile_batch_waiting_anomalies

from adapters.trading import TradingAdapter
from core.dispatch_planner import DispatchPlanner, DispatchBackend
from core.quality_gate import QualityGateEvaluator, check_artifact_truth, check_gate_consistency, check_batch_health, check_decision_action
from core.task_registry import get_default_registry, TaskRegistration, TaskStatus
from partial_continuation import (
    build_partial_closeout,
    adapt_closeout_for_trading,
    generate_registered_registrations_for_closeout,
    PartialCloseoutContract,
)

# ============== 常量定义 ==============

ADAPTER_NAME = "trading_roundtable"
SCENARIO = "trading_roundtable_phase1"
PACKET_VERSION = "trading_phase1_packet_v1"
PHASE_ID = "trading_phase1"
SUMMARYS_DIR = STATE_DIR.parent / "orchestrator" / "summaries"

PHASE1_INPUT_DOC = "docs/plans/2026-03-20-trading-roundtable-phase1-input.md"
CLOSURE_TEMPLATE_DOC = "docs/plans/2026-03-20-trading-roundtable-closure-template.md"
FOLLOWUP_VERDICT_DOC = "docs/plans/2026-03-20-trading-roundtable-followup-verdict.md"
FOLLOWUP_CHECKLIST_DOC = "docs/plans/2026-03-20-trading-roundtable-phase1-followup-checklist.md"
PACKET_REQUIRED_FIELDS_DOC = "docs/architecture/trading-phase1-packet-required-fields-2026-03.md"
PHASE_MAP_DOC = "docs/architecture/trading-phase1-orchestration-phase-map-2026-03.md"

# ============== 辅助函数 ==============


def _ensure_runtime_dirs() -> None:
    _ensure_dirs()
    SUMMARYS_DIR.mkdir(parents=True, exist_ok=True)


def _summary_file(batch_id: str) -> Path:
    return SUMMARYS_DIR / f"batch-{batch_id}-summary.md"


def _atomic_json_write(file_path: Path, payload: Dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_file, "w") as handle:
        json.dump(payload, handle, indent=2)
    tmp_file.replace(file_path)


def _merge_first_non_empty(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict):
            child = target.get(key, {})
            if not isinstance(child, dict):
                child = {}
            target[key] = _merge_first_non_empty(child, value)
        elif key not in target or target[key] in (None, "", [], {}):
            target[key] = value
    return target


def _extract_payloads(batch_id: str) -> Dict[str, Any]:
    """从 batch tasks 中提取 packet 和 roundtable 数据"""
    packet: Dict[str, Any] = {}
    roundtable: Dict[str, Any] = {}
    supporting_results: List[Dict[str, Any]] = []

    for task in get_batch_tasks(batch_id):
        result = task.get("result") or {}
        scoped = result.get(ADAPTER_NAME) or {}
        if isinstance(scoped.get("packet"), dict):
            packet = _merge_first_non_empty(packet, scoped["packet"])
        if isinstance(scoped.get("roundtable"), dict):
            roundtable = _merge_first_non_empty(roundtable, scoped["roundtable"])
        waiting_guard = result.get("waiting_guard") if isinstance(result.get("waiting_guard"), dict) else {}
        closeout = result.get("closeout") if isinstance(result.get("closeout"), dict) else waiting_guard.get("closeout")
        supporting_results.append(
            {
                "task_id": task["task_id"],
                "state": task.get("state"),
                "verdict": result.get("verdict"),
                "summary": result.get("summary") or scoped.get("summary"),
                "error": result.get("error"),
                "waiting_guard": waiting_guard or None,
                "closeout": closeout if isinstance(closeout, dict) else None,
            }
        )

    return {
        "packet": packet,
        "roundtable": roundtable,
        "supporting_results": supporting_results,
    }


def _new_id(prefix: str, batch_id: str) -> str:
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return f"{prefix}_{safe_batch_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _decision_file(decision_id: str) -> Path:
    return DECISIONS_DIR / f"{decision_id}.json"


def _dispatch_plan_file(dispatch_id: str) -> Path:
    return DISPATCHES_DIR / f"{dispatch_id}.json"


# ============== 核心逻辑 ==============


def _build_decision(batch_id: str, analysis: Dict[str, Any], adapter: TradingAdapter) -> Decision:
    """基于 batch 分析结果构建 Decision"""
    payloads = _extract_payloads(batch_id)
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    
    # 验证 packet
    validation = adapter.validate_packet(packet, roundtable)
    
    # 推导 decision
    conclusion = str(roundtable.get("conclusion") or packet.get("overall_gate") or "FAIL").upper()
    blocker = str(roundtable.get("blocker") or packet.get("primary_blocker") or "implementation_risk")
    next_step = str(roundtable.get("next_step") or "")
    completion_criteria = str(roundtable.get("completion_criteria") or "")
    
    if not validation["complete"]:
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
    
    recommended_next_tasks: List[Dict[str, Any]] = []
    if action in {"proceed", "fix_blocker"} and next_step:
        recommended_next_tasks.append(
            {
                "type": "trading_roundtable_followup",
                "adapter": ADAPTER_NAME,
                "scenario": SCENARIO,
                "next_step": next_step,
                "completion_criteria": completion_criteria,
                "blocker": blocker,
            }
        )
    
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


def _build_partial_closeout_for_trading(
    batch_id: str,
    decision: Decision,
) -> PartialCloseoutContract:
    """构建 generic partial closeout contract"""
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    supporting_results = decision.metadata.get("supporting_results", [])
    
    # 构建 completed_scope
    completed_scope = []
    for item in supporting_results:
        if item.get("state") in ("callback_received", "final_closed", "next_task_dispatched"):
            completed_scope.append(
                {
                    "item_id": item.get("task_id", ""),
                    "description": f"Task {item.get('task_id', '')}: {item.get('summary') or item.get('verdict') or 'completed'}",
                    "status": "completed",
                    "metadata": {
                        "state": item.get("state"),
                        "verdict": item.get("verdict"),
                    },
                }
            )
    
    # 构建 remaining_scope
    remaining_scope = []
    stop_reason = "completed_all"
    
    if decision.action == "proceed":
        next_step = roundtable.get("next_step", "")
        if next_step:
            remaining_scope.append(
                {
                    "item_id": "next_step_1",
                    "description": next_step,
                    "status": "not_started",
                    "metadata": {
                        "completion_criteria": roundtable.get("completion_criteria", ""),
                        "blocker": "none",
                    },
                }
            )
            stop_reason = "partial_completed"
    elif decision.action == "fix_blocker":
        blocker = roundtable.get("blocker") or packet.get("primary_blocker", "unknown")
        remaining_scope.append(
            {
                "item_id": "fix_blocker_1",
                "description": f"Resolve blocker: {blocker}",
                "status": "blocked",
                "metadata": {
                    "blocker_type": blocker,
                    "completion_criteria": roundtable.get("completion_criteria", ""),
                },
            }
        )
        stop_reason = "blocked"
    elif decision.action == "abort":
        stop_reason = "failed"
    
    # 如果 packet incomplete，添加 remaining scope
    if not validation.get("complete"):
        missing_fields = validation.get("missing_fields", [])
        for field in missing_fields[:3]:
            remaining_scope.append(
                {
                    "item_id": f"missing_{field.replace('.', '_')}",
                    "description": f"Fill missing field: {field}",
                    "status": "not_started",
                    "metadata": {"field_type": "packet_completeness"},
                }
            )
        if stop_reason == "completed_all":
            stop_reason = "partial_completed"
    
    # 构建 generic closeout contract
    closeout = build_partial_closeout(
        completed_scope=completed_scope,
        remaining_scope=remaining_scope,
        stop_reason=stop_reason,
        original_batch_id=batch_id,
        metadata={
            "decision_action": decision.action,
            "decision_reason": decision.reason,
        },
    )
    
    # 适配 trading 场景
    adapted_closeout = adapt_closeout_for_trading(
        closeout=closeout,
        packet=packet,
        roundtable=roundtable,
    )
    
    return adapted_closeout


def _generate_next_registrations_for_trading(
    closeout: PartialCloseoutContract,
    batch_id: str,
) -> List[Dict[str, Any]]:
    """生成 next task registration payloads"""
    if not closeout.should_generate_next_registration():
        return []
    
    registrations = generate_registered_registrations_for_closeout(
        closeout=closeout,
        adapter=ADAPTER_NAME,
        scenario=SCENARIO,
        max_candidates=3,
        context={
            "batch_id": batch_id,
            "generated_by": "trading_roundtable_partial_continuation_v2",
        },
        auto_register=True,
        batch_id=batch_id,
        owner=closeout.metadata.get("trading_roundtable", {}).get("owner"),
    )
    
    return [reg.to_dict() for reg in registrations]


def _persist_decision(batch_id: str, decision: Decision, summary_path: Path) -> Path:
    """持久化 decision 到文件"""
    decision_id = decision.decision_id or _new_id("dec", batch_id)
    decision.decision_id = decision_id
    payload = {
        "decision_id": decision_id,
        "batch_id": batch_id,
        "scenario": SCENARIO,
        "adapter": ADAPTER_NAME,
        "timestamp": _iso_now(),
        **decision.to_dict(),
        "artifacts": {
            "summary_path": str(summary_path),
        },
    }
    decision_path = _decision_file(decision_id)
    _atomic_json_write(decision_path, payload)
    return decision_path


def _mark_batch_terminal(batch_id: str, triggered: bool) -> None:
    for task in get_batch_tasks(batch_id):
        if triggered:
            mark_next_dispatched(task["task_id"], task.get("next_task_ids", []))
        else:
            mark_final_closed(task["task_id"])


# ============== 主入口函数 ==============


def process_trading_roundtable_callback(
    *,
    batch_id: str,
    task_id: str,
    result: Dict[str, Any],
    allow_auto_dispatch: Optional[bool] = None,
    runtime: str = "subagent",
    backend: str = "subagent",
    requester_session_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process a trading roundtable callback using the existing orchestrator building blocks.

    Returns a structured dict so callers/tests can inspect the persisted chain.
    """
    _ensure_runtime_dirs()
    mark_callback_received(task_id, result)

    # Reconcile waiting anomalies
    reconciled_waiting_anomalies = reconcile_batch_waiting_anomalies(
        batch_id=batch_id,
        next_owner=str(
            result.get("trading_roundtable", {}).get("roundtable", {}).get("owner")
            or result.get("trading_roundtable", {}).get("packet", {}).get("owner")
            or "trading"
        ),
        next_step=(
            "inspect the dropped/failed leaf task, recover callback/report if possible, otherwise rerun it and refresh phase1 packet truth before reopening trading continuation"
        ),
        artifact_hint=result.get("trading_roundtable", {}).get("packet", {}).get("report", {}).get("path"),
    )

    # 检查 batch 是否完成
    if not is_batch_complete(batch_id):
        return {
            "status": "pending",
            "batch_id": batch_id,
            "task_id": task_id,
            "reason": "batch not complete yet",
            "reconciled_waiting_anomalies": reconciled_waiting_anomalies,
        }

    # 分析 batch 结果
    check_and_summarize_batch(batch_id)
    analysis = analyze_batch_results(batch_id)
    
    # 创建 trading adapter
    adapter = TradingAdapter()
    
    # 构建 decision
    decision = _build_decision(batch_id, analysis, adapter)
    
    # 解析 orchestration contract
    normalized_backend = backend if backend in ("subagent", "tmux") else "subagent"
    decision.metadata["orchestration_contract"] = resolve_orchestration_contract(
        result,
        default_adapter=ADAPTER_NAME,
        default_scenario=SCENARIO,
        batch_key=batch_id,
        default_owner=decision.metadata.get("roundtable", {}).get("owner") or decision.metadata.get("packet", {}).get("owner"),
        default_backend=normalized_backend,
    )
    
    # 构建 continuation plan（使用 adapter）
    continuation = adapter.build_continuation_plan(decision.to_dict(), analysis)
    
    # 评估 auto-dispatch readiness（使用 adapter）
    readiness = adapter.evaluate_auto_dispatch_readiness(decision.to_dict(), analysis, continuation)
    
    decision.metadata["continuation"] = continuation
    decision.metadata["default_auto_dispatch_readiness"] = readiness
    decision.metadata["dispatch_backend"] = normalized_backend

    # ========== Universal Partial-Continuation Kernel Integration ==========
    partial_closeout = _build_partial_closeout_for_trading(batch_id, decision)
    decision.metadata["partial_closeout"] = partial_closeout.to_dict()
    
    next_registrations = _generate_next_registrations_for_trading(partial_closeout, batch_id)
    decision.metadata["next_task_registrations"] = next_registrations
    # =======================================================================

    # 解析 allow_auto_dispatch
    if allow_auto_dispatch is not None:
        resolved_allow_auto_dispatch = allow_auto_dispatch
        auto_dispatch_source = "explicit"
    elif readiness.get("eligible"):
        resolved_allow_auto_dispatch = True
        auto_dispatch_source = "whitelist_default"
    else:
        resolved_allow_auto_dispatch = False
        auto_dispatch_source = "default_deny"

    # 构建 summary（使用 adapter）
    summary_path = _summary_file(batch_id)
    summary_text = adapter.build_summary(batch_id, analysis, decision.to_dict())
    summary_path.write_text(summary_text)
    
    # 持久化 decision
    decision_path = _persist_decision(batch_id, decision, summary_path)
    
    # 构建 dispatch plan（使用 dispatch_planner 模块）
    dispatch_id = _new_id("disp", batch_id)
    planner = DispatchPlanner()
    
    # 准备 dispatch planner 输入
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    
    dispatch_plan = planner.create_plan(
        dispatch_id=dispatch_id,
        batch_id=batch_id,
        scenario=SCENARIO,
        adapter=ADAPTER_NAME,
        decision_id=decision.decision_id,
        decision=decision.to_dict(),
        continuation=continuation,
        backend=DispatchBackend(normalized_backend),
        allow_auto_dispatch=resolved_allow_auto_dispatch,
        auto_dispatch_source=auto_dispatch_source,
        requester_session_key=requester_session_key,
        validation=validation,
        analysis=analysis,
        readiness=readiness,
        roundtable=roundtable,
        packet=packet,
    )
    
    # 添加额外的 safety gates 信息
    dispatch_plan.safety_gates.update({
        "default_auto_dispatch_eligible": readiness.get("eligible", False),
        "default_auto_dispatch_status": readiness.get("status"),
        "default_auto_dispatch_blockers": readiness.get("blockers", []),
        "default_auto_dispatch_criteria": readiness.get("criteria", []),
        "default_auto_dispatch_gate_truth_issues": readiness.get("gate_truth_issues", []),
        "default_auto_dispatch_artifact_truth_issues": readiness.get("artifact_truth_issues", []),
        "default_auto_dispatch_upgrade_requirements": readiness.get("upgrade_requirements", []),
        # Additional fields expected by tests
        "allow_auto_dispatch": resolved_allow_auto_dispatch,
        "auto_dispatch_source": auto_dispatch_source,
        "requested_backend": normalized_backend,
        "supported_backends": ["subagent", "tmux"],
        "runtime_must_be_subagent_for_subagent_backend": True,
        "allowed_decisions": ["proceed", "retry"],
        "business_terminal_source": "canonical_callback",
        "backend_terminal_role": "diagnostic_only",
        "packet_complete": validation.get("complete", False),
        "roundtable_conclusion": roundtable.get("conclusion"),
        "batch_success_rate": analysis.get("success_rate", 0),
        "batch_failed_count": int(analysis.get("failed") or 0),
        "batch_timeout_count": int(analysis.get("timeout") or 0),
    })
    
    # 构建 followup prompt 并添加到 recommended_spawn
    followup_prompt = adapter.build_followup_prompt(batch_id, decision.to_dict(), summary_path)
    
    # 添加 canonical callback 信息
    dispatch_plan_data = dispatch_plan.to_dict()
    dispatch_plan_data["recommended_spawn"]["task"] = followup_prompt
    dispatch_plan_data["canonical_callback"] = {
        "required": True,
        "business_terminal_source": "scripts/orchestrator_callback_bridge.py complete",
        "callback_payload_schema": decision.metadata.get("orchestration_contract", {}).get("callback_payload_schema") or "trading_roundtable.v1.callback",
        "callback_envelope_schema": CANONICAL_CALLBACK_ENVELOPE_VERSION,
        "backend_terminal_role": "diagnostic_only",
        "report_role": "evidence_only_until_callback",
    }
    
    # 持久化 dispatch plan
    dispatch_path = _dispatch_plan_file(dispatch_id)
    _atomic_json_write(dispatch_path, dispatch_plan_data)
    
    dispatch_info = {
        "dispatch_path": str(dispatch_path),
        "dispatch_plan": dispatch_plan_data,
        "decision_path": str(decision_path),
    }

    # 标记 batch terminal 状态
    triggered = dispatch_plan_data["status"] == "triggered"
    if triggered:
        next_task_id = f"tsk_{batch_id}_next"
        for task in get_batch_tasks(batch_id):
            state = get_state(task["task_id"])
            if state is None:
                continue
            state_path = STATE_DIR / f"{task['task_id']}.json"
            state["next_task_ids"] = [next_task_id]
            _atomic_json_write(state_path, state)
    _mark_batch_terminal(batch_id, triggered=triggered)

    # 发送 completion ack
    ack_result = send_roundtable_completion_ack(
        batch_id=batch_id,
        decision=decision,
        summary_path=summary_path,
        dispatch_info=dispatch_info,
        requester_session_key=requester_session_key,
        adapter_name=ADAPTER_NAME,
        scenario=SCENARIO,
    )

    return {
        "status": "processed",
        "batch_id": batch_id,
        "task_id": task_id,
        "summary_path": str(summary_path),
        "decision_path": str(decision_path),
        "reconciled_waiting_anomalies": reconciled_waiting_anomalies,
        "ack_result": ack_result,
        # Universal Partial-Continuation Kernel outputs
        "partial_closeout": partial_closeout.to_dict(),
        "next_task_registrations": next_registrations,
        "has_remaining_work": partial_closeout.has_remaining_work(),
        **dispatch_info,
    }
