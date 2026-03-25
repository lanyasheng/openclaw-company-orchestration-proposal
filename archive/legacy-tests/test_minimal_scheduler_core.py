from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestration_runtime import (
    FileTaskRegistry,
    GatewayToolInvokeSubagentTransport,
    StepContext,
    StepOutcome,
    SubagentDispatchRequest,
    WorkflowDispatcher,
    await_terminal_handler,
    callback_send_once_handler,
    create_subagent_dispatch_handler,
    init_registry_handler,
    inline_payload_handler,
    load_json_file,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAIN_WORKFLOW_PATH = REPO_ROOT / "examples" / "workflows" / "chain-basic.scheduler.json"


class _FakeSpawnTransport:
    transport_name = "fake.sessions_spawn"

    def __init__(self) -> None:
        self.requests: list[SubagentDispatchRequest] = []

    def spawn(self, request: SubagentDispatchRequest) -> dict:
        self.requests.append(request)
        return {
            "status": "accepted",
            "childSessionKey": "agent:main:subagent:child-001",
            "runId": "run-child-001",
            "mode": "run",
        }


class _ZeroActiveFakeSpawnTransport(_FakeSpawnTransport):
    def spawn(self, request: SubagentDispatchRequest) -> dict:
        payload = super().spawn(request)
        payload["activeTaskCount"] = 0
        return payload


class _FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeOpener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests = []

    def open(self, request):
        self.requests.append(request)
        return _FakeHttpResponse(self.payload)


class FileTaskRegistryTest(unittest.TestCase):
    def test_upsert_patch_deep_merge_preserves_minimal_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = FileTaskRegistry(Path(temp_dir))
            registry.upsert(
                {
                    "task_id": "tsk_registry_core_001",
                    "owner": "zoe",
                    "runtime": "lobster",
                    "state": "queued",
                    "evidence": {
                        "workflow": {"id": "chain-basic"},
                        "child": {"a": 1},
                    },
                    "callback_status": "pending",
                }
            )

            record = registry.patch(
                "tsk_registry_core_001",
                state="running",
                runtime="subagent",
                callback_status="sent",
                evidence_merge={
                    "workflow": {"version": "v1"},
                    "child": {"b": 2},
                    "summary": "spawned",
                },
                continuation={
                    "next_step": "await_terminal",
                    "next_owner": "subagent",
                    "next_backend": "subagent",
                    "auto_continue_if": "subagent_terminal_received",
                    "stop_if": ["manual_abort"],
                    "stopped_because": "waiting_for_subagent_terminal",
                },
            )

            self.assertEqual(record["task_id"], "tsk_registry_core_001")
            self.assertEqual(record["state"], "running")
            self.assertEqual(record["runtime"], "subagent")
            self.assertEqual(record["callback_status"], "sent")
            self.assertEqual(record["evidence"]["workflow"], {"id": "chain-basic", "version": "v1"})
            self.assertEqual(record["evidence"]["child"], {"a": 1, "b": 2})
            self.assertEqual(record["evidence"]["summary"], "spawned")
            self.assertEqual(
                record["continuation"],
                {
                    "next_step": "await_terminal",
                    "next_owner": "subagent",
                    "next_backend": "subagent",
                    "auto_continue_if": ["subagent_terminal_received"],
                    "stop_if": ["manual_abort"],
                    "stopped_because": "waiting_for_subagent_terminal",
                },
            )
            self.assertTrue((Path(temp_dir) / "tasks" / "tsk_registry_core_001.json").exists())


class GatewayTransportContractTest(unittest.TestCase):
    def test_gateway_transport_uses_sessions_spawn_payload(self) -> None:
        opener = _FakeOpener(
            {
                "ok": True,
                "result": {
                    "status": "accepted",
                    "childSessionKey": "agent:main:subagent:child-transport-001",
                    "runId": "run-transport-001",
                    "mode": "run",
                },
            }
        )
        transport = GatewayToolInvokeSubagentTransport(
            gateway_url="http://127.0.0.1:18789",
            gateway_token="test-token",
            session_key="agent:main",
            opener=opener,
        )

        result = transport.spawn(
            SubagentDispatchRequest(
                task_id="tsk_transport_001",
                workflow_id="workflow.transport.v1",
                step_id="dispatch_subagent",
                prompt="请执行 acceptance harness",
                workdir="repos/workspace-trading",
                label="transport-demo",
                timeout_seconds=1800,
                spawn_args={"mode": "run", "thinking": "low"},
            )
        )

        self.assertEqual(result["childSessionKey"], "agent:main:subagent:child-transport-001")
        request = opener.requests[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18789/tools/invoke")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")

        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["tool"], "sessions_spawn")
        self.assertEqual(payload["sessionKey"], "agent:main")
        self.assertEqual(
            payload["args"],
            {
                "runtime": "subagent",
                "task": "请执行 acceptance harness",
                "cwd": "repos/workspace-trading",
                "label": "transport-demo",
                "timeoutSeconds": 1800,
                "mode": "run",
                "thinking": "low",
            },
        )


