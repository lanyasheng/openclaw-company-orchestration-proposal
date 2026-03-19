from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .callback_transport import CallbackTransportResult, FileCallbackTransport
from .scheduler import StepContext, StepOutcome
from .task_registry import TERMINAL_STATES
from .terminal_ingest import SubagentTerminalIngest

_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_REQUIRED_CHECKLIST_ITEM_IDS = frozenset(
    {
        "run_label_recorded",
        "candidate_id_recorded",
        "input_config_path_recorded",
        "artifact_path_recorded",
        "report_path_recorded",
        "git_commit_recorded",
        "test_commands_recorded",
        "verdict_summary_recorded",
    }
)
_DEFAULT_REQUIRED_DIMENSIONS = ("etf_basket", "oos", "regime", "stock_basket")
_ALLOWED_BUSINESS_VERDICTS = {"PASS", "CONDITIONAL", "FAIL"}


def init_registry_handler(context: StepContext) -> StepOutcome:
    workflow_id = context.workflow["workflow_id"]
    output = {
        "task_id": context.task_id,
        "workflow_id": workflow_id,
        "owner": context.workflow.get("owner", "zoe"),
    }
    return StepOutcome(
        kind="completed",
        state="queued",
        runtime="lobster",
        step_output=output,
        evidence_merge={
            "input": context.request,
            "workflow": {
                "workflow_id": workflow_id,
                "mode": context.workflow.get("mode", "chain-basic"),
            },
            context.step["id"]: output,
        },
        summary="初始化 task registry",
    )



def inline_payload_handler(context: StepContext) -> StepOutcome:
    template = context.step.get("output", {})
    rendered = _render_value(template, context)
    state = context.step.get("state", "running")
    runtime = context.step.get("runtime", "lobster")
    return StepOutcome(
        kind="completed",
        state=state,
        runtime=runtime,
        step_output=rendered,
        evidence_merge={context.step["id"]: rendered},
        summary=str(context.step.get("summary", f"{context.step['id']} 完成")),
    )



def subagent_local_cli_handler(context: StepContext) -> StepOutcome:
    workdir_value = context.step.get("workdir") or context.request.get("workspace_repo_path")
    if workdir_value in {None, ""}:
        raise ValueError("subagent.local_cli 需要 workdir 或 request.workspace_repo_path")

    command_template = context.step.get("command")
    if not isinstance(command_template, list) or not command_template:
        raise ValueError("subagent.local_cli.command 必须是非空数组")

    workdir = Path(str(_render_value(workdir_value, context))).expanduser().resolve()
    if not workdir.exists() or not workdir.is_dir():
        raise ValueError(f"subagent.local_cli workdir 不存在: {workdir}")

    command = [str(_render_value(item, context)) for item in command_template]
    timeout_seconds = context.step.get("timeoutSeconds")
    terminal_artifacts = _render_value(context.step.get("terminal_artifacts", {}), context)
    if not isinstance(terminal_artifacts, dict):
        terminal_artifacts = {}

    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds) if timeout_seconds is not None else None,
        )
        terminal = {
            "terminal_state": "completed" if result.returncode == 0 else "failed",
            "completed_at": _now_iso(),
            "exit_code": result.returncode,
            "stdout_tail": _tail_text(result.stdout),
            "stderr_tail": _tail_text(result.stderr),
            "artifacts": terminal_artifacts,
        }
        summary = str(context.step.get("summary", "本地 subagent CLI 已执行"))
    except subprocess.TimeoutExpired as exc:
        terminal = {
            "terminal_state": "timeout",
            "completed_at": _now_iso(),
            "exit_code": None,
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr),
            "artifacts": terminal_artifacts,
        }
        summary = str(context.step.get("timeoutSummary", "本地 subagent CLI 已超时"))

    payload = {
        "child_session_key": str(context.step.get("child_session_key") or f"local-subagent:{context.task_id}"),
        "command": command,
        "target_repo": context.request.get("workspace_repo"),
        "workdir": str(workdir),
        "terminal": terminal,
    }
    return StepOutcome(
        kind="completed",
        state="running",
        runtime="subagent",
        step_output=payload,
        evidence_merge={context.step["id"]: payload},
        summary=summary,
    )



