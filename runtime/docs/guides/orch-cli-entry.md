# Orch CLI Entry Guide

> **Version:** `orch_v1`  
> **Entry Point:** `runtime/scripts/orch`  
> **Design:** Ultra-thin wrapper over `orch_product.py`

## Quick Start

**Three commands that any agent can use:**

```bash
# 1. View channel onboarding recommendation
orch onboard

# 2. Trigger execution
orch run --task "Task description" --workdir /path/to/workdir

# 3. Check status
orch status
```

## Commands

### `orch onboard`

Generate channel onboarding recommendation card.

**Usage:**
```bash
orch onboard [options]
```

**Options:**
- `--channel-id`: Channel ID (e.g., `discord:channel:123456`)
- `--channel-name`: Channel name
- `--topic`: Discussion topic
- `--context`: Context (`channel_roundtable` | `trading_roundtable`)
- `--scenario`: Scenario identifier
- `--owner`: Task owner
- `--backend`: Backend preference (`subagent` | `tmux`)
- `--output`: Output format (`text` | `json`)

**Example:**
```bash
# Trading scenario
orch onboard --scenario trading_roundtable --owner trading

# JSON output
orch onboard --scenario trading_roundtable --output json
```

**Output:**
- Recommended adapter/scenario/owner/backend
- Gate policy
- Bootstrap capability card
- Next steps
- Example commands

---

### `orch run`

Trigger execution.

**Usage:**
```bash
orch run --task "Task description" [options]
```

**Required:**
- `--task`, `-t`: Task description

**Options:**
- `--channel-id`: Channel ID
- `--channel-name`: Channel name
- `--topic`: Discussion topic
- `--context`: Context
- `--scenario`: Scenario identifier
- `--owner`: Task owner
- `--backend`: Backend preference (`subagent` | `tmux`)
- `--workdir`, `-w`: Working directory
- `--duration`, `-d`: Estimated duration (minutes)
- `--type`, `-T`: Task type (`coding` | `documentation` | `research` | `custom`)
- `--monitor`, `-m`: Enable monitoring
- `--timeout`: Timeout (seconds)
- `--output`: Output format (`text` | `json`)

**Example:**
```bash
# Minimal
orch run --task "Refactor auth module"

# With workdir
orch run --task "Refactor auth module" --workdir /path/to/repo

# Trading scenario
orch run --task "Analyze AAPL tradability" \
  --scenario trading_roundtable \
  --owner trading \
  --backend subagent \
  --workdir /path/to/workdir

# JSON output
orch run --task "..." --output json
```

**Output:**
- Task ID
- Dispatch ID
- Backend (subagent | tmux)
- Session ID / Label
- Callback path
- Wake command
- Artifact paths
- Next steps

---

### `orch status`

View status overview.

**Usage:**
```bash
orch status [options]
```

**Options:**
- `--channel-id`: Channel ID filter
- `--batch-key`: Batch key filter
- `--task-id`: Task ID (query single task)
- `--owner`: Owner filter
- `--scenario`: Scenario filter
- `--stage`: Stage filter (`planning` | `dispatch` | `running` | `callback_received` | `closeout` | `completed` | `failed`)
- `--limit`, `-l`: Result limit (default: 20)
- `--output`: Output format (`text` | `json`)

**Example:**
```bash
# All tasks
orch status

# Filter by owner
orch status --owner trading

# Single task
orch status --task-id task_123

# JSON output
orch status --output json
```

**Output:**
- Summary (total/active/completed/failed)
- Active tasks
- Completed tasks
- Failed tasks / blockers
- Next steps
- Board snapshot path

---

## Architecture

```
orch (this script)
  │
  └─> orch_product.py (productized entry)
        │
        ├─> entry_defaults (contract generation)
        ├─> unified_execution_runtime (execution)
        └─> observability_card (status tracking)
```

**Design principles:**
- Ultra-thin wrapper: `orch` simply routes to `orch_product.py`
- Zero mental overhead: other agents learn once, use everywhere
- Backward compatible: `orch_product.py` and `orch_command.py` unchanged

---

## E2E Verification

**Test script:** `runtime/tests/orchestrator/test_orch_e2e_trading_20260330.py`

**Verification scope:**
1. ✅ `orch onboard` command
2. ✅ `orch run` command (dispatch generation)
3. ✅ Packet completeness validation
4. ✅ Artifact chain (dispatch → request → consumed → execution → receipt → closeout)

**Run verification:**
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 runtime/tests/orchestrator/test_orch_e2e_trading_20260330.py
```

**Reports:** `runtime/docs/e2e_reports/orch_e2e_trading_*.md`

---

## Migration Guide

**From `orch_product.py`:**

```bash
# Old
python3 runtime/scripts/orch_product.py onboard --scenario trading_roundtable

# New (shorter)
orch onboard --scenario trading_roundtable
```

```bash
# Old
python3 runtime/scripts/orch_product.py run --task "..." --scenario trading_roundtable

# New (shorter)
orch run --task "..." --scenario trading_roundtable
```

```bash
# Old
python3 runtime/scripts/orch_product.py status --owner trading

# New (shorter)
orch status --owner trading
```

**From `orch_command.py`:**

`orch_command.py` is for contract generation. Use `orch onboard` for onboarding recommendations.

---

## Troubleshooting

**Issue:** `orch` command not found

**Solution:**
```bash
# Use full path
python3 /path/to/runtime/scripts/orch ...

# Or add to PATH
export PATH="/path/to/runtime/scripts:$PATH"
```

**Issue:** Backend selection fails

**Solution:**
- Explicitly specify `--backend subagent` or `--backend tmux`
- Check `backend_selector.py` for auto-recommendation logic

**Issue:** Status shows no tasks

**Solution:**
- Ensure tasks were triggered via `orch run`
- Check observability cards in `~/.openclaw/shared-context/observability/`

---

## See Also

- `runtime/scripts/orch_product.py`: Productized entry implementation
- `runtime/scripts/orch_command.py`: Contract generation entry
- `runtime/orchestrator/entry_defaults.py`: Default contract generation
- `runtime/orchestrator/unified_execution_runtime.py`: Unified execution runtime
- `runtime/orchestrator/observability_card.py`: Observability card system
