> ⚠️ **SUPERSEDED**: This document describes v1 behavior. See README.md "Unified Main Chain (v2)" for current architecture.

# P0-3 Batch 4: Real sessions_spawn API Integration

> **Date**: 2026-03-23
> **Status**: ✅ Complete
> **Tests**: 405/405 passed (full orchestrator suite)

---

## Executive Summary

P0-3 Batch 4 connects the **generic execution request main chain** to the **real OpenClaw sessions_spawn API** via the subagent runner infrastructure. The implementation enables actual subagent spawning when safe conditions are met.

**Key Achievement**: `_call_via_python_api()` now calls the real subagent runner script, generating真实 runId / childSessionKey / pid.

---

## What Changed

### 1. Enhanced `_call_via_python_api()` (`sessions_spawn_bridge.py`)

**File**: `runtime/orchestrator/sessions_spawn_bridge.py`

**P0-3 Batch 4 Changes**:

```python
def _call_via_python_api(
    self,
    call_params: Dict[str, Any],
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    **P0-3 Batch 4**: 通过 Python API 调用真实 sessions_spawn。
    
    使用 OpenClaw 现有 subagent runner 基础设施：
    - 调用 run_subagent_claude_v1.sh 脚本
    - 生成唯一 run label
    - 跟踪 run 目录和状态
    - 返回 runId / childSessionKey
    
    Args:
        call_params: {task, runtime, cwd, label, metadata}
    
    Returns:
        (success, error_message, api_response)
    """
```

**Key Changes**:
1. Uses `run_subagent_claude_v1.sh` runner script
2. Generates unique `runId` and `childSessionKey`
3. Spawns subagent process in background (non-blocking)
4. Returns real `pid`, `runId`, `childSessionKey` in API response
5. Falls back gracefully if runner script not found

---

### 2. Updated Module Docstring (`sessions_spawn_bridge.py`)

**File**: `runtime/orchestrator/sessions_spawn_bridge.py`

**Changes**:
- Updated version from V9 to V10
- Added P0-3 Batch 4 enhancement notes
- Clarified real subagent runner integration

---

### 3. New Integration Tests (`test_sessions_spawn_bridge.py`)

**File**: `tests/orchestrator/test_sessions_spawn_bridge.py`

**New Test Class**: `TestP03Batch4RealAPICall`

**4 New Tests**:

| Test | Purpose | Status |
|------|---------|--------|
| `test_batch4_real_api_call_mock_boundary` | Verify safe_mode behavior (pending status) | ✅ |
| `test_batch4_real_api_call_real_execution_structure` | Verify API response structure (runId/childSessionKey/pid) | ✅ |
| `test_batch4_generic_scenario_not_trading_specific` | Verify generic implementation (not trading-specific) | ✅ |
| `test_batch4_execution_artifact_paths` | Verify artifact file paths and index | ✅ |

**Key Validation**:
- Real runner script path resolution
- API response structure with runId/childSessionKey/pid
- Generic scenario support (channel, trading, etc.)
- Artifact file paths and dedupe index

---

### 4. Updated Test File Docstring

**File**: `tests/orchestrator/test_sessions_spawn_bridge.py`

**Changes**:
- Updated version from V9 to V10
- Added P0-3 Batch 4 test coverage notes

---

## Design Decisions

### 1. Subagent Runner Integration

**Decision**: Use existing `run_subagent_claude_v1.sh` runner script.

**Rationale**:
- Leverages existing, tested infrastructure
- Consistent with how main agent spawns subagents
- No new dependencies required
- Supports all runner features (profiles, timeouts, milestones)

**Implementation**:
```python
runner_script = Path.home() / ".openclaw" / "workspace" / "scripts" / "run_subagent_claude_v1.sh"
cmd = [
    "bash",
    str(runner_script),
    "--cwd", cwd,
    "--profile", "auto",
    task,
    label,
]
process = subprocess.Popen(cmd, ...)
```

### 2. Non-Blocking Process Spawning

**Decision**: Use `subprocess.Popen` for background execution.

**Rationale**:
- sessions_spawn should be non-blocking (fire-and-forget)
- Subagent runs independently
- Caller gets immediate response with runId/pid
- Consistent with OpenClaw sessions_spawn semantics

**Implementation**:
```python
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=cwd,
    env={**os.environ, "RUN_ID": run_id, "CHILD_SESSION_KEY": child_session_key},
)
```

### 3. Safe Mode Default

**Decision**: Keep `safe_mode=True` as default.

**Rationale**:
- Production safety: prevent accidental subagent spawning
- Testing: allows full chain validation without real execution
- Opt-in for real execution: explicitly set `safe_mode=False`

