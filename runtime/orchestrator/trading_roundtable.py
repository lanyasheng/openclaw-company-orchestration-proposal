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
from typing import Any, Dict, List, Optional, Tuple

from batch_aggregator import analyze_batch_results, check_and_summarize_batch
from completion_ack_guard import send_roundtable_completion_ack
from continuation_backends import build_backend_plan, build_timeout_policy, normalize_dispatch_backend
from contracts import CANONICAL_CALLBACK_ENVELOPE_VERSION, resolve_orchestration_contract
from orchestrator import Decision, DECISIONS_DIR, DISPATCHES_DIR, _ensure_dirs
from partial_continuation import (
    build_partial_closeout,
    adapt_closeout_for_trading,
    generate_next_registrations_for_closeout,
    ScopeItem,
    PartialCloseoutContract,
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
from waiting_guard import reconcile_batch_waiting_anomalies

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

ROUNDTABLE_REQUIRED_FIELDS = [
    "conclusion",
    "blocker",
    "owner",
    "next_step",
    "completion_criteria",
]
TOP_LEVEL_PACKET_REQUIRED_FIELDS = [
    "packet_version",
    "phase_id",
    "candidate_id",
    "run_label",
    "input_config_path",
    "generated_at",
    "owner",
    "overall_gate",
    "primary_blocker",
]
ARTIFACT_REQUIRED_FIELDS = [
    ("artifact", "path"),
    ("artifact", "exists"),
    ("report", "path"),
    ("report", "exists"),
    ("commit", "repo"),
    ("commit", "git_commit"),
    ("test", "commands"),
    ("test", "summary"),
    ("repro", "commands"),
    ("repro", "notes"),
]
TRADABILITY_REQUIRED_FIELDS = [
    ("tradability", "annual_turnover"),
    ("tradability", "liquidity_flags"),
    ("tradability", "gross_return"),
    ("tradability", "net_return"),
    ("tradability", "benchmark_return"),
    ("tradability", "scenario_verdict"),
    ("tradability", "turnover_failure_reasons"),
    ("tradability", "liquidity_failure_reasons"),
    ("tradability", "net_vs_gross_failure_reasons"),
    ("tradability", "summary"),
]
DEFAULT_AUTO_DISPATCH_ALLOWED_CONTINUATION_MODES = {
    "advance_phase_handoff",
}


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


def _missing_nested_fields(payload: Dict[str, Any], required_fields: List[Tuple[str, str]]) -> List[str]:
    missing = []
    for parent, child in required_fields:
        parent_value = payload.get(parent)
        if not isinstance(parent_value, dict) or child not in parent_value:
            missing.append(f"{parent}.{child}")
            continue
        value = parent_value.get(child)
        if value in (None, ""):
            missing.append(f"{parent}.{child}")
    return missing


def _validate_packet(packet: Dict[str, Any], roundtable: Dict[str, Any]) -> Dict[str, Any]:
    missing_packet_fields = [
        field for field in TOP_LEVEL_PACKET_REQUIRED_FIELDS if packet.get(field) in (None, "")
    ]
    missing_roundtable_fields = [
        field for field in ROUNDTABLE_REQUIRED_FIELDS if roundtable.get(field) in (None, "")
    ]
    missing_artifact_fields = _missing_nested_fields(packet, ARTIFACT_REQUIRED_FIELDS)
    missing_tradability_fields = _missing_nested_fields(packet, TRADABILITY_REQUIRED_FIELDS)

    version_ok = packet.get("packet_version") in (None, PACKET_VERSION) and (
        not packet.get("packet_version") or packet.get("packet_version") == PACKET_VERSION
    )
    phase_ok = packet.get("phase_id") in (None, PHASE_ID) and (
        not packet.get("phase_id") or packet.get("phase_id") == PHASE_ID
    )

    all_missing = [
        *missing_packet_fields,
        *missing_roundtable_fields,
        *missing_artifact_fields,
        *missing_tradability_fields,
    ]
    if not version_ok:
        all_missing.append("packet_version!=trading_phase1_packet_v1")
    if not phase_ok:
        all_missing.append("phase_id!=trading_phase1")

    return {
        "complete": len(all_missing) == 0,
        "missing_fields": all_missing,
        "missing_packet_fields": missing_packet_fields,
        "missing_roundtable_fields": missing_roundtable_fields,
        "missing_artifact_fields": missing_artifact_fields,
        "missing_tradability_fields": missing_tradability_fields,
    }


def _artifact_truth_issues(packet: Dict[str, Any]) -> List[str]:
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

    return issues


def _gate_consistency_issues(packet: Dict[str, Any], roundtable: Dict[str, Any]) -> List[str]:
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

    return issues


def _decision_from_payload(batch_id: str, analysis: Dict[str, Any]) -> Decision:
    payloads = _extract_payloads(batch_id)
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    validation = _validate_packet(packet, roundtable)

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
    analysis: Dict[str, Any],
) -> PartialCloseoutContract:
    """
    基于 trading roundtable decision 构建 generic partial closeout contract。
    
    这是通用 kernel 与 trading 场景的接缝：把 trading-specific decision
    转换成通用 partial closeout contract，供后续 auto-replan / registration 使用。
    
    返回：PartialCloseoutContract（通用 contract，不绑定 trading）
    """
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    supporting_results = decision.metadata.get("supporting_results", [])
    
    # 构建 completed_scope: 已完成的任务
    completed_scope = []
    for item in supporting_results:
        if item.get("state") in ("callback_received", "final_closed", "next_task_dispatched"):
            completed_scope.append(
                ScopeItem(
                    item_id=item.get("task_id", ""),
                    description=f"Task {item.get('task_id', '')}: {item.get('summary') or item.get('verdict') or 'completed'}",
                    status="completed",
                    metadata={
                        "state": item.get("state"),
                        "verdict": item.get("verdict"),
                    },
                )
            )
    
    # 构建 remaining_scope: 基于 decision 推导
    remaining_scope = []
    stop_reason = "completed_all"
    
    if decision.action == "proceed":
        # PASS 且有 next_step -> partial_completed
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
        # 有 blocker 需要修复
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
        # 中止，但有 remaining work（只是不执行）
        stop_reason = "failed"
    elif decision.action == "retry":
        # 需要重试
        stop_reason = "partial_completed"
    
    # 如果 packet incomplete，添加 remaining scope
    if not validation.get("complete"):
        missing_fields = validation.get("missing_fields", [])
        for field in missing_fields[:3]:  # 限制数量
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
    
    # 构建 generic closeout contract
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
    """
    为 trading roundtable 生成 next task registration payloads with status（v2）。
    
    这是 v2 升级：使用 generate_registered_registrations_for_closeout
    把 registration payload 变成真实注册记录（可落盘到 task registry）。
    
    返回：NextTaskRegistrationWithStatus.to_dict() 列表
    """
    if not closeout.should_generate_next_registration():
        return []
    
    # 使用 v2 API：generate_registered_registrations_for_closeout
    # 这会自动注册到 task registry（如果 auto_register=True）
    registrations = generate_registered_registrations_for_closeout(
        closeout=closeout,
        adapter=ADAPTER_NAME,
        scenario=SCENARIO,
        max_candidates=3,
        context={
            "batch_id": batch_id,
            "generated_by": "trading_roundtable_partial_continuation_v2",
        },
        auto_register=True,  # v2: 自动注册到 task registry
        batch_id=batch_id,
        owner=closeout.metadata.get("trading_roundtable", {}).get("owner"),
    )
    
    return [reg.to_dict() for reg in registrations]


