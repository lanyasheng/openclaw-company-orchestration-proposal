# Dual-Track Backend Strategy (tmux + subagent)

> **Version**: Dual-Track (2026-03-23)  
> **Status**: Active - Both backends supported  
> **Owner**: Zoe (CTO & Chief Orchestrator)

---

## Executive Summary

This document provides the **final boundary** for the P0-3 legacy cleanup initiative (Batches 1-6, 2026-03-23).

**Key decisions**:
1. ✅ **subagent backend** is the **DEFAULT** path for new development
2. ✅ **tmux backend** is **RETAINED** as a fully-supported compatibility path
3. 📋 **Both backends coexist** - no breaking removal planned
4. 🚫 **No further cleanup batches** - dual-track is the final state

**Strategy**:
- **Default**: subagent (recommended for new development)
- **Compatible**: tmux (fully functional, retained indefinitely)
- **No forced migration**: users can choose either backend based on their needs

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

**Marked for clarity** (retained with documentation):
- `continuation_backends.py` - added backend policy documentation
- `tmux_terminal_receipts.py` - added module header
- `orchestrator_dispatch_bridge.py` - added module docstring

**Retained** (dual-track strategy):
- tmux backend - fully supported compatibility path
- dispatch bridge script - tmux lifecycle management
- tmux receipts - tmux backend support

---

### Batch 3: Command Documentation (2026-03-23)
**Commit**: `8df3de3`

**Documented usage patterns**:
- `describe` - debug utility
- `capture` - tmux pane observation
- `attach` - tmux session attachment
- `watchdog` - internal lifecycle monitoring

**Core commands** (fully supported for both backends):
- `prepare` - dispatch plan reference
- `start` - launch session
- `status` - query session status
- `receipt` - build terminal receipt
- `complete` - complete dispatch & callback bridge

---

### Batch 4: Backend Policy Documentation (2026-03-23)
**Commit**: `7ef74cc`

**Policy documentation**:
- `continuation_backends.py` - documented subagent as DEFAULT, tmux as SUPPORTED
- `entry_defaults.py` - updated documentation
- `runtime/orchestrator/README.md` - added Backend Policy section

**No code removed** - documentation only

---

### Batch 5: Default Path Clarification (2026-03-23)
**Commit**: `62ed6ca`

**Updated**:
- `entry_defaults.py` - clarified default examples
- `continuation_backends.py` - clarified backend_plan documentation
- `runtime/orchestrator/README.md` - reinforced dual-track strategy

**Both backends remain functional**:
- subagent: default for new development
- tmux: fully supported for existing and new use cases

---

### Batch 6: Generic Lifecycle Kernel (2026-03-23)
**Commit**: `06dbe0b`

**Extracted to kernel**:
- `GenericBackendStatus` enum - backend-agnostic lifecycle states
- `BackendStatusAdapter` protocol - extensible status mapping
- `BackendLifecycleConfig` dataclass - backend-specific configuration
- `decide_watchdog_action()` - now backend-agnostic

**Retained** (dual-track support):
- tmux status constants in `tmux_terminal_receipts.py` - used by `BackendLifecycleConfig.for_tmux()`
- `cmd_watchdog()` CLI - retained as entry point, delegates to kernel

---

## 2. Dual-Track Backend Strategy

### 2.1 Backend Comparison

| Aspect | subagent (DEFAULT) | tmux (SUPPORTED) |
|--------|-------------------|------------------|
| **Status** | Default for new development | Fully supported compatibility path |
| **Use case** | Automated execution, CI/CD | Interactive sessions, manual observation |
| **Observation** | Runner artifacts (`status.json`, `final-report.md`) | tmux session monitoring, live output |
| **Integration** | `sessions_spawn(runtime="subagent")` | `orchestrator_dispatch_bridge.py` |
| **Removal planned** | ❌ No | ❌ No - retained indefinitely |

---

### 2.2 tmux Backend (`continuation_backends.py`)

**Why retained**:
- Observable session scenarios require intermediate state monitoring
- Interactive debugging and manual intervention use cases
- User preference for tmux-based workflows
- **Dual-track strategy**: both backends supported indefinitely

**Current status**: ✅ **FULLY SUPPORTED** - no migration required

---

### 2.3 Dispatch Bridge Script (`orchestrator_dispatch_bridge.py`)

**Why retained**:
- Provides complete tmux dispatch lifecycle management
- Receipt/callback bridge functionality
- **Dual-track strategy**: tmux path remains fully functional

**Current status**: ✅ **FULLY SUPPORTED** - tmux backend dependency

---

### 2.4 tmux Terminal Receipts (`tmux_terminal_receipts.py`)

**Why retained**:
- tmux receipt building logic
- Trading/channel roundtable standardization for tmux path
- Backend lifecycle config constants for tmux
- **Dual-track strategy**: tmux receipts remain canonical for tmux backend

**Current status**: ✅ **FULLY SUPPORTED** - tmux backend dependency

---

### 2.5 Command Support Matrix

