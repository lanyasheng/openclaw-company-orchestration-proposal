# Legacy Migration & Retirement Plan

> **Version**: Final (2026-03-23)  
> **Status**: Active migration in progress  
> **Owner**: Zoe (CTO & Chief Orchestrator)

---

## Executive Summary

This document provides the **final boundary** for the P0-3 legacy cleanup initiative (Batches 1-6, 2026-03-23).

**Key decisions**:
1. ✅ **subagent backend** is now the ONLY default path for new development
2. ⚠️ **tmux backend** is retained as COMPAT-ONLY for existing production dispatches
3. 📋 **Retained legacy** items are documented with clear removal conditions
4. 🚫 **No further incremental cleanup batches** planned - migration is now user-driven

**Migration status**:
- Batches 1-6 completed: runtime cleanup, command deprecation, backend policy update, lifecycle kernel extraction
- Remaining work: **production dispatch migration** (user-driven, not code-driven)

---

## 1. What Was Cleaned Up (Batches 1-6)

### Batch 1: Archive Legacy Docs & POCs (2026-03-23)
**Commit**: `8879a98`

**Cleaned up**:
- `docs/archive/old-docs/` - historical POCs and superseded designs
- `docs/archive/old-docs/partial-continuation-kernel-v*.md` - archived kernel iteration docs
- Legacy prototype code and examples

**Impact**: Zero - these were already superseded

---

### Batch 2: Legacy Runtime Cleanup (2026-03-23)
**Commit**: `6c31e83`

**Cleaned up**:
- `runtime/orchestrator/core/dispatch_planner.py` - removed non-existent `stop` command reference

**Marked deprecated** (retained for compatibility):
- `continuation_backends.py` - added P0-3 Batch 2 comments
- `tmux_terminal_receipts.py` - added deprecation header
- `orchestrator_dispatch_bridge.py` - added legacy docstring

**Retained** (with clear reasons):
- tmux backend - production dispatches still using
- dispatch bridge script - tmux lifecycle management
- tmux receipts - backward compatibility

---

### Batch 3: Legacy Command Deprecation (2026-03-23)
**Commit**: `8df3de3`

**Deprecated commands** (retained, not deleted):
- `describe` - debug only, low usage
- `capture` - prefer runner-based observation
- `attach` - prefer runner-based observation
- `watchdog` - internal use, integrated into kernel

**Core commands** (still supported):
- `prepare` - dispatch plan reference
- `start` - launch tmux session
- `status` - query session status
- `receipt` - build terminal receipt
- `complete` - complete dispatch & callback bridge

---

### Batch 4: Subagent as Default Backend (2026-03-23)
**Commit**: `7ef74cc`

**Policy changes**:
- `continuation_backends.py` - marked subagent as PRIMARY, tmux as COMPAT-ONLY
- `entry_defaults.py` - updated tmux_bridge reference with deprecation
- `runtime/orchestrator/README.md` - added Backend Policy section

**No code removed** - policy/documentation update only

---

### Batch 5: Direct tmux → subagent Migration (2026-03-23)
**Commit**: `62ed6ca`

**Cleaned up**:
- `entry_defaults.py` - commented out `complete_tmux` example command
- `continuation_backends.py` - removed deprecated commands from backend_plan
- `runtime/orchestrator/README.md` - reinforced subagent as ONLY default

**Minimized surface**:
- tmux backend_plan now only shows core lifecycle commands
- Deprecated commands removed from operator-facing documentation

---

### Batch 6: Generic Lifecycle Kernel (2026-03-23)
**Commit**: `06dbe0b`

**Extracted to kernel**:
- `GenericBackendStatus` enum - backend-agnostic lifecycle states
- `BackendStatusAdapter` protocol - extensible status mapping
- `BackendLifecycleConfig` dataclass - backend-specific configuration
- `decide_watchdog_action()` - now backend-agnostic

**Retained** (for compatibility):
- tmux status constants in `tmux_terminal_receipts.py` - used by `BackendLifecycleConfig.for_tmux()`
- `cmd_watchdog()` CLI - retained as entry point, delegates to kernel

---

## 2. What Is Retained (And Why)

### 2.1 tmux Backend (`continuation_backends.py`)

**Why retained**:
- Existing production dispatches still use tmux backend
- Observable session scenarios require intermediate state monitoring
- Migration requires user action (cannot be automated)

**Removal conditions**:
- ✅ All production dispatches migrated to subagent backend
- ✅ No tmux dispatches in last 30 days (verified via logs/metrics)
- ✅ Migration guide documented and tested

**Current status**: ⚠️ **IN USE** - migration pending

---

### 2.2 Dispatch Bridge Script (`orchestrator_dispatch_bridge.py`)

**Why retained**:
- Provides complete tmux dispatch lifecycle management
- Receipt/callback bridge functionality
- Backward compatibility for existing workflows

**Removal conditions**:
- ✅ tmux backend fully retired
- ✅ All users migrated to subagent + runner observation
- ✅ Alternative callback bridge path documented

**Current status**: ⚠️ **IN USE** - depends on tmux backend

---

### 2.3 tmux Terminal Receipts (`tmux_terminal_receipts.py`)

**Why retained**:
- tmux receipt building logic
- Trading/channel roundtable standardization for tmux path
- Backend lifecycle config constants

**Removal conditions**:
- ✅ tmux backend fully retired
- ✅ All receipt paths migrated to completion_receipt.py

**Current status**: ⚠️ **IN USE** - depends on tmux backend

---

### 2.4 Deprecated Commands

