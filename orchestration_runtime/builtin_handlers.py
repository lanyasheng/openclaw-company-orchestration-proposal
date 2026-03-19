from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from .scheduler import StepContext, StepOutcome
from .task_registry import TERMINAL_STATES

_TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


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


def await_terminal_handler(context: StepContext) -> StepOutcome:
    signal_key = str(context.step.get("signal_key", "terminal"))
    terminal_signal = (context.signal or {}).get(signal_key)
    if terminal_signal is None:
        child_ref = context.step.get("child_session_from")
        child_session_key: Optional[str] = None
        if isinstance(child_ref, str) and child_ref in context.step_outputs:
            candidate = context.step_outputs.get(child_ref)
            if isinstance(candidate, dict):
                child_session_key = candidate.get("child_session_key")
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

    if not isinstance(terminal_signal, dict):
        raise ValueError("terminal signal 必须是 object")

    terminal_output = dict(terminal_signal)
    return StepOutcome(
        kind="completed",
        state="running",
        runtime="lobster",
        step_output=terminal_output,
        evidence_merge={context.step["id"]: terminal_output},
        summary="收到 subagent terminal",
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
    callback_evidence = {
        "last_payload": callback_payload,
        "last_result": str(context.step.get("delivery_result", "acked")),
    }
    return StepOutcome(
        kind="completed",
        state=state,
        runtime=context.record["runtime"],
        callback_status=str(context.step.get("delivery_result", "acked")),
        step_output=callback_payload,
        evidence_merge={
            "callback": callback_evidence,
            context.step["id"]: callback_payload,
        },
        summary="final callback 已发送",
    )


def _build_callback_payload(context: StepContext) -> Dict[str, Any]:
    payload = {}
    for field in _iter_payload_fields(context.step.get("payloadFields", [])):
        payload[field] = _resolve_callback_field(field, context)
    summary_template = context.step.get("summary")
    if summary_template is not None:
        payload["summary"] = _render_value(summary_template, context)
    return payload


def _iter_payload_fields(fields: Iterable[Any]) -> Iterable[str]:
    for field in fields:
        yield str(field)


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
