# OpenClaw Orchestration Control Plane

> When an agent finishes a task, what happens next?
> This repo makes the answer explicit, traceable, and safe.

[中文版](README_CN.md) · [Operations Guide](docs/OPERATIONS.md)

---

## The Problem

Multi-agent systems fail at **coordination**, not capability:

| Gap | What Goes Wrong |
|-----|-----------------|
| **No explicit handoff** | Agent A finishes. Nobody tells Agent B. Work stalls silently. |
| **No fan-in** | 5 parallel tasks return mixed results. Proceed or stop? By what rule? |
| **No state continuity** | Process crashes. Where were we? What was done? How to resume? |
| **No safety gate** | Auto-dispatch without guardrails → runaway agents, wasted compute. |

---

## What This Repo Provides

An **orchestration control plane** with two co-existing execution paths:

| Path | Use Case | Entry |
|------|----------|-------|
| **DAG Workflow** | Pre-planned batch orchestration: plan all batches → auto-advance | `cli.py plan / run / resume / show` |
| **Callback-Driven** | Event-driven: message → callback → decision → next dispatch | `cli.py status / decide / stuck` |

Both paths share the same execution substrate (`SubagentExecutor` + `TmuxTaskExecutor`).

### Core Capabilities

| Capability | How It Works | Status |
|-----------|-------------|--------|
| **Batch DAG Planning** | `depends_on` defines dependencies. Kahn's algorithm validates DAG, topological sort determines execution order. | ✅ Production |
| **Parallel Dispatch + Retry** | `BatchExecutor` dispatches via pluggable executors, monitors completion, retries failed tasks. | ✅ Production |
| **Fan-in Review** | `BatchReviewer` applies `all_success` / `any_success` / `majority` policy. | ✅ Production |
| **Safety Gates** | Configurable gate conditions pause workflow for human review. | ✅ Production |
| **Single JSON Truth** | One `workflow_state_*.json` per workflow — all batches, tasks, decisions. | ✅ Production |
| **LangGraph Integration** | Optional LangGraph StateGraph engine. Falls back to zero-dependency polling loop. | ✅ Production |
| **Continuation Kernel** | 9-version artifact chain: `registration → dispatch → spawn → execute → receipt → callback → auto-continue`. | ✅ Production |
| **Hooks System** | Three-mode enforcement (audit/warn/enforce): promise verification, completion translation. | ✅ Production |
| **Observability** | Per-task status cards, dashboard rendering, tmux session sync. | ✅ Production |
| **Alerts** | Rule-based alerting with audit trail and dispatch routing. | ✅ Production |
| **Pluggable Executors** | `TaskExecutorBase` abstract interface — swap in any execution backend. | ✅ Interface defined |
| **Circuit Breaker** | Tracks consecutive (3) and total (20) failures per dispatch target; auto-trip. | ✅ Implemented |

---

## Quick Start

```bash
pip install langgraph langgraph-checkpoint-sqlite  # optional

# 1. Plan — validate DAG, create state file
python3 runtime/orchestrator/cli.py plan "Analyze codebase" config.json

# 2. Run — execute batches
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace /path/to/project

# 3. Monitor — check progress
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json

# 4. Resume — continue from gate or crash
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

### Example `config.json`

```json
[
  {
    "batch_id": "collect",
    "label": "Data Collection",
    "tasks": [
      {"task_id": "t1", "label": "Source A", "max_retries": 2},
      {"task_id": "t2", "label": "Source B"}
    ],
    "depends_on": [],
    "fan_in_policy": "any_success"
  },
  {
    "batch_id": "synthesize",
    "label": "Merge Results",
    "tasks": [{"task_id": "t3", "label": "Synthesize"}],
    "depends_on": ["collect"]
  }
]
```

---

## Architecture

### System Overview

```
                        ┌─────────────────────────────────────┐
                        │       Orchestration Control Plane     │
                        │                                       │
  cli.py ───────────┬── │  TaskPlanner (DAG validate, topo sort)│
                    │   │  WorkflowState (single JSON truth)    │
                    │   └───────────────────────────────────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
  DAG Workflow Path    Callback-Driven Path
  ┌──────────────┐    ┌──────────────────┐
  │ WorkflowLoop │    │ orchestrator.py  │
  │ WorkflowGraph│    │ (rule chain)     │
  │ BatchExecutor│    │ auto_dispatch    │
  │ BatchReviewer│    │ bridge_consumer  │
  └──────┬───────┘    └────────┬─────────┘
         │                     │
  ┌──────┴─────────────────────┴──────┐
  │       Execution Substrate          │
  │  SubagentExecutor (process mgmt)   │
  │  TmuxTaskExecutor (tmux sessions)  │
  │  executor_interface (pluggable)    │
  └──────┬─────────────────────┬──────┘
         │                     │
  ┌──────┴───────┐    ┌───────┴────────┐
  │  Reliability  │    │  Observability  │
  │  watchdog     │    │  obs cards      │
  │  circuit brk  │    │  dashboard      │
  │  single_writer│    │  tmux sync      │
  │  fallback     │    │  hooks          │
  └──────────────┘    └────────────────┘
