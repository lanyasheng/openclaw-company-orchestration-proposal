# Partial Continuation Kernel v3 — Auto-Dispatch Execution

> **Generated:** 2026-03-22
> **Status:** v3 implemented (auto-dispatch intent + limited execution)
> **Location:** `runtime/orchestrator/auto_dispatch.py`

## What This Is

**v3 upgrade: Auto-Dispatch Execution Layer** — extends v2 with:
1. Auto-dispatch selector: Select tasks from registry with `ready_for_auto_dispatch=True`
2. Dispatch policy evaluation: Evaluate eligibility (blocked / missing anchor / scenario allowlist / duplicate)
3. Dispatch artifact generation: Real dispatch records with `dispatch_status` / `dispatch_reason` / `dispatch_time` / `dispatch_target`
4. Minimal execution path: Trading scenario produces real dispatch artifact + execution intent

**Key point:** v3 transforms `registered tasks` to `dispatched tasks with execution intent`.

## What This Is NOT

- ❌ NOT "fully automatic 无人续跑" — still limited to allowlist scenarios
- ❌ NOT universal auto-pilot — blocked / missing anchor / manual-only tasks are stopped
- ❌ NOT production-ready for all scenarios — trading is the first plug-in scenario
- ❌ NOT a complete automation engine — current state: `proposal -> registration -> auto-dispatch intent / limited execution`

## Core Concepts (v3 Additions)

### 1. Dispatch Status

```python
DispatchStatus = Literal["dispatched", "skipped", "blocked"]
```

- `dispatched`: Task is dispatched (execution intent generated)
- `skipped`: Task is skipped (e.g., no remaining work)
- `blocked`: Task is blocked (policy evaluation failed)

### 2. Dispatch Policy

```python
DispatchPolicy:
  - scenario_allowlist: List[str]  # Default: ["trading_roundtable_phase1"]
  - blocked_statuses: List[str]    # Default: ["blocked", "in_progress"]
  - require_anchor: bool           # Default: True
  - prevent_duplicate: bool        # Default: True
```

**Purpose:** Controls which tasks can be auto-dispatched.

### 3. Dispatch Artifact

```python
DispatchArtifact:
  - dispatch_id: str
  - registration_id: str
  - task_id: str
  - dispatch_status: DispatchStatus
  - dispatch_reason: str
  - dispatch_time: str
  - dispatch_target: Dict  # {scenario, adapter, batch_id, owner}
  - execution_intent: Optional[Dict]  # {recommended_spawn, ...}
  - policy_evaluation: Dict
```

**Purpose:** Canonical artifact for dispatch records (writable to disk).

### 4. Execution Intent (Minimal Execution Path)

```python
execution_intent:
  - recommended_spawn:
      - runtime: "subagent"
      - task_preview: str
      - task: str
      - cwd: str
      - metadata:
          - dispatch_id: str
          - registration_id: str
          - task_id: str
          - source: "auto_dispatch_v3"
          - trading_context: Dict  # For trading scenario
```

**Purpose:** Provides actionable spawn intent for downstream execution.

### 5. Dispatch Storage

New module: `runtime/orchestrator/auto_dispatch.py`

**Storage:**
- Dispatch artifacts: `~/.openclaw/shared-context/dispatches/{dispatch_id}.json`

## API Quick Reference (v3)

```python
from runtime.orchestrator.auto_dispatch import (
    AutoDispatchSelector,
    DispatchExecutor,
    DispatchPolicy,
    select_ready_tasks,
    evaluate_dispatch_policy,
    execute_dispatch,
    list_dispatches,
    get_dispatch,
)
from runtime.orchestrator.task_registration import list_registrations

# 1. Select ready tasks
ready_tasks = select_ready_tasks(limit=10)
print(f"Found {len(ready_tasks)} ready tasks")

# 2. Evaluate policy for a task
for record in ready_tasks:
    evaluation = evaluate_dispatch_policy(record)
    print(f"Task {record.task_id}: eligible={evaluation['eligible']}")
    if not evaluation["eligible"]:
        print(f"  Blocked: {evaluation['blocked_reasons']}")

# 3. Execute dispatch (writes artifact + updates task status)
for record in ready_tasks:
    artifact = execute_dispatch(record)
    print(f"Dispatch {artifact.dispatch_id}: {artifact.dispatch_status}")
    if artifact.execution_intent:
        print(f"  Execution intent: {artifact.execution_intent['recommended_spawn']['task_preview']}")

# 4. List dispatches
all_dispatches = list_dispatches()
dispatched = list_dispatches(dispatch_status="dispatched")
by_registration = list_dispatches(registration_id="reg_123")

# 5. Get single dispatch
dispatch = get_dispatch("dispatch_abc123")
if dispatch:
    print(f"Status: {dispatch.dispatch_status}")
    print(f"Reason: {dispatch.dispatch_reason}")

# 6. Custom policy
custom_policy = DispatchPolicy(
    scenario_allowlist=["trading_roundtable_phase1", "custom_scenario"],
    require_anchor=True,
    prevent_duplicate=True,
)
ready_tasks = select_ready_tasks(limit=10, policy=custom_policy)
```

