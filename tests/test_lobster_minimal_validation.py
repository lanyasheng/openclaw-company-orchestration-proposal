from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from poc.lobster_minimal_validation.poc_runner import PocRunner


class LobsterMinimalValidationTest(unittest.TestCase):
    def make_runner(self) -> PocRunner:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return PocRunner(Path(temp_dir.name))

    def make_human_payload(
        self,
        *,
        request_transport: str = "file",
        request_source_ref: str | None = None,
    ) -> dict:
        if request_source_ref is None:
            request_source_ref = (
                "local://human-gate/request/tsk_p0_human_001"
                if request_transport == "file"
                else "discord:channel:1483883339701158102:message:1483900000000000000"
            )
        return {
            "task_id": "tsk_p0_human_001",
            "change": "deploy-demo",
            "requires_approval": True,
            "resume_token": "lobster_resume_tsk_p0_human_001",
            "request_transport": request_transport,
            "request_source_ref": request_source_ref,
            "approval_prompt": "是否批准 deploy-demo?",
            "timeout_ms": 1_800_000,
        }

    def make_decision_payload(
        self,
        verdict: str,
        *,
        actor_id: str = "user_boss",
        reason: str | None = None,
        transport: str = "file",
        ref: str | None = None,
    ) -> dict:
        if ref is None:
            ref = (
                f"poc/lobster_minimal_validation/inputs/human-gate-decision-{verdict}.json"
                if transport == "file"
                else "discord:channel:1483883339701158102:message:1483900000000000000"
            )
        payload = {
            "decision_id": f"dec_{verdict}_001",
            "task_id": "tsk_p0_human_001",
            "resume_token": "lobster_resume_tsk_p0_human_001",
            "verdict": verdict,
            "source": {
                "transport": transport,
                "ref": ref,
            },
            "actor": {
                "id": actor_id,
                "name": "老板" if actor_id != "system" else "system",
            },
            "decided_at": "2026-03-19T08:31:12Z",
        }
        if reason:
            payload["reason"] = reason
        return payload

    def test_chain_completes_and_callback_only_once(self) -> None:
        runner = self.make_runner()
        result = runner.run_chain(
            {"task_id": "tsk_p0_chain_001", "topic": "hello", "target": "internal-demo"}
        )
        registry = result["registry"]
        self.assertEqual(registry["state"], "completed")
        self.assertEqual(registry["callback_status"], "acked")
        self.assertEqual([item["state"] for item in registry["state_history"]], ["queued", "running", "completed"])
        self.assertEqual(result["callback"]["result"], "completed")

    def test_human_gate_approve_path_records_request_decision_and_resolution(self) -> None:
        runner = self.make_runner()
        result = runner.run_human_gate(
            self.make_human_payload(),
            decision_payload=self.make_decision_payload("approve"),
        )
        registry = result["registry"]
        states = [item["state"] for item in registry["state_history"]]
        human_gate = registry["evidence"]["human_gate"]

        self.assertEqual(states, ["queued", "running", "waiting_human", "running", "completed"])
        self.assertEqual(registry["state"], "completed")
        self.assertFalse(human_gate["decision"]["native"])
        self.assertEqual(human_gate["request"]["transport"], "file")
        self.assertEqual(human_gate["decision"]["verdict"], "approve")
        self.assertEqual(human_gate["resolution"]["status"], "resumed")
        self.assertEqual(result["callback"]["result"], "completed")

    def test_human_gate_message_approve_path_consumes_message_decision_payload(self) -> None:
        runner = self.make_runner()
        human_payload = self.make_human_payload(request_transport="message")
        result = runner.run_human_gate(
            human_payload,
            decision_payload=self.make_decision_payload(
                "approve",
                transport="message",
                ref=human_payload["request_source_ref"],
            ),
        )
        registry = result["registry"]
        human_gate = registry["evidence"]["human_gate"]

        self.assertEqual(registry["state"], "completed")
        self.assertEqual(result["callback"]["result"], "completed")
        self.assertEqual(human_gate["request"]["transport"], "message")
        self.assertEqual(human_gate["request"]["source_ref"], human_payload["request_source_ref"])
        self.assertEqual(human_gate["decision"]["source"]["transport"], "message")
        self.assertEqual(human_gate["decision"]["source"]["ref"], human_payload["request_source_ref"])
        self.assertEqual(human_gate["resolution"]["status"], "resumed")

    def test_human_gate_message_reject_path_consumes_message_decision_payload(self) -> None:
        runner = self.make_runner()
        human_payload = self.make_human_payload(request_transport="message")
        result = runner.run_human_gate(
            human_payload,
            decision_payload=self.make_decision_payload(
                "reject",
                transport="message",
                ref=human_payload["request_source_ref"],
                reason="change_risk_too_high",
            ),
        )
        registry = result["registry"]
        human_gate = registry["evidence"]["human_gate"]

        self.assertEqual(registry["state"], "degraded")
        self.assertEqual(result["callback"]["result"], "degraded")
        self.assertEqual(human_gate["request"]["transport"], "message")
        self.assertEqual(human_gate["decision"]["source"]["transport"], "message")
        self.assertEqual(human_gate["decision"]["source"]["ref"], human_payload["request_source_ref"])
        self.assertEqual(human_gate["resolution"]["status"], "rejected")
        self.assertEqual(human_gate["resolution"]["reason"], "change_risk_too_high")

    def test_human_gate_non_approve_verdicts_follow_expected_terminal_states(self) -> None:
        runner = self.make_runner()
        cases = [
            ("reject", "degraded", "degraded", "rejected", "human_rejected"),
            ("timeout", "failed", "failed", "timed_out", "approval_timeout"),
            ("withdraw", "degraded", "degraded", "withdrawn", "request_withdrawn"),
        ]

        for verdict, expected_state, expected_result, resolution_status, default_reason in cases:
            with self.subTest(verdict=verdict):
                decision_payload = self.make_decision_payload(
                    verdict,
                    actor_id="system" if verdict == "timeout" else "user_boss",
                )
                result = runner.run_human_gate(self.make_human_payload(), decision_payload=decision_payload)
                registry = result["registry"]
                human_gate = registry["evidence"]["human_gate"]

                self.assertEqual(registry["state"], expected_state)
                self.assertEqual(result["callback"]["result"], expected_result)
                self.assertEqual(human_gate["decision"]["verdict"], verdict)
                self.assertEqual(human_gate["resolution"]["status"], resolution_status)
                self.assertEqual(human_gate["resolution"]["reason"], default_reason)
                self.assertEqual(registry["callback_status"], "acked")

    def test_human_gate_reject_uses_explicit_reason_when_provided(self) -> None:
        runner = self.make_runner()
        result = runner.run_human_gate(
            self.make_human_payload(),
            decision_payload=self.make_decision_payload("reject", reason="change_risk_too_high"),
        )
        resolution = result["registry"]["evidence"]["human_gate"]["resolution"]
        self.assertEqual(resolution["reason"], "change_risk_too_high")

    def test_human_gate_requires_matching_resume_token(self) -> None:
        runner = self.make_runner()
        decision_payload = self.make_decision_payload("approve")
        decision_payload["resume_token"] = "lobster_resume_wrong"

        with self.assertRaisesRegex(ValueError, "resume_token"):
            runner.run_human_gate(self.make_human_payload(), decision_payload=decision_payload)

    def test_failure_branch_degrades_with_stub(self) -> None:
        runner = self.make_runner()
        result = runner.run_failure_branch(
            {"task_id": "tsk_p0_fail_001", "mode": "force_fail_step_b", "target": "internal-demo"}
        )
        registry = result["registry"]
        self.assertEqual(registry["state"], "degraded")
        self.assertEqual(registry["evidence"]["error"], "forced_failure_at_step_b")
        self.assertFalse(registry["evidence"]["failure_branch"]["native"])
        self.assertEqual(result["callback"]["result"], "degraded")

    def test_run_poc_reads_decision_file(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "input.json"
            decision_path = temp_path / "decision.json"
            output_dir = temp_path / "run-output"

            input_path.write_text(json.dumps(self.make_human_payload(request_transport="message")), encoding="utf-8")
            decision_path.write_text(
                json.dumps(self.make_decision_payload("approve", transport="message")),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "poc.lobster_minimal_validation.run_poc",
                    "human-gate",
                    "--input",
                    str(input_path),
                    "--decision-file",
                    str(decision_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["callback"]["result"], "completed")
            self.assertEqual(payload["registry"]["evidence"]["human_gate"]["decision"]["verdict"], "approve")
            self.assertEqual(payload["registry"]["evidence"]["human_gate"]["decision"]["source"]["transport"], "message")
            self.assertTrue((output_dir / "registry.json").exists())
            self.assertTrue((output_dir / "callback.json").exists())


if __name__ == "__main__":
    unittest.main()
