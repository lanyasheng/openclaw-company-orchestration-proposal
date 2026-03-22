from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from contracts import build_canonical_callback_envelope


TERMINAL_DONE_STATUSES = {"likely_done", "done_session_ended"}
TERMINAL_FAILED_STATUSES = {"dead", "stuck"}
NON_TERMINAL_STATUSES = {"running", "idle"}
TRADING_PACKET_VERSION = "trading_phase1_packet_v1"
TRADING_PHASE_ID = "trading_phase1"
TRADING_CALLBACK_SCHEMA = "trading_roundtable.v1.callback"
CHANNEL_PACKET_VERSION = "channel_roundtable_v1"
EMBEDDED_BUSINESS_PAYLOAD_KEYS = (
    "business_callback_payload",
    "structured_callback_payload",
    "callback_payload",
)
BLOCKED_TRADING_MISSING_FIELDS = [
    "candidate_id",
    "run_label",
    "input_config_path",
    "commit.repo",
    "commit.git_commit",
    "test.commands",
    "test.summary",
    "repro.commands",
    "repro.notes",
    "tradability.annual_turnover",
    "tradability.liquidity_flags",
    "tradability.gross_return",
    "tradability.net_return",
    "tradability.benchmark_return",
    "tradability.scenario_verdict",
    "tradability.turnover_failure_reasons",
    "tradability.liquidity_failure_reasons",
    "tradability.net_vs_gross_failure_reasons",
    "tradability.summary",
]


def _iso_now() -> str:
    return datetime.now().isoformat()


def _read_json_if_exists(path: Optional[Path]) -> Dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dispatch_paths(dispatch_path: Path) -> Dict[str, Path]:
    orchestrator_dir = dispatch_path.parent.parent
    receipts_dir = orchestrator_dir / "tmux_receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    stem = dispatch_path.stem
    return {
        "receipts_dir": receipts_dir,
        "receipt_path": receipts_dir / f"{stem}.terminal-receipt.json",
        "business_payload_path": receipts_dir / f"{stem}.business-callback.json",
        "callback_payload_path": receipts_dir / f"{stem}.callback-payload.json",
    }


def _default_report_json_path(dispatch: Dict[str, Any]) -> Path:
    backend_plan = dispatch.get("backend_plan") if isinstance(dispatch.get("backend_plan"), dict) else {}
    session = str(backend_plan.get("session") or "").strip()
    if session:
        return Path("/tmp") / f"{session}-completion-report.json"
    label = str(backend_plan.get("label") or dispatch.get("dispatch_id") or "dispatch").strip()
    session = label if label.startswith("cc-") else f"cc-{label}"
    return Path("/tmp") / f"{session}-completion-report.json"


def _default_report_md_path(dispatch: Dict[str, Any]) -> Path:
    backend_plan = dispatch.get("backend_plan") if isinstance(dispatch.get("backend_plan"), dict) else {}
    session = str(backend_plan.get("session") or "").strip()
    if session:
        return Path("/tmp") / f"{session}-completion-report.md"
    label = str(backend_plan.get("label") or dispatch.get("dispatch_id") or "dispatch").strip()
    session = label if label.startswith("cc-") else f"cc-{label}"
    return Path("/tmp") / f"{session}-completion-report.md"


def _bool_path_exists(path_str: Any) -> bool:
    text = str(path_str or "").strip()
    return bool(text) and Path(text).exists()


def _payload_source_from_report(report: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    explicit_path = str(
        report.get("business_callback_payload_path")
        or report.get("business_payload_path")
        or ""
    ).strip()
    if explicit_path:
        payload = _read_json_if_exists(Path(explicit_path).expanduser())
        if payload:
            return payload, f"report_path:{explicit_path}"

    for key in EMBEDDED_BUSINESS_PAYLOAD_KEYS:
        raw = report.get(key)
        if isinstance(raw, dict):
            return dict(raw), f"embedded_report:{key}"

    if isinstance(report.get("trading_roundtable"), dict) or isinstance(report.get("channel_roundtable"), dict):
        payload: Dict[str, Any] = {}
        for key in ("summary", "verdict", "closeout", "orchestration", "trading_roundtable", "channel_roundtable"):
            if key in report:
                payload[key] = report[key]
        return payload, "embedded_report:scoped_payload"

    return {}, None


def _detect_business_callback_payload(
    dispatch: Dict[str, Any],
    receipt: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str]]:
    artifact_paths = receipt.get("artifact_paths") if isinstance(receipt.get("artifact_paths"), dict) else {}
    business_payload_path = str(artifact_paths.get("business_payload_path") or "").strip()
    if business_payload_path:
        payload = _read_json_if_exists(Path(business_payload_path))
        if payload:
            return payload, f"business_payload_path:{business_payload_path}"

    report = receipt.get("report") if isinstance(receipt.get("report"), dict) else {}
    if report:
        payload, source = _payload_source_from_report(report)
        if payload:
            return payload, source

    return {}, None


