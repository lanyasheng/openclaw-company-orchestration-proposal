#!/usr/bin/env python3
"""Minimal completion acknowledgement guard for roundtable callbacks."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from state_machine import STATE_DIR, _iso_now

ACK_RECEIPTS_DIR = STATE_DIR.parent / "orchestrator" / "ack_receipts"
ACK_AUDIT_DIR = STATE_DIR.parent / "orchestrator" / "ack_audit"
ACK_DISABLE_DELIVERY_ENV = "OPENCLAW_ACK_GUARD_DISABLE_DELIVERY"
DEFAULT_NODE_BIN = Path("/opt/homebrew/bin/node")
DEFAULT_OPENCLAW_BIN = Path("/Users/study/.npm-global/bin/openclaw")


def extract_channel_id_from_session_key(requester_session_key: Optional[str]) -> Optional[str]:
    if not requester_session_key:
        return None
    parts = requester_session_key.strip().split(":")
    if len(parts) >= 4 and parts[-2] == "channel":
        return parts[-1]
    return None


def _receipt_stem(adapter_name: str, batch_id: str) -> str:
    safe_adapter = str(adapter_name or "unknown").replace("/", "_").replace(" ", "_")
    safe_batch = str(batch_id or "unknown").replace("/", "_").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"ack-{safe_adapter}-{safe_batch}-{timestamp}"


def _write_json(file_path: Path, payload: Dict[str, Any]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp_file.replace(file_path)


def _write_receipt_markdown(*, file_path: Path, receipt: Dict[str, Any]) -> None:
    artifacts = receipt.get("artifacts") if isinstance(receipt.get("artifacts"), dict) else {}
    lines = [
        f"# {receipt.get('adapter_name', 'Roundtable')} Completion Ack Receipt",
        "",
        f"- Timestamp: {receipt.get('timestamp')}",
        f"- Batch ID: {receipt.get('batch_id')}",
        f"- Scenario: {receipt.get('scenario')}",
        f"- Decision: {receipt.get('decision_action')}",
        f"- Conclusion: {receipt.get('conclusion')}",
        f"- Blocker: {receipt.get('blocker')}",
        f"- Dispatch Status: {receipt.get('dispatch_status')}",
        f"- Ack Status: {receipt.get('ack_status')}",
        f"- Delivery Status: {receipt.get('delivery_status')}",
        f"- Delivery Reason: {receipt.get('delivery_reason')}",
        f"- Requester Session: {receipt.get('requester_session_key') or 'N/A'}",
        f"- Channel ID: {receipt.get('channel_id') or 'N/A'}",
        "",
        "## Requester-visible completion trace",
        "",
        f"- Summary: `{artifacts.get('summary_path', 'N/A')}`",
        f"- Decision File: `{artifacts.get('decision_path', 'N/A')}`",
        f"- Dispatch Plan: `{artifacts.get('dispatch_path', 'N/A')}`",
        f"- Next Step: {receipt.get('next_step')}",
        f"- Action Required: {receipt.get('next_action')}",
        "",
        "## Ack Message",
        "",
        receipt.get("message", ""),
        "",
    ]
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("\n".join(lines), encoding="utf-8")


def _delivery_reason_from_dispatch(dispatch_plan: Dict[str, Any]) -> str:
    if dispatch_plan.get("status") == "triggered":
        backend = dispatch_plan.get("backend", "subagent")
        return f"continuation will proceed via backend={backend}; roundtable advances only after the canonical callback is bridged"
    skip_reasons = dispatch_plan.get("skip_reasons") if isinstance(dispatch_plan.get("skip_reasons"), list) else []
    if skip_reasons:
        messages = [str(item.get("message", "")).strip() for item in skip_reasons[:2] if isinstance(item, dict)]
        joined = "; ".join(item for item in messages if item)
        if joined:
            return joined
    return str(dispatch_plan.get("reason") or "manual confirmation required")


def _build_message(
    *,
    adapter_name: str,
    batch_id: str,
    scenario: str,
    decision_action: str,
    conclusion: str,
    blocker: str,
    dispatch_status: str,
    next_step: str,
    next_action: str,
    artifacts: Dict[str, Any],
) -> str:
    dispatch_triggered = dispatch_status == "triggered"
    emoji = "🔁" if dispatch_triggered else "⏸️"
    status_text = "AUTO_DISPATCH_TRIGGERED" if dispatch_triggered else "MANUAL_REVIEW_REQUIRED"
    lines = [
        f"{emoji} {adapter_name.replace('_', ' ').title()} Completion Acknowledgement",
        "",
        f"- Batch ID: `{batch_id}`",
        f"- Scenario: {scenario}",
        f"- Decision: {decision_action}",
        f"- Roundtable Conclusion: {conclusion}",
        f"- Blocker: {blocker}",
        f"- Dispatch Status: {status_text}",
        "",
        f"**Next Step**: {next_step}",
        "",
        f"**Action Required**: {next_action}",
        "",
        "---",
        f"- Summary: `{artifacts.get('summary_path', 'N/A')}`",
        f"- Decision: `{artifacts.get('decision_path', 'N/A')}`",
        f"- Dispatch Plan: `{artifacts.get('dispatch_path', 'N/A')}`",
    ]
    return "\n".join(lines)


def _deliver_message(*, message: str, channel_id: Optional[str]) -> Dict[str, Any]:
    if not channel_id:
        return {"status": "skipped", "reason": "missing_requester_channel_id"}
    if os.environ.get(ACK_DISABLE_DELIVERY_ENV) == "1":
        return {"status": "skipped", "reason": "delivery_disabled_by_env"}

    cmd = [
        str(DEFAULT_NODE_BIN),
        str(DEFAULT_OPENCLAW_BIN),
        "agent",
        "--agent",
        "main",
        "--channel",
        "discord",
        "--deliver",
        "--message",
        message,
        "--reply-to",
        f"channel:{channel_id}",
    ]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "reason": "timeout_60s"}
    except FileNotFoundError as exc:
        return {"status": "failed", "reason": "openclaw_binary_not_found", "error": str(exc)}
    except Exception as exc:  # pragma: no cover - defensive only
        return {
            "status": "failed",
            "reason": f"unexpected_error:{type(exc).__name__}",
            "error": str(exc),
        }

    if result.returncode == 0:
        return {
            "status": "sent",
            "reason": "delivered_via_openclaw_agent",
            "stdout": result.stdout[:200] if result.stdout else "",
            "stderr": result.stderr[:200] if result.stderr else "",
        }
    return {
        "status": "failed",
        "reason": f"openclaw_agent_exit_{result.returncode}",
        "error": result.stderr[:300] if result.stderr else "unknown error",
    }


def _finalize_ack(
    *,
    adapter_name: str,
    batch_id: str,
    scenario: str,
    requester_session_key: Optional[str],
    decision_action: str,
    conclusion: str,
    blocker: str,
    dispatch_status: str,
    next_step: str,
    next_action: str,
    message: str,
    artifacts: Dict[str, Any],
    delivery: Dict[str, Any],
) -> Dict[str, Any]:
    channel_id = extract_channel_id_from_session_key(requester_session_key)
    delivery_status = str(delivery.get("status") or "skipped")
    delivery_reason = str(delivery.get("reason") or "unknown")
    ack_status = "sent" if delivery_status == "sent" else "fallback_recorded"
    receipt = {
        "timestamp": _iso_now(),
        "adapter_name": adapter_name,
        "batch_id": batch_id,
        "scenario": scenario,
        "requester_session_key": requester_session_key,
        "channel_id": channel_id,
        "decision_action": decision_action,
        "conclusion": conclusion,
        "blocker": blocker,
        "dispatch_status": dispatch_status,
        "next_step": next_step,
        "next_action": next_action,
        "ack_status": ack_status,
        "delivery_status": delivery_status,
        "delivery_reason": delivery_reason,
        "artifacts": artifacts,
        "message": message,
    }

    stem = _receipt_stem(adapter_name, batch_id)
    receipt_path = ACK_RECEIPTS_DIR / f"{stem}.md"
    audit_path = ACK_AUDIT_DIR / f"{stem}.json"
    _write_receipt_markdown(file_path=receipt_path, receipt=receipt)
    _write_json(
        audit_path,
        {
            **receipt,
            "delivery": delivery,
        },
    )

    result = {
        "ack_status": ack_status,
        "delivery_status": delivery_status,
        "reason": (
            delivery_reason if delivery_status == "sent" else f"fallback_receipt_recorded_after_{delivery_reason}"
        ),
        "channel_id": channel_id,
        "requester_session_key": requester_session_key,
        "message_sent": message,
        "receipt_path": str(receipt_path),
        "audit_file": str(audit_path),
    }
    if "error" in delivery:
        result["error"] = delivery["error"]
    if "stdout" in delivery or "stderr" in delivery:
        result["delivery_metadata"] = {
            "stdout": delivery.get("stdout", ""),
            "stderr": delivery.get("stderr", ""),
        }
    return result


def send_roundtable_completion_ack(
    *,
    batch_id: str,
    decision: Any,
    summary_path: Path,
    dispatch_info: Dict[str, Any],
    requester_session_key: Optional[str],
    adapter_name: str,
    scenario: str,
) -> Dict[str, Any]:
    roundtable = decision.metadata.get("roundtable", {}) if hasattr(decision, "metadata") else {}
    continuation = decision.metadata.get("continuation", {}) if hasattr(decision, "metadata") else {}
    dispatch_plan = dispatch_info.get("dispatch_plan") if isinstance(dispatch_info.get("dispatch_plan"), dict) else {}

    artifacts = {
        "summary_path": str(summary_path),
        "decision_path": dispatch_info.get("decision_path", "N/A"),
        "dispatch_path": dispatch_info.get("dispatch_path", "N/A"),
    }
    decision_action = getattr(decision, "action", "unknown")
    conclusion = str(roundtable.get("conclusion") or "N/A")
    blocker = str(roundtable.get("blocker") or "N/A")
    next_step = str(continuation.get("task_preview") or roundtable.get("next_step") or "see dispatch plan")
    dispatch_status = str(dispatch_plan.get("status") or "unknown")
    next_action = _delivery_reason_from_dispatch(dispatch_plan)
    message = _build_message(
        adapter_name=adapter_name,
        batch_id=batch_id,
        scenario=scenario,
        decision_action=decision_action,
        conclusion=conclusion,
        blocker=blocker,
        dispatch_status=dispatch_status,
        next_step=next_step,
        next_action=next_action,
        artifacts=artifacts,
    )
    delivery = _deliver_message(
        message=message,
        channel_id=extract_channel_id_from_session_key(requester_session_key),
    )
    return _finalize_ack(
        adapter_name=adapter_name,
        batch_id=batch_id,
        scenario=scenario,
        requester_session_key=requester_session_key,
        decision_action=decision_action,
        conclusion=conclusion,
        blocker=blocker,
        dispatch_status=dispatch_status,
        next_step=next_step,
        next_action=next_action,
        message=message,
        artifacts=artifacts,
        delivery=delivery,
    )


def ensure_callback_ack_result(
    result: Dict[str, Any],
    *,
    adapter_name: str,
    batch_id: str,
    scenario: str,
    requester_session_key: Optional[str],
) -> Dict[str, Any]:
    ack_result = result.get("ack_result") if isinstance(result.get("ack_result"), dict) else None
    if ack_result and ack_result.get("receipt_path"):
        result["ack_guard"] = {
            "status": "present",
            "ack_status": ack_result.get("ack_status"),
            "receipt_path": ack_result.get("receipt_path"),
        }
        return result

    dispatch_plan = result.get("dispatch_plan") if isinstance(result.get("dispatch_plan"), dict) else {}
    artifacts = {
        "summary_path": str(result.get("summary_path") or "N/A"),
        "decision_path": str(result.get("decision_path") or "N/A"),
        "dispatch_path": str(result.get("dispatch_path") or "N/A"),
    }
    next_step = str(
        dispatch_plan.get("continuation", {}).get("task_preview")
        if isinstance(dispatch_plan.get("continuation"), dict)
        else ""
    ) or str(dispatch_plan.get("reason") or "see persisted artifacts")
    next_action = _delivery_reason_from_dispatch(dispatch_plan)
    message = _build_message(
        adapter_name=adapter_name,
        batch_id=batch_id,
        scenario=scenario,
        decision_action=str(dispatch_plan.get("decision") or "unknown"),
        conclusion="N/A",
        blocker="N/A",
        dispatch_status=str(dispatch_plan.get("status") or "unknown"),
        next_step=next_step,
        next_action=next_action,
        artifacts=artifacts,
    )
    synthesized = _finalize_ack(
        adapter_name=adapter_name,
        batch_id=batch_id,
        scenario=scenario,
        requester_session_key=requester_session_key,
        decision_action=str(dispatch_plan.get("decision") or "unknown"),
        conclusion="N/A",
        blocker="N/A",
        dispatch_status=str(dispatch_plan.get("status") or "unknown"),
        next_step=next_step,
        next_action=next_action,
        message=message,
        artifacts=artifacts,
        delivery={"status": "skipped", "reason": "bridge_synthesized_fallback"},
    )
    result["ack_result"] = synthesized
    result["ack_guard"] = {
        "status": "synthesized_fallback",
        "ack_status": synthesized.get("ack_status"),
        "receipt_path": synthesized.get("receipt_path"),
    }
    return result
