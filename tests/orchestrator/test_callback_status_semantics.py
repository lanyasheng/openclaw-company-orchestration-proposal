from __future__ import annotations

import json
import unittest
from pathlib import Path


TERMINAL_STATES = {"completed", "failed", "degraded"}


def validate_case(case: dict) -> None:
    steps = case["steps"]
    if not steps:
        raise AssertionError("steps must not be empty")

    previous_status = None
    for index, step in enumerate(steps):
        event = step["event"]
        state = step["state"]
        status = step["callback_status"]

        if index == 0:
            if status != "pending":
                raise AssertionError("first step must start with callback_status=pending")
            previous_status = status
            continue

        assert previous_status is not None

        if status != previous_status:
            if previous_status == "pending" and status == "sent":
                if event != "final_callback_sent":
                    raise AssertionError(
                        f"pending -> sent is only allowed on final_callback_sent, got {event}"
                    )
                if state not in TERMINAL_STATES:
                    raise AssertionError("final callback may be sent only after task state is terminal")
            elif previous_status == "pending" and status == "failed":
                if event != "final_callback_failed":
                    raise AssertionError(
                        f"pending -> failed is only allowed on final_callback_failed, got {event}"
                    )
                if state not in TERMINAL_STATES:
                    raise AssertionError("final callback failure may be recorded only after task state is terminal")
            elif previous_status == "sent" and status == "acked":
                if event != "callback_receipt_acked":
                    raise AssertionError(
                        f"sent -> acked is only allowed on callback_receipt_acked, got {event}"
                    )
                if state not in TERMINAL_STATES:
                    raise AssertionError("callback receipt ack requires terminal task state")
            else:
                raise AssertionError(f"illegal callback_status transition: {previous_status} -> {status}")

        previous_status = status


class CallbackStatusSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        examples_path = repo_root / "examples" / "callback-status-transitions.json"
        cls.payload = json.loads(examples_path.read_text(encoding="utf-8"))

    def test_valid_cases_pass(self) -> None:
        valid_cases = [case for case in self.payload["cases"] if case["expected_valid"]]
        self.assertGreater(len(valid_cases), 0)
        for case in valid_cases:
            with self.subTest(case_id=case["case_id"]):
                validate_case(case)

    def test_invalid_cases_fail(self) -> None:
        invalid_cases = [case for case in self.payload["cases"] if not case["expected_valid"]]
        self.assertGreater(len(invalid_cases), 0)
        for case in invalid_cases:
            with self.subTest(case_id=case["case_id"]):
                with self.assertRaises(AssertionError):
                    validate_case(case)


if __name__ == "__main__":
    unittest.main()