## Policy Evaluation Logic

| Check | Description | Pass Condition |
|-------|-------------|----------------|
| `scenario_allowlist` | Scenario is in allowlist | `scenario in policy.scenario_allowlist` |
| `truth_anchor_required` | Truth anchor is present | `record.truth_anchor is not None` (if `require_anchor=True`) |
| `registration_status` | Registration status is registered | `record.registration_status == "registered"` |
| `task_status_not_blocked` | Task status is not blocked | `record.status not in policy.blocked_statuses` |
| `ready_for_auto_dispatch` | Ready flag is true | `record.ready_for_auto_dispatch == True` |
| `prevent_duplicate_dispatch` | No existing dispatch | No existing dispatch with `dispatch_status="dispatched"` |

## Scenario Allowlist (Default)

```python
DEFAULT_AUTO_DISPATCH_ALLOWED_SCENARIOS = [
    "trading_roundtable_phase1",
    # More scenarios can be added
]
```

**Rationale:**
- Trading roundtable phase 1 is low-risk (evidence/orchestration layer only)
- Does not trigger real trading execution
- Single-step continuation with clear completion criteria

## Execution Intent Structure

### Generic Structure

```json
{
  "recommended_spawn": {
    "runtime": "subagent",
    "task_preview": "Trading continuation",
    "task": "Continue trading roundtable phase 1...",
    "cwd": "/Users/study/.openclaw/workspace",
    "metadata": {
      "dispatch_id": "dispatch_abc123",
      "registration_id": "reg_xyz789",
      "task_id": "task_def456",
      "source": "auto_dispatch_v3"
    }
  }
}
```

### Trading Scenario Enhancement

```json
{
  "recommended_spawn": {
    "metadata": {
      "dispatch_id": "dispatch_abc123",
      "trading_context": {
        "batch_id": "batch_123",
        "phase": "phase1_continuation",
        "adapter": "trading_roundtable"
      }
    }
  }
}
```

## Dispatch Lifecycle

```
v2 registered task
       ↓
v3: Auto-dispatch selector
       ↓
Policy evaluation (eligible? blocked? duplicate?)
       ↓
  ┌────┴────┐
  │         │
eligible   blocked
  │         │
  ↓         ↓
Generate dispatch artifact
  - dispatch_status = "dispatched"
  - execution_intent = {...}
  - Update task status to "in_progress"
  - Write artifact to disk
       ↓
Downstream execution (subagent spawn, etc.)
```

## Testing

```bash
# Run v3 auto_dispatch tests
python3 -m pytest tests/orchestrator/test_auto_dispatch.py -v

# Run all orchestrator tests with keyword filter
python3 -m pytest tests/orchestrator -q -k "dispatch or registration or partial"
```

**Coverage:**
- ✅ Select ready tasks from registry
- ✅ Filter not-ready tasks
- ✅ Filter blocked status tasks
- ✅ Policy evaluation: happy path (trading scenario)
- ✅ Policy evaluation: blocked (scenario not in allowlist)
- ✅ Policy evaluation: blocked (missing anchor)
- ✅ Policy evaluation: blocked (duplicate dispatch)
- ✅ Execute dispatch: generates artifact
- ✅ Execute dispatch: blocked path
- ✅ Trading scenario: execution intent with trading_context
- ✅ List and get dispatches
- ✅ Dispatch artifact serialization
- ✅ Custom policy

## Integration with v2

### v2 → v3 Flow