| Command | subagent | tmux | Notes |
|---------|----------|------|-------|
| `prepare` | ✅ | ✅ | Both backends |
| `start` | ✅ | ✅ | tmux: launches tmux session |
| `status` | ✅ | ✅ | tmux: queries tmux session |
| `receipt` | ✅ | ✅ | tmux: builds tmux receipt |
| `complete` | ✅ | ✅ | Both backends bridge to callback |
| `describe` | ✅ | ✅ | Debug utility |
| `capture` | N/A | ✅ | tmux-specific (pane observation) |
| `attach` | N/A | ✅ | tmux-specific (session attachment) |
| `watchdog` | ✅ | ✅ | Both backends (kernel-integrated) |

**All commands retained** - no removal planned under dual-track strategy

---

## 3. Choosing Your Backend

### 3.1 For New Development

**Recommended**: subagent backend (default, automated execution)

```python
# Recommended: subagent backend (default)
from continuation_backends import normalize_dispatch_backend
backend = normalize_dispatch_backend("subagent")  # DEFAULT

# Also supported: tmux backend (interactive sessions)
backend = normalize_dispatch_backend("tmux")  # FULLY SUPPORTED
```

### 3.2 When to Use Each Backend

**Use subagent when**:
- Automated execution is preferred
- CI/CD integration needed
- Runner-based artifact observation is sufficient
- Building new workflows

**Use tmux when**:
- Interactive session monitoring is required
- Manual intervention during execution is expected
- Live output observation is needed
- Existing tmux-based workflows

### 3.3 Backend Selection Examples

```python
# Default (subagent)
backend = normalize_dispatch_backend("subagent")

# Explicit tmux (fully supported)
backend = normalize_dispatch_backend("tmux")

# Auto-detect from dispatch
dispatch = {"backend": "tmux", ...}
backend = normalize_dispatch_backend(dispatch.get("backend"))
```

---

## 4. Documentation Updates

### 4.1 What New Readers Should Know

**From `CURRENT_TRUTH.md`**:
- subagent is the DEFAULT backend for new development
- tmux is FULLY SUPPORTED for interactive/observable scenarios
- Both backends coexist under dual-track strategy

**From `runtime/orchestrator/README.md`**:
- Backend Policy section documents dual-track strategy
- Example commands show both backends
- Both paths are fully functional

**From `technical-debt-2026-03-22.md`**:
- Section 0.5-0.9 document each batch
- Clear rationale for dual-track strategy

### 4.2 What This Document Adds

This document provides:
1. **Single source of truth** for dual-track backend strategy
2. **Backend comparison** and selection guidance
3. **User-facing documentation** for both paths
4. **Final boundary**: both backends retained indefinitely

---

## 5. Success Metrics

### 5.1 Dual-Track Success Criteria:

- [x] Both backends functional and tested
- [x] Clear documentation for backend selection
- [x] No breaking changes to either path
- [x] Test coverage for both backends

### 5.2 Current Metrics (2026-03-23)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| subagent backend tests | ✅ | ✅ Passing | ✅ Complete |
| tmux backend tests | ✅ | ✅ Passing | ✅ Complete |
| Total test coverage | >80% | ✅ 434 tests | ✅ Complete |
| Documentation clarity | 100% | ✅ Done | ✅ Complete |

---

## 6. Final Boundary Statement

**This is the final boundary: dual-track backend strategy.**

**What this means**:
- No further cleanup batches planned
- **Both backends retained indefinitely**
- No breaking removal of tmux functionality
- Users can choose either backend based on their needs

**Why this boundary**:
- Trading live path preserved
- tmux use cases remain fully supported
- Dual-track provides flexibility for different workflows
- Clear policy + documentation is the final state

**Next steps**:
1. Users choose backend based on their needs
2. Both backends continue to be maintained
3. New features support both paths
4. Update documentation as needed

---

## 7. Appendix: File-by-File Status

### 7.1 Archived (Historical Reference)

| File | Status | Commit |
|------|--------|--------|
| `docs/archive/old-docs/*.md` | Archived (historical POCs) | `8879a98` |
| `dispatch_planner.py` stop reference | Removed (non-existent command) | `6c31e83` |

### 7.2 Retained (Dual-Track Support)

| File | Purpose | Status |
|------|---------|--------|
| `continuation_backends.py` | Backend policy + lifecycle kernel | ✅ Both backends |
| `orchestrator_dispatch_bridge.py` | tmux lifecycle management | ✅ Fully supported |
| `tmux_terminal_receipts.py` | tmux receipts + lifecycle config | ✅ Fully supported |
| `cmd_describe/capture/attach` | tmux utilities | ✅ Fully supported |
| `entry_defaults.py` | Entry defaults (both backends) | ✅ Both backends |

### 7.3 Enhanced (Kernel Extraction)

| File | Enhancement | Commit |
|------|-------------|--------|
| `continuation_backends.py` | Generic lifecycle kernel | `06dbe0b` |
| `tmux_terminal_receipts.py` | Lifecycle config source | `06dbe0b` |

---

**Last Updated**: 2026-03-23  
**Strategy**: Dual-Track (subagent + tmux)  
**Owner**: Zoe (CTO & Chief Orchestrator)
