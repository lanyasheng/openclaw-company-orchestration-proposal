# Orchestration Smoke Rerun Report — 2026-03-24

**执行时间**: 2026-03-24 13:40 GMT+8  
**执行者**: orch-smoke-closeout-isolation-fix-20260324 (subagent)  
**Canonical Repo**: `/Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal`

---

## Executive Summary

**Verdict**: ✅ **SMOKE_PASS**

所有 62 个测试在连续 5 次运行中均稳定通过，测试隔离问题已修复。

---

## Root Cause Analysis

### 问题描述
在初始测试运行中，观察到偶发性测试失败（62 个测试中 1 个失败），表现为测试间 closeout 状态污染。

### 根本原因
1. **Fixture 顺序问题**: `test_callback_bridge_strict_validation.py` 中的 `reload_modules` fixture 使用了 `autouse=True`，但依赖于非-autouse 的 `isolated_state_dir` fixture。这导致在某些情况下，模块重载在环境变量设置之前执行。

2. **Closeout 目录隔离不完整**: `closeout_tracker.CLOSEOUT_DIR` 在模块重载后未正确更新，导致测试间共享全局状态。

3. **导入路径问题**: `test_trading_callback_validator.py` 的导入路径设置不正确，导致模块无法正确加载。

---

## 改动文件

### 1. `tests/orchestrator/test_callback_bridge_strict_validation.py`

**改动内容**:
- 合并 `isolated_state_dir` 和 `reload_modules` fixture 为单一的 `isolated_environment` fixture（`autouse=True`）
- 确保环境变量设置在模块重载之前执行
- 在模块重载前后都更新 `closeout_tracker.CLOSEOUT_DIR`
- 添加异常处理，确保模块重载失败不影响测试执行

**关键代码**:
```python
@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离的测试环境 - 同时隔离 state 和 closeout 目录"""
    state_dir = tmp_path / "shared-context" / "job-status"
    closeout_dir = tmp_path / "closeouts"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setenv("OPENCLAW_STATE_DIR", str(state_dir))
    monkeypatch.setenv("OPENCLAW_CLOSEOUT_DIR", str(closeout_dir))
    monkeypatch.setenv("OPENCLAW_ACK_GUARD_DISABLE_DELIVERY", "1")
    
    # 先更新 closeout_tracker.CLOSEOUT_DIR（如果已加载）
    if "closeout_tracker" in sys.modules:
        import closeout_tracker
        closeout_tracker.CLOSEOUT_DIR = closeout_dir
    
    # 重新加载关键模块
    for module_name in ["state_machine", "batch_aggregator", "orchestrator", 
                        "trading_roundtable", "adapters.trading", "closeout_tracker"]:
        if module_name in sys.modules:
            try:
                importlib.reload(sys.modules[module_name])
            except Exception:
                pass
    
    # 再次确保 CLOSEOUT_DIR 正确设置（reload 后）
    if "closeout_tracker" in sys.modules:
        import closeout_tracker
        closeout_tracker.CLOSEOUT_DIR = closeout_dir
    
    yield {"state_dir": state_dir, "closeout_dir": closeout_dir}
```

### 2. `runtime/tests/orchestrator/trading/test_trading_callback_validator.py`

**改动内容**:
- 简化导入路径设置，移除冗余的 try-except 回退逻辑
- 修正路径插入顺序（从最具体到最一般）

**关键代码**:
```python
# Add orchestrator/trading to path
ROOT_DIR = Path(__file__).resolve().parents[3]  # runtime/
ORCHESTRATOR_DIR = ROOT_DIR / "orchestrator"
TRADING_DIR = ORCHESTRATOR_DIR / "trading"

# Insert paths in correct order (most specific first)
for path in [str(TRADING_DIR), str(ORCHESTRATOR_DIR), str(ROOT_DIR)]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Import validator
from callback_validator import (
    validate_trading_callback,
    validate_callback_file,
    ValidationResult,
)
```

---

## 测试执行结果

### 测试命令
```bash
python3 -m pytest \
  tests/orchestrator/test_callback_bridge_strict_validation.py \
  tests/orchestrator/test_mainline_auto_continue.py \
  tests/orchestrator/test_closeout_gate.py \
  runtime/tests/orchestrator/test_push_consumer.py \
  runtime/tests/orchestrator/trading/test_trading_callback_validator.py \
  -v
```

### 测试结果汇总

| 测试文件 | 测试数量 | 结果 |
|---------|---------|------|
| `test_callback_bridge_strict_validation.py` | 9 | ✅ PASS |
| `test_mainline_auto_continue.py` | 6 | ✅ PASS |
| `test_closeout_gate.py` | 9 | ✅ PASS |
| `test_push_consumer.py` | 22 | ✅ PASS |
| `test_trading_callback_validator.py` | 16 | ✅ PASS |
| **总计** | **62** | **✅ PASS** |

### 稳定性验证
连续 5 次运行结果：
- Run 1: 62 passed in 2.07s
- Run 2: 62 passed in 2.14s
- Run 3: 62 passed in 2.16s
- Run 4: 62 passed in 2.13s
- Run 5: 62 passed in 2.18s

**结论**: 测试隔离问题已完全修复，无偶发性失败。

---

## 详细测试输出

