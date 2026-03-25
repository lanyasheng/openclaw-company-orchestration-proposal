# OpenClaw Orchestration Control Plane

> Multi-agent workflow orchestration for OpenClaw — one chain, one state file, automatic batch-to-batch advancement.

[中文文档](README_CN.md)

## What It Does

After one agent task finishes, what happens next? This framework answers that question with a structured control plane:

1. **Decompose** — break a goal into ordered batches of parallel tasks
2. **Execute** — dispatch tasks to SubagentExecutor in parallel
3. **Review** — evaluate batch results with configurable fan-in policies
4. **Advance** — automatically proceed to the next batch, or stop at a gate

```
TaskPlanner → BatchExecutor → BatchReviewer → advance → next batch → ...
```

## Quick Start

```bash
# 1. Create a workflow
python3 runtime/orchestrator/cli.py plan "Trading analysis" config.json

# 2. Run it (auto-detects LangGraph or falls back to polling loop)
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json

# 3. Check status
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json

# 4. Resume after interruption or gate
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

### Example config.json

```json
[
  {
    "batch_id": "b0",
    "label": "Data collection",
    "tasks": [
      {"task_id": "t1", "label": "Collect A-share data"},
      {"task_id": "t2", "label": "Collect HK data"}
    ],
    "depends_on": []
  },
  {
    "batch_id": "b1",
    "label": "Analysis",
    "tasks": [
      {"task_id": "t3", "label": "Cross-market trend analysis"}
    ],
    "depends_on": ["b0"],
    "fan_in_policy": "all_success"
  }
]
```

## Architecture

```
cli.py                          ← single entry point
  │
  ├── task_planner.py           ← DAG validation + topological sort
  │     └── workflow_state.py   ← unified state model
  │
  ├── workflow_graph.py         ← LangGraph StateGraph (recommended)
  │   (or workflow_loop.py)     ← polling fallback (no langgraph dep)
  │     │
  │     ├── batch_executor.py   ← parallel SubagentExecutor dispatch
  │     │     └── subagent_executor.py
  │     │
  │     └── batch_reviewer.py   ← fan-in evaluation + gate conditions
  │
  └── workflow_state.py         ← load / save / query
```

### Single Source of Truth

All state lives in one file: `workflow_state_<id>.json`

```
workflow_state.json
├── workflow_id, status         # global state
├── plan.current_batch_index    # which batch is active
├── batches[]                   # each batch's full state
│   ├── tasks[]                 # each task's result and status
│   └── continuation            # review decision (proceed/gate/stop)
└── context_summary             # LLM semantic recovery after context compression
```

### Execution Engines

| Engine | File | When |
|--------|------|------|
| **LangGraph** | `workflow_graph.py` | `langgraph` installed — automatic checkpointing, conditional routing, interrupt/resume |
| **WorkflowLoop** | `workflow_loop.py` | No langgraph — equivalent functionality via polling |

Both share the same underlying modules. The CLI auto-detects which to use.

## Core Concepts

### Continuation Contract

Every batch completion produces an explicit decision:

```python
ContinuationDecision(
    stopped_because="all tasks completed",
    decision="proceed",       # proceed | gate | stop
    next_batch="b1",
    decided_at="2026-03-25T10:05:00Z"
)
```

### Fan-in Policies

| Policy | Rule | Use Case |
|--------|------|----------|
| `all_success` | Every task must complete | Critical workflows |
| `any_success` | At least one task succeeds | Exploratory research |
| `majority` | >50% tasks succeed | Voting / consensus |

### Gate Conditions

If any task result contains `NEEDS_REVIEW`, the batch triggers a gate — the workflow pauses until a human approves and runs `resume`.

### DAG Dependencies

Batches can declare dependencies. The planner validates the DAG (cycle detection via Kahn's algorithm) and orders batches topologically.

### Context Recovery

`context_summary` is auto-generated after each state change. When an LLM agent's context window compresses, it can read this field to understand where the workflow left off — no need to replay the full history.

## Python API

```python
from task_planner import TaskPlanner
from workflow_graph import run_workflow
from workflow_state import save_workflow_state, load_workflow_state

# Plan
planner = TaskPlanner()
state = planner.plan("My workflow", batches_config)
save_workflow_state(state, "state.json")

# Run
result = run_workflow(state, "state.json", workspace_dir=".")

# Resume
from workflow_graph import resume_workflow
result = resume_workflow("state.json")
```

## Testing

```bash
pip install pytest langgraph

# Run all tests
PYTHONPATH=runtime/orchestrator:runtime/scripts pytest tests/orchestrator/ -q

# v2 tests only
PYTHONPATH=runtime/orchestrator:runtime/scripts pytest tests/orchestrator/test_workflow_v2.py -v
```

**781 tests passing** — 34 v2 tests (state, planner, reviewer, LangGraph graph) + 747 v1 tests.

## Project Structure

```
runtime/orchestrator/
├── cli.py                  # CLI entry point
├── workflow_state.py       # Unified state model
├── workflow_graph.py       # LangGraph engine
├── workflow_loop.py        # Polling engine (fallback)
├── task_planner.py         # DAG planner
├── batch_executor.py       # Parallel dispatch
├── batch_reviewer.py       # Fan-in + gate
├── subagent_executor.py    # SubagentExecutor wrapper
├── state_machine.py        # v1 task state (compat)
├── orchestrator.py         # v1 callback handler (compat)
└── ...                     # v1 modules (preserved for reference)

tests/orchestrator/
├── test_workflow_v2.py     # v2 test suite
└── ...                     # v1 tests

docs/
├── CURRENT_TRUTH.md        # Current system state
├── OPERATIONS.md           # Operations guide
└── ...                     # Design documents
```

## Why This Exists

Most multi-agent frameworks (LangGraph, CrewAI, AutoGen) focus on agent-to-agent communication or graph execution. They don't answer:

- **Who owns the task?** Owner/Executor decoupling separates business judgment from execution.
- **What happens after completion?** Continuation Contract makes every transition explicit.
- **How do you recover after context compression?** `context_summary` provides semantic recovery.
- **How do you safely auto-advance?** Gate conditions + fan-in policies, not just "run the next node."

This framework is a **control plane** that sits above the execution layer. It can use LangGraph as its execution engine while adding orchestration semantics that LangGraph doesn't provide out of the box.

## License

MIT
