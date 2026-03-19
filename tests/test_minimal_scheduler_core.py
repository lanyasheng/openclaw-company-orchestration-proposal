from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestration_runtime import (
    FileTaskRegistry,
    StepContext,
    StepOutcome,
    WorkflowDispatcher,
    await_terminal_handler,
    callback_send_once_handler,
    init_registry_handler,
    inline_payload_handler,
    load_json_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAIN_WORKFLOW_PATH = REPO_ROOT / "examples" / "workflows" / "chain-basic.scheduler.json"


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
            )

            self.assertEqual(record["task_id"], "tsk_registry_core_001")
            self.assertEqual(record["state"], "running")
            self.assertEqual(record["runtime"], "subagent")
            self.assertEqual(record["callback_status"], "sent")
            self.assertEqual(record["evidence"]["workflow"], {"id": "chain-basic", "version": "v1"})
            self.assertEqual(record["evidence"]["child"], {"a": 1, "b": 2})
            self.assertEqual(record["evidence"]["summary"], "spawned")
            self.assertTrue((Path(temp_dir) / "tasks" / "tsk_registry_core_001.json").exists())


class MinimalSchedulerCoreTest(unittest.TestCase):
    def make_dispatcher(self, registry_root: Path) -> WorkflowDispatcher:
        handlers = {
            "control.init_registry": init_registry_handler,
            "control.inline_payload": inline_payload_handler,
            "subagent.await_terminal": await_terminal_handler,
            "callback.send_once": callback_send_once_handler,
            "subagent.dispatch": self.subagent_dispatch_handler,
            "control.classify_terminal": self.classify_terminal_handler,
        }
        return WorkflowDispatcher(FileTaskRegistry(registry_root), handlers)

    @staticmethod
    def subagent_dispatch_handler(context: StepContext) -> StepOutcome:
        child_session_key = f"agent:main:subagent:{context.task_id}"
        payload = {
            "child_session_key": child_session_key,
            "command": ["python3", "research/run_acceptance_harness.py"],
            "target_repo": context.request.get("workspace_repo", "workspace-trading"),
        }
        return StepOutcome(
            kind="completed",
            state="running",
            runtime="subagent",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="subagent 已派发",
        )

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
                    "summary": {
                        "workflow": "chain-basic",
                        "ordered_steps": ["step_a", "step_b", "final_callback"],
                        "evidence_keys": ["input", "step_a", "step_b"],
                    },
                },
            )

    def test_trading_like_workflow_waits_for_terminal_then_resumes(self) -> None:
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
                        "workspace_repo": "{{request.workspace_repo}}",
                        "input_config_path": "{{request.input_config_path}}",
                    },
                },
                {"id": "dispatch_acceptance_subagent", "type": "subagent.dispatch"},
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
                    "payloadFields": [
                        "task_id",
                        "workflow_id",
                        "workflow_state",
                        "run_label"
                    ]
                },
            ],
        }
        request = {
            "task_id": "tsk_trading_scheduler_001",
            "workspace_repo": "workspace-trading",
            "input_config_path": "research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json",
            "run_label": "dry-run-001",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            dispatcher = self.make_dispatcher(Path(temp_dir))
            first = dispatcher.dispatch(workflow, task_id=request["task_id"], request=request)

            self.assertEqual(first.status, "waiting")
            self.assertEqual(first.current_step_id, "await_terminal")
            self.assertEqual(first.waiting_for, {"step_id": "await_terminal", "kind": "subagent_terminal"})
            self.assertEqual(first.record["state"], "running")
            self.assertEqual(first.record["runtime"], "subagent")
            self.assertEqual(first.record["callback_status"], "pending")
            self.assertNotIn("collect_and_classify", first.record["evidence"])

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
                    "child_session_key": "agent:main:subagent:tsk_trading_scheduler_001",
                },
            )
            self.assertEqual(
                resumed.record["evidence"]["callback"]["last_payload"],
                {
                    "task_id": "tsk_trading_scheduler_001",
                    "workflow_id": "workspace-trading.acceptance-harness.scheduler.v1",
                    "workflow_state": "degraded",
                    "run_label": "dry-run-001",
                },
            )
            self.assertIsNone(resumed.current_step_id)
            self.assertIsNone(resumed.waiting_for)


if __name__ == "__main__":
    unittest.main()