**Implementation**:
```python
policy = SessionsSpawnBridgePolicy(safe_mode=True)  # Default
# safe_mode=True → pending status (recorded but not executed)
# safe_mode=False → started status (real subagent spawned)
```

### 4. Generic Implementation

**Decision**: Keep implementation adapter-agnostic.

**Rationale**:
- Trading is first validation scenario, not the only one
- Channel, macro, content scenarios use same path
- Avoids technical debt from scenario-specific logic

**Validation**: Test `test_batch4_generic_scenario_not_trading_specific` proves generic scenarios work.

---

## What's Real vs. What's Not

### ✅ Real (This Batch)
1. Real subagent runner script integration
2. Real runId / childSessionKey / pid generation
3. Real background process spawning (when safe_mode=False)
4. Full chain: `receipt → request → consumption → execution → subagent spawn`
5. Integration tests validate real call boundary
6. Generic implementation (trading is first validator)

### ⏳ Future Batches
1. Production configuration management (multi-environment)
2. Monitoring/alerting for execution chain health
3. Multi-scenario concurrent execution control (rate limiting)
4. Subagent completion callback integration
5. Run directory status tracking and cleanup

---

## Files Changed

| File | Changes |
|------|---------|
| `runtime/orchestrator/sessions_spawn_bridge.py` | Enhanced `_call_via_python_api()` with real runner integration; updated module docstring to V10 |
| `tests/orchestrator/test_sessions_spawn_bridge.py` | Added 4 integration tests for P0-3 Batch 4; updated docstring |
| `docs/batch-summaries/P0-3-Batch-4-Real-API-Integration.md` | This summary document |

---

## Test Results

### Full Orchestrator Suite
```
================= 405 passed, 12 warnings in 136.04s (0:02:16) =================
```

### P0-3 Batch 4 Specific Tests
```
tests/orchestrator/test_sessions_spawn_bridge.py::TestP03Batch4RealAPICall
  ✓ test_batch4_execution_artifact_paths
  ✓ test_batch4_generic_scenario_not_trading_specific
  ✓ test_batch4_real_api_call_mock_boundary
  ✓ test_batch4_real_api_call_real_execution_structure
```

### All P0-3 Tests (Batches 1-4)
- Batch 1: Trading dispatch chain tests ✅
- Batch 2: Bridge consumer auto-trigger decision ✅
- Batch 3: Consumption to execution chain ✅
- Batch 4: Real API integration ✅

---

## Usage

### Basic Real Execution (safe_mode=False)

```python
from runtime.orchestrator.sessions_spawn_bridge import (
    SessionsSpawnBridge,
    SessionsSpawnBridgePolicy,
    execute_sessions_spawn_api,
)

# Configure policy for real execution
policy = SessionsSpawnBridgePolicy(
    safe_mode=False,  # Real execution
    allowlist=["trading"],
    prevent_duplicate=True,
)

# Execute
artifact = execute_sessions_spawn_api(request_id, policy)

# Check result
if artifact.api_execution_status == "started":
    print(f"✓ Subagent spawned: runId={artifact.api_execution_result.runId}")
    print(f"  childSessionKey={artifact.api_execution_result.childSessionKey}")
    print(f"  pid={artifact.api_execution_result.api_response['pid']}")
```

### Safe Mode Testing (safe_mode=True)

```python
from runtime.orchestrator.sessions_spawn_bridge import (
    SessionsSpawnBridge,
    SessionsSpawnBridgePolicy,
)

# Safe mode: record but don't execute
policy = SessionsSpawnBridgePolicy(safe_mode=True)
bridge = SessionsSpawnBridge(policy)

artifact = bridge.execute(request)

# Result: pending status (recorded but not executed)
assert artifact.api_execution_status == "pending"
assert artifact.api_execution_result.api_response["status"] == "simulated"
```

### Auto-Trigger with Real Execution

```python
from runtime.orchestrator.sessions_spawn_request import (
    configure_auto_trigger,
    auto_trigger_consumption,
)
from runtime.orchestrator.sessions_spawn_bridge import (
    configure_auto_trigger_real_exec,
)

# 1. Configure auto-trigger for consumption
configure_auto_trigger(
    enabled=True,
    allowlist=["trading"],
    require_manual_approval=False,
)

# 2. Configure auto-trigger for real execution
configure_auto_trigger_real_exec(
    enabled=True,
    allowlist=["trading"],
    require_manual_approval=False,
    safe_mode=False,  # Real execution
)

# 3. Trigger with chain_to_execution=True
triggered, reason, consumed_id, execution_id = auto_trigger_consumption(
    request_id,
    chain_to_execution=True,
)

if triggered and execution_id:
    print(f"✓ Auto-triggered: {consumed_id} -> {execution_id}")
```

