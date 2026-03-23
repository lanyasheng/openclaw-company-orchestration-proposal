# P0-3 Batch 7: Fix Real Execution Path - Remove Non-Existent CLI Dependency

> **Date**: 2026-03-23
> **Status**: ✅ Complete
> **Tests**: 405/405 passed (full orchestrator suite)
> **Commit**: `256e299`

---

## Executive Summary

P0-3 Batch 7 fixes the **real execution path bug** where the implementation was trying to call `openclaw sessions_spawn` CLI command which doesn't exist. This was causing execution failures with error `unknown command 'sessions_spawn'`.

**Key Achievement**: Removed CLI dependency, always use Python API path with subagent runner. Trading continuation can now truly spawn real subagents.

---

## Problem Statement

### Symptom
API execution failures with error:
```
error: unknown command 'sessions_spawn'
```

### Root Cause Analysis

1. **CLI Path Tried First**: `_call_openclaw_sessions_spawn()` attempted to use OpenClaw CLI before falling back to Python API
2. **Non-Existent Command**: `openclaw sessions_spawn` subcommand doesn't exist in the CLI
3. **Empty cwd Parameter**: Even when Python API path was used, empty `cwd` caused `subprocess.Popen` to fail with `FileNotFoundError`

### Evidence from Failed Execution

From `exec_api_41bb10388954.json`:
```json
{
  "api_execution_status": "failed",
  "api_execution_reason": "API call failed: ... error: unknown command 'sessions_spawn'\n"
}
```

---

## What Changed

### 1. Removed CLI Path Entirely

**File**: `runtime/orchestrator/sessions_spawn_bridge.py`

