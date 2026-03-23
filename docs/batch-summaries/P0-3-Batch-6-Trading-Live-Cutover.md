# P0-3 Batch 6: Trading Live Cutover

**Date:** 2026-03-23  
**Status:** ✅ Completed  
**Commit:** TBD

## Summary

Enabled real execution (`safe_mode=False`) for trading allowlist scenarios and validated end-to-end live execution with real `childSessionKey` / `runId` / `pid` anchors.

## Changes

### 1. Configuration Change
**File:** `~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json`

```json
{
  "enabled": true,
  "allowlist": ["trading", "trading_batch3_7a6f70", "trading_batch3_904e6d"],
  "denylist": [],
  "require_manual_approval": false,
  "safe_mode": false,  // Changed from true to false
  "max_concurrent_executions": 3
}
```

### 2. Code Fixes
**File:** `runtime/orchestrator/sessions_spawn_bridge.py`

#### Fix 1: Policy Construction from Config
The `auto_trigger_real_execution()` function now constructs `SessionsSpawnBridgePolicy` from the config file instead of using default values:

```python
# P0-3 Batch 6 fix: Construct policy from config
if policy is None:
    policy = SessionsSpawnBridgePolicy(
        safe_mode=config.get("safe_mode", True),
        allowlist=config.get("allowlist", ["trading"]),
        denylist=config.get("denylist", []),
        require_manual_approval=config.get("require_manual_approval", True),
        max_concurrent=config.get("max_concurrent_executions", 3),
    )
```

#### Fix 2: CLI Fallback to Python API
The `_call_openclaw_sessions_spawn()` method now falls back to Python API when CLI fails:

```python
if cli_path:
    success, error, api_response = self._call_via_cli(cli_path, call_params)
    if success:
        return success, error, api_response
    # CLI failed, fall back to Python API
    print(f"[WARN] CLI call failed ({error}), falling back to Python API")

return self._call_via_python_api(call_params)
```

## Live Validation Results

### Test Case: batch6_live3_eaa91f
- **Request ID:** `req_batch6_3_eaa91f`
- **Receipt ID:** `batch6_live3_eaa91f`
- **Execution ID:** `exec_api_d2f7a81b0cd1`

### Execution Anchors (Real)
| Anchor | Value |
|--------|-------|
| `api_execution_status` | `started` |
| `childSessionKey` | `session_a505d68f5d27` |
| `runId` | `run_3bfd3562` |
| `pid` | `3883` |
| `label` | `batch6-live3-eaa91f` |
| `runtime` | `subagent` |
| `safe_mode` | `False` |
| `should_execute_real` | `True` |

### Execution Chain Validation
```
completion_receipt (batch6_live3_eaa91f)
    ↓
sessions_spawn_request (req_batch6_3_eaa91f, status=prepared)
    ↓
bridge_consumed (auto-triggered)
    ↓
api_execution (exec_api_d2f7a81b0cd1, status=started) ← REAL EXECUTION
    ↓
subagent runner (pid=3883) ← ACTUAL PROCESS STARTED
```

## Design Notes

### Generic vs Trading-Specific
- **Generic:** All orchestration logic remains adapter-agnostic
- **Trading-specific:** Only the allowlist configuration (`allowlist: ["trading", ...]`)
- **Safe mode:** Default remains `true` for non-allowlisted scenarios

### Backward Compatibility
- Existing `safe_mode=true` artifacts remain unchanged
- `pending` status still recorded for safe-mode scenarios
- Dedupe index includes both `started` and `pending` executions

## Next Steps: Legacy Cleanup (Batch 7+)

1. **Remove safe_mode flag** after validating trading continuation in production
2. **Consolidate allowlist/denylist** into a single `execution_policy` config
3. **Add metrics/logging** for execution latency and success rates
4. **Clean up test artifacts** from batch 3-6 validation runs
5. **Document production runbook** for enabling real execution for new adapters

## Artifacts

- Config: `~/.openclaw/shared-context/spawn_requests/auto_trigger_real_exec_config.json`
- Execution: `~/.openclaw/shared-context/api_executions/exec_api_d2f7a81b0cd1.json`
- Request: `~/.openclaw/shared-context/spawn_requests/req_batch6_3_eaa91f.json`
- Receipt: `~/.openclaw/shared-context/completion_receipts/batch6_live3_eaa91f.json`
