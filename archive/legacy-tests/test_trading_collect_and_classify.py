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
    collect_and_classify_handler,
    init_registry_handler,
    inline_payload_handler,
)


REQUIRED_DIMENSIONS = ["etf_basket", "stock_basket", "oos", "regime"]
REQUIRED_CHECKLIST_ITEM_IDS = [
    "run_label_recorded",
    "candidate_id_recorded",
    "input_config_path_recorded",
    "artifact_path_recorded",
    "report_path_recorded",
    "git_commit_recorded",
    "test_commands_recorded",
    "verdict_summary_recorded",
]


class TradingCollectAndClassifyTest(unittest.TestCase):
    def make_dispatcher(self, registry_root: Path) -> WorkflowDispatcher:
        handlers = {
            "control.init_registry": init_registry_handler,
            "control.inline_payload": inline_payload_handler,
            "subagent.await_terminal": await_terminal_handler,
            "control.collect_and_classify": collect_and_classify_handler,
            "callback.send_once": callback_send_once_handler,
            "subagent.dispatch": self.dispatch_stub_handler,
        }
        return WorkflowDispatcher(FileTaskRegistry(registry_root), handlers)

    @staticmethod
    def dispatch_stub_handler(context: StepContext) -> StepOutcome:
        artifact_json_path = str(context.request["artifact_json_path"])
        report_path = str(context.request["report_path"])
        payload = {
            "child_session_key": f"agent:main:subagent:{context.task_id}",
            "terminal": {
                "terminal_state": "completed",
                "completed_at": "2026-03-20T00:10:00Z",
                "exit_code": 0,
                "artifacts": {
                    "artifact_json_path": artifact_json_path,
                    "report_path": report_path,
                },
            },
        }
        return StepOutcome(
            kind="completed",
            state="running",
            runtime="subagent",
            step_output=payload,
            evidence_merge={context.step["id"]: payload},
            summary="stub terminal ready",
        )

    @staticmethod
    def workflow_definition() -> dict:
        return {
            "workflow_id": "workspace-trading.acceptance-harness-dry-run.v1",
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
                        "artifact_json_path": "{{request.artifact_json_path}}",
                        "report_path": "{{request.report_path}}",
                    },
                },
                {"id": "dispatch_acceptance_subagent", "type": "subagent.dispatch"},
                {
                    "id": "await_terminal",
                    "type": "subagent.await_terminal",
                    "child_session_from": "dispatch_acceptance_subagent",
                    "signal_key": "terminal",
                },
                {
                    "id": "collect_and_classify",
                    "type": "control.collect_and_classify",
                    "required_scenario_count": 4,
                    "required_dimensions": REQUIRED_DIMENSIONS,
                },
                {
                    "id": "final_callback",
                    "type": "callback.send_once",
                    "payloadFields": [
                        "task_id",
                        "workflow_id",
                        "run_label",
                        "workflow_state",
                        {
                            "name": "business_overall_verdict",
                            "path": "steps.collect_and_classify.business_overall_verdict",
                        },
                        {
                            "name": "candidate_id",
                            "path": "steps.collect_and_classify.candidate_id",
                        },
                    ],
                    "continuation": {
                        "next_step": "review_acceptance_result_and_decide_dispatch",
                        "next_owner": "main",
                        "next_backend": "manual",
                        "auto_continue_if": [
                            "business_overall_verdict=PASS",
                            "whitelist_allows_triggered_dispatch",
                        ],
                        "stop_if": [
                            "business_overall_verdict!=PASS",
                            "artifacts_incomplete",
                            "human_override_stop",
                        ],
                        "stopped_because": "acceptance_result_ready_for_dispatch_decision",
                    },
                },
            ],
        }

    def build_request(self, repo_root: Path, artifact_json_path: str, report_path: str, *, run_label: str) -> dict:
        return {
            "task_id": f"tsk_{run_label}",
            "run_label": run_label,
            "workspace_repo": "workspace-trading",
            "workspace_repo_path": str(repo_root),
            "artifact_json_path": artifact_json_path,
            "report_path": report_path,
        }

    def write_artifact(self, repo_root: Path, *, verdict: str, run_label: str) -> tuple[str, str]:
        artifacts_dir = repo_root / "artifacts" / "acceptance" / run_label
        reports_dir = repo_root / "reports" / "acceptance" / run_label
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

        artifact_rel = f"artifacts/acceptance/{run_label}/acceptance_harness_{run_label}.json"
        report_rel = f"reports/acceptance/{run_label}/acceptance_harness_{run_label}.md"
        artifact_path = repo_root / artifact_rel
        report_path = repo_root / report_rel

        checklist_items = [
            {"item_id": item_id, "status": "PASS", "detail": item_id}
            for item_id in REQUIRED_CHECKLIST_ITEM_IDS
        ]
        payload = {
            "manifest_version": "acceptance_harness.v1",
            "generated_at": "2026-03-20T00:00:00Z",
            "run_label": run_label,
            "candidate": {
                "strategy_name": "RelativeStrengthRotationStrategy",
                "strategy_template_id": "relative_strength_rotation",
                "candidate_id": f"candidate-{run_label}",
                "rebalance_frequency": "weekly",
                "parameters": {},
            },
            "summary": {
                "scenario_count": 4,
                "dimensions_covered": ["etf_basket", "oos", "regime", "stock_basket"],
                "verdict_counts": {"PASS": 1, "CONDITIONAL": 1, "FAIL": 2},
                "tradability_counts": {"PASS": 1, "CONDITIONAL": 1, "FAIL": 2},
            },
            "scenarios": [],
            "acceptance_manifest": {
                "schema_version": "acceptance_manifest.v1",
                "generated_at": "2026-03-20T00:00:00Z",
                "run_label": run_label,
                "candidate_id": f"candidate-{run_label}",
                "input_config_path": "research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json",
                "generated_artifact_path": artifact_rel,
                "report_path": report_rel,
                "git_commit": "abc1234",
                "test_commands": ["python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py -q"],
                "verdict_summary": {
                    "overall_verdict": verdict,
                    "scenario_count": 4,
                    "dimensions_covered": ["etf_basket", "oos", "regime", "stock_basket"],
                },
            },
            "acceptance_checklist": {
                "schema_version": "acceptance_checklist.v1",
                "generated_at": "2026-03-20T00:00:00Z",
                "overall_status": "PASS",
                "items": checklist_items,
            },
        }
        artifact_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(f"# report {run_label}\n", encoding="utf-8")
        return artifact_rel, report_rel

    def assert_terminal_mapping(self, verdict: str, expected_state: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "workspace-trading"
            repo_root.mkdir(parents=True, exist_ok=True)
            artifact_json_path, report_path = self.write_artifact(
                repo_root,
                verdict=verdict,
                run_label=verdict.lower(),
            )
            request = self.build_request(
                repo_root,
                artifact_json_path,
                report_path,
                run_label=verdict.lower(),
            )
            dispatcher = self.make_dispatcher(Path(temp_dir) / "runtime")
            result = dispatcher.dispatch(
                self.workflow_definition(),
                task_id=request["task_id"],
                request=request,
            )

            self.assertEqual(result.status, expected_state)
            self.assertEqual(result.record["state"], expected_state)
            self.assertEqual(result.record["callback_status"], "acked")
            self.assertEqual(
                result.record["evidence"]["collect_and_classify"]["business_overall_verdict"],
                verdict,
            )
            self.assertEqual(
                result.record["evidence"]["collect_and_classify"]["terminal_state"],
                "completed",
            )
            self.assertEqual(
                result.record["evidence"]["callback"]["last_payload"]["business_overall_verdict"],
                verdict,
            )
            self.assertEqual(
                result.record["evidence"]["callback"]["last_payload"]["candidate_id"],
                f"candidate-{verdict.lower()}",
            )
            self.assertEqual(
                result.record["evidence"]["callback"]["last_payload"]["continuation"],
                {
                    "next_step": "review_acceptance_result_and_decide_dispatch",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": [
                        "business_overall_verdict=PASS",
                        "whitelist_allows_triggered_dispatch",
                    ],
                    "stop_if": [
                        "business_overall_verdict!=PASS",
                        "artifacts_incomplete",
                        "human_override_stop",
                    ],
                    "stopped_because": "acceptance_result_ready_for_dispatch_decision",
                },
            )
            self.assertEqual(
                result.record["continuation"],
                {
                    "next_step": "review_acceptance_result_and_decide_dispatch",
                    "next_owner": "main",
                    "next_backend": "manual",
                    "auto_continue_if": [
                        "business_overall_verdict=PASS",
                        "whitelist_allows_triggered_dispatch",
                    ],
                    "stop_if": [
                        "business_overall_verdict!=PASS",
                        "artifacts_incomplete",
                        "human_override_stop",
                    ],
                    "stopped_because": "acceptance_result_ready_for_dispatch_decision",
                },
            )

    def test_pass_verdict_maps_to_completed(self) -> None:
        self.assert_terminal_mapping("PASS", "completed")

    def test_conditional_verdict_maps_to_degraded(self) -> None:
        self.assert_terminal_mapping("CONDITIONAL", "degraded")

    def test_fail_verdict_maps_to_degraded(self) -> None:
        self.assert_terminal_mapping("FAIL", "degraded")


if __name__ == "__main__":
    unittest.main()