```

### Dispatch Engine (`start-tmux-task.sh`)

Generic task dispatch — creates tmux sessions with Claude Code, manages lifecycle.

```bash
start-tmux-task.sh --label <name> --workdir <dir> --task <prompt> \
  [--type <type>] [--model <model>] [--auto-exit] [--no-ralph] [--no-worktree]
```

| Feature | Detail |
|---------|--------|
| Concurrency lock | `mkdir`-based atomic lock, 60s stale recovery |
| Results dedup | Skips already-completed tasks |
| Worktree isolation | Auto-creates git worktree for coding tasks |
| Auto-exit | Marker file + `on-stop.sh` for unattended sessions |
| Configurable prefix | `OPENCLAW_SESSION_PREFIX` env var (default: `oc`) |

### Pluggable Executors

```python
class MyExecutor(TaskExecutorBase):
    def execute(self, task_id, label, context) -> str: ...
    def poll(self, handle) -> TaskResult: ...
    def cancel(self, handle) -> bool: ...
    def cleanup(self, handle) -> None: ...
```

Built-in: `SubagentExecutor` (process management, fork guard) and `TmuxTaskExecutor` (tmux sessions, Ralph-aware poll).

---

## Hooks System

Three-mode behavioral enforcement hooks at the control plane level:

| Hook | Purpose | Modes |
|------|---------|-------|
| **PostPromiseVerifyHook** | Verifies "in progress" claims have a real execution anchor (dispatch_id, session_id, tmux_session). | audit / warn / enforce |
| **PostCompletionTranslateHook** | Forces human-readable completion reports after subtask completion. Required: conclusion, evidence, action. | audit / warn / enforce |

Configure via `OPENCLAW_HOOK_ENFORCE_MODE` (default: `audit`).

---

## Reliability

| Mechanism | Implementation |
|-----------|---------------|
| **Atomic Writes** | `tempfile + os.fsync + os.replace` via `utils/io.py` |
| **File-Level Locking** | `SingleWriterGuard` with `fcntl.flock`, 5-min timeout, reentrant |
| **Circuit Breaker** | Tracks consecutive (3) and total (20) failures per target; auto-trip |
| **Watchdog** | Stall detection, dead process reconciliation, orphan completion recovery |
| **Fork Bomb Prevention** | Three-layer guard: spawn depth + pgrep count + semaphore |
| **UTC Timestamps** | All timeout/comparison code uses `datetime.now(timezone.utc)` |
| **Subprocess Timeouts** | 60s dispatch, 30s kill-session, 5s capture-pane |
| **Dispatch Lock** | `mkdir`-based atomic lock in `start-tmux-task.sh` |
| **Crash Recovery** | `workflow_loop` persists state before exit on unhandled exceptions |

---

## Continuation Kernel

Every task execution maintains a traceable artifact chain:

```
registration_id → dispatch_id → spawn_id → execution_id
    → receipt_id → request_id → consumed_id → api_execution_id
