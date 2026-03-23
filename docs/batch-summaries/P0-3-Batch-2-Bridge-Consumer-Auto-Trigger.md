# P0-3 Batch 2: Bridge Consumer Auto-Trigger Path

> **Date**: 2026-03-23
> **Status**: ✅ Complete
> **Tests**: 18/18 passed (bridge_consumer), 398/398 passed (full orchestrator suite)

---

## Executive Summary

P0-3 Batch 2 enables the **general bridge_consumer auto-trigger path** with readiness/safety_gates/truth_anchor checks. Trading is the first validation scenario, but the implementation remains adapter-agnostic.

**Key Achievement**: Auto-trigger decision now evaluates:
1. ✅ readiness.eligible / readiness.status
2. ✅ safety_gates.allow_auto_dispatch
3. ✅ truth_anchor (for traceability)

---

## What Changed

### 1. Enhanced Auto-Trigger Guard (`sessions_spawn_request.py`)

**File**: `runtime/orchestrator/sessions_spawn_request.py`

**Function**: `_should_auto_trigger()`

**P0-3 Batch 2 Enhancements**:
```python
# Check 6: truth_anchor present (traceability)
truth_anchor = metadata.get("truth_anchor")
# Soft check - allows backward compatibility

# Check 7: readiness eligible (if present)
readiness = metadata.get("readiness")
if readiness:
    if not readiness.get("eligible", False) or readiness.get("status") != "ready":
        return False, f"Readiness not met: status={readiness_status}, blockers={blockers}"

# Check 8: safety_gates.allow_auto_dispatch (if present)
safety_gates = metadata.get("safety_gates")
if safety_gates:
    if safety_gates.get("allow_auto_dispatch", False) is False:
        return False, f"Safety gates not passed: allow_auto_dispatch={allow_auto_dispatch}"
```

**Design Principle**: Checks are conditional - if readiness/safety_gates are not present in metadata, the guard doesn't block (backward compatibility). This allows gradual migration.

---

### 2. Integration Tests (`test_bridge_consumer.py`)

**File**: `tests/orchestrator/test_bridge_consumer.py`

**New Test Class**: `TestAutoTriggerWithReadinessSafetyGates`

**4 New Tests**:

| Test | Purpose | Status |
|------|---------|--------|
| `test_auto_trigger_with_ready_readiness_safety_gates` | Happy path: readiness/safety_gates met → auto-trigger succeeds | ✅ |
| `test_auto_trigger_blocked_by_readiness` | Readiness not met → auto-trigger blocked | ✅ |
| `test_auto_trigger_blocked_by_safety_gates` | Safety gates not passed → auto-trigger blocked | ✅ |
| `test_auto_trigger_general_not_trading_specific` | Generic scenario (not trading) → auto-trigger works | ✅ |

**Key Validation**: The last test proves the implementation is **generic**, not trading-specific.

---

## Design Decisions

### 1. Generic First, Trading as First Validator

**Decision**: Keep bridge_consumer and auto-trigger guard adapter-agnostic.

**Rationale**:
- Trading is the first use case, but not the only one
- Channel roundtable, macro, content, and other scenarios will use the same path
- Avoids technical debt from scenario-specific logic

**Implementation**:
- Readiness/safety_gates are generic fields in metadata
- Scenario allowlist/denylist is configurable
- No trading-specific semantics in bridge_consumer

### 2. Conditional Checks (Backward Compatibility)

**Decision**: Readiness/safety_gates checks are conditional.

**Rationale**:
- Existing receipts may not have readiness/safety_gates in metadata
- Allows gradual migration without breaking existing flows
- New receipts should include these fields for full auto-trigger protection

**Implementation**:
```python
readiness = metadata.get("readiness")
if readiness:  # Only check if present
    ...

safety_gates = metadata.get("safety_gates")
if safety_gates:  # Only check if present
    ...
```

### 3. Auto-Trigger Decision Only (Not Execution)

**Decision**: This batch enables auto-trigger **decision**, not execution.

**Rationale**:
- Separation of concerns: decision vs. execution
- Execution (real sessions_spawn API call) is V9 / future batch
- This batch focuses on safe semi-auto decision logic