class MinimalSchedulerCoreTest(unittest.TestCase):
    def make_dispatcher(self, registry_root: Path, transport: _FakeSpawnTransport | None = None) -> WorkflowDispatcher:
        handlers = {
            "control.init_registry": init_registry_handler,
            "control.inline_payload": inline_payload_handler,
            "subagent.await_terminal": await_terminal_handler,
            "callback.send_once": callback_send_once_handler,
            "subagent.dispatch": create_subagent_dispatch_handler(transport or _FakeSpawnTransport()),
            "control.classify_terminal": self.classify_terminal_handler,
        }
        return WorkflowDispatcher(FileTaskRegistry(registry_root), handlers)

    @staticmethod
    def classify_terminal_handler(context: StepContext) -> StepOutcome:
        terminal = context.step_outputs["await_terminal"]
        verdict = (context.signal or {}).get("business_verdict", "PASS")
        if terminal["terminal_state"] != "completed":
            workflow_state = "failed"
        elif verdict == "PASS":
            workflow_state = "completed"
        else:
            workflow_state = "degraded"

        payload = {
            "workflow_state": workflow_state,
            "business_overall_verdict": verdict,
            "terminal_state": terminal["terminal_state"],
            "child_session_key": context.step_outputs["dispatch_acceptance_subagent"]["child_session_key"],
        }
        return StepOutcome(
            kind="completed",
            state=workflow_state,
            runtime="lobster",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="terminal 已分类",
        )

    def test_chain_basic_advances_to_terminal_and_acks_callback(self) -> None:
        workflow = load_json_file(CHAIN_WORKFLOW_PATH)
        request = {
            "task_id": "tsk_chain_scheduler_001",
            "topic": "hello",
            "target": "internal-demo",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher = self.make_dispatcher(Path(temp_dir))
            result = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.record["state"], "completed")
            self.assertEqual(result.record["callback_status"], "acked")
            self.assertEqual(result.executed_steps, ["init_registry", "step_a", "step_b", "final_callback"])
            self.assertEqual(result.record["evidence"]["step_a"], {"status": "ok", "topic": "hello"})
            self.assertEqual(
                result.record["evidence"]["step_b"],
                {"status": "ok", "target": "internal-demo", "message": "hello -> internal-demo"},
            )
            self.assertEqual(
                result.record["evidence"]["callback"]["last_payload"],
                {
                    "task_id": "tsk_chain_scheduler_001",
                    "workflow_id": "chain-basic.scheduler.v1",
                    "workflow_state": "completed",
                    "continuation": {
                        "next_step": "review_result_and_decide_followup_dispatch",
                        "next_owner": "main",
                        "next_backend": "manual",
                        "auto_continue_if": [],
                        "stop_if": ["no_follow_up_needed", "manual_closeout"],
                        "stopped_because": "workflow_completed",
                    },
                    "summary": {
                        "workflow": "chain-basic",
                        "ordered_steps": ["step_a", "step_b", "final_callback"],
                        "evidence_keys": ["input", "step_a", "step_b"],
                    },
                },
            )
            self.assertEqual(
                result.record["continuation"],
                {
                    "next_step": "review_result_and_decide_followup_dispatch",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": [],
                    "stop_if": ["no_follow_up_needed", "manual_closeout"],
                    "stopped_because": "workflow_completed",
                },
            )

    def test_callback_failure_promotes_continuation_to_retry_callback_delivery(self) -> None:
        workflow = load_json_file(CHAIN_WORKFLOW_PATH)
        workflow["steps"][-1]["transport"] = {
            "simulate": "failed",
            "error_code": "receiver_down",
            "error_message": "receiver unavailable",
        }
        request = {
            "task_id": "tsk_chain_scheduler_callback_failed_001",
            "topic": "hello",
            "target": "internal-demo",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher = self.make_dispatcher(Path(temp_dir))
            result = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.record["state"], "completed")
            self.assertEqual(result.record["callback_status"], "failed")
            self.assertEqual(
                result.record["evidence"]["callback"]["last_payload"]["continuation"],
                {
                    "next_step": "review_result_and_decide_followup_dispatch",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": [],
                    "stop_if": ["no_follow_up_needed", "manual_closeout"],
                    "stopped_because": "workflow_completed",
                },
            )
            self.assertEqual(
                result.record["continuation"],
                {
                    "next_step": "retry_final_callback_delivery",
                    "next_owner": "callback_plane",
                    "next_backend": "callback",
                    "auto_continue_if": ["callback_transport_recovered", "manual_retry_requested"],
                    "stop_if": ["manual_abort", "task_cancelled"],
                    "stopped_because": "final_callback_delivery_failed",
                },
            )

    def test_trading_like_workflow_waits_for_terminal_and_persists_dispatch_artifacts(self) -> None:
        workflow = {
            "workflow_id": "workspace-trading.acceptance-harness.scheduler.v1",
            "owner": "main",
            "mode": "chain-basic",
            "steps": [
                {"id": "init_registry", "type": "control.init_registry"},
                {
                    "id": "validate_request",
                    "type": "control.inline_payload",
                    "state": "running",
                    "output": {
                        "workspace_repo_path": "{{request.workspace_repo_path}}",
                        "input_config_path": "{{request.input_config_path}}",
                    },
                },
                {
                    "id": "dispatch_acceptance_subagent",
                    "type": "subagent.dispatch",
                    "task": "python3 research/run_acceptance_harness.py --input {{request.input_config_path}}",
                    "workdir": "{{request.workspace_repo_path}}",
                    "label": "acceptance-{{request.run_label}}",
                    "timeout_seconds": 1800,
                    "spawn_args": {"mode": "run", "thinking": "low"},
                },
                {
                    "id": "await_terminal",
                    "type": "subagent.await_terminal",
                    "child_session_from": "dispatch_acceptance_subagent",
                    "signal_key": "terminal",
                },
                {"id": "collect_and_classify", "type": "control.classify_terminal"},
                {
                    "id": "final_callback",
                    "type": "callback.send_once",
                    "payloadFields": ["task_id", "workflow_id", "workflow_state", "run_label"],
                },
            ],
        }
        request = {
            "task_id": "tsk_trading_scheduler_001",
            "workspace_repo_path": "repos/workspace-trading",
            "input_config_path": "research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json",
            "run_label": "dry-run-001",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            transport = _FakeSpawnTransport()
            dispatcher = self.make_dispatcher(Path(temp_dir), transport=transport)
            first = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)

            self.assertEqual(first.status, "waiting")
            self.assertEqual(first.current_step_id, "await_terminal")
            self.assertEqual(first.waiting_for, {"step_id": "await_terminal", "kind": "subagent_terminal"})
            self.assertEqual(first.record["state"], "running")
            self.assertEqual(first.record["runtime"], "subagent")
            self.assertEqual(first.record["callback_status"], "pending")
            self.assertEqual(
                first.record["continuation"],
                {
                    "next_step": "await_terminal",
                    "next_owner": "subagent",
                    "next_backend": "subagent",
                    "auto_continue_if": ["subagent_terminal_received"],
                    "stop_if": ["subagent_timeout", "manual_abort"],
                    "stopped_because": "waiting_for_subagent_terminal",
                },
            )
            self.assertEqual(len(transport.requests), 1)

            dispatch_step = first.record["evidence"]["dispatch_acceptance_subagent"]
            self.assertEqual(dispatch_step["child_session_key"], "agent:main:subagent:child-001")
            self.assertEqual(
                dispatch_step["run_handle"],
                {
                    "status": "accepted",
                    "mode": "run",
                    "run_id": "run-child-001",
                    "transport": "fake.sessions_spawn",
                },
            )

            dispatch_evidence = dispatch_step["dispatch_evidence"]
            request_path = Path(temp_dir) / dispatch_evidence["artifacts"]["request_path"]
            response_path = Path(temp_dir) / dispatch_evidence["artifacts"]["response_path"]
            mapping_path = Path(temp_dir) / dispatch_evidence["artifacts"]["child_session_mapping_path"]
            self.assertTrue(request_path.exists())
            self.assertTrue(response_path.exists())
            self.assertTrue(mapping_path.exists())

            request_artifact = json.loads(request_path.read_text(encoding="utf-8"))
            self.assertEqual(
                request_artifact["dispatch_request"],
                {
                    "task_id": "tsk_trading_scheduler_001",
                    "workflow_id": "workspace-trading.acceptance-harness.scheduler.v1",
                    "step_id": "dispatch_acceptance_subagent",
                    "prompt": "python3 research/run_acceptance_harness.py --input research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json",
                    "workdir": "repos/workspace-trading",
                    "label": "acceptance-dry-run-001",
                    "session_key": None,
                    "timeout_seconds": 1800.0,
                    "spawn_args": {"mode": "run", "thinking": "low"},
                },
            )

            mapping_artifact = json.loads(mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(mapping_artifact["task_id"], "tsk_trading_scheduler_001")
            self.assertEqual(mapping_artifact["workflow_id"], "workspace-trading.acceptance-harness.scheduler.v1")
            self.assertEqual(mapping_artifact["step_id"], "dispatch_acceptance_subagent")
            self.assertEqual(mapping_artifact["child_session_key"], "agent:main:subagent:child-001")

            still_waiting = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)
            self.assertEqual(still_waiting.status, "waiting")
            self.assertEqual(still_waiting.current_step_id, "await_terminal")
            self.assertNotIn("collect_and_classify", still_waiting.record["evidence"])

            resumed = dispatcher.dispatch(
                workflow,
                task_id=request["task_id"],
                request=request,
                signal={
                    "terminal": {
                        "terminal_state": "completed",
                        "completed_at": "2026-03-19T13:30:00Z",
                        "artifacts": {
                            "artifact_json_path": "artifacts/acceptance/dry-run-001.json",
                            "report_path": "reports/acceptance/dry-run-001.md",
                        },
                    },
                    "business_verdict": "CONDITIONAL",
                },
            )

            self.assertEqual(resumed.status, "degraded")
            self.assertEqual(resumed.record["state"], "degraded")
            self.assertEqual(resumed.record["runtime"], "lobster")
            self.assertEqual(resumed.record["callback_status"], "acked")
            self.assertEqual(
                resumed.record["evidence"]["collect_and_classify"],
                {
                    "workflow_state": "degraded",
                    "business_overall_verdict": "CONDITIONAL",
                    "terminal_state": "completed",
                    "child_session_key": "agent:main:subagent:child-001",
                },
            )
            self.assertEqual(
                resumed.record["evidence"]["callback"]["last_payload"],
                {
                    "task_id": "tsk_trading_scheduler_001",
                    "workflow_id": "workspace-trading.acceptance-harness.scheduler.v1",
                    "workflow_state": "degraded",
                    "run_label": "dry-run-001",
                    "continuation": {
                        "next_step": "review_degraded_result_and_decide_retry_or_fallback",
                        "next_owner": "main",
                        "next_backend": "manual",
                        "auto_continue_if": ["operator_confirms_retry", "operator_confirms_followup_dispatch"],
                        "stop_if": ["manual_closeout", "accept_degraded_outcome"],
                        "stopped_because": "workflow_degraded",
                    },
                },
            )
            self.assertEqual(
                resumed.record["continuation"],
                {
                    "next_step": "review_degraded_result_and_decide_retry_or_fallback",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": ["operator_confirms_retry", "operator_confirms_followup_dispatch"],
                    "stop_if": ["manual_closeout", "accept_degraded_outcome"],
                    "stopped_because": "workflow_degraded",
                },
            )
            self.assertIsNone(resumed.current_step_id)
            self.assertIsNone(resumed.waiting_for)

    def test_trading_like_waiting_without_active_execution_is_hard_closed(self) -> None:
        workflow = {
            "workflow_id": "workspace-trading.acceptance-harness.scheduler.v1",
            "owner": "main",
            "mode": "chain-basic",
            "steps": [
                {"id": "init_registry", "type": "control.init_registry"},
                {
                    "id": "validate_request",
                    "type": "control.inline_payload",
                    "state": "running",
                    "output": {
                        "workspace_repo_path": "{{request.workspace_repo_path}}",
                        "input_config_path": "{{request.input_config_path}}",
                    },
                },
                {
                    "id": "dispatch_acceptance_subagent",
                    "type": "subagent.dispatch",
                    "task": "python3 research/run_acceptance_harness.py --input {{request.input_config_path}}",
                    "workdir": "{{request.workspace_repo_path}}",
                    "label": "acceptance-{{request.run_label}}",
                    "timeout_seconds": 1800,
                    "spawn_args": {"mode": "run", "thinking": "low"},
                },
                {
                    "id": "await_terminal",
                    "type": "subagent.await_terminal",
                    "child_session_from": "dispatch_acceptance_subagent",
                    "signal_key": "terminal",
                },
                {"id": "collect_and_classify", "type": "control.classify_terminal"},
                {
                    "id": "final_callback",
                    "type": "callback.send_once",
                    "payloadFields": ["task_id", "workflow_id", "workflow_state", "run_label"],
                },
            ],
        }
        request = {
            "task_id": "tsk_trading_scheduler_zero_active_001",
            "workspace_repo_path": "repos/workspace-trading",
            "input_config_path": "research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json",
            "run_label": "dry-run-zero-active",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            transport = _ZeroActiveFakeSpawnTransport()
            dispatcher = self.make_dispatcher(Path(temp_dir), transport=transport)
            result = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.record["state"], "failed")
            self.assertEqual(result.record["runtime"], "lobster")
            self.assertEqual(result.record["callback_status"], "pending")
            self.assertEqual(
                result.record["continuation"],
                {
                    "next_step": "rerun_subagent_dispatch_with_fresh_session",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": ["operator_confirms_rerun"],
                    "stop_if": ["manual_closeout", "accept_missing_artifact"],
                    "stopped_because": "subagent_waiting_without_active_execution",
                },
            )
            self.assertEqual(
                result.record["evidence"]["waiting_anomaly"],
                {
                    "code": "subagent_waiting_without_active_execution",
                    "resolution": "dropped",
                    "summary": "waiting_for=subagent_terminal for agent:main:subagent:child-001 but active_task_count=0",
                    "child_session_key": "agent:main:subagent:child-001",
                    "active_task_count": 0,
                },
            )
            self.assertEqual(
                result.record["evidence"]["closeout"],
                {
                    "stopped_because": "subagent_waiting_without_active_execution",
                    "next_step": "rerun_subagent_dispatch_with_fresh_session",
                    "next_owner": "main",
                    "dispatch_readiness": "blocked",
                },
            )
            self.assertEqual(result.record["evidence"]["scheduler"]["steps"]["await_terminal"]["status"], "dropped")
            self.assertIsNone(result.record["evidence"]["scheduler"]["waiting_for"])
            self.assertIsNone(result.waiting_for)
            self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
