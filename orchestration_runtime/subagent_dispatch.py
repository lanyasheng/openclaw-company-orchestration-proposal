from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from .context_render import render_context_value
from .scheduler import StepContext, StepOutcome
from .task_registry import load_json_file, write_json_atomic

DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789"
DEFAULT_ARTIFACT_NAMESPACE = "subagent_dispatch"


class SubagentDispatchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubagentDispatchRequest:
    task_id: str
    workflow_id: str
    step_id: str
    prompt: str
    workdir: str
    label: str
    session_key: Optional[str] = None
    timeout_seconds: Optional[float] = None
    spawn_args: Dict[str, Any] = field(default_factory=dict)

    def to_spawn_args(self) -> Dict[str, Any]:
        args = dict(self.spawn_args)
        args.update(
            {
                "runtime": "subagent",
                "task": self.prompt,
                "cwd": self.workdir,
                "label": self.label,
            }
        )
        if self.timeout_seconds is not None:
            args["timeoutSeconds"] = self.timeout_seconds
        return args

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "prompt": self.prompt,
            "workdir": self.workdir,
            "label": self.label,
            "session_key": self.session_key,
            "timeout_seconds": self.timeout_seconds,
            "spawn_args": dict(self.spawn_args),
        }


@dataclass(frozen=True)
class SubagentDispatchResult:
    child_session_key: str
    run_handle: Dict[str, Any]
    dispatch_evidence: Dict[str, Any]
    raw_response: Dict[str, Any]


class SubagentSpawnTransport(Protocol):
    transport_name: str

    def spawn(self, request: SubagentDispatchRequest) -> Dict[str, Any]:
        ...


