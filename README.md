# OpenClaw Orchestration Control Plane

> **Single entry point for multi-agent workflow orchestration on OpenClaw.**
>
> **Default backend:** subagent | **Compat backend:** tmux | **First validated scenario:** trading continuation
>
> **Maturity:** safe semi-auto / thin bridge / production-validated

---

## Quick Start (30 seconds)

**Unified entry command:**

```bash
python3 ~/.openclaw/scripts/orch_command.py
```

**Common scenarios:**

```bash
# Default: use current channel context
python3 ~/.openclaw/scripts/orch_command.py

# Specify channel/topic
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "discussion topic"

# Trading scenario
python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable

# First-time users: verify stability before auto-execution
python3 ~/.openclaw/scripts/orch_command.py --auto-execute false
```

**Default behavior:**
- ✅ coding lane → Claude Code (via subagent)
- ✅ non-coding lane → subagent
- ✅ auto_execute=true (auto-register/dispatch/callback/continue)
- ✅ gate_policy=stop_on_gate (stops normally at gates)

**Documentation:**
- **Skill entry:** [`runtime/skills/orchestration-entry/SKILL.md`](runtime/skills/orchestration-entry/SKILL.md)
- **Other channels:** [`docs/quickstart/quickstart-other-channels.md`](docs/quickstart/quickstart-other-channels.md)
- **Current truth:** [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md)

---

## What Problem This Solves

**Core question:** After one task completes, how does the system know what to do next—and keep moving safely?

Real multi-agent systems rarely fail because "the model cannot answer." They fail because:
- A task completes but nobody owns the next step
- Multiple child tasks return without a clean fan-in point
- The system can plan but cannot safely dispatch the next action
- A callback is emitted but never reaches the right parent or channel
- Business ownership and execution ownership are mixed together

**This repository makes those transitions explicit** through:
- Continuation contracts
- Handoff schemas
- Registration and readiness tracking
- Dispatch plans
- Bridge consumption
- Execution requests and receipts
- Callback/ack separation

---

## Why This Exists (and Why Not Temporal/LangGraph)

Many teams jump too early into Temporal-style complexity, or stay stuck in script spaghetti. This repo explores the **middle path**:
- Enough structure to be reliable
- Not so much machinery that iteration stops

**Why not Temporal as backbone?**
- Temporal is durable workflow infrastructure—heavy on worker management, determinism guarantees, versioning
- Our current need: thin control plane for agent handoffs, not enterprise workflow engine
- Decision: Use OpenClaw as runtime foundation; keep control plane thin and explicit

**Why not LangGraph as backbone?**
- LangGraph excels at agent-internal reasoning graphs
- Our need: company-wide orchestration across multiple agents and scenarios
- Decision: Keep control plane in OpenClaw; use LangGraph only for local analysis graphs if needed

**Design principle:** External frameworks enter only at leaf execution layer, not as control plane replacement.

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────┐
│ Business Scenarios                                  │
│ trading / channel / future domain adapters          │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ Control Plane (THIS REPO)                           │
│ contracts / planning / registration / readiness     │
│ callbacks / receipts / dispatch / continuation      │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ Execution Layer                                     │
│ subagent (default) / Claude Code / tmux (compat)    │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ OpenClaw Runtime Foundation                         │
│ sessions / tools / hooks / channels / messaging     │
└─────────────────────────────────────────────────────┘
```

**Key boundary:** Control plane decides **what happens next**; execution layer **runs the step**; OpenClaw provides primitives.

### Main Flow

```
Request → Planning → Registration → Readiness Check → Dispatch
       → Execution → Receipt → Callback → Next-Step Decision
       → (repeat or closeout)
```

**Core principle:** A task is not finished when execution stops—it is finished when **the next-step state is made explicit**.

### Owner vs Executor Contract

```text
owner    = who owns the business judgment (acceptance / decision)
executor = who actually performs the work

