# Orch Live Chain Validation Report

**Report ID:** `orch_live_chain_validation_20260331085500`  
**Timestamp:** 2026-03-31T08:55:00+08:00  
**Entry Point:** `orch run --live-chain` / `orch_run_live.py`  
**Verdict:** ✓ **FULL PASS**

---

## Executive Summary

This validation confirms that `orch run --live-chain` successfully triggers the **complete shared-context artifact chain** for trading scenarios:

1. ✓ SpawnExecutionArtifact
2. ✓ CompletionReceipt
3. ✓ SessionsSpawnRequest
4. ✓ BridgeConsumed
5. ✓ APIExecution (real sessions_spawn API call)

**Key Achievement:** The artifact chain is now **real** (not simulated), with actual subagent processes spawned via `SubagentExecutor`.

---

## Validation Results

### Test Run 1: Direct `orch_run_live.py` Invocation

**Command:**
```bash
python3 runtime/scripts/orch_run_live.py \
  --scenario trading_roundtable \
  --task "Live chain validation test #2" \
  --workdir /Users/study/.openclaw/workspace \
  --output json
```

**Artifacts Produced:**

| Artifact Type | ID | Path | Status |
|--------------|-----|------|--------|
| SpawnExecution | `live_exec_20260331085350` | `~/.openclaw/shared-context/spawn_executions/live_exec_20260331085350.json` | ✓ exists |
| CompletionReceipt | `receipt_ac8f928bf14e` | `~/.openclaw/shared-context/completion_receipts/receipt_ac8f928bf14e.json` | ✓ exists |
| SessionsSpawnRequest | `req_0bebfcfa1d47` | `~/.openclaw/shared-context/spawn_requests/req_0bebfcfa1d47.json` | ✓ exists |
| BridgeConsumed | `consumed_257f1b15444b` | `~/.openclaw/shared-context/bridge_consumed/consumed_257f1b15444b.json` | ✓ exists |
| APIExecution | `exec_api_c32be1b19430` | `~/.openclaw/shared-context/api_executions/exec_api_c32be1b19430.json` | ✓ exists |

**API Execution Details:**
- `api_execution_status`: `started`
- `api_execution_reason`: `API call successful`
- `childSessionKey`: `task_0bebfcfa1d47`
- `runId`: `task_0bebfcfa1d47`
- `pid`: `21893` (real subagent process)
- `message`: `Wave 2 Cutover (2026-03-24): Real sessions_spawn via SubagentExecutor`

**Verdict:** ✓ **FULL PASS** - All artifacts exist, linkage complete, no `simulate` semantics.

---

### Test Run 2: `orch run --live-chain` CLI Invocation

**Command:**
```bash
python3 runtime/scripts/orch run \
  --live-chain \
  --scenario trading_roundtable \
  --task "Orch live chain test via orch CLI" \
  --workdir /Users/study/.openclaw/workspace \
  --output json
```

**Artifacts Produced:**

| Artifact Type | ID | Status |
|--------------|-----|--------|
| SpawnExecution | `live_exec_20260331085457` | ✓ exists |
| CompletionReceipt | `receipt_54100377e30b` | ✓ exists |
| SessionsSpawnRequest | `req_d236c5f4fabc` | ✓ exists |
| BridgeConsumed | `consumed_e8d7b1481515` | ✓ exists |
| APIExecution | `exec_api_615bbc7951ba` | ✓ exists |

**API Execution Details:**
- `api_execution_status`: `started`
- `api_execution_reason`: `API call successful`
- `childSessionKey`: `task_d236c5f4fabc`
- `runId`: `task_d236c5f4fabc`

**Verdict:** ✓ **FULL PASS** - CLI entry point works correctly.

---

## Acceptance Criteria Verification

### A. Entry Point Standard ✓

- **Entry point:** `runtime/scripts/orch run --live-chain` (or `orch_run_live.py`)
- **Full command recorded:** Yes, see test runs above
- **Backward compatible:** `orch run` (without `--live-chain`) still uses original `orch_product.py` path

