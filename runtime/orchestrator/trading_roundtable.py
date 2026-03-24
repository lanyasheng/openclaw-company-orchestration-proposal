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
from core.handoff_schema import (
    build_registration_handoff,
    build_execution_handoff,
    handoff_to_task_registration,
    handoff_to_dispatch_spawn,
)
from task_registration import register_from_handoff
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
    build_continuation_contract,
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
from closeout_tracker import (
    CloseoutTracker,
    create_closeout,
    ContinuationContract,
    _closeout_file,
    check_closeout_gate,
    CloseoutGateResult,
)

# 初始化适配器和规划器
_adapter = TradingAdapter()
_planner = DispatchPlanner()
_closeout_tracker = CloseoutTracker()


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


def _decision_from_payload(
    batch_id: str,
    analysis: Dict[str, Any],
    preflight_validation: Optional[Dict[str, Any]] = None,
) -> Decision:
    """
    从 payload 构建 decision
    
    Args:
        batch_id: 批次 ID
        analysis: batch 分析结果
        preflight_validation: P0-1 前置校验结果（可选）
    
    C2: 强校验逻辑
    - 缺关键 packet/roundtable 字段时，不允许 completed/PASS 混过去
    - empty-result（无 artifact/report/test summary）时硬拦截
    - 输出明确 blocked/error 状态，而不是静默接受
    """
    payloads = _extract_payloads(batch_id)
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    
    # 使用适配器验证 packet（完整验证）
    validation = _adapter.validate_packet(packet, roundtable)
    
    # P0-1: 如果有 preflight validation，合并到 validation metadata 中
    if preflight_validation:
        validation["preflight"] = preflight_validation
    
    # ========== C2: Empty-Result Hard Block ==========
    # 检查是否为 empty-result（无 artifact/report/test summary）
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