def await_terminal_handler(context: StepContext) -> StepOutcome:
    signal_key = str(context.step.get("signal_key", "terminal"))
    terminal_signal = (context.signal or {}).get(signal_key)
    child_session_key = _extract_child_session_key(context)
    ingest = SubagentTerminalIngest(context.registry)

    if terminal_signal is None:
        terminal_signal = _extract_inline_terminal(context)

    if terminal_signal is not None:
        if not isinstance(terminal_signal, dict):
            raise ValueError("terminal signal 必须是 object")
        raw_event = dict(terminal_signal)
        raw_event.setdefault("task_id", context.task_id)
        if child_session_key is not None and not raw_event.get("child_session_key") and not raw_event.get("session_key"):
            raw_event["child_session_key"] = child_session_key
        terminal_output = ingest.ingest(raw_event)
        return StepOutcome(
            kind="completed",
            state=str(terminal_output["state"]),
            runtime="subagent",
            step_output=terminal_output,
            evidence_merge={context.step["id"]: terminal_output},
            summary="收到 subagent terminal",
        )

    terminal_output = ingest.load_waiter(context.task_id)
    if terminal_output is not None:
        if child_session_key is not None and terminal_output.get("child_session_key") != child_session_key:
            raise ValueError("terminal envelope child_session_key 与当前 step 绑定不一致")
        return StepOutcome(
            kind="completed",
            state=str(terminal_output.get("state", context.record["state"])),
            runtime="subagent",
            step_output=terminal_output,
            evidence_merge={context.step["id"]: terminal_output},
            summary="收到 subagent terminal",
        )

    return StepOutcome(
        kind="waiting",
        state="running",
        runtime="subagent",
        wait_kind="subagent_terminal",
        evidence_merge={
            context.step["id"]: {
                "waiting": True,
                "child_session_key": child_session_key,
            }
        },
        summary="等待 subagent terminal",
    )