### B. Truth Chain Standard ✓

All required shared-context artifacts are produced and verified:

| Artifact Directory | Example File | Verified |
|-------------------|--------------|----------|
| `~/.openclaw/shared-context/spawn_executions/` | `live_exec_*.json` | ✓ |
| `~/.openclaw/shared-context/completion_receipts/` | `receipt_*.json` | ✓ |
| `~/.openclaw/shared-context/spawn_requests/` | `req_*.json` | ✓ |
| `~/.openclaw/shared-context/bridge_consumed/` | `consumed_*.json` | ✓ |
| `~/.openclaw/shared-context/api_executions/` | `exec_api_*.json` | ✓ |

**Linkage:** Complete chain from execution → receipt → request → consumed → api_execution.

### C. Non-Simulated Standard ✓

- **No `simulate` semantics:** API execution shows `status: started`, `reason: API call successful`
- **Real subagent process:** `pid: 21893` (actual running process)
- **Real sessions_spawn API:** `message: Wave 2 Cutover (2026-03-24): Real sessions_spawn via SubagentExecutor`

**Verdict:** ✓ **FULL PASS** - This is a real execution, not a simulation.

---

## Test Results

### Unit Tests

```bash
python3 -m pytest tests/orchestrator/test_orch_product.py -v
```

**Result:** 20 passed in 1.73s ✓

### Integration Tests

- ✓ `orch_run_live.py` direct invocation
- ✓ `orch run --live-chain` CLI invocation
- ✓ Complete artifact chain verification
- ✓ API execution with real subagent spawn

---

## Files Changed

| File | Change Summary |
|------|---------------|
| `runtime/scripts/orch_run_live.py` | **NEW** - Live chain entry point |
| `runtime/scripts/orch` | Added `--live-chain` flag support |
| `runtime/orchestrator/sessions_spawn_bridge.py` | No changes (existing API) |
| `runtime/orchestrator/sessions_spawn_request.py` | No changes (existing API) |

---

## Artifact IDs (Latest Run)

```
Execution:     live_exec_20260331085457
Receipt:       receipt_54100377e30b
Request:       req_d236c5f4fabc
Consumed:      consumed_e8d7b1481515
APIExecution:  exec_api_615bbc7951ba
```

**Paths:**
```
~/.openclaw/shared-context/spawn_executions/live_exec_20260331085457.json
~/.openclaw/shared-context/completion_receipts/receipt_54100377e30b.json
~/.openclaw/shared-context/spawn_requests/req_d236c5f4fabc.json
~/.openclaw/shared-context/bridge_consumed/consumed_e8d7b1481515.json
~/.openclaw/shared-context/api_executions/exec_api_615bbc7951ba.json
```

---

## Blockers

**None.** Full pass achieved.

---

## Next Steps

1. ✓ Entry point `orch run --live-chain` is ready for use
2. ✓ Complete artifact chain verified
3. ✓ Real sessions_spawn API integration confirmed
4. Consider: Auto-enable `--live-chain` for `trading_roundtable` scenario by default
5. Consider: Add `--live-chain` to `orch_product.py run` command for unified experience

---

## Appendix: Raw Validation Output

```json
{
  "version": "orch_run_live_v1",
  "timestamp": "2026-03-31T08:54:58+08:00",
  "entry_point": "orch_run_live.py",
  "linkage": {
    "execution_id": "live_exec_20260331085457",
    "receipt_id": "receipt_54100377e30b",
    "request_id": "req_d236c5f4fabc",
    "consumed_id": "consumed_e8d7b1481515",
    "api_execution_id": "exec_api_615bbc7951ba"
  },
  "validation": {
    "complete_chain": true,
    "all_artifacts_exist": true,
    "linkage_complete": true
  }
}
```

---

**Report Generated:** 2026-03-31T08:55:00+08:00  
**Author:** Subagent (orchestration validation task)  
**Commit:** Pending
