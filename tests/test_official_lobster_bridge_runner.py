from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from poc.official_lobster_bridge.run_official import (
    DEFAULT_LOCAL_BIN,
    ROOT,
    OfficialLobsterRunnerError,
    run_chain_basic,
)


class OfficialLobsterBridgeRunnerTest(unittest.TestCase):
    def test_run_chain_basic_with_fake_lobster_bin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_lobster = temp_path / "lobster"
            input_file = temp_path / "input.json"
            output_dir = temp_path / "out"
            workflow_file = temp_path / "chain-basic.lobster"

            fake_lobster.write_text(
                "#!/bin/sh\n"
                "cat <<'EOF'\n"
                '{"protocolVersion":1,"ok":true,"status":"ok","output":[{"status":"ok","topic":"hello","target":"internal-demo","message":"hello -> internal-demo"}],"requiresApproval":null}\n'
                "EOF\n",
                encoding="utf-8",
            )
            fake_lobster.chmod(fake_lobster.stat().st_mode | stat.S_IEXEC)

            input_file.write_text(
                json.dumps({"task_id": "tsk_p0_chain_001", "topic": "hello", "target": "internal-demo"}),
                encoding="utf-8",
            )
            workflow_file.write_text("name: fake\nsteps: []\n", encoding="utf-8")

            artifacts = run_chain_basic(
                input_file=input_file,
                output_dir=output_dir,
                workflow_file=workflow_file,
                lobster_bin=str(fake_lobster),
            )

            registry = artifacts["registry"]
            callback = artifacts["callback"]

            self.assertEqual(registry["state"], "completed")
            self.assertEqual(registry["callback_status"], "acked")
            self.assertEqual(registry["evidence"]["step_a"], {"status": "ok", "topic": "hello"})
            self.assertEqual(
                registry["evidence"]["step_b"],
                {"status": "ok", "target": "internal-demo", "message": "hello -> internal-demo"},
            )
            self.assertEqual(callback["summary"]["workflow"], "chain-basic")
            self.assertEqual(callback["summary"]["runtime"], "official-lobster-cli")
            self.assertFalse(callback["summary"]["fallback"])
            self.assertEqual(registry["evidence"]["official_runtime"]["mode"], "official")
            self.assertEqual(registry["evidence"]["official_runtime"]["bin"], str(fake_lobster))
            self.assertTrue((output_dir / "registry.json").exists())
            self.assertTrue((output_dir / "callback.json").exists())
            self.assertTrue((output_dir / "lobster-envelope.json").exists())
            self.assertTrue((output_dir / "lobster-command.json").exists())

    def test_non_json_output_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_lobster = temp_path / "lobster"
            input_file = temp_path / "input.json"
            workflow_file = temp_path / "chain-basic.lobster"

            fake_lobster.write_text("#!/bin/sh\necho not-json\n", encoding="utf-8")
            fake_lobster.chmod(fake_lobster.stat().st_mode | stat.S_IEXEC)
            input_file.write_text(
                json.dumps({"task_id": "tsk_p0_chain_001", "topic": "hello", "target": "internal-demo"}),
                encoding="utf-8",
            )
            workflow_file.write_text("name: fake\nsteps: []\n", encoding="utf-8")

            with self.assertRaises(OfficialLobsterRunnerError):
                run_chain_basic(input_file=input_file, workflow_file=workflow_file, lobster_bin=str(fake_lobster))

    def test_run_chain_basic_falls_back_to_legacy_poc_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_file = temp_path / "input.json"
            output_dir = temp_path / "out"
            workflow_file = temp_path / "chain-basic.lobster"

            input_file.write_text(
                json.dumps({"task_id": "tsk_p0_chain_001", "topic": "hello", "target": "internal-demo"}),
                encoding="utf-8",
            )
            workflow_file.write_text("name: fake\nsteps: []\n", encoding="utf-8")

            artifacts = run_chain_basic(
                input_file=input_file,
                output_dir=output_dir,
                workflow_file=workflow_file,
                lobster_bin=str(temp_path / "missing-lobster"),
                fallback_to_poc=True,
            )

            registry = artifacts["registry"]
            callback = artifacts["callback"]

            self.assertEqual(registry["state"], "completed")
            self.assertEqual(registry["callback_status"], "acked")
            self.assertTrue(callback["summary"]["fallback"])
            self.assertEqual(callback["summary"]["runtime"], "legacy-poc-fallback")
            self.assertEqual(registry["evidence"]["official_runtime"]["mode"], "fallback-poc")
            self.assertTrue(registry["evidence"]["official_runtime"]["error"])
            self.assertIn("canonical_entry", registry["evidence"]["official_runtime"])
            self.assertTrue((output_dir / "registry.json").exists())
            self.assertTrue((output_dir / "callback.json").exists())
            self.assertTrue((output_dir / "lobster-envelope.json").exists())
            self.assertTrue((output_dir / "lobster-command.json").exists())

    @unittest.skipUnless(DEFAULT_LOCAL_BIN.exists(), "local lobster bin missing; run npm install in poc/official_lobster_bridge")
    def test_run_chain_basic_with_real_local_lobster_bin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "out"
            artifacts = run_chain_basic(
                input_file=ROOT / "inputs" / "chain-basic.args.json",
                output_dir=output_dir,
                lobster_bin=str(DEFAULT_LOCAL_BIN),
            )

            registry = artifacts["registry"]
            callback = artifacts["callback"]

            self.assertEqual(registry["state"], "completed")
            self.assertEqual(registry["callback_status"], "acked")
            self.assertEqual(registry["evidence"]["official_runtime"]["mode"], "official")
            self.assertEqual(registry["evidence"]["official_runtime"]["envelope_status"], "ok")
            self.assertEqual(callback["summary"]["runtime"], "official-lobster-cli")
            self.assertFalse(callback["summary"]["fallback"])
            self.assertTrue((output_dir / "registry.json").exists())
            self.assertTrue((output_dir / "callback.json").exists())
            self.assertTrue((output_dir / "lobster-envelope.json").exists())
            self.assertTrue((output_dir / "lobster-command.json").exists())


if __name__ == "__main__":
    unittest.main()
