# Partial Continuation Kernel v2 — Auto-Registration Layer

> **Generated:** 2026-03-22
> **Status:** v2 implemented (auto-registration + dispatch-ready intent)
> **Location:** `runtime/orchestrator/partial_continuation.py`, `runtime/orchestrator/task_registration.py`

## What This Is

**v2 upgrade: Auto-Registration Layer** — extends v1 kernel with:
1. Real task registration (writes to task registry ledger)
2. `registration_status` (registered | skipped | blocked)
3. `truth_anchor` (stable source linkage)
4. `ready_for_auto_dispatch` flag (for v3 auto-dispatch)

**Key point:** v2 transforms `next_task_registrations` from "structured proposal" to "real registered tasks with stable linkage".

## What This Is NOT

- ❌ NOT "fully automatic无人续跑" — still requires explicit registration (v2 does registration, v3 will do dispatch)
- ❌ NOT conversation-to-task auto-pilot
- ❌ NOT trading private patch — trading is just the first plug-in scenario
- ❌ NOT a complete automation engine — current state: `proposal -> registration -> dispatch-ready intent`

## Core Concepts (v2 Additions)

### 1. Registration Status

```python
RegistrationStatus = Literal["registered", "skipped", "blocked"]
```

- `registered`: Task is registered to task registry (canonical artifact)
- `skipped`: No remaining work or explicitly skipped
- `blocked`: Closeout is blocked (e.g., FAIL verdict, unresolved blocker)

### 2. Truth Anchor

```python
TruthAnchor:
  - anchor_type: "task_id" | "batch_id" | "branch" | "commit" | "push"
  - anchor_value: str  # Stable ID
  - metadata: Dict     # Source linkage (source_task_id, source_batch_id, etc.)
```

**Purpose:** Provides stable linkage between:
- Source closeout (original task/batch)
- New registration (new task_id)
- Scenario context (adapter, scenario)

### 3. Ready for Auto-Dispatch

```python
ready_for_auto_dispatch: bool
```

**Rules:**
- `registration_status == "registered"` AND
- `closeout.dispatch_readiness == "ready"` AND
- `candidate.priority == 1`

This flag enables v3 to implement full auto-dispatch without re-evaluating readiness.

### 4. Task Registry (Ledger)

New module: `runtime/orchestrator/task_registration.py`

**Features:**
- `TaskRegistry`: JSONL-based ledger for all registrations
- `TaskRegistrationRecord`: Canonical record with full metadata
- `register_task()`: Register new task with stable ID
- `get_registration()`: Retrieve by registration_id
- `list_registrations()`: List with filters (status, batch, etc.)
- `get_registrations_by_source()`: Query by source task/batch

**Storage:**
- Registry file: `~/.openclaw/shared-context/task-registry/registry.jsonl`
- Individual records: `~/.openclaw/shared-context/task-registry/{registration_id}.json`

## API Quick Reference (v2)

```python
from runtime.orchestrator.partial_continuation import (
    build_partial_closeout,
    generate_registered_registrations_for_closeout,  # v2 API
    adapt_closeout_for_trading,
)
from runtime.orchestrator.task_registration import (
    get_registration,
    list_registrations,
    get_registrations_by_source,
)

# 1. Build closeout contract
closeout = build_partial_closeout(
    completed_scope=[{"item_id": "c1", "description": "Done"}],
    remaining_scope=[{"item_id": "r1", "description": "Next step"}],
    stop_reason="partial_completed",
    dispatch_readiness="ready",
    original_batch_id="batch_123",
)

# 2. Adapt for scenario (optional)
adapted = adapt_closeout_for_trading(
    closeout=closeout,
    packet={"overall_gate": "PASS"},
    roundtable={"conclusion": "PASS", "blocker": "none"},
)

# 3. Generate registrations with status (v2 API)
# This automatically writes to task registry (auto_register=True)
registrations = generate_registered_registrations_for_closeout(
    closeout=adapted,
    adapter="trading_roundtable",
    scenario="trading_roundtable_phase1",
    auto_register=True,  # v2: writes to task registry
    batch_id="batch_123",
    owner="trading",
)

# 4. Inspect results
for reg in registrations:
    print(f"Registration: {reg.registration.registration_id}")
    print(f"  Status: {reg.registration_status}")
    print(f"  Truth Anchor: {reg.truth_anchor}")
    print(f"  Ready for Auto-Dispatch: {reg.ready_for_auto_dispatch}")
    
    # If auto_register=True, task_registry_record is populated
    if "task_registry_record" in reg.metadata:
        task_id = reg.metadata["task_registry_record"]["task_id"]
        print(f"  Task ID: {task_id}")

# 5. Query task registry
all_registered = list_registrations(registration_status="registered")
by_source = get_registrations_by_source(source_batch_id="batch_123")
```

## Migration from v1 to v2

### v1 API (still works)
```python
from partial_continuation import generate_next_registrations_for_closeout

registrations = generate_next_registrations_for_closeout(closeout, ...)
# Returns: List[NextTaskRegistrationPayload]
```

### v2 API (recommended)
```python
from partial_continuation import generate_registered_registrations_for_closeout

registrations = generate_registered_registrations_for_closeout(
    closeout,
    auto_register=True,  # Automatically writes to task registry
    ...
)
# Returns: List[NextTaskRegistrationWithStatus]
```