def _continuation_mode_from_next_step(next_step: str) -> str:
    text = next_step.lower()
    if "rerun" in text or "re-run" in text:
        return "artifact_rerun"
    if "freeze" in text and "packet" in text:
        return "packet_freeze"
    if "review" in text or "gate" in text:
        return "gate_review"
    return "advance_phase_handoff"


def _build_continuation_plan(decision: Decision, analysis: Dict[str, Any]) -> Dict[str, Any]:
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    blocker = str(roundtable.get("blocker") or packet.get("primary_blocker") or "unknown")
    next_step = str(roundtable.get("next_step") or "review the batch summary and continue the minimal next step")
    completion_criteria = str(
        roundtable.get("completion_criteria") or "produce the smallest verifiable continuation artifact"
    )

    timeout_count = int(analysis.get("timeout") or 0)
    failed_count = int(analysis.get("failed") or 0)
    missing_fields = validation.get("missing_fields") or []

    if timeout_count or failed_count:
        affected = [
            item["task_id"]
            for item in decision.metadata.get("supporting_results", [])
            if item.get("state") in {"timeout", "failed"}
        ]
        return {
            "mode": "artifact_rerun",
            "task_preview": "rerun timeout/failed artifacts, refresh packet truth paths, then re-open the gate review",
            "next_round_goal": "recover missing evidence from timeout/failed tasks before trusting the current trading verdict",
            "rationale": "batch contains timeout/failed tasks, so the next round must refresh evidence instead of pretending the packet is clean",
            "review_required": True,
            "required_actions": [
                f"rerun affected tasks: {', '.join(affected) if affected else 'timeout/failed tasks in this batch'}",
                "refresh artifact/report/test/repro truth paths in phase1 packet v1",
                "only reopen roundtable gate review after rerun evidence is attached",
            ],
            "completion_criteria": completion_criteria,
        }

    if missing_fields:
        return {
            "mode": "packet_freeze",
            "task_preview": "freeze phase1 packet v1 by backfilling missing truth fields before any further continuation",
            "next_round_goal": "turn the current roundtable output into a complete phase1 packet v1 with all required truth fields",
            "rationale": "packet/closure is incomplete, so the next actionable hop is packet freeze instead of broader follow-up",
            "review_required": True,
            "required_actions": [
                f"fill missing fields: {', '.join(missing_fields)}",
                "persist artifact/report/commit/test/repro truth paths in the frozen packet",
                "re-run gate review only after the packet is complete",
            ],
            "completion_criteria": completion_criteria,
        }

    inferred_mode = _continuation_mode_from_next_step(next_step)
    if decision.action == "proceed":
        return {
            "mode": inferred_mode,
            "task_preview": next_step,
            "next_round_goal": "freeze this passing gate and open exactly one minimal next-round trading continuation",
            "rationale": "roundtable gate passed, so the next hop should be a single minimal continuation with packet/gate truth carried forward",
            "review_required": inferred_mode != "advance_phase_handoff",
            "required_actions": [
                "freeze the accepted packet/gate record before any wider follow-up",
                "keep continuation scope to a single task with explicit artifact outputs",
                "persist updated packet/report paths in the final answer",
            ],
            "completion_criteria": completion_criteria,
        }

    if blocker == "tradability":
        return {
            "mode": inferred_mode if inferred_mode != "advance_phase_handoff" else "packet_freeze",
            "task_preview": next_step,
            "next_round_goal": "freeze tradability evidence and prepare a focused re-review instead of opening a broader new phase",
            "rationale": "tradability is still the blocker, so the next round must collect/freeze blocker evidence before another gate decision",
            "review_required": True,
            "required_actions": [
                "attach turnover/liquidity/net_vs_gross failure reasons to phase1 packet v1",
                "if a rerun is requested, link the new artifact/report/verdict to the same packet",
                "return with a narrow gate-review packet, not a wider architecture rewrite",
            ],
            "completion_criteria": completion_criteria,
        }

    return {
        "mode": inferred_mode if inferred_mode != "advance_phase_handoff" else "gate_review",
        "task_preview": next_step,
        "next_round_goal": "resolve the single named blocker and return with a smaller, more reviewable packet",
        "rationale": "the roundtable did not fully pass, so continuation stays focused on blocker repair + re-review",
        "review_required": True,
        "required_actions": [
            f"resolve blocker: {blocker}",
            "keep the scope to one blocker-oriented follow-up",
            "persist updated packet/report/decision truth in the return artifact",
        ],
        "completion_criteria": completion_criteria,
    }