### CLI Usage

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal

# Check auto-trigger status
python3 -c "
from runtime.orchestrator.sessions_spawn_bridge import get_auto_trigger_real_exec_status
import json
print(json.dumps(get_auto_trigger_real_exec_status(), indent=2))
"

# Execute single request
python3 -c "
from runtime.orchestrator.sessions_spawn_bridge import execute_sessions_spawn_api, SessionsSpawnBridgePolicy
artifact = execute_sessions_spawn_api('req_xxx', SessionsSpawnBridgePolicy(safe_mode=True))
print(f'Status: {artifact.api_execution_status}')
print(f'Execution ID: {artifact.execution_id}')
"
```

---

## Artifact Paths

### Real Artifact Paths (After This Batch)

| Artifact Type | Path | Example |
|--------------|------|---------|
| Sessions Spawn Request | `~/.openclaw/shared-context/spawn_requests/{request_id}.json` | `req_325b9feb6c79.json` |
| Bridge Consumed | `~/.openclaw/shared-context/bridge_consumed/{consumed_id}.json` | `consumed_e1c893404b53.json` |
| API Execution | `~/.openclaw/shared-context/api_executions/{execution_id}.json` | `exec_api_285429403324.json` |

### Execution Anchors (P0-3 Batch 4)

| Anchor | Description | Example |
|--------|-------------|---------|
| `runId` | Unique run identifier | `run_a1b2c3d4` |
| `childSessionKey` | OpenClaw subagent session key | `session_x1y2z3w4v5u6` |
| `pid` | Subagent process ID | `12345` |
| `label` | Subagent label | `orch-task123` |

---

## Risk Assessment

### Low Risk
- ✅ All existing tests pass (405/405)
- ✅ New tests cover edge cases
- ✅ Safe mode enabled by default
- ✅ Backward compatible (no breaking changes)
- ✅ Generic implementation (not trading-specific)

### Mitigation
- If issues arise, disable auto-trigger: `configure_auto_trigger(enabled=False)`
- Enable safe mode: `configure_auto_trigger_real_exec(safe_mode=True)` (default)
- Revert code changes: `git revert <commit-hash>`

---

## Rollback Plan

1. **Disable real execution**:
   ```python
   configure_auto_trigger_real_exec(safe_mode=True)  # Back to simulation
   ```

2. **Disable auto-trigger**:
   ```python
   configure_auto_trigger(enabled=False)
   configure_auto_trigger_real_exec(enabled=False)
   ```

3. **Revert code changes**:
   ```bash
   cd <path-to-repo>/openclaw-company-orchestration-proposal
   git revert <commit-hash>
   ```

---

## Next Steps (P0-3 Batch 5+)

1. **Production Configuration**: Multi-environment config management (dev/staging/prod)
2. **Monitoring/Alerting**: Track execution chain health, latency, error rates
3. **Multi-Scenario Validation**: Test with channel/macro/content scenarios concurrently
4. **Concurrent Execution Control**: Rate limiting, queue management, max concurrent executions
5. **Subagent Completion Callback**: Integrate with completion receipt chain
6. **Run Directory Management**: Status tracking, cleanup, archival

---

## Conclusion

P0-3 Batch 4 successfully connects the generic execution request main chain to the real OpenClaw sessions_spawn API via the subagent runner infrastructure. The implementation:

- ✅ Calls real subagent runner script
- ✅ Generates真实 runId / childSessionKey / pid
- ✅ Spawns subagent in background (non-blocking)
- ✅ Maintains safe_mode default for production safety
- ✅ Keeps generic implementation (trading is first validator)
- ✅ All 405 tests pass

**Status**: ✅ Complete, ready for commit.

---

## Commit Plan

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal

git add -A
git commit -m "P0-3 Batch 4: Real sessions_spawn API integration via subagent runner

- Enhanced _call_via_python_api() to call real run_subagent_claude_v1.sh
- Generates真实 runId / childSessionKey / pid
- Spawns subagent in background (non-blocking)
- Maintains safe_mode=True default for production safety
- Added 4 integration tests for P0-3 Batch 4
- All 405 orchestrator tests pass
- Generic implementation (trading is first validator, not only scenario)

Trading continuation can now trigger real subagent spawning when:
- readiness.eligible=True
- safety_gates.allow_auto_dispatch=True
- truth_anchor present
- safe_mode=False (opt-in for real execution)"

git push origin main
```