```python
from runtime.orchestrator.partial_continuation import (
    generate_registered_registrations_for_closeout,
    adapt_closeout_for_trading,
)
from runtime.orchestrator.auto_dispatch import execute_dispatch

# v2: Generate registrations from closeout
registrations = generate_registered_registrations_for_closeout(
    closeout=adapted,
    adapter="trading_roundtable",
    auto_register=True,
    batch_id="batch_123",
)

# v3: Execute dispatch for ready registrations
for reg in registrations:
    if reg.ready_for_auto_dispatch:
        # Get full record from registry
        record = get_registration(reg.registration.registration_id)
        
        # Execute dispatch
        artifact = execute_dispatch(record)
        
        if artifact.dispatch_status == "dispatched":
            # Access execution intent
            spawn_intent = artifact.execution_intent["recommended_spawn"]
            print(f"Ready to spawn: {spawn_intent['task_preview']}")
```

### Current Maturity

| Capability | Status |
|------------|--------|
| Generic closeout contract (v1) | ✅ Implemented |
| Auto-replan helper (v1) | ✅ Implemented |
| Next-task registration payload (v1) | ✅ Implemented |
| Task registry ledger (v2) | ✅ Implemented |
| `registration_status` (v2) | ✅ Implemented |
| `truth_anchor` (v2) | ✅ Implemented |
| `ready_for_auto_dispatch` (v2) | ✅ Implemented |
| Trading scenario integration (v2) | ✅ Integrated |
| Auto-dispatch selector (v3) | ✅ Implemented |
| Dispatch policy evaluation (v3) | ✅ Implemented |
| Dispatch artifact generation (v3) | ✅ Implemented |
| Execution intent (v3) | ✅ Implemented |
| Trading scenario integration (v3) | ✅ Integrated |
| Full auto-dispatch execution | ⏳ Minimal execution path (artifact + intent) |
| Universal 无人续跑 | ❌ Not implemented (intentional) |

## Current State: v3 Achievement

```
v1: proposal (NextTaskRegistrationPayload)
       ↓
v2: registration (TaskRegistrationRecord in ledger)
       ↓
v3: dispatch (DispatchArtifact with execution intent)
       ↓
v4+: full execution (subagent spawn, callback, closeout) [TODO]
```

**v3 has achieved:**
- ✅ Auto-dispatch selector (reads from task registry)
- ✅ Dispatch policy evaluation (allowlist / anchor / duplicate checks)
- ✅ Dispatch artifact generation (writable to disk)
- ✅ Execution intent (recommended_spawn for downstream)
- ✅ Trading scenario integration (trading_context in metadata)
- ✅ Task status update (pending → in_progress after dispatch)

**v3 has NOT achieved:**
- ❌ Actual subagent spawn (downstream execution)
- ❌ Callback-driven continuation (v4+ goal)
- ❌ Universal 无人续跑 (still limited to allowlist)

## Design Principles

1. **Real dispatch > fancy abstraction** — v3 writes actual dispatch artifacts
2. **Policy-first** — Explicit allowlist / checks before dispatch
3. **Minimal execution path** — Execution intent is actionable, not just metadata
4. **Generic kernel** — Core logic has no trading/channel specifics
5. **Explicit boundaries** — Current state is `auto-dispatch intent / limited execution`, not full automation

## Files Changed (v3)

- `runtime/orchestrator/auto_dispatch.py` — New (auto-dispatch selector + executor)
- `tests/orchestrator/test_auto_dispatch.py` — New (50+ tests)
- `docs/partial-continuation-kernel-v3.md` — This document
- `docs/CURRENT_TRUTH.md` — Updated (v3 section)

## Relationship to Existing Mechanisms

- **task_registration.py (v2)**: v3 reads from task registry
- **partial_continuation.py (v1/v2)**: v3 dispatches v2 registrations
- **trading_roundtable.py**: v3 integrates with trading scenario
- **orchestrator_dispatch_bridge.py**: v3 execution intent can feed into dispatch bridge
- **state_machine.py**: v3 updates task status (pending → in_progress)

## Next Steps (v4+)

- [ ] Actual subagent spawn from execution intent
- [ ] Callback-driven continuation (dispatch → execute → callback → closeout → next dispatch)
- [ ] More scenario integrations (channel_roundtable, etc.)
- [ ] Advanced replan strategies (dependency graph, priority queue)
- [ ] Monitoring / observability for dispatch lifecycle

## Commit

See git history for latest commit hash.
