from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from poc.subagent_bridge_sim.poc_runner import SubagentBridgeSimulator

REPO_ROOT = Path(__file__).resolve().parents[1]
POC_DIR = REPO_ROOT / "poc" / "subagent_bridge_sim"
SAMPLE_DIR = POC_DIR / "inputs"
EXPECTED_DIR = POC_DIR / "expected"


def load_json(directory: Path, name: str):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def load_callback_events(name: str) -> list[dict]:
    payload = load_json(SAMPLE_DIR, name)
    if isinstance(payload, list):
        return payload
    return payload["events"]


class SubagentBridgeSimulatorTest(unittest.TestCase):
    def make_simulator(self) -> SubagentBridgeSimulator:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return SubagentBridgeSimulator(Path(temp_dir.name))

    def test_terminal_event_patches_registry_and_unblocks_waiter(self) -> None:
        simulator = self.make_simulator()
        result = simulator.run_simulation(
            load_json(SAMPLE_DIR, "spawn-request.json"),
            load_json(SAMPLE_DIR, "terminal-event.json"),
        )

        registry = result["registry"]
        awaited = result["await_terminal"]
        envelope = result["terminal_envelope"]

        self.assertEqual(result["spawn_response"]["state"], "running")
        self.assertEqual(awaited["state"], "completed")
        self.assertEqual(envelope["task_id"], "tsk_p0_subagent_bridge_sim_001")
        self.assertEqual(registry["runtime"], "subagent")
        self.assertEqual(registry["state"], "completed")
        self.assertEqual(registry["callback_status"], "pending")
        self.assertEqual(registry["evidence"]["child_session_key"], "agent:main:subagent:sim-001")
        self.assertEqual(registry["evidence"]["terminal_state"], "completed")
        self.assertEqual(
            registry["evidence"]["artifacts"]["final_report_path"],
            "runs/p0-5-subagent-bridge-sim/final-report.md",
        )

    def test_run_simulation_writes_registry_patched_output(self) -> None:
        simulator = self.make_simulator()
        simulator.run_simulation(
            load_json(SAMPLE_DIR, "spawn-request.json"),
            load_json(SAMPLE_DIR, "terminal-event.json"),
        )
        patched_path = simulator.outputs_dir / "registry.patched.json"
        self.assertTrue(patched_path.exists())
        patched = json.loads(patched_path.read_text(encoding="utf-8"))
        expected = load_json(EXPECTED_DIR, "registry.patched.json")
        self.assertEqual(patched, expected)

    def test_callback_sequence_advances_pending_to_sent_to_acked_without_mutating_state(self) -> None:
        simulator = self.make_simulator()
        result = simulator.run_simulation(
            load_json(SAMPLE_DIR, "spawn-request.json"),
            load_json(SAMPLE_DIR, "terminal-event.json"),
            callback_events=load_callback_events("callback-events-success.json"),
        )

        registry = result["registry"]
        callback_envelopes = result["callback_envelopes"]
        callback_evidence = registry["evidence"]["callback"]

        self.assertEqual(registry["state"], "completed")
        self.assertEqual(registry["callback_status"], "acked")
        self.assertEqual([event["callback_status"] for event in callback_envelopes], ["sent", "acked"])
        self.assertEqual([event["stage"] for event in callback_envelopes], ["final_callback_sent", "callback_receipt_acked"])
        self.assertEqual(callback_evidence["last_stage"], "callback_receipt_acked")
        self.assertEqual(callback_evidence["delivery"]["delivery_id"], "cb-sim-001")
        self.assertEqual(callback_evidence["receipt"]["ack_id"], "ack-sim-001")
        self.assertEqual(len(callback_evidence["history"]), 2)
        self.assertEqual(callback_evidence["history"][0]["callback_status"], "sent")
        self.assertEqual(callback_evidence["history"][1]["callback_status"], "acked")

        expected = load_json(EXPECTED_DIR, "registry.callback-acked.json")
        self.assertEqual(registry, expected)

    def test_callback_failure_advances_pending_to_failed_without_overwriting_terminal_state(self) -> None:
        simulator = self.make_simulator()
        result = simulator.run_simulation(
            load_json(SAMPLE_DIR, "spawn-request.json"),
            load_json(SAMPLE_DIR, "terminal-event-failed.json"),
            callback_events=load_callback_events("callback-events-failed.json"),
        )

        registry = result["registry"]
        callback_envelope = result["callback_envelopes"][0]
        callback_evidence = registry["evidence"]["callback"]

        self.assertEqual(registry["state"], "failed")
        self.assertEqual(registry["callback_status"], "failed")
        self.assertEqual(callback_envelope["previous_callback_status"], "pending")
        self.assertEqual(callback_envelope["callback_status"], "failed")
        self.assertEqual(callback_evidence["last_stage"], "final_callback_failed")
        self.assertEqual(callback_evidence["error"]["code"], "simulated_delivery_error")
        self.assertEqual(
            registry["evidence"]["artifacts"]["final_report_path"],
            "runs/p0-6-callback-integration/final-report.md",
        )

        expected = load_json(EXPECTED_DIR, "registry.callback-failed.json")
        self.assertEqual(registry, expected)


if __name__ == "__main__":
    unittest.main()