| Command | Status | Reason | Alternative |
|---------|--------|--------|-------------|
| `describe` | ⚠️ Deprecated | Debug only, low usage | Read dispatch JSON directly |
| `capture` | ⚠️ Deprecated | Low usage | subagent + runner artifacts |
| `attach` | ⚠️ Deprecated | Low usage | subagent + runner artifacts |
| `watchdog` | ⚠️ Internal | Integrated into kernel | continuation_backends.decide_watchdog_action() |

**Why retained**:
- Backward compatibility
- Zero cost to retain (code already written)
- No active harm

**Removal conditions**:
- ✅ 90+ days since last usage (verified via logs)
- ✅ Breaking change announced and migration period completed

---

## 3. Migration Path for Users

### 3.1 For New Development

**Use subagent backend exclusively**:

```python
# ✅ CORRECT: subagent backend (default)
from continuation_backends import normalize_dispatch_backend
backend = normalize_dispatch_backend("subagent")  # or omit, it's the default

# ❌ WRONG: tmux backend for new development
backend = normalize_dispatch_backend("tmux")  # COMPAT-ONLY, migration required
```

### 3.2 For Existing tmux Dispatches

**Migration steps**:

1. **Identify tmux dispatches**:
   ```bash
   grep -r '"backend": "tmux"' ~/.openclaw/shared-context/orchestrator/dispatches/
   ```

2. **Update dispatch configuration**:
   ```python
   # Before
   dispatch = {"backend": "tmux", ...}
   
   # After
   dispatch = {"backend": "subagent", ...}
   ```

3. **Update observation method**:
   - **Before**: tmux status scripts, attach to session
   - **After**: runner artifacts (`status.json`, `final-summary.json`, `final-report.md`)

4. **Test migration**:
   ```bash
   python3 -m pytest tests/orchestrator/test_tmux_dispatch_bridge.py -v
   python3 -m pytest tests/orchestrator/ -v --tb=short
   ```

### 3.3 Migration Timeline

| Phase | Date | Action |
|-------|------|--------|
| **Phase 1** | 2026-03-23 | Batches 1-6 completed, policy documented |
| **Phase 2** | 2026-03-24 to 2026-04-23 | User-driven migration period |
| **Phase 3** | 2026-04-24 | Review migration progress, identify blockers |
| **Phase 4** | 2026-05-01+ | Consider removal if migration complete |

---

## 4. Documentation Updates

### 4.1 What New Readers Should Know

**From `CURRENT_TRUTH.md`**:
- subagent is the PRIMARY AND DEFAULT backend
- tmux is COMPAT-ONLY for existing dispatches
- New development MUST use subagent

**From `runtime/orchestrator/README.md`**:
- Backend Policy section clearly states default
- Example commands only show subagent path
- tmux commands marked as deprecated

**From `technical-debt-2026-03-22.md`**:
- Section 0.5-0.9 document each batch
- Clear retention rationale for each legacy item

### 4.2 What This Document Adds

This document provides:
1. **Single source of truth** for migration status
2. **Clear removal conditions** for each retained item
3. **User-facing migration guide** with concrete steps
4. **Timeline** for expected completion

---

## 5. Success Metrics

### 5.1 Migration Complete When:

- [ ] Zero production tmux dispatches in last 30 days
- [ ] All example commands use subagent backend
- [ ] No new tmux dispatches created in last 90 days
- [ ] Migration guide tested and validated
- [ ] Breaking change announcement completed

### 5.2 Current Metrics (2026-03-23)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Production tmux dispatches | 0 | TBD | ⚠️ Pending audit |
| New dispatches using tmux | 0 | TBD | ⚠️ Pending audit |
| Documentation clarity | 100% | ✅ Done | ✅ Complete |
| Test coverage | >80% | ✅ 434 tests | ✅ Complete |

---

## 6. Final Boundary Statement

**This is the final cleanup boundary.**

**What this means**:
- No further incremental cleanup batches planned
- Migration is now **user-driven**, not code-driven
- Legacy code will be removed **only when migration conditions are met**
- All future development MUST use subagent backend

**Why this boundary**:
- Trading live path cannot be broken
- Production dispatches require migration time
- Further code changes without user migration provide no value
- Clear policy + documentation is more valuable than partial code removal

**Next steps**:
1. Users migrate existing dispatches to subagent
2. Monitor metrics for 30-90 days
3. When conditions met, remove legacy code in single PR
4. Update this document with final retirement date

---

## 7. Appendix: File-by-File Status

### 7.1 Cleaned Up (Removed/Archived)

| File | Status | Commit |
|------|--------|--------|
| `docs/archive/old-docs/*.md` | Archived | `8879a98` |
| `dispatch_planner.py` stop reference | Removed | `6c31e83` |
| `entry_defaults.py` tmux example | Commented | `62ed6ca` |
| `continuation_backends.py` deprecated commands | Removed from plan | `62ed6ca` |

### 7.2 Retained (With Deprecation)

| File | Reason | Removal Condition |
|------|--------|-------------------|
| `continuation_backends.py` tmux backend | Production use | Zero tmux dispatches |
| `orchestrator_dispatch_bridge.py` | tmux lifecycle | tmux backend retired |
| `tmux_terminal_receipts.py` | tmux receipts | tmux backend retired |
| `cmd_describe/capture/attach` | Backward compat | 90+ days unused |

### 7.3 Enhanced (Kernel Extraction)

| File | Enhancement | Commit |
|------|-------------|--------|
| `continuation_backends.py` | Generic lifecycle kernel | `06dbe0b` |
| `tmux_terminal_receipts.py` | Lifecycle config source | `06dbe0b` |

---

**Last Updated**: 2026-03-23  
**Next Review**: 2026-04-23 (30-day migration check)  
**Owner**: Zoe (CTO & Chief Orchestrator)
