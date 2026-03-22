---
name: orchestration-entry
description: Formal orchestration contract + guard-discovery entry for OpenClaw. Use when starting `channel_roundtable`, `trading_roundtable`, or other fan-out / callback / dispatch tasks, and also when the issue is about orchestration completion, subagent terminal/completion receipt, roundtable ack, orphan/stale task, or waiting anomaly. Canonical entry stays `python3 ~/.openclaw/scripts/orch_command.py` with default `auto_execute=true` and `gate_policy.mode=stop_on_gate`.
---

Run `python3 ~/.openclaw/scripts/orch_command.py` as the canonical runtime entry command.

This skill is also the **discovery entry** for already-existing orchestration guards. It helps an agent find completion receipt / ack / waiting hard-close paths without implying that the skill itself implements those guards.

Source of truth:
- Workspace skill source: `~/.openclaw/workspace/skills/orchestration-entry/SKILL.md`
- Workspace command source: `~/.openclaw/workspace/scripts/orch_command.py`
- Install / refresh global runtime copy: `python3 ~/.openclaw/workspace/scripts/install_orchestration_entry_global.py`

Quick start:
```bash
python3 ~/.openclaw/scripts/orch_command.py
python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable
python3 ~/.openclaw/scripts/orch_command.py --context channel_roundtable --output tmp/orch-contract.json
python3 ~/.openclaw/scripts/orch_command.py --scenario <your_scenario> --channel-id discord:channel:<id> --owner <owner>
```

Defaults:
- No input: derive the current orchestration contract from ambient context.
- `auto_execute=true`
- `gate_policy.mode=stop_on_gate`
- Output: JSON contract for launch / completion / callback hooks (includes `bootstrap_capability_card` for discoverability).

**Other channel onboarding / generic channel onboarding**:
- Non-trading scenarios use `channel_roundtable` adapter (no new adapter needed).
- Generated contract includes `onboarding.bootstrap_capability_card` with key constraints and operator kit path.
- First run recommendation: `allow_auto_dispatch=false` until callback/ack/dispatch artifacts are proven stable.
- See `orchestrator/examples/generic_channel_roundtable_onboarding_kit.md` for the full onboarding kit.

If the task is about orchestration completion, subagent terminal/completion receipt, orphan task, roundtable ack, or waiting anomaly, also read:
- `~/.openclaw/skills/orchestration-entry/references/hook-guard-capabilities.md`

That reference is for capability discovery only; the actual guards live in runtime hook / orchestrator code.

Read `~/.openclaw/workspace/docs/architecture/2026-03-21-orchestration-skill-and-command-defaults.md` before changing defaults or adding a new scenario.