def collect_and_classify_handler(context: StepContext) -> StepOutcome:
    terminal = context.step_outputs.get("await_terminal")
    if not isinstance(terminal, dict):
        raise ValueError("collect_and_classify 需要 await_terminal 输出")

    terminal_state = str(terminal.get("terminal_state") or "unknown")
    child_session_key = _extract_child_session_key(context)
    artifact_meta = terminal.get("artifacts")
    if not isinstance(artifact_meta, dict):
        artifact_meta = {}

    artifact_json_path = _first_non_empty(
        artifact_meta.get("artifact_json_path"),
        context.request.get("artifact_json_path"),
    )
    workspace_repo = str(context.request.get("workspace_repo") or "").strip()
    if workspace_repo != "workspace-trading":
        raise ValueError("collect_and_classify 仅允许 workspace_repo=workspace-trading")

    workspace_repo_path = _require_workspace_repo_path(context)
    payload: Dict[str, Any] = {
        "workflow_state": "failed",
        "business_overall_verdict": None,
        "terminal_state": terminal_state,
        "child_session_key": child_session_key,
        "artifact_json_path": artifact_json_path,
        "report_path": _first_non_empty(
            artifact_meta.get("report_path"),
            context.request.get("report_path"),
        ),
        "candidate_id": None,
        "checklist_overall_status": None,
        "scenario_count": None,
        "dimensions_covered": [],
        "contract_failures": [],
    }

    if terminal_state != "completed":
        payload["contract_failures"] = [f"terminal_not_completed:{terminal_state}"]
        return StepOutcome(
            kind="completed",
            state="failed",
            runtime="lobster",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="terminal 未完成，按 failed 收敛",
        )

    if artifact_json_path is None:
        payload["contract_failures"] = ["artifact_json_path_missing"]
        return StepOutcome(
            kind="completed",
            state="failed",
            runtime="lobster",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="artifact 路径缺失",
        )

    artifact_file = _resolve_repo_relative_path(artifact_json_path, workspace_repo_path)
    if not artifact_file.exists():
        payload["contract_failures"] = ["artifact_json_missing"]
        return StepOutcome(
            kind="completed",
            state="failed",
            runtime="lobster",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="artifact JSON 不存在",
        )

    artifact_payload = _load_json_path(artifact_file)
    failure_reasons: list[str] = []

    if str(artifact_payload.get("manifest_version") or "") != "acceptance_harness.v1":
        failure_reasons.append("artifact_manifest_version_invalid")

    manifest_payload = _resolve_contract_payload(
        nested_payload=artifact_payload.get("acceptance_manifest"),
        sidecar_path=_first_non_empty(
            artifact_meta.get("acceptance_manifest_path"),
            context.request.get("acceptance_manifest_path"),
        ),
        repo_root=workspace_repo_path,
        expected_key="acceptance_manifest",
        failure_reasons=failure_reasons,
    )
    checklist_payload = _resolve_contract_payload(
        nested_payload=artifact_payload.get("acceptance_checklist"),
        sidecar_path=_first_non_empty(
            artifact_meta.get("acceptance_checklist_path"),
            context.request.get("acceptance_checklist_path"),
        ),
        repo_root=workspace_repo_path,
        expected_key="acceptance_checklist",
        failure_reasons=failure_reasons,
    )

    summary_payload = artifact_payload.get("summary")
    if not isinstance(summary_payload, dict):
        failure_reasons.append("summary_missing")
        summary_payload = {}

    required_dimensions = tuple(
        sorted(
            str(item)
            for item in context.step.get("required_dimensions", _DEFAULT_REQUIRED_DIMENSIONS)
        )
    )
    required_scenario_count = int(context.step.get("required_scenario_count", len(required_dimensions)))

    scenario_count = summary_payload.get("scenario_count")
    if scenario_count != required_scenario_count:
        failure_reasons.append(
            f"scenario_count_mismatch:{scenario_count!r}!={required_scenario_count}"
        )

    dimensions_covered = summary_payload.get("dimensions_covered")
    normalized_dimensions = _normalize_dimensions(dimensions_covered)
    if normalized_dimensions != required_dimensions:
        failure_reasons.append(
            "dimensions_covered_mismatch:"
            f"{list(normalized_dimensions)}!={list(required_dimensions)}"
        )

    overall_verdict = None
    candidate_id = None
    manifest_report_path = None

    if manifest_payload is None:
        failure_reasons.append("acceptance_manifest_missing")
    else:
        if manifest_payload.get("schema_version") != "acceptance_manifest.v1":
            failure_reasons.append("acceptance_manifest_schema_invalid")
        candidate_id = manifest_payload.get("candidate_id")
        manifest_report_path = manifest_payload.get("report_path")
        generated_artifact_path = manifest_payload.get("generated_artifact_path")
        if generated_artifact_path is None:
            failure_reasons.append("manifest_generated_artifact_path_missing")
        elif not _paths_match_relative_to_repo(
            generated_artifact_path,
            artifact_json_path,
            workspace_repo_path,
        ):
            failure_reasons.append("manifest_generated_artifact_path_mismatch")

        verdict_summary = manifest_payload.get("verdict_summary")
        if not isinstance(verdict_summary, dict):
            failure_reasons.append("manifest_verdict_summary_missing")
        else:
            overall_verdict = str(verdict_summary.get("overall_verdict") or "")
            if overall_verdict not in _ALLOWED_BUSINESS_VERDICTS:
                failure_reasons.append(f"business_overall_verdict_invalid:{overall_verdict or 'missing'}")
            if verdict_summary.get("scenario_count") != required_scenario_count:
                failure_reasons.append("manifest_scenario_count_mismatch")
            manifest_dimensions = _normalize_dimensions(verdict_summary.get("dimensions_covered"))
            if manifest_dimensions != required_dimensions:
                failure_reasons.append("manifest_dimensions_covered_mismatch")

    checklist_overall_status = None
    if checklist_payload is None:
        failure_reasons.append("acceptance_checklist_missing")
    else:
        if checklist_payload.get("schema_version") != "acceptance_checklist.v1":
            failure_reasons.append("acceptance_checklist_schema_invalid")
        checklist_overall_status = str(checklist_payload.get("overall_status") or "")
        items = checklist_payload.get("items")
        if not isinstance(items, list):
            failure_reasons.append("acceptance_checklist_items_missing")
            items = []
        item_ids = {str(item.get("item_id")) for item in items if isinstance(item, dict)}
        missing_item_ids = sorted(_REQUIRED_CHECKLIST_ITEM_IDS - item_ids)
        if missing_item_ids:
            failure_reasons.append(
                "acceptance_checklist_items_incomplete:" + ",".join(missing_item_ids)
            )
        fail_item_ids = sorted(
            str(item.get("item_id"))
            for item in items
            if isinstance(item, dict) and str(item.get("status") or "") == "FAIL"
        )
        if fail_item_ids:
            failure_reasons.append(
                "acceptance_checklist_failed_items:" + ",".join(fail_item_ids)
            )
        if checklist_overall_status == "FAIL":
            failure_reasons.append("acceptance_checklist_overall_status_fail")

    if payload["report_path"] is None and manifest_report_path is not None:
        payload["report_path"] = manifest_report_path
    elif payload["report_path"] is not None and manifest_report_path is not None:
        if not _paths_match_relative_to_repo(
            payload["report_path"],
            manifest_report_path,
            workspace_repo_path,
        ):
            failure_reasons.append("report_path_mismatch_between_terminal_and_manifest")

    workflow_state = "failed"
    if not failure_reasons and overall_verdict == "PASS":
        workflow_state = "completed"
    elif not failure_reasons and overall_verdict in {"CONDITIONAL", "FAIL"}:
        workflow_state = "degraded"

    payload.update(
        {
            "workflow_state": workflow_state,
            "business_overall_verdict": overall_verdict,
            "candidate_id": candidate_id,
            "checklist_overall_status": checklist_overall_status,
            "scenario_count": scenario_count,
            "dimensions_covered": list(normalized_dimensions),
            "contract_failures": failure_reasons,
        }
    )
    return StepOutcome(
        kind="completed",
        state=workflow_state,
        runtime="lobster",
        step_output=payload,
        evidence_merge={context.step["id"]: payload},
        summary="trading acceptance artifact 已收敛",
    )