**Key differences:**
- v2 returns `NextTaskRegistrationWithStatus` (includes status, truth_anchor, ready_for_auto_dispatch)
- v2 automatically writes to task registry (if `auto_register=True`)
- v2 provides stable linkage via `truth_anchor`

## Scenario Integration

### Trading Roundtable (已接入)

`runtime/orchestrator/trading_roundtable.py` now uses v2 API:

```python
# In _generate_next_registrations_for_trading():
registrations = generate_registered_registrations_for_closeout(
    closeout=closeout,
    adapter=ADAPTER_NAME,
    scenario=SCENARIO,
    auto_register=True,  # v2: auto-register to task registry
    batch_id=batch_id,
    owner=closeout.metadata.get("trading_roundtable", {}).get("owner"),
)
```

**Result:** When trading roundtable completes with PASS + no blocker:
1. Partial closeout is generated (generic kernel)
2. Next task registrations are auto-generated (auto-replan)
3. Registrations are written to task registry (v2 auto-registration)
4. Each registration has stable `truth_anchor` linking back to source batch
5. `ready_for_auto_dispatch` flag indicates if v3 can auto-dispatch

### Channel Roundtable (可接入)

Same pattern can be applied:

```python
from partial_continuation import adapt_closeout_for_channel, generate_registered_registrations_for_closeout

adapted = adapt_closeout_for_channel(
    closeout=closeout,
    channel_packet={...},
    roundtable={...},
)

registrations = generate_registered_registrations_for_closeout(
    closeout=adapted,
    adapter="channel_roundtable",
    auto_register=True,
)
```

## Registration Status Logic

| Scenario | `registration_status` | `ready_for_auto_dispatch` | Writes to Registry? |
|----------|----------------------|--------------------------|---------------------|
| PASS + no blocker | `registered` | `true` | ✅ Yes |
| CONDITIONAL | `registered` | `false` | ✅ Yes (requires review) |
| FAIL | `blocked` | `false` | ❌ No |
| Blocked scope | `blocked` | `false` | ❌ No |
| Fully completed | N/A (no registrations) | N/A | ❌ No |

## Testing

```bash
# Run v2 task registration tests
python3 -m pytest tests/orchestrator/test_task_registration.py -v

# Run partial continuation tests (v1 + v2)
python3 -m pytest tests/orchestrator/test_partial_continuation.py -v

# Run all orchestrator tests with keyword filter
python3 -m pytest tests/orchestrator -q -k "partial or registration or trading"
```

**Coverage:**
- ✅ Task registry basic operations (register, get, list, update)
- ✅ Registration creates real files (JSONL ledger + individual records)
- ✅ No registrations when fully completed
- ✅ No registrations when blocked
- ✅ Trading scenario triggers real registration
- ✅ Stable linkage (source task/batch → new task id)
- ✅ `ready_for_auto_dispatch` flag logic
- ✅ Registration payload → record conversion

## Current Maturity

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
| Channel scenario integration | ⏳ Can be plugged in |
| Full auto-dispatch (v3) | ❌ Not implemented |

## Current State: v2 Achievement

```
v1: proposal (NextTaskRegistrationPayload)
       ↓
v2: registration (TaskRegistrationRecord in ledger)
       ↓
v3: dispatch (auto-dispatch without manual approval) [TODO]
```

**v2 has achieved:**
- ✅ Registration payload → real registration record (writable to ledger)
- ✅ Stable task_id / batch_id / source linkage
- ✅ `registration_status` (registered | skipped | blocked)
- ✅ `truth_anchor` with source closeout linkage
- ✅ `ready_for_auto_dispatch` flag for v3

**v2 has NOT achieved:**
- ❌ Full auto-dispatch (v3 goal)
- ❌ Universal无人续跑 (still requires explicit registration)

## Design Principles

1. **Real registration > fancy interface** — v2 writes to actual ledger
2. **Stable linkage** — Every registration has `truth_anchor` back to source
3. **Explicit status** — `registration_status` makes state clear
4. **Dispatch-ready intent** — `ready_for_auto_dispatch` enables v3
5. **Generic kernel** — Core logic has no trading/channel specifics

## Files Changed (v2)

- `runtime/orchestrator/task_registration.py` — New (task registry ledger)
- `runtime/orchestrator/partial_continuation.py` — Extended (v2 API: `generate_registered_registrations_for_closeout`, `NextTaskRegistrationWithStatus`)
- `runtime/orchestrator/trading_roundtable.py` — Modified (uses v2 API)
- `tests/orchestrator/test_task_registration.py` — New (12 tests)
- `docs/partial-continuation-kernel-v2.md` — This document

## Relationship to Existing Mechanisms

- **post_completion_replan.py**: Complements — focuses on follow-up mode (existing_dispatch vs pending_registration)
- **state_machine.py**: Task registry is parallel to state machine (registration vs execution state)
- **partial_continuation.py (v1)**: v2 extends v1 with auto-registration layer
- **waiting_guard.py**: Registration provides better "what's next" semantics

## Next Steps (v3)

- [ ] Auto-dispatch when `ready_for_auto_dispatch=True`
- [ ] Channel roundtable integration
- [ ] More sophisticated replan strategies
- [ ] Dependency graph between candidates
- [ ] Integration with subagent spawn system

## Commit

See git history for latest commit hash.