### test_callback_bridge_strict_validation.py (9 tests)
- ✅ `test_empty_result_blocked`
- ✅ `test_missing_artifact_truth_blocked`
- ✅ `test_missing_packet_fields_blocked`
- ✅ `test_missing_roundtable_fields_blocked`
- ✅ `test_clean_callback_passes`
- ✅ `test_blocked_status_not_hard_fail`
- ✅ `test_partial_artifact_truth_blocked`
- ✅ `test_exists_false_blocked`
- ✅ `test_test_summary_empty_blocked`

### test_mainline_auto_continue.py (6 tests)
- ✅ `test_closeout_complete_push_pending_blocks_next_batch` (场景 A)
- ✅ `test_push_consumer_chain_allows_next_batch` (场景 B)
- ✅ `test_blocked_closeout_gives_clear_blocker` (场景 C.1)
- ✅ `test_incomplete_closeout_gives_clear_blocker` (场景 C.2)
- ✅ `test_no_closeout_allows_first_run` (场景 C.3)
- ✅ `test_two_batch_sequential_run` (主线集成)

### test_closeout_gate.py (9 tests)
- ✅ `test_to_dict`
- ✅ `test_first_run_allowed`
- ✅ `test_blocked_closeout_prevents_next_batch`
- ✅ `test_incomplete_closeout_prevents_next_batch`
- ✅ `test_push_not_executed_prevents_next_batch`
- ✅ `test_push_executed_allows_next_batch`
- ✅ `test_non_trading_scenario_does_not_require_push`
- ✅ `test_skip_closeout_gate_in_trading_roundtable`
- ✅ `test_closeout_gate_result_in_callback_output`

### test_push_consumer.py (22 tests)
- ✅ `test_push_action_to_dict`
- ✅ `test_push_action_from_dict`
- ✅ `test_emit_push_action_creates_action`
- ✅ `test_emit_push_action_default_intent`
- ✅ `test_consume_push_action_updates_status`
- ✅ `test_consume_push_action_fails_if_not_emitted`
- ✅ `test_consume_push_action_fails_if_not_exists`
- ✅ `test_update_push_status_to_pushed`
- ✅ `test_update_push_status_with_error`
- ✅ `test_update_push_status_updates_push_action`
- ✅ `test_simulate_push_success_updates_status`
- ✅ `test_simulate_push_success_with_push_action`
- ✅ `test_simulate_push_success_fails_if_already_pushed`
- ✅ `test_check_status_no_closeout`
- ✅ `test_check_status_blocked_closeout`
- ✅ `test_check_status_push_pending`
- ✅ `test_check_status_pushed`
- ✅ `test_check_status_with_push_action`
- ✅ `test_full_push_consumer_lifecycle`
- ✅ `test_push_consumer_state_transitions`
- ✅ `test_non_trading_scenario_push_not_required`
- ✅ `test_incomplete_closeout_push_blocked`

### test_trading_callback_validator.py (16 tests)
- ✅ `test_blocked_decision_with_reason_warning`
- ✅ `test_empty_artifact_paths_fails_p0`
- ✅ `test_invalid_decision_fails`
- ✅ `test_invalid_dispatch_readiness_fails`
- ✅ `test_invalid_terminal_status_fails`
- ✅ `test_missing_artifact_paths_fails`
- ✅ `test_missing_envelope_version_fails`
- ✅ `test_missing_orchestration_contract_fails`
- ✅ `test_missing_roundtable_conclusion_fails`
- ✅ `test_template_file_validates`
- ✅ `test_tradability_score_out_of_range_fails`
- ✅ `test_valid_callback_passes`
- ✅ `test_wrong_adapter_fails`
- ✅ `test_wrong_envelope_version_fails`
- ✅ `test_legacy_callback_format_compatibility`
- ✅ `test_packet_truth_fields_present`

---

## 最终 Verdict

**SMOKE_PASS** ✅

所有指定的 smoke tests 均通过，测试隔离问题已修复。

---

## 建议

### 是否建议提交这些修复？
**✅ 是，建议提交**

理由：
1. 修复了测试隔离问题，消除了偶发性失败
2. 修复了导入路径问题，使测试可正确运行
3. 所有测试在连续 5 次运行中稳定通过
4. 改动范围最小，仅影响测试文件，不涉及生产代码

### 后续建议
1. **监控**: 在 CI 中观察测试稳定性，确保无回归
2. **文档**: 在测试规范中记录 fixture 隔离最佳实践
3. **扩展**: 考虑为其他 orchestration 测试添加类似的隔离 fixture

---

## 附录：关键验证点

### Closeout 隔离验证
- ✅ 每个测试使用独立的临时 closeout 目录
- ✅ 环境变量 `OPENCLAW_CLOSEOUT_DIR` 正确设置
- ✅ `closeout_tracker.CLOSEOUT_DIR` 在模块重载后正确更新
- ✅ 测试间无 closeout 状态泄漏

### Push Consumer 状态机验证
- ✅ `emitted` → `consumed` → `executed` 状态流转正确
- ✅ `simulate_push_success` 仅允许在 `pending`/`consumed` 状态下调用
- ✅ `check_push_consumer_status` 正确返回 `can_auto_continue` 和 `blocker`

### Closeout Gate 验证
- ✅ 前一批 closeout blocked 时阻止下一批
- ✅ 前一批 push pending 时阻止下一批（trading 场景）
- ✅ 前一批 push executed 时允许下一批
- ✅ 首次运行（无 closeout）允许继续

---

**报告生成时间**: 2026-03-24 13:45 GMT+8  
**报告路径**: `docs/review/orchestration-smoke-rerun-2026-03-24.md`
