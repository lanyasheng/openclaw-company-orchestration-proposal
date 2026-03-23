#!/usr/bin/env python3
"""
Generic channel/thread roundtable continuation glue.

目标：在不做大 refactor 的前提下，把现有 state_machine / batch_aggregator /
orchestrator 的最小能力接到“其他频道 / 其他讨论线程”上。

默认策略：safe semi-auto
- 总是持久化 summary / decision / dispatch plan
- 默认仍然安全关闭，但允许对精确白名单频道/线程做默认放开
- 若调用方显式传入 allow_auto_dispatch，则显式值优先
- 自动续跑仍只对明确可推进决策开放（如 proceed / retry）

最小输入契约：
result.channel_roundtable = {
  "packet": {
    "packet_version": "channel_roundtable_v1",
    "scenario": "architecture_roundtable",
    "channel_id": "discord:channel:...",
    "channel_name": "temporal-vs-langgraph",
    "topic": "Temporal vs LangGraph runtime architecture discussion",
    "owner": "main",
    "generated_at": "2026-03-20T19:30:00+08:00"
  },
  "roundtable": {
    "conclusion": "PASS|CONDITIONAL|FAIL",
    "blocker": "none|<blocker>",
    "owner": "main",
    "next_step": "...",
    "completion_criteria": "..."
  }
}
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from batch_aggregator import analyze_batch_results, check_and_summarize_batch
from completion_ack_guard import send_roundtable_completion_ack
from continuation_backends import build_backend_plan, build_timeout_policy, normalize_dispatch_backend
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
from partial_continuation import build_continuation_contract

ADAPTER_NAME = "channel_roundtable"
PACKET_VERSION = "channel_roundtable_v1"
SUMMARYS_DIR = STATE_DIR.parent / "orchestrator" / "summaries"
CHANNEL_ONBOARDING_DOC = "docs/architecture/2026-03-20-runtime-integration.md"

ROUNDTABLE_REQUIRED_FIELDS = [
    "conclusion",
    "blocker",
    "owner",
    "next_step",
    "completion_criteria",
]
CHANNEL_PACKET_REQUIRED_FIELDS = [
    "packet_version",
    "scenario",
    "channel_id",
    "topic",
    "owner",
    "generated_at",
]

CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS = {
    "1483883339701158102",
}
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_SCENARIO = "current_channel_architecture_roundtable"
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_TOPIC = "Temporal vs LangGraph｜OpenClaw 公司级编排架构"
CURRENT_ARCHITECTURE_DEFAULT_ALLOW_OWNER = "main"


def _ensure_runtime_dirs() -> None:
    _ensure_dirs()
    SUMMARYS_DIR.mkdir(parents=True, exist_ok=True)


def _summary_file(batch_id: str) -> Path:
    return SUMMARYS_DIR / f"batch-{batch_id}-summary.md"


def _decision_file(decision_id: str) -> Path:
    return DECISIONS_DIR / f"{decision_id}.json"


def _dispatch_plan_file(dispatch_id: str) -> Path:
    return DISPATCHES_DIR / f"{dispatch_id}.json"


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
        scoped = result.get(ADAPTER_NAME) or result.get("generic_roundtable") or {}
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


def _validate_packet(packet: Dict[str, Any], roundtable: Dict[str, Any]) -> Dict[str, Any]:
    missing_packet_fields = [
        field for field in CHANNEL_PACKET_REQUIRED_FIELDS if packet.get(field) in (None, "")
    ]
    missing_roundtable_fields = [
        field for field in ROUNDTABLE_REQUIRED_FIELDS if roundtable.get(field) in (None, "")
    ]

    version_ok = packet.get("packet_version") in (None, PACKET_VERSION) and (
        not packet.get("packet_version") or packet.get("packet_version") == PACKET_VERSION
    )

    all_missing = [*missing_packet_fields, *missing_roundtable_fields]
    if not version_ok:
        all_missing.append("packet_version!=channel_roundtable_v1")

    return {
        "complete": len(all_missing) == 0,
        "missing_fields": all_missing,
        "missing_packet_fields": missing_packet_fields,
        "missing_roundtable_fields": missing_roundtable_fields,
    }


def _normalized_channel_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.split(":")[-1]


def _packet_matches_default_auto_dispatch_whitelist(packet: Dict[str, Any]) -> bool:
    channel_id = _normalized_channel_id(packet.get("channel_id"))
    scenario = str(packet.get("scenario") or "")
    topic = str(packet.get("topic") or "")
    owner = str(packet.get("owner") or "")

    if channel_id in CURRENT_ARCHITECTURE_DEFAULT_ALLOW_CHANNEL_IDS:
        return True

    return (
        scenario == CURRENT_ARCHITECTURE_DEFAULT_ALLOW_SCENARIO
        and topic == CURRENT_ARCHITECTURE_DEFAULT_ALLOW_TOPIC
        and owner == CURRENT_ARCHITECTURE_DEFAULT_ALLOW_OWNER
    )


def _resolve_allow_auto_dispatch(packet: Dict[str, Any], allow_auto_dispatch: Optional[bool]) -> tuple[bool, str]:
    if allow_auto_dispatch is not None:
        return allow_auto_dispatch, "explicit"
    if _packet_matches_default_auto_dispatch_whitelist(packet):
        return True, "whitelist_default"
    return False, "default_deny"


def _decision_from_payload(batch_id: str, analysis: Dict[str, Any]) -> Decision:
    payloads = _extract_payloads(batch_id)
    packet = payloads["packet"]
    roundtable = payloads["roundtable"]
    validation = _validate_packet(packet, roundtable)

    scenario = str(packet.get("scenario") or "channel_roundtable")
    conclusion = str(roundtable.get("conclusion") or "FAIL").upper()
    blocker = str(roundtable.get("blocker") or "unknown")
    next_step = str(roundtable.get("next_step") or "")
    completion_criteria = str(roundtable.get("completion_criteria") or "")

    if not validation["complete"]:
        action = "fix_blocker"
        reason = "channel roundtable packet or closure is incomplete"
    elif conclusion == "PASS" and blocker == "none":
        action = "proceed"
        reason = f"channel roundtable {scenario} is PASS and no blocker remains"
    elif conclusion == "CONDITIONAL":
        action = "fix_blocker"
        reason = f"channel roundtable {scenario} is CONDITIONAL with blocker={blocker}"
    elif conclusion == "FAIL":
        action = "abort"
        reason = f"channel roundtable {scenario} is FAIL with blocker={blocker}"
    else:
        action = "fix_blocker"
        reason = f"unrecognized channel roundtable conclusion={conclusion}"

    recommended_next_tasks: List[Dict[str, Any]] = []
    if action in {"proceed", "fix_blocker"} and next_step:
        recommended_next_tasks.append(
            {
                "type": "channel_roundtable_followup",
                "adapter": ADAPTER_NAME,
                "scenario": scenario,
                "next_step": next_step,
                "completion_criteria": completion_criteria,
                "blocker": blocker,
            }
        )

    metadata = {
        "adapter": ADAPTER_NAME,
        "scenario": scenario,
        "channel_packet": packet,
        "roundtable": roundtable,
        "packet_validation": validation,
        "batch_analysis": analysis,
        "supporting_results": payloads["supporting_results"],
    }
    
    # P0-1 Batch 3: Inject unified continuation contract into decision metadata
    # Derive stopped_because from action and conclusion
    if action == "proceed":
        stopped_because = "roundtable_gate_pass_continuation_ready"
    elif action == "fix_blocker":
        stopped_because = f"roundtable_gate_conditional_blocker_{blocker}"
    elif action == "abort":
        stopped_because = f"roundtable_gate_fail_blocker_{blocker}"
    else:
        stopped_because = f"decision_action_{action}"
    
    # Derive next_step from roundtable or decision reason
    derived_next_step = next_step or reason
    
    # Derive next_owner from roundtable or packet
    derived_next_owner = roundtable.get("owner", "") or packet.get("owner", "") or "main"
    
    # Build continuation contract and inject into metadata
    continuation = build_continuation_contract(
        stopped_because=stopped_because,
        next_step=derived_next_step,
        next_owner=derived_next_owner,
        metadata={
            "decision_action": action,
            "roundtable_conclusion": conclusion,
            "roundtable_blocker": blocker,
        },
    )
    metadata["continuation_contract"] = continuation.to_dict()
    
    return Decision(
        action=action,
        reason=reason,
        next_tasks=recommended_next_tasks,
        metadata=metadata,
    )


def _build_channel_summary(batch_id: str, analysis: Dict[str, Any], decision: Decision) -> str:
    packet = decision.metadata.get("channel_packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    validation = decision.metadata.get("packet_validation", {})
    dispatch_backend = decision.metadata.get("dispatch_backend", "subagent")
    timeout_policy = build_timeout_policy(dispatch_backend)

    lines = [
        f"# Channel Roundtable Continuation Summary — {batch_id}",
        "",
        f"- Generated: {_iso_now()}",
        f"- Adapter: {ADAPTER_NAME}",
        f"- Scenario: {decision.metadata.get('scenario', 'N/A')}",
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
        "## Channel Packet",
        "",
        f"- Packet Version: {packet.get('packet_version', 'N/A')}",
        f"- Channel ID: {packet.get('channel_id', 'N/A')}",
        f"- Channel Name: {packet.get('channel_name', 'N/A')}",
        f"- Topic: {packet.get('topic', 'N/A')}",
        f"- Owner: {packet.get('owner', 'N/A')}",
        f"- Packet Complete: {'yes' if validation.get('complete') else 'no'}",
        "",
        "## Roundtable Closure",
        "",
        f"- Conclusion: {roundtable.get('conclusion', 'N/A')}",
        f"- Blocker: {roundtable.get('blocker', 'N/A')}",
        f"- Owner: {roundtable.get('owner', 'N/A')}",
        f"- Next Step: {roundtable.get('next_step', 'N/A')}",
        f"- Completion Criteria: {roundtable.get('completion_criteria', 'N/A')}",
        "",
        "## Onboarding Contract",
        "",
        f"- doc: {CHANNEL_ONBOARDING_DOC}",
        f"- adapter: {ADAPTER_NAME}",
        "",
        "## Task Results",
        "",
    ]

    missing_fields = validation.get("missing_fields") or []
    if missing_fields:
        lines.extend(["## Missing Fields", ""])
        for field in missing_fields:
            lines.append(f"- {field}")
        lines.extend(["", "## Task Results", ""])

    for item in decision.metadata.get("supporting_results", []):
        closeout = item.get("closeout") if isinstance(item.get("closeout"), dict) else {}
        closeout_bits = []
        if closeout:
            closeout_bits.append(f"stopped_because={closeout.get('stopped_because') or 'N/A'}")
            closeout_bits.append(f"next_owner={closeout.get('next_owner') or 'N/A'}")
            closeout_bits.append(f"dispatch_readiness={closeout.get('dispatch_readiness') or 'N/A'}")
        suffix = f" error={item.get('error') or 'N/A'}" if item.get("error") else ""
        if closeout_bits:
            suffix += f" closeout[{', '.join(closeout_bits)}]"
        lines.append(
            f"- {item.get('task_id')}: state={item.get('state')} verdict={item.get('verdict')} summary={item.get('summary') or 'N/A'}{suffix}"
        )

    return "\n".join(lines) + "\n"


def _build_manual_followup_prompt(batch_id: str, decision: Decision, summary_path: Path) -> str:
    packet = decision.metadata.get("channel_packet", {})
    roundtable = decision.metadata.get("roundtable", {})
    scenario = decision.metadata.get("scenario", ADAPTER_NAME)
    next_step = roundtable.get("next_step") or "review the batch summary and continue the minimal next step"
    completion_criteria = roundtable.get("completion_criteria") or "produce the smallest verifiable continuation artifact"

    prompt_lines = [
        "# Channel Roundtable Follow-up",
        "",
        f"Adapter: {ADAPTER_NAME}",
        f"Scenario: {scenario}",
        f"Batch ID: {batch_id}",
        f"Decision: {decision.action}",
        f"Reason: {decision.reason}",
        f"Summary: {summary_path}",
        f"Contract Doc: {CHANNEL_ONBOARDING_DOC}",
        "",
        f"Channel ID: {packet.get('channel_id', 'N/A')}",
        f"Channel Name: {packet.get('channel_name', 'N/A')}",
        f"Topic: {packet.get('topic', 'N/A')}",
        f"Owner: {packet.get('owner', roundtable.get('owner', 'N/A'))}",
        f"Blocker: {roundtable.get('blocker', 'N/A')}",
        "",
        f"Next Step: {next_step}",
        f"Completion Criteria: {completion_criteria}",
        "",
        "Rules:",
        "- Do not widen scope beyond the single next step above.",
        "- Keep default mode safe semi-auto; only explicit allow or whitelist-default should auto-trigger.",
        "- Persist any updated summary/decision/dispatch artifacts in the final answer.",
    ]
    return "\n".join(prompt_lines)


def _new_id(prefix: str, batch_id: str) -> str:
    safe_batch_id = batch_id.replace("/", "_").replace(" ", "_")
    return f"{prefix}_{safe_batch_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"


def _persist_decision(batch_id: str, decision: Decision, summary_path: Path) -> Path:
    decision_id = decision.decision_id or _new_id("dec", batch_id)
    decision.decision_id = decision_id
    payload = {
        "decision_id": decision_id,
        "batch_id": batch_id,
        "scenario": decision.metadata.get("scenario"),
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
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    dispatch_id = _new_id("disp", batch_id)
    prompt = _build_manual_followup_prompt(batch_id, decision, summary_path)
    validation = decision.metadata.get("packet_validation", {})
    roundtable = decision.metadata.get("roundtable", {})
    scenario = decision.metadata.get("scenario", ADAPTER_NAME)
    backend = normalize_dispatch_backend(backend)

    reasons = []
    status = "triggered"
    timeout_count = int(analysis.get("timeout") or 0)
    failed_count = int(analysis.get("failed") or 0)
    if not allow_auto_dispatch:
        status = "skipped"
        reasons.append("manual confirmation required for channel roundtable continuation")
    if not validation.get("complete"):
        status = "skipped"
        reasons.append("channel roundtable packet or closure is incomplete")
    if timeout_count > 0:
        status = "skipped"
        reasons.append(f"batch has {timeout_count} timeout task(s), so waiting is not continuation-safe")
    if failed_count > 0:
        status = "skipped"
        reasons.append(f"batch has {failed_count} failed task(s), so waiting is not continuation-safe")
    if decision.action not in {"proceed", "retry"}:
        status = "skipped"
        reasons.append(f"decision {decision.action} is not auto-dispatchable")
    if backend == "subagent" and runtime != "subagent":
        status = "skipped"
        reasons.append(f"runtime {runtime} is not eligible for backend=subagent; only subagent is allowed")
    if backend == "subagent" and allow_auto_dispatch and status == "triggered" and not requester_session_key:
        status = "skipped"
        reasons.append("missing requester_session_key for runtime wake-up")

    reason = "; ".join(reasons) if reasons else f"channel roundtable {scenario} can continue via backend={backend}"
    dispatch_path = _dispatch_plan_file(dispatch_id)
    timeout_policy = build_timeout_policy(backend)
    backend_plan = build_backend_plan(
        backend=backend,
        dispatch_id=dispatch_id,
        dispatch_path=dispatch_path,
        batch_id=batch_id,
        scenario=scenario,
        adapter=ADAPTER_NAME,
        workdir=Path.cwd(),
        task_preview=roundtable.get("next_step") or decision.reason,
    )

    payload = {
        "dispatch_id": dispatch_id,
        "batch_id": batch_id,
        "scenario": scenario,
        "adapter": ADAPTER_NAME,
        "decision_id": decision.decision_id,
        "timestamp": _iso_now(),
        "status": status,
        "reason": reason,
        "backend": backend,
        "timeout_policy": timeout_policy,
        "backend_plan": backend_plan,
        "orchestration_contract": decision.metadata.get("orchestration_contract"),
        "canonical_callback": {
            "required": True,
            "business_terminal_source": "scripts/orchestrator_callback_bridge.py complete",
            "callback_payload_schema": (decision.metadata.get("orchestration_contract") or {}).get("callback_payload_schema") or "channel_roundtable.v1.callback",
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
            "packet_complete": validation.get("complete", False),
            "roundtable_conclusion": roundtable.get("conclusion"),
            "whitelist_match": _packet_matches_default_auto_dispatch_whitelist(
                decision.metadata.get("channel_packet", {})
            ),
            "batch_failed_count": failed_count,
            "batch_timeout_count": timeout_count,
        },
        "recommended_spawn": {
            "runtime": "subagent",
            "task_preview": roundtable.get("next_step") or decision.reason,
            "task": prompt,
        },
        "parent_message": None,
        "artifacts": {
            "batch_summary": str(summary_path),
            "decision_file": str(decision_path),
            "contract_doc": CHANNEL_ONBOARDING_DOC,
        },
    }

    if status == "triggered":
        if backend == "subagent":
            payload["parent_message"] = "\n".join(
                [
                    f"🔁 AUTO_DISPATCH_REQUEST adapter={ADAPTER_NAME} scenario={scenario} batch={batch_id} decision={decision.action} backend=subagent",
                    f"Read dispatch plan: {dispatch_path}",
                    'Execute exactly one sessions_spawn(runtime="subagent") using recommended_spawn from that file.',
                    "Roundtable closeout still depends on the canonical callback, not backend-local status alone.",
                    "Do not fan out further in this turn; this is a single-step continuation.",
                ]
            )
        else:
            payload["parent_message"] = "\n".join(
                [
                    f"🔁 AUTO_DISPATCH_REQUEST adapter={ADAPTER_NAME} scenario={scenario} batch={batch_id} decision={decision.action} backend=tmux",
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


def process_channel_roundtable_callback(
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
    Process a non-trading channel/thread roundtable callback using the existing orchestrator building blocks.

    Returns a structured dict so callers/tests can inspect the persisted chain.
    """
    _ensure_runtime_dirs()
    mark_callback_received(task_id, result)

    if not is_batch_complete(batch_id):
        return {
            "status": "pending",
            "batch_id": batch_id,
            "task_id": task_id,
            "reason": "batch not complete yet",
        }

    check_and_summarize_batch(batch_id)
    analysis = analyze_batch_results(batch_id)
    decision = _decision_from_payload(batch_id, analysis)
    normalized_backend = normalize_dispatch_backend(backend)
    decision.metadata["dispatch_backend"] = normalized_backend
    decision.metadata["orchestration_contract"] = resolve_orchestration_contract(
        result,
        default_adapter=ADAPTER_NAME,
        default_scenario=decision.metadata.get("scenario"),
        batch_key=batch_id,
        default_owner=decision.metadata.get("roundtable", {}).get("owner") or decision.metadata.get("channel_packet", {}).get("owner"),
        default_backend=normalized_backend,
    )

    channel_packet = decision.metadata.get("channel_packet", {})
    resolved_allow_auto_dispatch, auto_dispatch_source = _resolve_allow_auto_dispatch(
        channel_packet,
        allow_auto_dispatch,
    )

    summary_path = _summary_file(batch_id)
    summary_path.write_text(_build_channel_summary(batch_id, analysis, decision))
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
        analysis=analysis,
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
        scenario=decision.metadata.get("scenario", ADAPTER_NAME),
    )

    return {
        "status": "processed",
        "batch_id": batch_id,
        "task_id": task_id,
        "summary_path": str(summary_path),
        "decision_path": str(decision_path),
        "ack_result": ack_result,
        **dispatch_info,
    }