**Removed Methods**:
- `_find_openclaw_cli()`: Find OpenClaw CLI path (no longer needed)
- `_call_via_cli()`: Call CLI with `sessions_spawn` subcommand (doesn't exist)

**Updated Method**:
```python
def _call_openclaw_sessions_spawn(self, request: SessionsSpawnRequest) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    调用真实 OpenClaw sessions_spawn API。
    
    使用 OpenClaw 现有 subagent runner 基础设施（run_subagent_claude_v1.sh）。
    
    注意：不使用 `openclaw sessions_spawn` CLI 命令，因为该子命令不存在。
    直接使用 Python API 调用 runner 脚本。
    """
    # ... build call_params ...
    
    # 直接调用 Python sessions_spawn API（使用 subagent runner）
    # 注意：不使用 CLI 路径，因为 `openclaw sessions_spawn` 子命令不存在
    return self._call_via_python_api(call_params)
```

**Rationale**: 
- `openclaw sessions_spawn` CLI command doesn't exist
- Python API path via subagent runner is the correct, working path
- Simplifies code by removing dead branch

---

### 2. Fixed Empty `cwd` Handling

**Problem**: `call_params.get("cwd", default)` returns empty string if key exists with empty value, not the default.

**Fix**: Use `or` operator to handle empty strings:
```python
# Before (buggy)
cwd = spawn_params.get("cwd", str(Path.home() / ".openclaw" / "workspace"))

# After (fixed)
cwd = spawn_params.get("cwd") or str(Path.home() / ".openclaw" / "workspace")
```

**Applied In**:
- `_call_openclaw_sessions_spawn()`: Building `call_params`
- `_call_via_python_api()`: Extracting `cwd` from `call_params`

---

### 3. Added Path Resolution

**Added**: `runner_script = runner_script.resolve()` to ensure absolute paths.

**Rationale**: Prevents issues with relative paths in subprocess calls.

---

## Live Validation Results

### Test Execution

**Request**: `req_9cfdc6587306` (trading scenario)

**Result**:
```
Status: started
Reason: API call successful
runId: run_fe98f3b0
childSessionKey: session_4705ff51ed8d
pid: 9580
runner_script: `~/.openclaw/scripts/run_subagent_claude_v1.sh`
```

**Execution Anchors**:
| Anchor | Value |
|--------|-------|
| `runId` | `run_fe98f3b0` |
| `childSessionKey` | `session_4705ff51ed8d` |
| `pid` | `9580` |
| `label` | `orch-batch7_l` |
| `runner_script` | `~/.openclaw/scripts/run_subagent_claude_v1.sh` |

**Artifact Path**: `~/.openclaw/shared-context/api_executions/exec_api_*.json`

---

## Files Changed

| File | Changes |
|------|---------|
| `runtime/orchestrator/sessions_spawn_bridge.py` | Removed CLI path methods; fixed empty `cwd` handling; added path resolution |
| `docs/batch-summaries/P0-3-Batch-7-Fix-Real-Execution-Path.md` | This summary document |

**Diff Stats**: `12 insertions(+), 81 deletions(-)`

---

## Test Results

### Full Orchestrator Suite
```
====================== 405 passed, 12 warnings in 129.82s =======================
```

### P0-3 Batch 7 Specific Validation

**Live Validation**:
```
✓ Created receipt: batch7_live3_05640f4a
✓ Created request: req_9cfdc6587306
✓ Execution Status: started
✓ runId: run_fe98f3b0
✓ childSessionKey: session_4705ff51ed8d
✓ pid: 9580
```

**All P0-3 Batches (1-7)**:
- Batch 1: Trading dispatch chain tests ✅
- Batch 2: Bridge consumer auto-trigger ✅
- Batch 3: Consumption to execution chain ✅
- Batch 4: Real API integration ✅
- Batch 5: Trading real dispatch validation ✅
- Batch 6: Policy fixes (safe_mode=false) ✅
- **Batch 7: Fix real execution path** ✅

---

## Design Decisions

### 1. Remove CLI Path Entirely

**Decision**: Delete `_find_openclaw_cli()` and `_call_via_cli()` methods.

**Rationale**:
- `openclaw sessions_spawn` doesn't exist
- Keeping dead code creates confusion
- Python API path is the correct, working path
- Simpler code = fewer bugs

**Alternative Considered**: Check if CLI subcommand exists before using it.

**Rejected Because**: Adds complexity for no benefit; CLI path is never correct.

---

### 2. Use `or` for Empty String Handling

**Decision**: Use `call_params.get("cwd") or default` instead of `call_params.get("cwd", default)`.

**Rationale**:
- `get(key, default)` returns empty string if key exists with empty value
- `get(key) or default` correctly handles empty strings
- Common Python idiom for this pattern

---

### 3. Generic Implementation

**Decision**: Keep implementation adapter-agnostic (not trading-specific).

**Rationale**:
- Trading is first validation scenario
- Channel, macro, content scenarios use same path
- Avoids technical debt from scenario-specific logic
- Proven by previous batches

---

## What's Real vs. What's Not

### ✅ Real (This Batch)
1. Real subagent spawning via `run_subagent_claude_v1.sh`
2. Real `runId` / `childSessionKey` / `pid` generation
3. Full chain: `receipt → request → consumption → execution → subagent spawn`
4. Live validation with real execution anchors
5. All 405 tests pass

### ⏳ Future Batches
1. Multi-scenario concurrent execution validation
2. Subagent completion callback integration
3. Run directory status tracking and cleanup
4. Production monitoring/alerting

---

## Risk Assessment

### Low Risk
- ✅ All existing tests pass (405/405)
- ✅ Live validation successful
- ✅ Backward compatible (no breaking changes)
- ✅ Generic implementation (not trading-specific)
- ✅ Safe mode default still available

### Mitigation
- If issues arise, disable auto-trigger: `configure_auto_trigger(enabled=False)`
- Enable safe mode: `configure_auto_trigger_real_exec(safe_mode=True)`
- Revert code changes: `git revert 256e299`

---

## Rollback Plan

1. **Disable real execution**:
   ```python
   configure_auto_trigger_real_exec(safe_mode=True)
   ```

2. **Disable auto-trigger**:
   ```python
   configure_auto_trigger(enabled=False)
   ```

3. **Revert code changes**:
   ```bash
   cd <path-to-repo>/openclaw-company-orchestration-proposal
   git revert 256e299
   ```

---

## Usage

### Enable Real Execution (Production)

```python
from runtime.orchestrator.sessions_spawn_bridge import configure_auto_trigger_real_exec

# Enable real subagent spawning for trading scenario
configure_auto_trigger_real_exec(
    enabled=True,
    allowlist=["trading"],
    require_manual_approval=False,
    safe_mode=False,  # Real execution
)
```

### Verify Execution

```python
from runtime.orchestrator.sessions_spawn_bridge import get_api_execution

artifact = get_api_execution("exec_api_*")
print(f"Status: {artifact.api_execution_status}")
print(f"runId: {artifact.api_execution_result.runId}")
print(f"childSessionKey: {artifact.api_execution_result.childSessionKey}")
```

---

## Legacy Cleanup Recommendations (Next Batches)

### 1. Remove Deprecated Workspace Paths

**Path**: `~/.openclaw/workspace/orchestrator/` (symlink to monorepo)

**Action**: Remove symlink after confirming all consumers use monorepo `runtime/` path.

### 2. Simplify Trading Adapter

**Path**: `runtime/orchestrator/trading_roundtable.py`

**Action**: Refactor to use generic `channel_roundtable` path where possible.

### 3. Archive Manual Trigger Scripts

**Path**: Various ad-hoc scripts in `scripts/`

**Action**: Archive after confirming no active users; use `orch_command.py` and auto-trigger.

---

## Conclusion

P0-3 Batch 7 successfully fixes the **real execution path bug** by removing the non-existent CLI dependency and fixing empty `cwd` handling. The implementation now correctly uses the Python API path with subagent runner.

**Key Results**:
- ✅ Removed CLI path (81 lines deleted)
- ✅ Fixed empty `cwd` handling
- ✅ Live validation successful with real execution anchors
- ✅ All 405 tests pass
- ✅ Generic implementation (trading is first validator)

**Answer to core question**:
> "Trading 是否已真正开始真实执行？"

**Yes**:
- Real execution path is now fixed and working
- Live validation produced real `runId`, `childSessionKey`, and `pid`
- Trading continuation can now truly spawn real subagents when conditions are met

---

## Commit

```
commit 256e299
Author: Zoe <zoe@openclaw.ai>
Date:   Mon Mar 23 2026

    P0-3 Batch 7: Fix real execution path - remove non-existent CLI dependency
    
    - Removed CLI path (_find_openclaw_cli, _call_via_cli methods)
    - Always use Python API path (_call_via_python_api) with subagent runner
    - Fixed empty cwd handling (use 'or' instead of 'get(default)')
    - Added runner_script.resolve() for absolute paths
    - Live validation: runId=run_fe98f3b0, childSessionKey=session_4705ff51ed8d
    - All 405 orchestrator tests pass
```

---

## Next Steps (P0-3 Batch 8+)

1. **Multi-Scenario Validation**: Test with channel/macro/content scenarios concurrently
2. **Completion Callback Integration**: Wire up subagent completion to receipt chain
3. **Run Directory Management**: Status tracking, cleanup, archival
4. **Monitoring/Alerting**: Track execution chain health, latency, error rates
5. **Legacy Cleanup**: Remove deprecated workspace paths and scripts