Examples:
- owner=trading, executor=claude_code
- owner=main, executor=subagent
- owner=content, executor=tmux
```

This decoupling allows coding lanes to default to Claude Code without requiring every business-role agent to become the executor.

**Detailed architecture:** [`docs/architecture/overview.md`](docs/architecture/overview.md)

---

## What This Is NOT (Boundaries)

- ❌ Not a generic DAG platform
- ❌ Not an OpenClaw replacement
- ❌ Not a LangGraph/Temporal/DeepAgents wrapper
- ❌ Not just a trading bot repo
- ❌ Not "fully automatic with no human oversight"

**Current scope:** thin bridge / allowlist / safe semi-auto / validated on trading continuation

---

## Current Maturity

| Aspect | Status | Notes |
|--------|--------|-------|
| **Backend strategy** | ✅ Dual-track | subagent (default) + tmux (compat) |
| **Trading continuation** | ✅ Production-validated | Real execution path verified |
| **Control plane** | ✅ Main chain in place | Registration → dispatch → execution → receipt → callback |
| **Tests** | ✅ 468 passing | 100% pass rate |
| **Auto-continue** | ⚠️ Safe semi-auto | Allowlist-based, condition-triggered, reversible |
| **Git push auto-continue** | ⚠️ Not fully automatic | Internal simulation closed; real push executor pending |

**Honest summary:** Further along than a proposal, but intentionally earlier than a fully general-purpose workflow platform.

---

## Repository Structure

```text
openclaw-company-orchestration-proposal/
├── README.md / README.zh.md          # Single entry point (this file)
├── docs/
│   ├── CURRENT_TRUTH.md              # Current truth entry point
│   ├── executive-summary.md          # 5-minute overview
│   ├── architecture/                 # Architecture diagrams & overviews
│   ├── quickstart/                   # Channel-specific quickstart guides
│   ├── configuration/                # Auto-trigger config & troubleshooting
│   ├── plans/                        # Current plans & roadmaps
│   ├── reports/                      # Validation & health reports
│   ├── review/                       # Architecture reviews
│   ├── technical-debt/               # Technical debt backlog
│   └── ...                           # Other documentation
├── runtime/
│   ├── orchestrator/                 # Core orchestration logic
│   ├── skills/                       # OpenClaw skill integrations
│   └── scripts/                      # Entry commands & utilities
├── tests/
│   └── orchestrator/                 # Behavioral tests (source of truth)
├── archive/                          # Historical material (reference only)
└── scripts/                          # Utility scripts
```

| Directory | Purpose |
|-----------|---------|
| `docs/` | Human-facing documentation: current truth, architecture, migration, releases |
| `runtime/` | Actual orchestration runtime: contracts, continuation, dispatch, bridge consumer |
| `tests/` | Behavioral proof—tests are a source of truth, not just packaging hygiene |
| `archive/` | Historical material kept for reference, not for the active path |

---

## Documentation Navigation

| Goal | Entry Point |
|------|-------------|
| **First-time overview** | [`docs/executive-summary.md`](docs/executive-summary.md) |
| **Current truth (latest)** | [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) |
| **Architecture deep dive** | [`docs/architecture/overview.md`](docs/architecture/overview.md) |
| **Other channels setup** | [`docs/quickstart/quickstart-other-channels.md`](docs/quickstart/quickstart-other-channels.md) |
| **Auto-trigger config** | [`docs/configuration/auto-trigger-config-guide.md`](docs/configuration/auto-trigger-config-guide.md) |
| **Validation status** | [`docs/validation-status.md`](docs/validation-status.md) |
| **Current plans** | [`docs/plans/overall-plan.md`](docs/plans/overall-plan.md) |
| **Technical debt** | [`docs/technical-debt/technical-debt-2026-03-22.md`](docs/technical-debt/technical-debt-2026-03-22.md) |
| **Recent reports** | [`docs/reports/`](docs/reports/) |
| **Architecture reviews** | [`docs/review/`](docs/review/) |

### Document Roles

- **`docs/CURRENT_TRUTH.md`**: Single source of truth for current iteration state (v10, dual-track backend)
- **`docs/executive-summary.md`**: Historical batch-1 plan; read for context but defer to README/CURRENT_TRUTH
- **`docs/plans/overall-plan.md`**: Current true plan with P0/P1/P2 priorities and boundaries
- **`docs/validation-status.md`**: What's validated vs. what's not; why this direction was chosen
- **`docs/technical-debt/technical-debt-2026-03-22.md`**: Known optimization points and backlog

---

## Testing

**Run all tests:**

```bash
cd openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/ -v
```

**Current status:** 468 tests passing (100% pass rate)

**Key test files:**
- `test_execute_mode_and_auto_trigger.py` — Execute mode + auto-trigger validation (formerly test_v8_execute_mode.py)
- `test_sessions_spawn_api_execution.py` — Real sessions_spawn API integration (formerly test_v9_sessions_spawn_api.py)
- `test_mainline_auto_continue.py` — Trading mainline auto-continue validation
- `test_sessions_spawn_bridge.py` — Sessions spawn bridge validation
- `test_continuation_backends_lifecycle.py` — Generic lifecycle kernel tests

---

## One-Sentence Summary

> **This repository builds a practical orchestration control-plane for OpenClaw: subagent as default execution path, tmux as compatibility path, trading as first real proving ground, external frameworks at leaf layer only.**

---

## Owner & Maintenance

**Owner:** Zoe (CTO & Chief Orchestrator)

**Last updated:** 2026-03-24 (Repository consolidation)

**Related repositories:**
- OpenClaw core: `~/.openclaw/`
- Workspace: `~/.openclaw/workspace/`