def _check_empty_result(packet: Dict[str, Any]) -> Optional[str]:
    """
    C2: 检查是否为 empty-result
    
    Empty result 定义：
    - 无 artifact path/exists
    - 无 report path/exists
    - 无 test commands/summary
    
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
    adapted = adapt_closeout_for_trading(closeout=closeout, packet=packet, roundtable=roundtable)
    
    # P0-1 Batch 3: Inject unified continuation contract into closeout metadata
    # Derive stopped_because from stop_reason and decision
    if decision.action == "proceed":
        stopped_because = "roundtable_gate_pass_continuation_ready"
    elif decision.action == "fix_blocker":
        stopped_because = f"roundtable_gate_conditional_blocker_{roundtable.get('blocker', 'unknown')}"
    elif decision.action == "abort":
        stopped_because = f"roundtable_gate_fail_blocker_{roundtable.get('blocker', 'unknown')}"
    else:
        stopped_because = f"decision_action_{decision.action}"
    
    # Derive next_step from roundtable or decision
    next_step = roundtable.get("next_step", "") or decision.reason
    
    # Derive next_owner from roundtable or packet
    next_owner = roundtable.get("owner", "") or packet.get("owner", "") or "trading"
    
    # Build and merge continuation contract
    continuation = build_continuation_contract(
        stopped_because=stopped_because,
        next_step=next_step,
        next_owner=next_owner,
        metadata={
            "decision_action": decision.action,
            "roundtable_conclusion": roundtable.get("conclusion", ""),
            "roundtable_blocker": roundtable.get("blocker", ""),
        },
    )
    continuation.merge_into_closeout(adapted)
    
    return adapted


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
    skip_closeout_gate: bool = False,
) -> Dict[str, Any]:
    """
    处理 trading roundtable callback（Phase Engine 架构）
    
    主入口函数，使用 TradingAdapter 和 DispatchPlanner。
    
    P0-1: Packet Schema 前置校验
    - 在 callback 处理的最早阶段进行 schema presence validation
    - 显式标记 incomplete 状态，避免等 closeout 才发现缺失
    
    P0-4 Batch 2: Closeout Gate Glue
    - 在 batch 开始前检查前一批的 closeout 状态
    - 如果前一批 closeout 未完成或 push 未执行，阻止继续
    - skip_closeout_gate=True 可跳过检查（用于测试/紧急修复）
    """
    _ensure_runtime_dirs()
    
    # ========== P0-4 Batch 2: Closeout Gate Glue ==========
    # 检查前一批 closeout 状态，决定是否允许当前 batch 继续
    if not skip_closeout_gate:
        gate_result: CloseoutGateResult = check_closeout_gate(
            batch_id=batch_id,
            scenario=SCENARIO,
            require_push_complete=True,  # trading 场景强制要求 push complete
        )
        
        if not gate_result.allowed:
            # Closeout gate 检查失败，阻止 batch 继续
            return {
                "status": "blocked_by_closeout_gate",
                "batch_id": batch_id,
                "task_id": task_id,
                "reason": gate_result.reason,
                "closeout_gate": gate_result.to_dict(),
            }
        
        # Closeout gate 检查通过，记录到返回结果
        closeout_gate_output = gate_result.to_dict()
    else:
        closeout_gate_output = {
            "allowed": True,
            "reason": "Closeout gate check skipped (skip_closeout_gate=True)",
        }
    # ========== End P0-4 Batch 2 ==========
    
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
    
    # ========== P0-1: Packet Schema Preflight Validation ==========
    # 在 batch complete 之后、decision 构建之前，进行前置校验
    # 提取 packet 和 roundtable 进行校验
    packet = result.get("trading_roundtable", {}).get("packet", {}) if isinstance(result.get("trading_roundtable"), dict) else {}
    roundtable = result.get("trading_roundtable", {}).get("roundtable", {}) if isinstance(result.get("trading_roundtable"), dict) else {}
    
    # 执行前置校验
    preflight_validation = _adapter.validate_packet_preflight(packet, roundtable)
    
    # 如果前置校验失败，显式标记 incomplete 状态
    # 注意：不阻断流程，但确保校验结果进入所有 downstream artifacts
    preflight_incomplete = not preflight_validation.get("complete", True)
    # ========== End P0-1 ==========
    
    # 分析 batch 结果
    check_and_summarize_batch(batch_id)
    analysis = analyze_batch_results(batch_id)
    
    # 构建 decision（传入 preflight validation 结果）
    decision = _decision_from_payload(batch_id, analysis, preflight_validation=preflight_validation)
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
    
    # P0-3 Batch 5: 注入 executor 信息 (owner/executor 解耦)
    # 从 roundtable/continuation 推导 execution_profile 和 executor
    roundtable = decision.metadata.get("roundtable", {})
    next_step = roundtable.get("next_step", "") or decision.reason
    
    # 默认 trading 场景使用 generic_subagent profile
    # 如果 next_step 包含 coding keywords，使用 coding profile
    execution_profile = "generic_subagent"
    coding_keywords = ["coding", "implementation", "refactor", "fix", "test-fix", "bugfix"]
    if any(kw in next_step.lower() for kw in coding_keywords):
        execution_profile = "coding"
    
    # 根据 profile 推导 executor
    executor = "claude_code" if execution_profile == "coding" else "subagent"
    
    decision.metadata["orchestration_contract"]["execution_profile"] = execution_profile
    decision.metadata["orchestration_contract"]["executor"] = executor
    
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
    
    # P0-2 Batch 2: 使用统一 handoff schema 生成 registration/execution handoff
    planning_handoff = dispatch_plan.to_planning_handoff()
    registration_handoff = build_registration_handoff(
        planning_handoff,
        batch_id=batch_id,
        registration_status=None,  # 从 safety_gates 推导
        ready_for_auto_dispatch=None,  # 从 safety_gates 推导
    )
    
    # P0-2 Batch 3: 实际注册任务到 task registry
    registration_record = register_from_handoff(registration_handoff)
    
    # 仅在 triggered 时构建 execution handoff
    execution_handoff = None
    if dispatch_plan.status == DispatchStatus.TRIGGERED:
        execution_handoff = build_execution_handoff(
            planning_handoff,
            runtime="subagent" if normalized_backend == "subagent" else "tmux",
            timeout_seconds=3600,
        )
    
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
    
    # P0-2 Batch 2: 准备 handoff schema 输出
    handoff_artifacts = {
        "planning_handoff": planning_handoff.to_dict(),
        "registration_handoff": registration_handoff.to_dict(),
    }
    if execution_handoff:
        handoff_artifacts["execution_handoff"] = execution_handoff.to_dict()
    
    # P0-2 Batch 3: 包含 registration record 信息
    registration_info = {
        "registration_id": registration_record.registration_id,
        "task_id": registration_record.task_id,
        "registration_status": registration_record.registration_status,
        "ready_for_auto_dispatch": registration_record.ready_for_auto_dispatch,
    }
    
    # ========== P0-4 Batch 1: Closeout Chain Fix ==========
    # 创建并 emit closeout artifact，显式标记 closeout 状态和 push_required
    # 这是最小可行修复，解决"batch 完成后 closeout 链路缺失"问题
    
    # 从 dispatch_plan 提取 continuation_contract
    continuation_contract = dispatch_plan.continuation_contract
    if not continuation_contract:
        # fallback: 从 continuation dict 构建
        continuation_contract = ContinuationContract(
            stopped_because=continuation.get("stopped_because", continuation.get("stop_reason", "batch_completed")),
            next_step=continuation.get("next_step", roundtable.get("next_step", "see dispatch plan")),
            next_owner=continuation.get("next_owner", roundtable.get("owner", "trading")),
            metadata={"source": "trading_roundtable_closeout_fix"},
        )
    
    # 创建 closeout artifact
    closeout_artifact = create_closeout(
        batch_id=batch_id,
        scenario=SCENARIO,
        continuation=continuation_contract,
        has_remaining_work=partial_closeout.has_remaining_work(),
        artifacts={
            "summary_path": str(summary_path),
            "decision_path": str(decision_path),
            "dispatch_path": str(dispatch_path),
        },
        metadata={
            "packet": decision.metadata.get("packet", {}),
            "roundtable": decision.metadata.get("roundtable", {}),
            "dispatch_plan_status": dispatch_plan.status.value,
            "closeout_source": "trading_roundtable_v1_closeout_fix",
        },
    )
    
    # 在返回结果中包含 closeout 状态
    closeout_status_output = {
        "closeout_id": closeout_artifact.closeout_id,
        "closeout_status": closeout_artifact.closeout_status,
        "push_required": closeout_artifact.push_required,
        "push_status": closeout_artifact.push_status,
        "closeout_path": str(_closeout_file(batch_id)),
        "continuation_contract": closeout_artifact.continuation_contract.to_dict(),
    }
    # ========== End P0-4 Batch 1 ==========
    
    # ========== P0-1: Packet Schema Preflight Validation Output ==========
    # 在返回结果中包含 preflight validation 状态
    preflight_output = {
        "preflight_status": preflight_validation.get("preflight_status", "unknown"),
        "preflight_complete": preflight_validation.get("complete", False),
        "preflight_missing_fields": preflight_validation.get("missing_fields", []),
        "checked_at": "callback_entry",
    }
    # ========== End P0-1 ==========
    
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
        "handoff_schema": handoff_artifacts,
        "registration": registration_info,
        # P0-4 Batch 1: Closeout chain fix output
        "closeout": closeout_status_output,
        # P0-4 Batch 2: Closeout gate glue output
        "closeout_gate": closeout_gate_output,
        # P0-1: Packet Schema Preflight Validation output
        "preflight_validation": preflight_output,
    }
