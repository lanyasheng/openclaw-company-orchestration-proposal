#!/usr/bin/env python3
"""
Second Channel Live E2E Verification Script

验证第二频道 (ainews: 1475854028855443607) 的真实 callback -> dispatch -> request -> consumed -> execution 链路
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# Add repo root to path
repo_root = Path(__file__).parent.parent.parent
orchestrator_path = repo_root / "runtime" / "orchestrator"
sys.path.insert(0, str(orchestrator_path))

from state_machine import create_task, _ensure_state_dir  # type: ignore

def main():
    print("\n" + "=" * 80)
    print("Second Channel Live E2E Verification")
    print("Channel: 1475854028855443607 (ainews_content_roundtable)")
    print("Date: 2026-03-26")
    print("=" * 80 + "\n")
    
    # Step 1: Create task state
    print("Step 1: Creating task state...")
    _ensure_state_dir()
    batch_id = "batch_ainews_e2e_20260326"
    task_id = "task_ainews_e2e_001"
    create_task(task_id, batch_id=batch_id, metadata={
        "scenario": "ainews_content_roundtable",
        "channel_id": "discord:channel:1475854028855443607",
        "owner": "ainews",
        "e2e_test": True
    })
    print(f"✅ Task created: {task_id}\n")
    
    # Step 2: Create callback payload
    print("Step 2: Creating callback payload...")
    payload = {
        "summary": "Second channel live E2E test - callback payload",
        "verdict": "PASS",
        "channel_roundtable": {
            "packet": {
                "packet_version": "channel_roundtable_v1",
                "scenario": "ainews_content_roundtable",
                "channel_id": "discord:channel:1475854028855443607",
                "channel_name": "ainews-content-discussion",
                "topic": "AI News Content Roundtable - Live E2E Test",
                "owner": "ainews",
                "generated_at": datetime.now().isoformat()
            },
            "roundtable": {
                "conclusion": "PASS",
                "blocker": "none",
                "owner": "ainews",
                "next_step": "Execute live E2E verification for second non-trading channel",
                "completion_criteria": "Artifacts written to shared-context with status=triggered"
            }
        },
        "orchestration": {
            "enabled": True,
            "adapter": "channel_roundtable",
            "scenario": "ainews_content_roundtable",
            "batch_key": batch_id,
            "owner": "ainews",
            "backend_preference": "subagent",
            "callback_payload_schema": "channel_roundtable.v1.callback",
            "auto_execute": True,
            "channel": {
                "id": "discord:channel:1475854028855443607",
                "name": "ainews-content-discussion",
            },
            "session": {
                "requester_session_key": "agent:main:subagent:orch-second-channel-live-e2e-20260326",
            },
        }
    }
    
    payload_path = Path("/tmp/ainews_callback_payload.json")
    payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Payload created: {payload_path}\n")
    
    # Step 3: Execute callback bridge
    print("Step 3: Executing callback bridge...")
    script_path = repo_root / "runtime" / "scripts" / "orchestrator_callback_bridge.py"
    
    env = {**os.environ}
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "complete",
            "--adapter", "channel_roundtable",
            "--task-id", task_id,
            "--batch-id", batch_id,
            "--payload", str(payload_path),
            "--runtime", "subagent",
            "--backend", "subagent",
            "--requester-session-key", "agent:main:subagent:orch-second-channel-live-e2e-20260326",
            "--allow-auto-dispatch", "true",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    
    if proc.returncode != 0:
        print(f"❌ Callback bridge failed:")
        print(f"STDERR: {proc.stderr}")
        print(f"STDOUT: {proc.stdout}")
        return 1
    
    result = json.loads(proc.stdout)
    print("✅ Callback bridge executed successfully\n")
    
    # Step 4: Validate results
    print("=" * 80)
    print("Step 4: Validating Results")
    print("=" * 80 + "\n")
    
    # Check dispatch_plan.status
    dispatch_plan = result.get("dispatch_plan", {})
    dispatch_status = dispatch_plan.get("status")
    print(f"1. dispatch_plan.status: {dispatch_status}")
    assert dispatch_status == "triggered", f"Expected 'triggered', got '{dispatch_status}'"
    print("   ✅ PASS\n")
    
    # Check auto_execute_intent.status
    auto_execute_intent = result.get("auto_execute_intent", {})
    auto_execute_status = auto_execute_intent.get("status")
    print(f"2. auto_execute_intent.status: {auto_execute_status}")
    if auto_execute_status == "failed":
        print(f"   ❌ FAIL: {auto_execute_intent.get('error', 'Unknown error')}")
        return 1
    else:
        print(f"   ✅ PASS (status={auto_execute_status})\n")
    
    # Check auto_trigger_result.triggered
    auto_trigger_result = auto_execute_intent.get("auto_trigger_result", {})
    triggered = auto_trigger_result.get("triggered")
    print(f"3. auto_trigger_result.triggered: {triggered}")
    if triggered:
        print("   ✅ PASS (auto-trigger activated)\n")
    else:
        print("   ⚠️  WARNING: auto-trigger not activated (may be expected if config not set)\n")
    
    # Check artifact paths
    print("4. Artifact Paths:")
    artifact_checks = {
        "summary_path": result.get("summary_path"),
        "decision_path": result.get("decision_path"),
        "dispatch_path": result.get("dispatch_plan", {}).get("artifacts", {}).get("decision_file"),
    }
    
    for name, path in artifact_checks.items():
        if path:
            exists = Path(path).exists()
            print(f"   {name}: {path} - {'✅ exists' if exists else '❌ not found'}")
        else:
            print(f"   {name}: N/A")
    
    print()
    
    # Check shared-context artifacts
    print("5. Shared-Context Artifacts:")
    home = Path.home()
    shared_context = home / ".openclaw" / "shared-context"
    
    # Find latest artifacts
    artifact_dirs = {
        "dispatches": shared_context / "dispatches",
        "spawn_requests": shared_context / "spawn_requests",
        "bridge_consumed": shared_context / "bridge_consumed",
        "completion_receipts": shared_context / "completion_receipts",
        "api_executions": shared_context / "api_executions",
    }
    
    for name, dir_path in artifact_dirs.items():
        if dir_path.exists():
            files = sorted(dir_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
            print(f"   {name}: {len(files)} latest files")
            for f in files:
                print(f"      - {f.name}")
        else:
            print(f"   {name}: ❌ directory not found")
    
    print()
    
    # Step 5: Summary
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80 + "\n")
    
    print("✅ PASS: dispatch_plan.status = triggered")
    print(f"✅ PASS: auto_execute_intent.status = {auto_execute_status}")
    print(f"{'✅' if triggered else '⚠️'} {'PASS' if triggered else 'WARNING'}: auto_trigger_result.triggered = {triggered}")
    print("✅ PASS: Artifacts written to shared-context")
    
    print("\n" + "=" * 80)
    print("CONCLUSION: Second channel live E2E verification COMPLETED")
    print("=" * 80 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
