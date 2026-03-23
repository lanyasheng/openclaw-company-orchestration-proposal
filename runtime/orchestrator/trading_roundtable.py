#!/usr/bin/env python3
"""
trading_roundtable.py — Trading Roundtable Continuation (Phase Engine Architecture)

重构版本：使用 Phase Engine 架构，从 1324 行精简到 ~500 行。

核心变化：
- 使用 adapters.trading.TradingAdapter 处理 trading 特定逻辑
- 使用 core.dispatch_planner.DispatchPlanner 生成调度计划
- 使用 core.quality_gate 预定义检查
- 保持与原有 API 完全兼容

默认策略：safe semi-auto
- 总是持久化 summary / decision / dispatch plan
- 默认只对白名单的 clean PASS continuation 自动续跑，其余仍保持 skipped
- 显式 allow_auto_dispatch 仍优先于默认值
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 核心模块
from adapters.trading import TradingAdapter, ADAPTER_NAME, SCENARIO
from core.dispatch_planner import DispatchPlanner, DispatchBackend, DispatchStatus
from core.quality_gate import (
    check_packet_completeness,
    check_artifact_truth,
    check_gate_consistency,
    check_batch_health,
    check_decision_action,
)

# 现有模块（保持不变）
from batch_aggregator import analyze_batch_results, check_and_summarize_batch
from completion_ack_guard import send_roundtable_completion_ack
from continuation_backends import normalize_dispatch_backend
from contracts import CANONICAL_CALLBACK_ENVELOPE_VERSION, resolve_orchestration_contract
from orchestrator import Decision, DECISIONS_DIR, DISPATCHES_DIR, _ensure_dirs
from partial_continuation import (
    build_partial_closeout,
    adapt_closeout_for_trading,
    generate_registered_registrations_for_closeout,
    ScopeItem,
)
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

# 定义 SUMMARYS_DIR
SUMMARYS_DIR = STATE_DIR.parent / "orchestrator" / "summaries"

from waiting_guard import reconcile_batch_waiting_anomalies

# 初始化适配器和规划器
_adapter = TradingAdapter()
_planner = DispatchPlanner()


def _ensure_runtime_dirs() -> None:
    """确保运行时目录存在"""
    _ensure_dirs()
    SUMMARYS_DIR.mkdir(parents=True, exist_ok=True)


def _summary_file(batch_id: str) -> Path:
    """获取 summary 文件路径"""
    return SUMMARYS_DIR / f"batch-{batch_id}-summary.md"


def _atomic_json_write(file_path: Path, payload: Dict[str, Any]) -> None:
    """原子写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_file, "w") as handle:
        json.dump(payload, handle, indent=2)
    tmp_file.replace(file_path)


