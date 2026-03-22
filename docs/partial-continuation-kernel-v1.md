# Partial Continuation Kernel v1

> **Generated:** 2026-03-22
> **Status:** v1 implemented (minimum viable kernel)
> **Location:** `runtime/orchestrator/partial_continuation.py`

## What This Is

**Universal partial-completion continuation framework** — a generic kernel for handling tasks that complete partially and need to continue with remaining work.

**Key point:** This is **generic infrastructure**, NOT trading-specific. Trading/channel roundtables are plug-in scenarios that use this kernel.

## What This Is NOT

- ❌ NOT "fully automatic无人续跑" — still requires explicit registration
- ❌ NOT conversation-to-task auto-pilot
- ❌ NOT trading private patch — trading is just the first plug-in scenario
- ❌ NOT a complete automation engine — this is v1 minimum viable kernel

## Core Concepts

### 1. Partial Closeout Contract

Describes the state after a task completes (fully or partially):

```python
PartialCloseoutContract:
  - completed_scope: List[ScopeItem]    # What was done
  - remaining_scope: List[ScopeItem]    # What's left
  - stop_reason: StopReason             # Why stopped
  - dispatch_readiness: DispatchReadiness  # Ready for next dispatch?
  - next_candidates: List[Dict]         # Auto-generated candidates
```

**Key rules:**
- `should_generate_next_registration()` returns True only when:
  - Has `remaining_scope` AND
  - `dispatch_readiness != "blocked"` AND
  - NOT fully completed

### 2. Auto-Replan Helper

Automatically generates next task candidates from `remaining_scope`:

```python
candidates = auto_replan(closeout, max_candidates=3, context={...})
```

- Prioritizes by scope item status (partial > not_started > blocked)
- Respects `max_candidates` limit
- Returns sorted candidates by priority

### 3. Next-Task Registration Payload

Canonical artifact for registering next tasks:

```python
NextTaskRegistrationPayload:
  - registration_id: str
  - source_closeout: Dict  # PartialCloseoutContract.to_dict()
  - candidate: Dict        # NextTaskCandidate.to_dict()
  - proposed_task: Dict    # Structured task proposal
  - requires_manual_approval: bool
```

**This is the output artifact** — operator/main can consume this to actually register and dispatch next tasks.

## API Quick Reference

```python
from runtime.orchestrator.partial_continuation import (
    build_partial_closeout,
    auto_replan,
    build_next_task_registration,
    generate_next_registrations_for_closeout,
    adapt_closeout_for_trading,
    adapt_closeout_for_channel,
)

# 1. Build generic closeout contract
closeout = build_partial_closeout(
    completed_scope=[{"item_id": "c1", "description": "Done"}],
    remaining_scope=[{"item_id": "r1", "description": "Next step"}],
    stop_reason="partial_completed",
    original_task_id="task_123",
)

# 2. Adapt for specific scenario (optional)
adapted = adapt_closeout_for_trading(
    closeout=closeout,
    packet={"overall_gate": "PASS"},
    roundtable={"conclusion": "PASS", "blocker": "none"},
)

# 3. Auto-generate next candidates
candidates = auto_replan(adapted, max_candidates=3)

# 4. Generate registration payloads
registrations = generate_next_registrations_for_closeout(
    closeout=adapted,
    adapter="trading_roundtable",
    scenario="trading_roundtable_phase2",
)

# 5. Check if should generate registrations
if closeout.should_generate_next_registration():
    # Has remaining work and not blocked
    ...
else:
    # Fully completed or blocked — no registrations
    ...
```

## Scenario Integration

### Trading Roundtable (已接入)

`runtime/orchestrator/trading_roundtable.py` now integrates the generic kernel:

```python
# In process_trading_roundtable_callback():
partial_closeout = _build_partial_closeout_for_trading(batch_id, decision, analysis)
next_registrations = _generate_next_registrations_for_trading(partial_closeout, batch_id)

# Outputs available in return dict:
{
    "partial_closeout": {...},
    "next_task_registrations": [...],
    "has_remaining_work": True/False,
    ...
}
```

### Channel Roundtable (可接入)

Same pattern can be applied to `channel_roundtable.py`:

```python
from partial_continuation import adapt_closeout_for_channel, ...

adapted = adapt_closeout_for_channel(
    closeout=closeout,
    channel_packet={...},
    roundtable={...},
)
```

## Dispatch Readiness Logic

| Scenario | `dispatch_readiness` | Generates Registrations? |
|----------|---------------------|-------------------------|
| PASS + no blocker | `ready` | ✅ Yes |
| CONDITIONAL | `needs_review` | ✅ Yes (with approval) |
| FAIL | `blocked` | ❌ No |
| Blocked | `blocked` | ❌ No |
| Fully completed | `not_applicable` | ❌ No |

## Testing

```bash
# Run partial continuation tests
python3 -m pytest tests/orchestrator/test_partial_continuation.py -v

# Run with keyword filter
python3 -m pytest tests/orchestrator -q -k "partial or replan or registration"
```

**Coverage:**
- ✅ Generic partial closeout contract construction
- ✅ Auto-replan generates next candidates
- ✅ No registrations when fully completed
- ✅ No registrations when blocked
- ✅ Trading scenario integration
- ✅ Channel scenario integration

## Current Maturity

| Capability | Status |
|------------|--------|
| Generic closeout contract | ✅ v1 implemented |
| Auto-replan helper | ✅ v1 implemented |
| Next-task registration payload | ✅ v1 implemented |
| Trading scenario integration | ✅ Minimum viable integration |
| Channel scenario integration | ⏳ Can be plugged in (not yet done) |
| Auto-write to state machine | ❌ Not implemented (manual step) |
| Full auto-dispatch | ❌ Not implemented |

## Next Steps (Not In Scope For v1)

- [ ] Auto-write registrations to state machine
- [ ] Full auto-dispatch without manual approval
- [ ] Channel roundtable integration
- [ ] More sophisticated replan strategies
- [ ] Dependency graph between candidates

## Design Principles

1. **Generic first** — Core kernel has no trading/channel specifics
2. **Explicit over implicit** — Registrations are explicit artifacts, not magic
3. **Safe defaults** — Blocked/failed states don't auto-generate next tasks
4. **Composable** — Scenarios plug in via adapter functions
5. **Observable** — All outputs are structured dicts for inspection

## Relationship to Existing Mechanisms

- **post_completion_replan.py**: Complements this — focuses on follow-up mode (existing_dispatch vs pending_registration)
- **state_machine.py**: Registrations can eventually write to state machine (not yet)
- **contracts.py**: Uses orchestration contracts for scenario metadata
- **waiting_guard.py**: Partial closeout provides better "why stopped" semantics

## Files Changed

- `runtime/orchestrator/partial_continuation.py` — New (generic kernel)
- `runtime/orchestrator/trading_roundtable.py` — Modified (integration)
- `tests/orchestrator/test_partial_continuation.py` — New (33 tests)
- `docs/partial-continuation-kernel-v1.md` — This document

## Commit

See git history for latest commit hash.