def callback_send_once_handler(context: StepContext) -> StepOutcome:
    state = context.record["state"]
    if state not in TERMINAL_STATES:
        raise ValueError(f"callback.send_once 只能在终态后执行，当前 state={state}")
    if context.record["callback_status"] != "pending":
        return StepOutcome(
            kind="completed",
            state=state,
            runtime=context.record["runtime"],
            callback_status=context.record["callback_status"],
            step_output=context.record.get("evidence", {}).get("callback", {}).get("last_payload"),
            summary="callback 已存在，跳过重复发送",
        )

    callback_payload = _build_callback_payload(context)
    transport = FileCallbackTransport(context.registry.root_dir)
    transport_result = transport.send(
        task_id=context.task_id,
        payload=callback_payload,
        step_config=context.step,
        workflow_state=state,
    )
    callback_evidence = _build_callback_evidence(context, callback_payload, transport_result)
    summary = "final callback 已发送" if transport_result.callback_status != "failed" else "final callback 发送失败"
    return StepOutcome(
        kind="completed",
        state=state,
        runtime=context.record["runtime"],
        callback_status=transport_result.callback_status,
        step_output=callback_payload,
        evidence_merge={
            "callback": callback_evidence,
            context.step["id"]: callback_payload,
        },
        summary=summary,
    )



def _build_callback_evidence(
    context: StepContext,
    callback_payload: Dict[str, Any],
    transport_result: CallbackTransportResult,
) -> Dict[str, Any]:
    existing = context.record.get("evidence", {}).get("callback", {})
    callback_evidence: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    history = list(callback_evidence.get("history", []))
    history.extend(transport_result.history)
    callback_evidence.update(
        {
            "last_payload": callback_payload,
            "last_result": transport_result.callback_status,
            "last_stage": transport_result.history[-1]["stage"] if transport_result.history else None,
            "history": history,
        }
    )
    if transport_result.delivery is not None:
        callback_evidence["delivery"] = transport_result.delivery
    if transport_result.receipt is not None:
        callback_evidence["receipt"] = transport_result.receipt
    if transport_result.error is not None:
        callback_evidence["error"] = transport_result.error
    return callback_evidence



def _build_callback_payload(context: StepContext) -> Dict[str, Any]:
    payload = {}
    for field_name, source in _iter_payload_fields(context.step.get("payloadFields", [])):
        payload[field_name] = _resolve_callback_field(source, context)
    summary_template = context.step.get("summary")
    if summary_template is not None:
        payload["summary"] = _render_value(summary_template, context)
    return payload



