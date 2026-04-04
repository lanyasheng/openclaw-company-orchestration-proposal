#!/usr/bin/env python3
"""最小编排示例 — python3 quickstart.py "做某件事" """
import json, sys, os, subprocess, tempfile, glob

desc = sys.argv[1] if len(sys.argv) > 1 else "Hello Orchestration"
config = [{"batch_id": "do", "label": desc, "tasks": [{"task_id": "t1", "label": desc}], "depends_on": [], "fan_in_policy": "all_success"}]
cfg_path = os.path.join(tempfile.gettempdir(), "oc_quickstart_config.json")
with open(cfg_path, "w") as f:
    json.dump(config, f)

cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime", "orchestrator", "cli.py")
print(f"[quickstart] 目标: {desc}\n[quickstart] 执行: plan → show")
subprocess.run([sys.executable, cli, "plan", desc, cfg_path], check=True)
states = sorted(glob.glob("workflow_state_wf_*.json"), key=os.path.getmtime, reverse=True)
if states:
    subprocess.run([sys.executable, cli, "show", states[0]])
    print(f"\n[quickstart] 下一步: python3 {cli} run {states[0]} --workspace .")