def parse_tmux_status_output(stdout: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def derive_terminal_state(*, tmux_status: str, report_exists: bool) -> str:
    status = str(tmux_status or "").strip().lower()
    if report_exists or status in TERMINAL_DONE_STATUSES:
        return "completed"
    if status in TERMINAL_FAILED_STATUSES:
        return "failed"
    if status in NON_TERMINAL_STATUSES:
        return status
    return status or "unknown"


def derive_dispatch_readiness(*, terminal_state: str, report_exists: bool, report: Dict[str, Any]) -> str:
    if terminal_state != "completed" or not report_exists:
        return "blocked"

    recommendation = str(report.get("recommendation") or "keep").strip().lower()
    scope_drift = bool(report.get("scopeDrift"))
    lint_ok = (report.get("lint") if isinstance(report.get("lint"), dict) else {}).get("ok")
    build_ok = (report.get("build") if isinstance(report.get("build"), dict) else {}).get("ok")

    if recommendation == "rollback":
        return "blocked"
    if recommendation == "partial_rollback":
        return "human_gate"
    if scope_drift:
        return "human_gate"
    if lint_ok is False or build_ok is False:
        return "human_gate"
    return "ready"


def derive_stopped_because(*, tmux_status: str, terminal_state: str, report_exists: bool) -> str:
    status = str(tmux_status or "").strip().lower()
    if terminal_state == "completed" and report_exists:
        return "tmux_completion_report_ready"
    if terminal_state == "completed":
        return "tmux_terminal_without_report"
    if status == "dead":
        return "tmux_session_dead_without_report"
    if status == "stuck":
        return "tmux_session_stuck"
    if status in NON_TERMINAL_STATUSES:
        return f"tmux_not_terminal_{status}"
    return f"tmux_terminal_{terminal_state or 'unknown'}"


def derive_next_step(*, dispatch_readiness: str, dispatch: Dict[str, Any]) -> str:
    continuation = dispatch.get("continuation") if isinstance(dispatch.get("continuation"), dict) else {}
    task_preview = str(continuation.get("task_preview") or "").strip()

    if dispatch_readiness == "ready":
        return task_preview or "review tmux completion artifacts, attach the real trading packet/report truth, then re-enter the trading roundtable callback"
    if dispatch_readiness == "human_gate":
        return "manually review tmux completion artifacts, decide keep vs partial rollback, then re-enter the trading roundtable callback with explicit evidence"
    return "inspect tmux failure or missing-report state, recover artifacts if possible, otherwise rerun the same continuation before any next dispatch"


def derive_summary(*, terminal_state: str, report_exists: bool, report: Dict[str, Any], dispatch: Dict[str, Any], tmux_status: str) -> str:
    if report_exists:
        notes = str(report.get("notes") or "").strip()
        if notes:
            return notes
        diff_stat = str(report.get("diffStat") or "").strip()
        if diff_stat:
            return f"tmux completion report ready: {diff_stat.splitlines()[0]}"
        changed_files = report.get("changedFiles") if isinstance(report.get("changedFiles"), list) else []
        if changed_files:
            return f"tmux completion report ready with {len(changed_files)} changed file(s)"
        return "tmux completion report ready"

    continuation = dispatch.get("continuation") if isinstance(dispatch.get("continuation"), dict) else {}
    task_preview = str(continuation.get("task_preview") or "").strip()
    if terminal_state == "failed":
        return task_preview or f"tmux backend ended in terminal failure state={tmux_status or 'unknown'} before a completion report was available"
    return task_preview or f"tmux backend state={terminal_state or 'unknown'} status={tmux_status or 'unknown'}"


def build_tmux_terminal_receipt(
    *,
    dispatch: Dict[str, Any],
    dispatch_path: Path,
    tmux_status: str,
    report_json_path: Optional[Path] = None,
    report_md_path: Optional[Path] = None,
    observed_at: Optional[str] = None,
) -> Dict[str, Any]:
    report_json_path = report_json_path or _default_report_json_path(dispatch)
    report_md_path = report_md_path or _default_report_md_path(dispatch)
    report = _read_json_if_exists(report_json_path)
    report_exists = bool(report) or report_json_path.exists() or report_md_path.exists()
    terminal_state = derive_terminal_state(tmux_status=tmux_status, report_exists=report_exists)
    dispatch_readiness = derive_dispatch_readiness(
        terminal_state=terminal_state,
        report_exists=report_exists,
        report=report,
    )
    stopped_because = derive_stopped_because(
        tmux_status=tmux_status,
        terminal_state=terminal_state,
        report_exists=report_exists,
    )

    contract = dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}
    next_owner = str(contract.get("owner") or dispatch.get("adapter") or "main")
    next_step = derive_next_step(dispatch_readiness=dispatch_readiness, dispatch=dispatch)
    summary = derive_summary(
        terminal_state=terminal_state,
        report_exists=report_exists,
        report=report,
        dispatch=dispatch,
        tmux_status=tmux_status,
    )
    lifecycle_paths = _dispatch_paths(dispatch_path)

    receipt: Dict[str, Any] = {
        "receipt_version": "tmux_terminal_receipt.v1",
        "observed_at": observed_at or _iso_now(),
        "adapter": dispatch.get("adapter"),
        "scenario": dispatch.get("scenario"),
        "batch_id": dispatch.get("batch_id"),
        "dispatch_id": dispatch.get("dispatch_id"),
        "backend": "tmux",
        "tmux_status": tmux_status,
        "terminal_state": terminal_state,
        "summary": summary,
        "stopped_because": stopped_because,
        "next_step": next_step,
        "next_owner": next_owner,
        "dispatch_readiness": dispatch_readiness,
        "report_exists": report_exists,
        "artifact_paths": {
            "dispatch_path": str(dispatch_path),
            "receipt_path": str(lifecycle_paths["receipt_path"]),
            "business_payload_path": str(lifecycle_paths["business_payload_path"]),
            "callback_payload_path": str(lifecycle_paths["callback_payload_path"]),
            "dispatch_summary_path": str((dispatch.get("artifacts") or {}).get("batch_summary") or ""),
            "dispatch_decision_path": str((dispatch.get("artifacts") or {}).get("decision_file") or ""),
            "prompt_file": str((dispatch.get("backend_plan") or {}).get("prompt_file") or ""),
            "report_json": str(report_json_path),
            "report_md": str(report_md_path),
        },
        "report": report,
    }

    business_payload, source = _detect_business_callback_payload(dispatch, receipt)
    receipt["business_callback"] = {
        "required_for_business_closeout": True,
        "schema": str(contract.get("callback_payload_schema") or ""),
        "path": str(lifecycle_paths["business_payload_path"]),
        "detected": bool(business_payload),
        "source": source or "none",
    }
    return receipt