def _evaluate_default_auto_dispatch_readiness(
    decision: Decision,
    analysis: Dict[str, Any],
    continuation: Dict[str, Any],
) -> Dict[str, Any]:
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    tradability = packet.get("tradability", {}) if isinstance(packet.get("tradability"), dict) else {}

    timeout_count = int(analysis.get("timeout") or 0)
    failed_count = int(analysis.get("failed") or 0)
    artifact_issues = _artifact_truth_issues(packet)
    gate_issues = _gate_consistency_issues(packet, roundtable)

    criteria = [
        {
            "name": "roundtable_conclusion_pass",
            "field": "roundtable.conclusion",
            "expected": "PASS",
            "actual": str(roundtable.get("conclusion") or "").upper() or "N/A",
            "passed": str(roundtable.get("conclusion") or "").upper() == "PASS",
        },
        {
            "name": "roundtable_blocker_none",
            "field": "roundtable.blocker",
            "expected": "none",
            "actual": str(roundtable.get("blocker") or "").lower() or "N/A",
            "passed": str(roundtable.get("blocker") or "").lower() == "none",
        },
        {
            "name": "packet_overall_gate_pass",
            "field": "packet.overall_gate",
            "expected": "PASS",
            "actual": str(packet.get("overall_gate") or "").upper() or "N/A",
            "passed": str(packet.get("overall_gate") or "").upper() == "PASS",
        },
        {
            "name": "packet_primary_blocker_none",
            "field": "packet.primary_blocker",
            "expected": "none",
            "actual": str(packet.get("primary_blocker") or "").lower() or "N/A",
            "passed": str(packet.get("primary_blocker") or "").lower() == "none",
        },
        {
            "name": "tradability_scenario_verdict_pass",
            "field": "packet.tradability.scenario_verdict",
            "expected": "PASS",
            "actual": str(tradability.get("scenario_verdict") or "").upper() or "N/A",
            "passed": str(tradability.get("scenario_verdict") or "").upper() == "PASS",
        },
        {
            "name": "batch_timeout_count_zero",
            "field": "batch.timeout",
            "expected": 0,
            "actual": timeout_count,
            "passed": timeout_count == 0,
        },
        {
            "name": "batch_failed_count_zero",
            "field": "batch.failed",
            "expected": 0,
            "actual": failed_count,
            "passed": failed_count == 0,
        },
        {
            "name": "truth_paths_complete",
            "field": "packet.artifact/report/test/repro truth paths",
            "expected": "complete + exists=true",
            "actual": "complete" if validation.get("complete") and not artifact_issues else "; ".join(
                [
                    *([f"missing_fields={','.join(validation.get('missing_fields') or [])}"] if validation.get("missing_fields") else []),
                    *artifact_issues,
                ]
            ) or "incomplete",
            "passed": bool(validation.get("complete")) and len(artifact_issues) == 0,
        },
        {
            "name": "continuation_mode_whitelisted",
            "field": "continuation.mode",
            "expected": "advance_phase_handoff",
            "actual": str(continuation.get("mode") or "N/A"),
            "passed": continuation.get("mode") in DEFAULT_AUTO_DISPATCH_ALLOWED_CONTINUATION_MODES,
        },
    ]

    blockers: List[str] = []
    upgrade_requirements: List[str] = []

    def add_blocker(code: str, requirement: str) -> None:
        if code not in blockers:
            blockers.append(code)
        if requirement not in upgrade_requirements:
            upgrade_requirements.append(requirement)

    if timeout_count > 0:
        add_blocker(
            "batch_has_timeout_tasks",
            "所有 timeout task 必须先 rerun 完并把新 artifact/report 真值回填到同一份 phase1 packet。",
        )
    if failed_count > 0:
        add_blocker(
            "batch_has_failed_tasks",
            "所有 failed task 必须先修复/重跑并回填证据，不能带着失败分支进入默认 auto。",
        )
    if not validation.get("complete"):
        add_blocker(
            "packet_incomplete",
            "phase1 packet v1 与 roundtable closure 5 字段必须完整，missing fields 归零。",
        )

    if artifact_issues:
        add_blocker(
            "artifact_truth_not_verified",
            "artifact/report/test/repro 真值必须完整且 exists=true，才能考虑默认 auto-dispatch。",
        )

    if gate_issues:
        add_blocker(
            "gate_truth_mismatch",
            "roundtable 结论与 packet overall_gate / primary_blocker / tradability verdict 必须一致。",
        )

    if decision.action != "proceed":
        add_blocker(
            f"decision_{decision.action}_requires_manual_gate",
            "只有 proceed 且 blocker=none 的 trading roundtable，才有资格讨论默认 auto-dispatch。",
        )

    if not criteria[0]["passed"]:
        add_blocker(
            "roundtable_not_pass",
            "默认 auto 仅适用于 PASS roundtable；CONDITIONAL/FAIL 仍保持人工 gate review。",
        )

    if not criteria[1]["passed"]:
        add_blocker(
            "roundtable_blocker_present",
            "roundtable blocker 必须为 none，且主 blocker 不再需要额外审议。",
        )

    if not criteria[2]["passed"]:
        add_blocker(
            "overall_gate_not_pass",
            "packet overall_gate 必须为 PASS，不能靠 roundtable 文案单独放行。",
        )

    if not criteria[3]["passed"]:
        add_blocker(
            "primary_blocker_present",
            "packet primary_blocker 必须为 none，不能把 blocker 带进默认 auto。",
        )

    if not criteria[4]["passed"]:
        add_blocker(
            "tradability_not_pass",
            "tradability.scenario_verdict 必须为 PASS；turnover/liquidity/net_vs_gross 不能残留硬失败。",
        )

    if not criteria[8]["passed"]:
        add_blocker(
            f"continuation_mode_{continuation.get('mode')}_not_whitelist_safe",
            "默认 auto 只适用于单步、低风险的 handoff；packet freeze / artifact rerun / gate review 仍需人工确认。",
        )

    eligible = len(blockers) == 0
    if eligible:
        upgrade_requirements = [
            "维持当前单步 continuation：freeze gate record -> open exactly one minimal next-round wiring task。",
            "继续限定为 subagent runtime + requester_session_key 存在 + 单轮不 fan-out。",
            "确认这条 continuation 不会触发真实交易执行，只是证据/编排层推进。",
        ]

    return {
        "eligible": eligible,
        "status": "eligible_for_default_whitelist" if eligible else "not_ready",
        "blockers": blockers,
        "upgrade_requirements": upgrade_requirements,
        "criteria": criteria,
        "gate_truth_issues": gate_issues,
        "artifact_truth_issues": artifact_issues,
    }