```

Any ID can query the full chain — forward or backward. Implemented across: `task_registration`, `spawn_closure`, `spawn_execution`, `completion_receipt`, `sessions_spawn_bridge`, `bridge_consumer`.

---

## Repository Structure

```
runtime/orchestrator/
├── cli.py                      # CLI: plan/run/show/resume/status/decide/stuck
├── workflow_state.py           # Single JSON truth model
├── workflow_state_store.py     # Mtime-based stale-write detection
├── workflow_loop.py            # Zero-dependency polling fallback
├── workflow_graph.py           # LangGraph engine (optional)
├── task_planner.py             # DAG validation + topological sort
├── batch_executor.py           # Parallel dispatch + retry
├── batch_reviewer.py           # Fan-in policy + gate conditions
├── batch_aggregator.py         # Batch analysis + stuck detection
├── orchestrator.py             # Rule chain decision engine
├── state_machine.py            # Per-task state (callback-driven core)
├── state_sync.py               # Callback → workflow state bridge
├── contracts.py                # Canonical callback envelope + task tiers
│
├── executor_interface.py       # TaskExecutorBase abstract interface
├── subagent_executor.py        # Process management + fork guard
├── subagent_config.py          # Subagent configuration
├── subagent_reconciler.py      # Queued task timeout reconciliation
├── subagent_state.py           # Subagent state persistence
├── tmux_executor.py            # Tmux session executor
├── tmux_status_sync.py         # Tmux → observability sync
├── tmux_terminal_receipts.py   # Terminal receipt extraction
│
├── auto_dispatch.py            # Policy-based auto-dispatch
├── bridge_consumer.py          # Callback consumption engine
├── completion_receipt.py       # Completion receipt generation
├── completion_validator.py     # Completion quality gate kernel
├── completion_validator_rules.py # Through/Block/Gate scoring
├── completion_ack_guard.py     # Acknowledge guard
├── completion_backwrite.py     # Completion backwrite
│
├── task_registration.py        # Task registration lifecycle
├── spawn_closure.py            # v4 continuation: dispatch → spawn
├── spawn_execution.py          # v5 continuation: spawn → execution
├── sessions_spawn_bridge.py    # Session spawn bridge
├── sessions_spawn_request.py   # Session spawn request handling
├── partial_continuation.py     # Continuation contract
├── continuation_backends.py    # Backend continuation logic
│
├── hooks/                      # Behavioral enforcement hooks
│   ├── hook_config.py          # Three-mode config (audit/warn/enforce)
│   ├── hook_dispatcher.py      # Hook dispatch engine
│   ├── hook_exceptions.py      # HookViolationError
│   ├── hook_integrations.py    # Integration points
│   ├── post_promise_verify_hook.py     # Empty promise detection
│   └── post_completion_translate_hook.py # Report enforcement
│
├── core/                       # Core abstractions
│   ├── types.py                # GateResult, FanOutMode, FanInMode
│   ├── validation.py           # Validation helpers
│   ├── phase_engine.py         # Phase state machine
│   ├── task_registry.py        # Multi-index task registry
│   ├── callback_router.py      # Priority-based callback routing
│   ├── dispatch_planner.py     # Backend selection + dispatch planning
│   ├── fanout_controller.py    # Fan-out/fan-in controller
│   ├── quality_gate.py         # Quality gate evaluator
│   └── handoff_schema.py       # Planning-to-execution handoff
│
├── adapters/                   # Domain-specific adapters
│   ├── base.py                 # Base adapter interface
│   └── trading.py              # Trading scenario adapter
│
├── trading/                    # Trading domain modules
│   ├── schemas.py              # Trading data schemas
│   ├── callback_validator.py   # Trading callback validation
│   └── simulation_adapter.py   # Trading simulation
│
├── alerts/                     # Alert system
│   └── trading_alert_sender.py # Alert delivery
├── alert_audit.py              # Alert audit logging
├── alert_dispatcher.py         # Alert routing
├── alert_rules.py              # Alert rule definitions
│
├── observability_card.py       # Per-task status cards
├── dashboard.py                # Dashboard rendering
├── telemetry.py                # Metrics collection
├── lineage.py                  # Task lineage tracking
│
├── fallback_protocol.py        # Retry/cancel + circuit breaker
├── retry_cancel_contract.py    # Unified retry/cancel semantics
├── single_writer_guard.py      # fcntl.flock file locking
├── watchdog.py                 # Stall detection + health checks
├── unified_execution_runtime.py # Single entry point for task execution
├── backend_selector.py         # Auto backend selection (tmux vs subagent)
│
└── utils/
    ├── io.py                   # Atomic file writes
    └── time.py                 # Unified UTC timestamps

scripts/
├── start-tmux-task.sh          # Generic tmux task launcher
├── monitor-tmux-task.sh        # Session monitoring loop
├── status-tmux-task.sh         # Session status query
└── sync-tmux-observability.py  # Observability registration

tests/orchestrator/             # Test suite
docs/                           # Operations guide
examples/                       # Sample configs + payloads
schemas/                        # JSON schemas
```

---

## Tests

```bash
PYTHONPATH=runtime/orchestrator python3 -m pytest tests/ -v -k "not e2e"
# e2e tests require real tmux + Claude Code CLI
```

---

## Positioning

| Framework | Relationship |
|-----------|-------------|
| **LangGraph** | Embedded as optional engine. We add batch DAG, fan-in, gates on top. |
| **CrewAI / AutoGen** | We are the control plane — we decide *when* agents run, not *what* they are. |
| **Temporal** | We are single-process + JSON checkpoint. No server cluster needed. |

**One line:** A thin, opinionated control plane. LangGraph is an optional backend. Agents do the work; we orchestrate the transitions.

---

## License

MIT