class GatewayToolInvokeSubagentTransport:
    transport_name = "openclaw.gateway.tools_invoke.sessions_spawn"

    def __init__(
        self,
        *,
        gateway_url: Optional[str] = None,
        gateway_token: Optional[str] = None,
        session_key: Optional[str] = None,
        config_path: Optional[Path] = None,
        opener: Optional[Any] = None,
    ) -> None:
        self.gateway_url = (gateway_url or os.getenv("OPENCLAW_GATEWAY_URL") or DEFAULT_GATEWAY_URL).rstrip("/")
        self.gateway_token = gateway_token or os.getenv("OPENCLAW_GATEWAY_TOKEN") or self._load_token_from_config(config_path)
        self.session_key = session_key
        self.opener = opener or urllib_request.build_opener()

    def spawn(self, request: SubagentDispatchRequest) -> Dict[str, Any]:
        if not self.gateway_token:
            raise SubagentDispatchError(
                "缺少 gateway token，无法调用 sessions_spawn；请设置 OPENCLAW_GATEWAY_TOKEN 或 ~/.openclaw/openclaw.json 中的 gateway.auth.token"
            )

        payload: Dict[str, Any] = {
            "tool": "sessions_spawn",
            "args": request.to_spawn_args(),
        }
        effective_session_key = request.session_key or self.session_key
        if effective_session_key:
            payload["sessionKey"] = effective_session_key

        http_request = urllib_request.Request(
            url=f"{self.gateway_url}/tools/invoke",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.gateway_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with self.opener.open(http_request) as response:
                raw_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise SubagentDispatchError(
                f"sessions_spawn HTTP 调用失败: status={exc.code}, body={error_body}"
            ) from exc
        except urllib_error.URLError as exc:
            raise SubagentDispatchError(f"gateway 不可达: {exc.reason}") from exc

        try:
            payload_body = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise SubagentDispatchError(f"gateway 返回了非 JSON 响应: {raw_body}") from exc

        if not payload_body.get("ok"):
            error_payload = payload_body.get("error") or {}
            raise SubagentDispatchError(
                f"sessions_spawn 未成功: {error_payload.get('type') or 'unknown'} / {error_payload.get('message') or payload_body}"
            )

        result = payload_body.get("result")
        if not isinstance(result, dict):
            raise SubagentDispatchError(f"sessions_spawn 返回格式非法: {payload_body}")
        return result

    @staticmethod
    def _load_token_from_config(config_path: Optional[Path]) -> Optional[str]:
        path = config_path or Path.home() / ".openclaw" / "openclaw.json"
        if not path.exists():
            return None
        try:
            config = load_json_file(path)
        except Exception:  # noqa: BLE001 - 配置读取失败时走 env/显式 token 即可
            return None
        gateway = config.get("gateway", {})
        if not isinstance(gateway, dict):
            return None
        auth = gateway.get("auth", {})
        if not isinstance(auth, dict):
            return None
        token = auth.get("token")
        return str(token) if token else None


class SubagentDispatchAdapter:
    def __init__(
        self,
        transport: SubagentSpawnTransport,
        *,
        artifact_namespace: str = DEFAULT_ARTIFACT_NAMESPACE,
    ) -> None:
        self.transport = transport
        self.artifact_namespace = artifact_namespace

    def create_handler(self) -> Callable[[StepContext], StepOutcome]:
        def handler(context: StepContext) -> StepOutcome:
            return self.dispatch(context)

        return handler

    def dispatch(self, context: StepContext) -> StepOutcome:
        dispatch_request = self._build_request(context)
        request_relpath = self._persist_request(context, dispatch_request)

        raw_response = self.transport.spawn(dispatch_request)
        normalized = self._normalize_response(context, dispatch_request, raw_response, request_relpath)

        response_relpath = self._persist_response(context, normalized)
        mapping_relpath = self._persist_child_session_mapping(context, dispatch_request, normalized)

        dispatch_evidence = dict(normalized.dispatch_evidence)
        dispatch_evidence["artifacts"] = {
            "request_path": request_relpath,
            "response_path": response_relpath,
            "child_session_mapping_path": mapping_relpath,
        }

        step_payload = {
            "child_session_key": normalized.child_session_key,
            "run_handle": normalized.run_handle,
            "dispatch_evidence": dispatch_evidence,
        }
        return StepOutcome(
            kind="completed",
            state=str(context.step.get("state", "running")),
            runtime="subagent",
            step_output=step_payload,
            evidence_merge={
                context.step["id"]: step_payload,
                "child_session_key": normalized.child_session_key,
                "run_handle": normalized.run_handle,
            },
            summary=str(context.step.get("summary", f"{context.step['id']} 已派发真实 subagent")),
        )

    def _build_request(self, context: StepContext) -> SubagentDispatchRequest:
        step = context.step
        workflow_id = str(context.workflow["workflow_id"])
        step_id = str(step["id"])

        prompt_template = step.get("task") or step.get("task_prompt") or step.get("prompt")
        if prompt_template is None:
            raise SubagentDispatchError("subagent.dispatch 缺少 task/task_prompt/prompt")
        workdir_template = step.get("workdir") or step.get("cwd")
        if workdir_template is None:
            raise SubagentDispatchError("subagent.dispatch 缺少 workdir/cwd")

        prompt = str(render_context_value(prompt_template, context)).strip()
        workdir = str(render_context_value(workdir_template, context)).strip()
        if not prompt:
            raise SubagentDispatchError("subagent.dispatch prompt 不能为空")
        if not workdir:
            raise SubagentDispatchError("subagent.dispatch workdir 不能为空")

        raw_label = step.get("label") or f"{workflow_id}-{step_id}-{context.task_id}"
        label = self._sanitize_label(str(render_context_value(raw_label, context)).strip())

        session_key = step.get("session_key")
        rendered_session_key = None
        if session_key is not None:
            rendered_session_key = str(render_context_value(session_key, context)).strip() or None

        timeout_seconds = step.get("timeout_seconds")
        rendered_timeout = None
        if timeout_seconds is not None:
            resolved_timeout = render_context_value(timeout_seconds, context)
            rendered_timeout = float(resolved_timeout)

        spawn_args = step.get("spawn_args") or {}
        rendered_spawn_args = render_context_value(spawn_args, context)
        if not isinstance(rendered_spawn_args, dict):
            raise SubagentDispatchError("subagent.dispatch spawn_args 必须渲染为 object")

        return SubagentDispatchRequest(
            task_id=context.task_id,
            workflow_id=workflow_id,
            step_id=step_id,
            prompt=prompt,
            workdir=workdir,
            label=label,
            session_key=rendered_session_key,
            timeout_seconds=rendered_timeout,
            spawn_args=dict(rendered_spawn_args),
        )

    def _normalize_response(
        self,
        context: StepContext,
        dispatch_request: SubagentDispatchRequest,
        raw_response: Mapping[str, Any],
        request_relpath: str,
    ) -> SubagentDispatchResult:
        payload = dict(raw_response)
        child_session_key = payload.get("childSessionKey") or payload.get("child_session_key")
        if not child_session_key:
            raise SubagentDispatchError(f"sessions_spawn 返回缺少 child_session_key: {payload}")

        run_id = payload.get("runId") or payload.get("run_id")
        status = str(payload.get("status") or "accepted")
        mode = str(payload.get("mode") or dispatch_request.spawn_args.get("mode") or "run")

        run_handle = {
            "status": status,
            "mode": mode,
            "run_id": run_id,
            "transport": self.transport.transport_name,
        }
        dispatch_evidence = {
            "transport": self.transport.transport_name,
            "task_id": dispatch_request.task_id,
            "workflow_id": dispatch_request.workflow_id,
            "step_id": dispatch_request.step_id,
            "label": dispatch_request.label,
            "workdir": dispatch_request.workdir,
            "request_path": request_relpath,
            "spawned_at": _now_iso(),
            "gateway_session_key": dispatch_request.session_key,
            "response_excerpt": {
                "status": status,
                "mode": mode,
                "run_id": run_id,
                "child_session_key": child_session_key,
            },
            "prompt_preview": dispatch_request.prompt[:240],
        }
        return SubagentDispatchResult(
            child_session_key=str(child_session_key),
            run_handle=run_handle,
            dispatch_evidence=dispatch_evidence,
            raw_response=payload,
        )

    def _persist_request(self, context: StepContext, dispatch_request: SubagentDispatchRequest) -> str:
        relpath = self._artifact_relpath("requests", context.task_id, context.step["id"])
        payload = {
            "recorded_at": _now_iso(),
            "transport": self.transport.transport_name,
            "dispatch_request": dispatch_request.to_dict(),
        }
        write_json_atomic(context.registry.root_dir / relpath, payload)
        return relpath

    def _persist_response(self, context: StepContext, result: SubagentDispatchResult) -> str:
        relpath = self._artifact_relpath("responses", context.task_id, context.step["id"])
        payload = {
            "recorded_at": _now_iso(),
            "transport": self.transport.transport_name,
            "child_session_key": result.child_session_key,
            "run_handle": result.run_handle,
            "dispatch_evidence": result.dispatch_evidence,
            "raw_response": result.raw_response,
        }
        write_json_atomic(context.registry.root_dir / relpath, payload)
        return relpath

    def _persist_child_session_mapping(
        self,
        context: StepContext,
        dispatch_request: SubagentDispatchRequest,
        result: SubagentDispatchResult,
    ) -> str:
        filename = f"{_safe_file_component(result.child_session_key)}.json"
        relpath = str(Path(self.artifact_namespace) / "by-child-session" / filename)
        payload = {
            "recorded_at": _now_iso(),
            "task_id": dispatch_request.task_id,
            "workflow_id": dispatch_request.workflow_id,
            "step_id": dispatch_request.step_id,
            "child_session_key": result.child_session_key,
            "run_handle": result.run_handle,
            "request": {
                "label": dispatch_request.label,
                "workdir": dispatch_request.workdir,
            },
        }
        write_json_atomic(context.registry.root_dir / relpath, payload)
        return relpath

    def _artifact_relpath(self, category: str, task_id: str, step_id: str) -> str:
        filename = f"{_safe_file_component(task_id)}__{_safe_file_component(step_id)}.json"
        return str(Path(self.artifact_namespace) / category / filename)

    @staticmethod
    def _sanitize_label(label: str) -> str:
        compact = "-".join(segment for segment in label.replace("/", "-").replace(":", "-").split() if segment)
        if not compact:
            compact = "subagent-dispatch"
        return compact[:120]


def create_subagent_dispatch_handler(
    transport: Optional[SubagentSpawnTransport] = None,
    *,
    artifact_namespace: str = DEFAULT_ARTIFACT_NAMESPACE,
) -> Callable[[StepContext], StepOutcome]:
    adapter = SubagentDispatchAdapter(
        transport or GatewayToolInvokeSubagentTransport(),
        artifact_namespace=artifact_namespace,
    )
    return adapter.create_handler()


def _safe_file_component(value: str) -> str:
    return value.replace(":", "__").replace("/", "__")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