def _iter_payload_fields(fields: Iterable[Any]) -> Iterable[tuple[str, str]]:
    for field in fields:
        if isinstance(field, dict):
            field_name = str(field.get("name") or field.get("field") or "").strip()
            source = str(field.get("path") or field.get("source") or field_name).strip()
            if field_name:
                yield field_name, source
            continue
        field_name = str(field)
        yield field_name, field_name



def _resolve_callback_field(field: str, context: StepContext) -> Any:
    if field == "task_id":
        return context.task_id
    if field == "workflow_id":
        return context.workflow["workflow_id"]
    if field == "workflow_state":
        return context.record["state"]
    if field in context.request:
        return context.request[field]
    if field in context.step_outputs:
        return context.step_outputs[field]
    dotted = _resolve_dotted_path(field, context)
    if dotted is not None:
        return dotted
    return None



def _render_value(value: Any, context: StepContext) -> Any:
    if isinstance(value, str):
        return _render_string(value, context)
    if isinstance(value, list):
        return [_render_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _render_value(item, context) for key, item in value.items()}
    return value



def _render_string(template: str, context: StepContext) -> str:
    def replace(match: re.Match[str]) -> str:
        resolved = _resolve_dotted_path(match.group(1), context)
        if resolved is None:
            return ""
        return str(resolved)

    return _TEMPLATE_RE.sub(replace, template)



def _resolve_dotted_path(path: str, context: StepContext) -> Any:
    path = path.strip()
    roots: Dict[str, Any] = {
        "request": context.request,
        "signal": context.signal or {},
        "steps": context.step_outputs,
        "record": context.record,
        "workflow": context.workflow,
    }
    segments = path.split(".")
    root = roots.get(segments[0])
    if root is None:
        return None
    current: Any = root
    for segment in segments[1:]:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current



def _extract_inline_terminal(context: StepContext) -> Optional[Dict[str, Any]]:
    child_ref = context.step.get("child_session_from")
    if not isinstance(child_ref, str) or child_ref not in context.step_outputs:
        return None
    candidate = context.step_outputs.get(child_ref)
    if not isinstance(candidate, dict):
        return None
    terminal = candidate.get("terminal")
    if isinstance(terminal, dict):
        return terminal
    terminal = candidate.get("terminal_envelope")
    if isinstance(terminal, dict):
        return terminal
    return None



def _tail_text(value: Any, max_chars: int = 2000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None



def _require_workspace_repo_path(context: StepContext) -> Path:
    raw_path = _first_non_empty(context.request.get("workspace_repo_path"))
    if raw_path is None:
        raise ValueError("request.workspace_repo_path 缺失")
    repo_path = Path(raw_path).expanduser().resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        raise ValueError(f"workspace_repo_path 不存在: {repo_path}")
    return repo_path



def _resolve_repo_relative_path(path_value: str, repo_root: Path) -> Path:
    candidate = Path(str(path_value)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (repo_root / candidate).resolve()



def _load_json_path(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))



def _resolve_contract_payload(
    *,
    nested_payload: Any,
    sidecar_path: str | None,
    repo_root: Path,
    expected_key: str,
    failure_reasons: list[str],
) -> Dict[str, Any] | None:
    nested_object = nested_payload if isinstance(nested_payload, dict) else None
    if sidecar_path is None:
        return nested_object

    sidecar_file = _resolve_repo_relative_path(sidecar_path, repo_root)
    if not sidecar_file.exists():
        failure_reasons.append(f"{expected_key}_sidecar_missing")
        return nested_object

    sidecar_payload = _load_json_path(sidecar_file)
    if nested_object is not None and sidecar_payload != nested_object:
        failure_reasons.append(f"{expected_key}_mismatch_between_artifact_and_sidecar")
    return sidecar_payload



def _normalize_dimensions(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(sorted(str(item) for item in value))



def _paths_match_relative_to_repo(left: str, right: str, repo_root: Path) -> bool:
    return _resolve_repo_relative_path(left, repo_root) == _resolve_repo_relative_path(right, repo_root)



def _extract_child_session_key(context: StepContext) -> str | None:
    dispatch_output = context.step_outputs.get("dispatch_acceptance_subagent")
    if not isinstance(dispatch_output, dict):
        return None
    child_session_key = dispatch_output.get("child_session_key")
    return str(child_session_key) if child_session_key is not None else None