def _resolve_allow_auto_dispatch(
    readiness: Dict[str, Any], allow_auto_dispatch: Optional[bool]
) -> tuple[bool, str]:
    if allow_auto_dispatch is not None:
        return allow_auto_dispatch, "explicit"
    if readiness.get("eligible"):
        return True, "whitelist_default"
    return False, "default_deny"


def _build_trading_summary(batch_id: str, analysis: Dict[str, Any], decision: Decision) -> str:
    packet = decision.metadata.get("packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    tradability = packet.get("tradability", {}) if isinstance(packet.get("tradability"), dict) else {}
    continuation = decision.metadata.get("continuation", {})
    readiness = decision.metadata.get("default_auto_dispatch_readiness", {})
    dispatch_backend = decision.metadata.get("dispatch_backend", "subagent")
    timeout_policy = build_timeout_policy(dispatch_backend)

    lines = [
        f"# Trading Roundtable Continuation Summary — {batch_id}",
        "",
        f"- Generated: {_iso_now()}",
        f"- Adapter: {ADAPTER_NAME}",
        f"- Scenario: {SCENARIO}",
        f"- Batch Complete: {'yes' if analysis.get('is_complete') else 'no'}",
        f"- Success Rate: {analysis.get('success_rate', 0):.1%}",
        f"- Failed Tasks: {analysis.get('failed', 0)}",
        f"- Timeout Tasks: {analysis.get('timeout', 0)}",
        f"- Dispatch Backend: {dispatch_backend}",
        f"- timeout_total_seconds: {timeout_policy.get('timeout_total_seconds')}",
        f"- timeout_stall_seconds: {timeout_policy.get('timeout_stall_seconds')}",
        f"- stall_grace_seconds: {timeout_policy.get('stall_grace_seconds')}",
        f"- Decision: {decision.action}",
        f"- Reason: {decision.reason}",
        "",
        "## Roundtable Closure",
        "",
        f"- Conclusion: {roundtable.get('conclusion', 'N/A')}",
        f"- Blocker: {roundtable.get('blocker', 'N/A')}",
        f"- Owner: {roundtable.get('owner', 'N/A')}",
        f"- Next Step: {roundtable.get('next_step', 'N/A')}",
        f"- Completion Criteria: {roundtable.get('completion_criteria', 'N/A')}",
        "",
        "## Phase 1 Packet",
        "",
        f"- Packet Version: {packet.get('packet_version', 'N/A')}",
        f"- Phase ID: {packet.get('phase_id', 'N/A')}",
        f"- Candidate ID: {packet.get('candidate_id', 'N/A')}",
        f"- Run Label: {packet.get('run_label', 'N/A')}",
        f"- Overall Gate: {packet.get('overall_gate', 'N/A')}",
        f"- Primary Blocker: {packet.get('primary_blocker', 'N/A')}",
        f"- Packet Complete: {'yes' if validation.get('complete') else 'no'}",
        "",
        "## Tradability Snapshot",
        "",
        f"- annual_turnover: {tradability.get('annual_turnover', 'N/A')}",
        f"- scenario_verdict: {tradability.get('scenario_verdict', 'N/A')}",
        f"- turnover_failure_reasons: {tradability.get('turnover_failure_reasons', [])}",
        f"- liquidity_failure_reasons: {tradability.get('liquidity_failure_reasons', [])}",
        f"- net_vs_gross_failure_reasons: {tradability.get('net_vs_gross_failure_reasons', [])}",
        f"- summary: {tradability.get('summary', 'N/A')}",
        "",
        "## Continuation Plan",
        "",
        f"- Mode: {continuation.get('mode', 'N/A')}",
        f"- Task Preview: {continuation.get('task_preview', 'N/A')}",
        f"- Next-Round Goal: {continuation.get('next_round_goal', 'N/A')}",
        f"- Rationale: {continuation.get('rationale', 'N/A')}",
        f"- Review Required: {'yes' if continuation.get('review_required') else 'no'}",
        f"- Completion Criteria: {continuation.get('completion_criteria', 'N/A')}",
        "",
        "## Default Auto-Dispatch Readiness",
        "",
        f"- Eligible Now: {'yes' if readiness.get('eligible') else 'no'}",
        f"- Status: {readiness.get('status', 'N/A')}",
        f"- Blockers: {readiness.get('blockers', [])}",
        "",
        "## Runtime Bridge Inputs",
        "",
        f"- phase1_input_doc: {PHASE1_INPUT_DOC}",
        f"- closure_template_doc: {CLOSURE_TEMPLATE_DOC}",
        f"- followup_verdict_doc: {FOLLOWUP_VERDICT_DOC}",
        f"- followup_checklist_doc: {FOLLOWUP_CHECKLIST_DOC}",
        f"- packet_required_fields_doc: {PACKET_REQUIRED_FIELDS_DOC}",
        f"- phase_map_doc: {PHASE_MAP_DOC}",
        "",
        "## Business Terminal Contract",
        "",
        "- Business closeout source: canonical callback via scripts/orchestrator_callback_bridge.py complete",
        "- tmux STATUS / completion report role: diagnostic evidence only; not a roundtable business terminal",
    ]

    missing_fields = validation.get("missing_fields") or []
    if missing_fields:
        lines.extend(["", "## Missing Fields", ""])
        for field in missing_fields:
            lines.append(f"- {field}")

    required_actions = continuation.get("required_actions") or []
    if required_actions:
        lines.extend(["", "## Next-Round Required Actions", ""])
        for item in required_actions:
            lines.append(f"- {item}")

    readiness_criteria = readiness.get("criteria") or []
    if readiness_criteria:
        lines.extend(["", "## Default Auto-Dispatch Criteria", ""])
        for item in readiness_criteria:
            lines.append(
                f"- {item.get('field')}: expected={item.get('expected')} actual={item.get('actual')} passed={'yes' if item.get('passed') else 'no'}"
            )

    upgrade_requirements = readiness.get("upgrade_requirements") or []
    if upgrade_requirements:
        lines.extend(["", "## Upgrade Requirements For Default Auto", ""])
        for item in upgrade_requirements:
            lines.append(f"- {item}")

    lines.extend(["", "## Task Results", ""])
    for item in decision.metadata.get("supporting_results", []):
        closeout = item.get("closeout") if isinstance(item.get("closeout"), dict) else {}
        closeout_bits = []
        if closeout:
            closeout_bits.append(f"stopped_because={closeout.get('stopped_because') or 'N/A'}")
            closeout_bits.append(f"next_owner={closeout.get('next_owner') or 'N/A'}")
            closeout_bits.append(f"dispatch_readiness={closeout.get('dispatch_readiness') or 'N/A'}")
        suffix = f" closeout[{', '.join(closeout_bits)}]" if closeout_bits else ""
        lines.append(
            f"- {item.get('task_id')}: state={item.get('state')} verdict={item.get('verdict')} error={item.get('error') or 'N/A'} summary={item.get('summary') or 'N/A'}{suffix}"
        )

    return "\n".join(lines) + "\n"


def _build_manual_followup_prompt(batch_id: str, decision: Decision, summary_path: Path) -> str:
    roundtable = decision.metadata.get("roundtable", {})
    packet = decision.metadata.get("packet", {})
    continuation = decision.metadata.get("continuation", {})
    next_step = continuation.get("task_preview") or roundtable.get(
        "next_step"
    ) or "review the batch summary and continue the minimal next step"
    completion_criteria = continuation.get("completion_criteria") or roundtable.get(
        "completion_criteria"
    ) or "produce the smallest verifiable continuation artifact"

    prompt_lines = [
        "# Trading Roundtable Follow-up",
        "",
        f"Adapter: {ADAPTER_NAME}",
        f"Scenario: {SCENARIO}",
        f"Batch ID: {batch_id}",
        f"Decision: {decision.action}",
        f"Reason: {decision.reason}",
        f"Summary: {summary_path}",
        "",
        "Read these docs first:",
        f"- {PHASE1_INPUT_DOC}",
        f"- {CLOSURE_TEMPLATE_DOC}",
        f"- {FOLLOWUP_VERDICT_DOC}",
        f"- {FOLLOWUP_CHECKLIST_DOC}",
        f"- {PACKET_REQUIRED_FIELDS_DOC}",
        f"- {PHASE_MAP_DOC}",
        "",
        f"Candidate ID: {packet.get('candidate_id', 'N/A')}",
        f"Run Label: {packet.get('run_label', 'N/A')}",
        f"Primary Blocker: {packet.get('primary_blocker', roundtable.get('blocker', 'N/A'))}",
        f"Continuation Mode: {continuation.get('mode', 'N/A')}",
        f"Next-Round Goal: {continuation.get('next_round_goal', 'N/A')}",
        f"Review Required: {'yes' if continuation.get('review_required') else 'no'}",
        "",
        f"Next Step: {next_step}",
        f"Completion Criteria: {completion_criteria}",
        "",
        "Required actions:",
    ]

    for item in continuation.get("required_actions") or []:
        prompt_lines.append(f"- {item}")

    prompt_lines.extend(
        [
            "",
            "Rules:",
            "- Do not widen scope beyond the single next step above.",
            "- Reuse existing trading mainline artifacts; do not rewrite the engine.",
            "- Persist any updated packet/verdict/report paths in the final answer.",
            "- If you need rerun evidence, attach it back to the same phase1 packet instead of opening a parallel packet lineage.",
        ]
    )
    return "\n".join(prompt_lines)


def _dispatch_plan_file(dispatch_id: str) -> Path:
    return DISPATCHES_DIR / f"{dispatch_id}.json"


def _decision_file(decision_id: str) -> Path:
    return DECISIONS_DIR / f"{decision_id}.json"


def _new_id(prefix: str, batch_id: str) -> str:
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return f"{prefix}_{safe_batch_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _persist_decision(batch_id: str, decision: Decision, summary_path: Path) -> Path:
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


def _persist_dispatch_plan(
    *,
    batch_id: str,
    decision: Decision,
    decision_path: Path,
    summary_path: Path,
    allow_auto_dispatch: bool,
    auto_dispatch_source: str,
    runtime: str,
    backend: str,
    requester_session_key: Optional[str],
) -> Dict[str, Any]:
    dispatch_id = _new_id("disp", batch_id)
    prompt = _build_manual_followup_prompt(batch_id, decision, summary_path)
    validation = decision.metadata.get("packet_validation", {})
    roundtable = decision.metadata.get("roundtable", {})
    packet = decision.metadata.get("packet", {})
    continuation = decision.metadata.get("continuation", {})
    readiness = decision.metadata.get("default_auto_dispatch_readiness", {})
    analysis = decision.metadata.get("batch_analysis", {})
    backend = normalize_dispatch_backend(backend)

    skip_reasons: List[Dict[str, str]] = []
    status = "triggered"

    def skip(code: str, message: str) -> None:
        nonlocal status
        status = "skipped"
        skip_reasons.append({"code": code, "message": message})

    if backend == "subagent" and runtime != "subagent":
        skip(
            "runtime_not_subagent",
            f"runtime {runtime} is not eligible for backend=subagent; only subagent is allowed",
        )

    if not allow_auto_dispatch:
        if auto_dispatch_source == "explicit":
            skip(
                "auto_dispatch_explicitly_disabled",
                "allow_auto_dispatch was explicitly set to false, so this continuation stays manual",
            )
        else:
            skip(
                "trading_default_deny_manual_review",
                "trading remains safe semi-auto by default outside the clean PASS whitelist; manual confirmation is required before continuation",
            )

    if not validation.get("complete"):
        skip(
            "phase1_packet_incomplete",
            "phase1 packet or roundtable closure is incomplete",
        )

    timeout_count = int(analysis.get("timeout") or 0)
    if timeout_count > 0:
        affected = [
            item["task_id"]
            for item in decision.metadata.get("supporting_results", [])
            if item.get("state") == "timeout"
        ]
        skip(
            "batch_has_timeout_tasks",
            f"batch has {timeout_count} timeout task(s): {', '.join(affected) if affected else 'unknown timeout task'}",
        )

    failed_count = int(analysis.get("failed") or 0)
    if failed_count > 0:
        affected = [
            item["task_id"]
            for item in decision.metadata.get("supporting_results", [])
            if item.get("state") == "failed"
        ]
        skip(
            "batch_has_failed_tasks",
            f"batch has {failed_count} failed task(s): {', '.join(affected) if affected else 'unknown failed task'}",
        )

    artifact_issues = _artifact_truth_issues(packet)
    if artifact_issues:
        skip(
            "artifact_truth_not_verified",
            "artifact/report/test/repro truth is not fully verified: " + ", ".join(artifact_issues),
        )

    gate_issues = _gate_consistency_issues(packet, roundtable)
    if gate_issues:
        skip(
            "gate_truth_mismatch",
            "roundtable gate and packet truth disagree: " + "; ".join(gate_issues),
        )

    if decision.action not in {"proceed", "retry"}:
        skip(
            "decision_not_auto_dispatchable",
            f"decision {decision.action} is not auto-dispatchable",
        )

    if backend == "subagent" and allow_auto_dispatch and status == "triggered" and not requester_session_key:
        skip(
            "missing_requester_session_key",
            "missing requester_session_key for runtime wake-up",
        )

    reason = "; ".join(item["message"] for item in skip_reasons) if skip_reasons else (
        f"trading roundtable {decision.action} can continue via backend={backend}"
    )
    dispatch_path = _dispatch_plan_file(dispatch_id)
    timeout_policy = build_timeout_policy(backend)
    backend_plan = build_backend_plan(
        backend=backend,
        dispatch_id=dispatch_id,
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        scenario=SCENARIO,
        adapter=ADAPTER_NAME,
        workdir=Path.cwd(),
        task_preview=continuation.get("task_preview") or roundtable.get("next_step") or decision.reason,
    )

    orchestration_contract = decision.metadata.get("orchestration_contract") or {}
    payload = {
        "dispatch_id": dispatch_id,
        "batch_id": batch_id,
        "scenario": SCENARIO,
        "adapter": ADAPTER_NAME,
        "decision_id": decision.decision_id,
        "timestamp": _iso_now(),
        "status": status,
        "reason": reason,
        "backend": backend,
        "timeout_policy": timeout_policy,
        "backend_plan": backend_plan,
        "skip_reasons": skip_reasons,
        "continuation": continuation,
        "orchestration_contract": orchestration_contract,
        "canonical_callback": {
            "required": True,
            "business_terminal_source": "scripts/orchestrator_callback_bridge.py complete",
            "callback_payload_schema": orchestration_contract.get("callback_payload_schema") or "trading_roundtable.v1.callback",
            "callback_envelope_schema": CANONICAL_CALLBACK_ENVELOPE_VERSION,
            "backend_terminal_role": "diagnostic_only",
            "report_role": "evidence_only_until_callback",
        },
        "safety_gates": {
            "default_mode": "safe_semi_auto",
            "allow_auto_dispatch": allow_auto_dispatch,
            "auto_dispatch_source": auto_dispatch_source,
            "requested_backend": backend,
            "supported_backends": ["subagent", "tmux"],
            "runtime_must_be_subagent_for_subagent_backend": True,
            "allowed_decisions": ["proceed", "retry"],
            "business_terminal_source": "canonical_callback",
            "backend_terminal_role": "diagnostic_only",
            "packet_complete": validation.get("complete", False),
            "roundtable_conclusion": roundtable.get("conclusion"),
            "batch_success_rate": analysis.get("success_rate", 0),
            "batch_failed_count": failed_count,
            "batch_timeout_count": timeout_count,
            "default_auto_dispatch_eligible": readiness.get("eligible", False),
            "default_auto_dispatch_status": readiness.get("status"),
            "default_auto_dispatch_blockers": readiness.get("blockers", []),
            "default_auto_dispatch_criteria": readiness.get("criteria", []),
            "default_auto_dispatch_gate_truth_issues": readiness.get("gate_truth_issues", []),
            "default_auto_dispatch_artifact_truth_issues": readiness.get("artifact_truth_issues", []),
            "default_auto_dispatch_upgrade_requirements": readiness.get("upgrade_requirements", []),
        },
        "recommended_spawn": {
            "runtime": "subagent",
            "task_preview": continuation.get("task_preview") or roundtable.get("next_step") or decision.reason,
            "task": prompt,
        },
        "parent_message": None,
        "artifacts": {
            "batch_summary": str(summary_path),
            "decision_file": str(decision_path),
            "phase1_input_doc": PHASE1_INPUT_DOC,
            "closure_template_doc": CLOSURE_TEMPLATE_DOC,
            "followup_verdict_doc": FOLLOWUP_VERDICT_DOC,
            "followup_checklist_doc": FOLLOWUP_CHECKLIST_DOC,
            "packet_required_fields_doc": PACKET_REQUIRED_FIELDS_DOC,
            "phase_map_doc": PHASE_MAP_DOC,
        },
    }

    if status == "triggered":
        if backend == "subagent":
            payload["parent_message"] = "\n".join(
                [
                    f"🔁 AUTO_DISPATCH_REQUEST adapter={ADAPTER_NAME} scenario={SCENARIO} batch={batch_id} decision={decision.action} backend=subagent",
                    f"Read dispatch plan: {dispatch_path}",
                    'Execute exactly one sessions_spawn(runtime="subagent") using recommended_spawn from that file.',
                    "Roundtable closeout still depends on the canonical callback, not backend-local status alone.",
                    "Do not fan out further in this turn; this is a single-step continuation.",
                ]
            )
        else:
            payload["parent_message"] = "\n".join(
                [
                    f"🔁 AUTO_DISPATCH_REQUEST adapter={ADAPTER_NAME} scenario={SCENARIO} batch={batch_id} decision={decision.action} backend=tmux",
                    f"Read dispatch plan: {dispatch_path}",
                    f"Start observable tmux continuation with: {backend_plan['commands']['start']}",
                    f"Check live status with: {backend_plan['commands']['status']}",
                    "tmux STATUS/completion report are diagnostic only; roundtable advances only after the canonical callback is bridged.",
                    "Do not fan out further in this turn; this is a single-step continuation.",
                ]
            )

    _atomic_json_write(dispatch_path, payload)
    return {
        "dispatch_path": str(dispatch_path),
        "dispatch_plan": payload,
    }


def _mark_batch_terminal(batch_id: str, triggered: bool) -> None:
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
    Process a trading roundtable callback using the existing orchestrator building blocks.

    Returns a structured dict so callers/tests can inspect the persisted chain.
    """
    _ensure_runtime_dirs()
    mark_callback_received(task_id, result)

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

    if not is_batch_complete(batch_id):
        return {
            "status": "pending",
            "batch_id": batch_id,
            "task_id": task_id,
            "reason": "batch not complete yet",
            "reconciled_waiting_anomalies": reconciled_waiting_anomalies,
        }

    check_and_summarize_batch(batch_id)
    analysis = analyze_batch_results(batch_id)
    decision = _decision_from_payload(batch_id, analysis)
    normalized_backend = normalize_dispatch_backend(backend)
    decision.metadata["orchestration_contract"] = resolve_orchestration_contract(
        result,
        default_adapter=ADAPTER_NAME,
        default_scenario=SCENARIO,
        batch_key=batch_id,
        default_owner=decision.metadata.get("roundtable", {}).get("owner") or decision.metadata.get("packet", {}).get("owner"),
        default_backend=normalized_backend,
    )
    continuation = _build_continuation_plan(decision, analysis)
    readiness = _evaluate_default_auto_dispatch_readiness(decision, analysis, continuation)
    decision.metadata["continuation"] = continuation
    decision.metadata["default_auto_dispatch_readiness"] = readiness
    decision.metadata["dispatch_backend"] = normalized_backend

    # ========== Universal Partial-Continuation Kernel Integration ==========
    # 构建 generic partial closeout contract（不绑定 trading）
    partial_closeout = _build_partial_closeout_for_trading(batch_id, decision, analysis)
    decision.metadata["partial_closeout"] = partial_closeout.to_dict()
    
    # 生成 next task registration payloads（canonical artifact）
    next_registrations = _generate_next_registrations_for_trading(partial_closeout, batch_id)
    decision.metadata["next_task_registrations"] = next_registrations
    # =======================================================================

    resolved_allow_auto_dispatch, auto_dispatch_source = _resolve_allow_auto_dispatch(
        readiness,
        allow_auto_dispatch,
    )

    summary_path = _summary_file(batch_id)
    summary_path.write_text(_build_trading_summary(batch_id, analysis, decision))
    decision_path = _persist_decision(batch_id, decision, summary_path)
    dispatch_info = _persist_dispatch_plan(
        batch_id=batch_id,
        decision=decision,
        decision_path=decision_path,
        summary_path=summary_path,
        allow_auto_dispatch=resolved_allow_auto_dispatch,
        auto_dispatch_source=auto_dispatch_source,
        runtime=runtime,
        backend=normalized_backend,
        requester_session_key=requester_session_key,
    )
    dispatch_info["decision_path"] = str(decision_path)

    triggered = dispatch_info["dispatch_plan"]["status"] == "triggered"
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