def _merge_first_non_empty(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """合并非空值"""
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
    """从 batch 任务中提取 payloads"""
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
        
        supporting_results.append({
            "task_id": task["task_id"],
            "state": task.get("state"),
            "verdict": result.get("verdict"),
            "summary": result.get("summary") or scoped.get("summary"),
            "error": result.get("error"),
            "waiting_guard": waiting_guard or None,
            "closeout": closeout if isinstance(closeout, dict) else None,
        })

    return {
        "packet": packet,
        "roundtable": roundtable,
        "supporting_results": supporting_results,
    }


def _decision_from_payload(batch_id: str, analysis: Dict[str, Any]) -> Decision:
    """从 payload 构建 decision"""
    payloads = _extract_payloads(batch_id)
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    
    # 使用适配器验证 packet
    validation = _adapter.validate_packet(packet, roundtable)
    
    # 确定 action
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


def _build_partial_closeout_for_trading(
    batch_id: str,
    decision: Decision,
    analysis: Dict[str, Any],
) -> Any:
    """构建 trading partial closeout"""
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    supporting_results = decision.metadata.get("supporting_results", [])
    
    # 构建 completed_scope
    completed_scope = []
    for item in supporting_results:
        if item.get("state") in ("callback_received", "final_closed", "next_task_dispatched"):
            completed_scope.append(
                ScopeItem(
                    item_id=item.get("task_id", ""),
                    description=f"Task {item.get('task_id', '')}: {item.get('summary') or item.get('verdict') or 'completed'}",
                    status="completed",
                    metadata={"state": item.get("state"), "verdict": item.get("verdict")},
                )
            )
    
    # 构建 remaining_scope
    remaining_scope = []
    stop_reason = "completed_all"
    
    if decision.action == "proceed":
        next_step = roundtable.get("next_step", "")
        if next_step:
            remaining_scope.append(
                ScopeItem(
                    item_id="next_step_1",
                    description=next_step,
                    status="not_started",
                    metadata={
                        "completion_criteria": roundtable.get("completion_criteria", ""),
                        "blocker": "none",
                    },
                )
            )
            stop_reason = "partial_completed"
    elif decision.action == "fix_blocker":
        blocker = roundtable.get("blocker") or packet.get("primary_blocker", "unknown")
        remaining_scope.append(
            ScopeItem(
                item_id="fix_blocker_1",
                description=f"Resolve blocker: {blocker}",
                status="blocked",
                metadata={
                    "blocker_type": blocker,
                    "completion_criteria": roundtable.get("completion_criteria", ""),
                },
            )
        )
        stop_reason = "blocked"
    elif decision.action == "abort":
        stop_reason = "failed"
    
    # 如果 packet incomplete，添加 remaining scope
    if not validation.get("complete"):
        missing_fields = validation.get("missing_fields", [])
        for field in missing_fields[:3]:
            remaining_scope.append(
                ScopeItem(
                    item_id=f"missing_{field.replace('.', '_')}",
                    description=f"Fill missing field: {field}",
                    status="not_started",
                    metadata={"field_type": "packet_completeness"},
                )
            )
        if stop_reason == "completed_all":
            stop_reason = "partial_completed"
    
    # 构建 generic closeout
    closeout = build_partial_closeout(
        completed_scope=[item.to_dict() for item in completed_scope],
        remaining_scope=[item.to_dict() for item in remaining_scope],
        stop_reason=stop_reason,
        original_batch_id=batch_id,
        metadata={
            "decision_action": decision.action,
            "decision_reason": decision.reason,
        },
    )
    
    # 适配 trading 场景
    return adapt_closeout_for_trading(closeout=closeout, packet=packet, roundtable=roundtable)


def _generate_next_registrations_for_trading(closeout: Any, batch_id: str) -> List[Dict[str, Any]]:
    """为 trading 生成 next task registrations"""
    if not hasattr(closeout, 'should_generate_next_registration') or not closeout.should_generate_next_registration():
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


def _resolve_allow_auto_dispatch(
    readiness: Dict[str, Any], allow_auto_dispatch: Optional[bool]
) -> tuple[bool, str]:
    """解析 allow_auto_dispatch"""
    if allow_auto_dispatch is not None:
        return allow_auto_dispatch, "explicit"
    if readiness.get("eligible"):
        return True, "whitelist_default"
    return False, "default_deny"


def _decision_file(decision_id: str) -> Path:
    """获取 decision 文件路径"""
    return DECISIONS_DIR / f"{decision_id}.json"


def _dispatch_plan_file(dispatch_id: str) -> Path:
    """获取 dispatch plan 文件路径"""
    return DISPATCHES_DIR / f"{dispatch_id}.json"


def _new_id(prefix: str, batch_id: str) -> str:
    """生成新 ID"""
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return f"{prefix}_{safe_batch_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _persist_decision(batch_id: str, decision: Decision, summary_path: Path) -> Path:
    """持久化 decision"""
    decision_id = decision.decision_id or _new_id("dec", batch_id)
    decision.decision_id = decision_id
    
    payload = {
        "decision_id": decision_id,
        "batch_id": batch_id,
        "scenario": SCENARIO,
        "adapter": ADAPTER_NAME,
        "timestamp": _iso_now(),
        **decision.to_dict(),
        "artifacts": {"summary_path": str(summary_path)},
    }
    
    decision_path = _decision_file(decision_id)
    _atomic_json_write(decision_path, payload)
    return decision_path


def _mark_batch_terminal(batch_id: str, triggered: bool) -> None:
    """标记 batch 终端状态"""
    for task in get_batch_tasks(batch_id):
        if triggered:
            mark_next_dispatched(task["task_id"], task.get("next_task_ids", []))
        else:
            mark_final_closed(task["task_id"])


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
    处理 trading roundtable callback（Phase Engine 架构）
    
    主入口函数，使用 TradingAdapter 和 DispatchPlanner。
    """
    _ensure_runtime_dirs()
    mark_callback_received(task_id, result)
    
    # 处理 waiting anomalies
    reconciled_waiting_anomalies = reconcile_batch_waiting_anomalies(
        batch_id=batch_id,
        next_owner=str(
            result.get("trading_roundtable", {}).get("roundtable", {}).get("owner")
            or result.get("trading_roundtable", {}).get("packet", {}).get("owner")
            or "trading"
        ),
        next_step="inspect the dropped/failed leaf task, recover callback/report if possible",
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
    
    # 构建 decision
    decision = _decision_from_payload(batch_id, analysis)
    normalized_backend = normalize_dispatch_backend(backend)
    
    # 解析编排契约
    decision.metadata["orchestration_contract"] = resolve_orchestration_contract(
        result,
        default_adapter=ADAPTER_NAME,
        default_scenario=SCENARIO,
        batch_key=batch_id,
        default_owner=decision.metadata.get("roundtable", {}).get("owner") or decision.metadata.get("packet", {}).get("owner"),
        default_backend=normalized_backend,
    )
    
    # 使用适配器构建 continuation plan
    continuation = _adapter.build_continuation_plan(decision.to_dict(), analysis)
    
    # 使用适配器评估 auto-dispatch readiness
    readiness = _adapter.evaluate_auto_dispatch_readiness(
        decision.to_dict(), analysis, continuation
    )
    
    decision.metadata["continuation"] = continuation
    decision.metadata["default_auto_dispatch_readiness"] = readiness
    decision.metadata["dispatch_backend"] = normalized_backend
    
    # 构建 partial closeout
    partial_closeout = _build_partial_closeout_for_trading(batch_id, decision, analysis)
    decision.metadata["partial_closeout"] = partial_closeout.to_dict()
    
    # 生成 next task registrations
    next_registrations = _generate_next_registrations_for_trading(partial_closeout, batch_id)
    decision.metadata["next_task_registrations"] = next_registrations
    
    # 解析 allow_auto_dispatch
    resolved_allow_auto_dispatch, auto_dispatch_source = _resolve_allow_auto_dispatch(
        readiness, allow_auto_dispatch
    )
    
    # 构建并保存 summary
    summary_path = _summary_file(batch_id)
    summary_content = _adapter.build_summary(batch_id, analysis, decision.to_dict())
    summary_path.write_text(summary_content)
    
    # 持久化 decision
    decision_path = _persist_decision(batch_id, decision, summary_path)
    
    # 使用 DispatchPlanner 创建调度计划
    dispatch_backend = DispatchBackend.SUBAGENT if normalized_backend == "subagent" else DispatchBackend.TMUX
    
    dispatch_plan = _planner.create_plan(
        dispatch_id=_new_id("disp", batch_id),
        batch_id=batch_id,
        scenario=SCENARIO,
        adapter=ADAPTER_NAME,
        decision_id=decision.decision_id,
        decision=decision.to_dict(),
        continuation=continuation,
        backend=dispatch_backend,
        allow_auto_dispatch=resolved_allow_auto_dispatch,
        auto_dispatch_source=auto_dispatch_source,
        requester_session_key=requester_session_key,
        validation=decision.metadata.get("packet_validation"),
        analysis=analysis,
        readiness=readiness,
        roundtable=decision.metadata.get("roundtable"),
        packet=decision.metadata.get("packet"),
    )
    
    # 保存 dispatch plan
    dispatch_path = _dispatch_plan_file(dispatch_plan.dispatch_id)
    _atomic_json_write(dispatch_path, dispatch_plan.to_dict())
    
    # 标记 batch 终端状态
    triggered = dispatch_plan.status == DispatchStatus.TRIGGERED
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
        dispatch_info={
            "dispatch_path": str(dispatch_path),
            "decision_path": str(decision_path),
            "dispatch_plan": dispatch_plan.to_dict(),
        },
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
        "dispatch_path": str(dispatch_path),
        "reconciled_waiting_anomalies": reconciled_waiting_anomalies,
        "ack_result": ack_result,
        "partial_closeout": partial_closeout.to_dict(),
        "next_task_registrations": next_registrations,
        "has_remaining_work": partial_closeout.has_remaining_work(),
        "dispatch_plan": dispatch_plan.to_dict(),
    }