**Current Flow**:
```
receipt → sessions_spawn_request (prepared) → auto-trigger guard → bridge_consumer.consume() → consumed artifact
```

**Future Flow** (V9+):
```
receipt → sessions_spawn_request (prepared) → auto-trigger guard → bridge_consumer.consume() → sessions_spawn_bridge.execute() → real API call
```

---

## What's Real vs. What's Not

### ✅ Real (This Batch)
1. Auto-trigger guard evaluates readiness/safety_gates/truth_anchor
2. Bridge consumer can consume requests with these fields
3. Integration tests validate the full chain: artifact → bridge_consumer → auto-trigger decision
4. Trading scenario validated (but implementation is generic)

### ⏳ Future Batches
1. Real sessions_spawn API execution (V9)
2. Auto-trigger to real execution (not just decision)
3. Multi-scenario concurrent execution control
4. Configuration management (version control / multi-env sync)

---

## Files Changed

| File | Changes |
|------|---------|
| `runtime/orchestrator/sessions_spawn_request.py` | Enhanced `_should_auto_trigger()` with readiness/safety_gates checks |
| `tests/orchestrator/test_bridge_consumer.py` | Added 4 integration tests for auto-trigger with readiness/safety_gates |
| `docs/batch-summaries/P0-3-Batch-2-Bridge-Consumer-Auto-Trigger.md` | This summary document |

---

## Test Results

### Bridge Consumer Tests
```
============================== 18 passed in 0.13s ==============================
```

### Full Orchestrator Suite
```
================= 398 passed, 12 warnings in 129.01s (0:02:09) =================
```

---

## Usage

### Configure Auto-Trigger

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal

# Enable auto-trigger for trading scenario
python3 -c "
from runtime.orchestrator.sessions_spawn_request import configure_auto_trigger
config = configure_auto_trigger(
    enabled=True,
    allowlist=['trading'],
    require_manual_approval=False,
)
print(config)
"
```

### Manual Auto-Trigger

```bash
# Trigger single request
python3 -c "
from runtime.orchestrator.sessions_spawn_request import auto_trigger_consumption
triggered, reason, consumed_id = auto_trigger_consumption('req_xxx')
print(f'Triggered: {triggered}, Reason: {reason}, Consumed ID: {consumed_id}')
"
```

### Check Auto-Trigger Status

```bash
python3 -c "
from runtime.orchestrator.sessions_spawn_request import get_auto_trigger_status
status = get_auto_trigger_status()
print(status)
"
```

---

## Risk Assessment

### Low Risk
- ✅ Backward compatible (conditional checks)
- ✅ All existing tests pass
- ✅ New tests cover edge cases
- ✅ No breaking changes to existing APIs

### Mitigation
- If issues arise, disable auto-trigger: `configure_auto_trigger(enabled=False)`
- Existing flows without readiness/safety_gates continue to work
- Manual approval mode available: `configure_auto_trigger(require_manual_approval=True)`

---

## Rollback Plan

1. **Disable auto-trigger**:
   ```python
   configure_auto_trigger(enabled=False)
   ```

2. **Revert code changes**:
   ```bash
   git revert <commit-hash>
   ```

3. **Restore previous config**:
   ```bash
   rm ~/.openclaw/shared-context/spawn_requests/auto_trigger_config.json
   ```

---

## Next Steps (P0-3 Batch 3+)

1. **V9 Real API Execution**: Connect bridge_consumer to sessions_spawn_bridge for real API calls
2. **Auto-Trigger to Execution**: Extend auto-trigger from decision to real execution
3. **Multi-Scenario Support**: Validate with channel/macro/content scenarios
4. **Monitoring/Alerting**: Add auto-trigger execution monitoring and alerts

---

## Conclusion

P0-3 Batch 2 successfully enables the general bridge_consumer auto-trigger path with readiness/safety_gates/truth_anchor checks. The implementation is adapter-agnostic, with trading as the first validation scenario. All tests pass, and the design maintains backward compatibility.

**Status**: ✅ Complete, ready for merge.