def _derived_closeout(receipt: Dict[str, Any], source: str) -> Dict[str, Any]:
    return {
        "stopped_because": receipt.get("stopped_because"),
        "next_step": receipt.get("next_step"),
        "next_owner": receipt.get("next_owner"),
        "dispatch_readiness": receipt.get("dispatch_readiness"),
        "business_payload_source": source,
    }


def _derived_orchestration(dispatch: Dict[str, Any], adapter: str) -> Dict[str, Any]:
    return {
        **(dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}),
        "enabled": True,
        "adapter": adapter,
        "scenario": dispatch.get("scenario"),
        "batch_key": dispatch.get("batch_id"),
        "backend_preference": "tmux",
    }


def _merge_top_level_mapping(base: Any, patch: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if key not in result or result[key] in (None, "", [], {}):
            result[key] = value
    return result


def _verdict_from_conclusion(conclusion: str, default: str = "FAIL") -> str:
    text = str(conclusion or "").strip().upper()
    if text == "PASS":
        return "PASS"
    if text in {"CONDITIONAL", "FAIL"}:
        return "FAIL"
    return default


def _normalize_trading_business_payload(
    raw_payload: Dict[str, Any],
    dispatch: Dict[str, Any],
    receipt: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    payload = dict(raw_payload)
    scoped_raw = payload.get("trading_roundtable") if isinstance(payload.get("trading_roundtable"), dict) else payload
    packet = dict(scoped_raw.get("packet")) if isinstance(scoped_raw.get("packet"), dict) else {}
    roundtable = dict(scoped_raw.get("roundtable")) if isinstance(scoped_raw.get("roundtable"), dict) else {}
    scoped_summary = str(scoped_raw.get("summary") or payload.get("summary") or receipt.get("summary") or "").strip()

    if not packet:
        packet = {}
    if not roundtable:
        roundtable = {}

    packet = _merge_top_level_mapping(
        packet,
        {
            "packet_version": TRADING_PACKET_VERSION if dispatch.get("scenario") == "trading_roundtable_phase1" else None,
            "phase_id": TRADING_PHASE_ID if dispatch.get("scenario") == "trading_roundtable_phase1" else None,
            "generated_at": receipt.get("observed_at"),
            "owner": receipt.get("next_owner"),
        },
    )
    roundtable = _merge_top_level_mapping(
        roundtable,
        {
            "owner": receipt.get("next_owner"),
            "next_step": receipt.get("next_step"),
            "completion_criteria": (dispatch.get("continuation") or {}).get("completion_criteria"),
        },
    )

    conclusion = str(roundtable.get("conclusion") or packet.get("overall_gate") or "FAIL").strip().upper() or "FAIL"
    if "blocker" not in roundtable or roundtable.get("blocker") in (None, ""):
        roundtable["blocker"] = packet.get("primary_blocker") or "implementation_risk"

    closeout = _merge_top_level_mapping(payload.get("closeout"), _derived_closeout(receipt, source))

    normalized: Dict[str, Any] = {
        **payload,
        "summary": str(payload.get("summary") or scoped_summary or receipt.get("summary") or "").strip(),
        "verdict": str(payload.get("verdict") or _verdict_from_conclusion(conclusion)),
        "closeout": closeout,
        "tmux_terminal_receipt": receipt,
        "orchestration": _merge_top_level_mapping(payload.get("orchestration"), _derived_orchestration(dispatch, "trading_roundtable")),
        "trading_roundtable": {
            "summary": scoped_summary or str(payload.get("summary") or receipt.get("summary") or "").strip(),
            "packet": packet,
            "roundtable": roundtable,
        },
    }
    return normalized


def _normalize_channel_business_payload(
    raw_payload: Dict[str, Any],
    dispatch: Dict[str, Any],
    receipt: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    payload = dict(raw_payload)
    if isinstance(payload.get("channel_roundtable"), dict):
        scoped_raw = payload.get("channel_roundtable")
    elif isinstance(payload.get("generic_roundtable"), dict):
        scoped_raw = payload.get("generic_roundtable")
    else:
        scoped_raw = payload

    packet = dict(scoped_raw.get("packet")) if isinstance(scoped_raw.get("packet"), dict) else {}
    roundtable = dict(scoped_raw.get("roundtable")) if isinstance(scoped_raw.get("roundtable"), dict) else {}
    scoped_summary = str(scoped_raw.get("summary") or payload.get("summary") or receipt.get("summary") or "").strip()

    contract = dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}
    channel = contract.get("channel") if isinstance(contract.get("channel"), dict) else {}
    artifact_paths = receipt.get("artifact_paths") if isinstance(receipt.get("artifact_paths"), dict) else {}
    artifact_path = str(artifact_paths.get("report_md") or artifact_paths.get("report_json") or "").strip()

    packet = _merge_top_level_mapping(
        packet,
        {
            "packet_version": CHANNEL_PACKET_VERSION,
            "scenario": dispatch.get("scenario"),
            "channel_id": channel.get("channel_id") or channel.get("id"),
            "channel_name": channel.get("channel_name") or channel.get("name"),
            "topic": channel.get("topic") or (contract.get("metadata") if isinstance(contract.get("metadata"), dict) else {}).get("topic"),
            "owner": receipt.get("next_owner"),
            "generated_at": receipt.get("observed_at"),
            "artifact": {
                "path": artifact_path,
                "exists": bool(artifact_path),
            },
        },
    )
    roundtable = _merge_top_level_mapping(
        roundtable,
        {
            "owner": receipt.get("next_owner"),
            "next_step": receipt.get("next_step"),
            "completion_criteria": (dispatch.get("continuation") or {}).get("completion_criteria"),
        },
    )

    conclusion = str(roundtable.get("conclusion") or ("PASS" if str(payload.get("verdict") or "").upper() == "PASS" else "FAIL")).strip().upper() or "FAIL"
    if "blocker" not in roundtable or roundtable.get("blocker") in (None, ""):
        roundtable["blocker"] = "none" if conclusion == "PASS" else str(receipt.get("stopped_because") or "implementation_risk")

    closeout = _merge_top_level_mapping(payload.get("closeout"), _derived_closeout(receipt, source))

    normalized_channel_payload = {
        "summary": scoped_summary or str(payload.get("summary") or receipt.get("summary") or "").strip(),
        "packet": packet,
        "roundtable": roundtable,
    }
    return {
        **payload,
        "summary": str(payload.get("summary") or scoped_summary or receipt.get("summary") or "").strip(),
        "verdict": str(payload.get("verdict") or _verdict_from_conclusion(conclusion)),
        "closeout": closeout,
        "tmux_terminal_receipt": receipt,
        "orchestration": _merge_top_level_mapping(payload.get("orchestration"), _derived_orchestration(dispatch, "channel_roundtable")),
        "channel_roundtable": normalized_channel_payload,
        "generic_roundtable": normalized_channel_payload,
    }


def _blocked_trading_summary(receipt: Dict[str, Any]) -> str:
    base = str(receipt.get("summary") or "tmux completion finished without a usable trading business callback payload").strip()
    return f"{base}; generated blocked trading callback payload because no real phase1 business payload was available"


def _build_blocked_trading_callback_payload(dispatch: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    blocked_reason = str(receipt.get("stopped_because") or "tmux_business_payload_missing")
    report = receipt.get("report") if isinstance(receipt.get("report"), dict) else {}
    artifact_paths = receipt.get("artifact_paths") if isinstance(receipt.get("artifact_paths"), dict) else {}

    packet: Dict[str, Any] = {
        "packet_version": TRADING_PACKET_VERSION,
        "phase_id": TRADING_PHASE_ID,
        "generated_at": receipt.get("observed_at"),
        "owner": receipt.get("next_owner"),
        "overall_gate": "FAIL",
        "primary_blocker": blocked_reason,
        "tmux_bridge": {
            "status": "blocked",
            "reason": blocked_reason,
            "dispatch_readiness": receipt.get("dispatch_readiness"),
            "tmux_status": receipt.get("tmux_status"),
            "business_payload_expected_at": artifact_paths.get("business_payload_path"),
            "report_json": artifact_paths.get("report_json"),
            "report_json_exists": _bool_path_exists(artifact_paths.get("report_json")),
            "report_md": artifact_paths.get("report_md"),
            "report_md_exists": _bool_path_exists(artifact_paths.get("report_md")),
            "completion_notes": report.get("notes"),
            "missing_business_fields": list(BLOCKED_TRADING_MISSING_FIELDS),
        },
    }

    roundtable = {
        "conclusion": "FAIL",
        "blocker": blocked_reason,
        "owner": receipt.get("next_owner"),
        "next_step": receipt.get("next_step"),
        "completion_criteria": "write a real trading phase1 callback payload, or keep this callback explicitly blocked with missing fields/evidence",
    }

    return {
        "summary": _blocked_trading_summary(receipt),
        "verdict": "FAIL",
        "closeout": _derived_closeout(receipt, "generated_blocked_payload"),
        "tmux_terminal_receipt": receipt,
        "orchestration": _derived_orchestration(dispatch, "trading_roundtable"),
        "trading_roundtable": {
            "summary": _blocked_trading_summary(receipt),
            "packet": packet,
            "roundtable": roundtable,
        },
    }


def _finalize_canonical_callback_payload(
    dispatch: Dict[str, Any],
    receipt: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    contract = dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}
    adapter = str(dispatch.get("adapter") or contract.get("adapter") or "").strip() or None
    finalized = dict(payload)
    finalized.setdefault("backend_terminal_receipt", receipt)
    if str(receipt.get("backend") or "").strip() == "tmux":
        finalized.setdefault("tmux_terminal_receipt", receipt)
    finalized["callback_envelope"] = build_canonical_callback_envelope(
        adapter=adapter,
        scenario=str(dispatch.get("scenario") or contract.get("scenario") or "").strip() or None,
        batch_id=str(dispatch.get("batch_id") or contract.get("batch_key") or "").strip() or None,
        backend_terminal_receipt=receipt,
        business_callback_payload=payload,
        orchestration_contract=contract,
        business_payload_source=source,
        callback_payload_schema=str(contract.get("callback_payload_schema") or "").strip() or None,
        metadata={
            "bridge": "scripts/orchestrator_dispatch_bridge.py complete",
            "builder": "orchestrator/tmux_terminal_receipts.py",
        },
    )
    return finalized


def build_callback_payload_from_tmux_receipt(dispatch: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    adapter = str(dispatch.get("adapter") or "").strip()
    business_payload, source = _detect_business_callback_payload(dispatch, receipt)
    resolved_source = source or "generic_tmux_receipt"

    if adapter == "trading_roundtable":
        payload = (
            _normalize_trading_business_payload(
                business_payload,
                dispatch,
                receipt,
                source=resolved_source,
            )
            if business_payload
            else _build_blocked_trading_callback_payload(dispatch, receipt)
        )
        return _finalize_canonical_callback_payload(dispatch, receipt, payload, source=resolved_source if business_payload else "generated_blocked_payload")

    if adapter == "channel_roundtable" and business_payload:
        payload = _normalize_channel_business_payload(
            business_payload,
            dispatch,
            receipt,
            source=resolved_source,
        )
        return _finalize_canonical_callback_payload(dispatch, receipt, payload, source=resolved_source)

    dispatch_readiness = str(receipt.get("dispatch_readiness") or "blocked")
    if dispatch_readiness == "ready":
        conclusion = "PASS"
        blocker = "none"
        verdict = "PASS"
    elif dispatch_readiness == "human_gate":
        conclusion = "CONDITIONAL"
        blocker = str(receipt.get("stopped_because") or "human_gate")
        verdict = "FAIL"
    else:
        conclusion = "FAIL"
        blocker = str(receipt.get("stopped_because") or "tmux_terminal_failure")
        verdict = "FAIL"

    closeout = _derived_closeout(receipt, source or "generic_tmux_receipt")
    payload: Dict[str, Any] = {
        "summary": receipt.get("summary"),
        "verdict": verdict,
        "closeout": closeout,
        "tmux_terminal_receipt": receipt,
        "orchestration": _derived_orchestration(dispatch, adapter),
    }

    roundtable = {
        "conclusion": conclusion,
        "blocker": blocker,
        "owner": receipt.get("next_owner"),
        "next_step": receipt.get("next_step"),
        "completion_criteria": "persist tmux terminal artifacts, then decide whether the continuation is ready, needs human gate, or must rerun",
    }

    if adapter == "channel_roundtable":
        contract = dispatch.get("orchestration_contract") if isinstance(dispatch.get("orchestration_contract"), dict) else {}
        channel = contract.get("channel") if isinstance(contract.get("channel"), dict) else {}
        artifact_paths = receipt.get("artifact_paths") if isinstance(receipt.get("artifact_paths"), dict) else {}
        artifact_path = str(artifact_paths.get("report_md") or artifact_paths.get("report_json") or "").strip()

        payload["channel_roundtable"] = {
            "summary": receipt.get("summary"),
            "packet": {
                "packet_version": CHANNEL_PACKET_VERSION,
                "scenario": dispatch.get("scenario"),
                "channel_id": channel.get("channel_id") or channel.get("id"),
                "channel_name": channel.get("channel_name") or channel.get("name"),
                "topic": channel.get("topic"),
                "owner": receipt.get("next_owner"),
                "generated_at": receipt.get("observed_at"),
                "artifact": {
                    "path": artifact_path,
                    "exists": bool(artifact_path),
                },
            },
            "roundtable": roundtable,
        }
        payload["generic_roundtable"] = payload["channel_roundtable"]
        return _finalize_canonical_callback_payload(dispatch, receipt, payload, source=resolved_source)

    raise ValueError(f"unsupported tmux callback adapter: {adapter!r}")


def write_json(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp_path.replace(path)
    return path


def receipt_lifecycle_paths(dispatch_path: Path) -> Dict[str, Path]:
    return _dispatch_paths(dispatch_path)
