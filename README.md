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

A **batch DAG workflow engine** that orchestrates multi-agent task execution via tmux + Claude Code CLI.

```
plan (DAG validate) → dispatch (parallel execute) → monitor (poll + retry)
    → review (fan-in + gate) → next batch or completed
```

### Core Capabilities

| Capability | How It Works | Status |
|-----------|-------------|--------|
| **Batch DAG Planning** | Define task batches with `depends_on`. Kahn's algorithm validates DAG, topological sort determines execution order. | ✅ Production |
| **Parallel Dispatch + Retry** | `BatchExecutor` dispatches tasks via configurable executors, monitors completion, retries failed tasks. | ✅ Production |
| **Fan-in Review** | `BatchReviewer` applies `all_success` / `any_success` / `majority` policy to determine batch outcome. | ✅ Production |
| **Safety Gates** | Configurable gate conditions pause workflow for human review. Resume when ready. | ✅ Production |
| **Single JSON Truth** | One `workflow_state_*.json` file per workflow — all batches, tasks, decisions. | ✅ Production |
| **LangGraph Integration** | Optional LangGraph StateGraph engine. Falls back to zero-dependency polling loop. | ✅ Production |
| **Context Recovery** | `context_summary` auto-generated at each save. Resume from crash or context compression. | ✅ Production |
| **Pluggable Executors** | `TaskExecutorBase` abstract interface — swap in any execution backend. | ✅ Interface defined |

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

```
cli.py ──→ TaskPlanner (DAG validate, topo sort)
       ──→ WorkflowEngine (LangGraph ↔ polling fallback)
              ├── BatchExecutor (parallel dispatch, retry)
              │     ├── SubagentExecutor (process mgmt, fork guard)
              │     └── TmuxTaskExecutor (tmux sessions, Ralph-aware poll)
              ├── BatchReviewer (fan-in policy, gate conditions)
              └── WorkflowState (single JSON truth, atomic writes)
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
    def execute(self, task_id, label, context) -> str: ...  # returns handle
    def poll(self, handle) -> TaskResult: ...
    def cancel(self, handle) -> bool: ...
    def cleanup(self, handle) -> None: ...
```

Built-in: `SubagentExecutor` (process management) and `TmuxTaskExecutor` (tmux sessions).

---

## Reliability

| Mechanism | Implementation |
|-----------|---------------|
| **Atomic Writes** | `tempfile + os.fsync + os.replace` via `utils/io.py` |
| **UTC Timestamps** | All modules use `datetime.now(timezone.utc)` |
| **Fork Bomb Prevention** | Three-layer guard: spawn depth + pgrep count + semaphore |
| **Subprocess Timeouts** | 60s dispatch, 30s kill-session, 5s capture-pane |
| **Dispatch Lock** | `mkdir`-based atomic lock in `start-tmux-task.sh` |
| **Crash Recovery** | `workflow_loop` wraps main loop in try-except, persists state before exit |

---

## Repository Structure

```
runtime/orchestrator/           # Core modules (18 files)
├── cli.py                      # CLI entry point: plan/run/show/resume
├── workflow_state.py           # Single JSON truth model
├── workflow_state_store.py     # Mtime-based stale-write detection
├── workflow_loop.py            # Zero-dependency polling fallback
├── workflow_graph.py           # LangGraph engine (optional)
├── task_planner.py             # DAG validation + topological sort
├── batch_executor.py           # Parallel dispatch + retry
├── batch_reviewer.py           # Fan-in policy + gate conditions
├── batch_aggregator.py         # Batch analysis + stuck detection
├── orchestrator.py             # Rule chain decision engine
├── state_machine.py            # Per-task state (JSON files)
├── state_sync.py               # Callback → workflow state bridge
├── executor_interface.py       # TaskExecutorBase abstract interface
├── subagent_executor.py        # Process management + fork guard
├── subagent_config.py          # Subagent configuration
├── subagent_reconciler.py      # Queued task timeout reconciliation
├── tmux_executor.py            # Tmux session executor
└── utils/                      # io.py (atomic writes), time.py (UTC)

scripts/                        # Shell dispatch engine
├── start-tmux-task.sh          # Generic tmux task launcher
├── monitor-tmux-task.sh        # Session monitoring loop
├── status-tmux-task.sh         # Session status query
└── sync-tmux-observability.py  # Observability sync

tests/orchestrator/             # Test suite (89 unit tests)
docs/                           # Operations guide
examples/                       # Sample configs
schemas/                        # JSON schemas
```

---

## Tests

```bash
PYTHONPATH=runtime/orchestrator python3 -m pytest tests/ -v -k "not e2e"
# 89 unit tests pass
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
