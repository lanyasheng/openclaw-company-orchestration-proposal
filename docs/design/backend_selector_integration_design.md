# Backend Selector Integration Design

**Date:** 2026-03-30  
**Author:** Zoe (CTO & Chief Orchestrator)  
**Status:** Implementation in progress

## Executive Summary

将 `backend_selector.py` 正式接入主 dispatch 路径，使系统能根据任务特征自动推荐最佳执行后端 (subagent/tmux)。同时收紧 tmux 链路口径，从"过渡态"收成"正式一等路径"。

## Scope

### In Scope
1. **Backend Selector 接入主 dispatch 路径**
   - 在 `dispatch_planner.py` 的 `create_plan()` 中集成 backend_selector
   - 当 `backend_preference` 未显式指定时，自动调用 backend_selector 推荐
   - 显式 `backend_preference` 保持最高优先级（不可覆盖）
   - 推荐结果需可解释（reason/factors），落到 dispatch metadata

2. **Tmux 链路口径收紧**
   - 修正 `entry_defaults.py` / `continuation_backends.py` / `orchestrator_dispatch_bridge.py` 中不一致的口径
   - 明确区分："桥脚本兼容层" vs "tmux backend 本身支持"
   - 保留 legacy 说明但不再标记为"COMPAT-ONLY"，改为"DUAL-TRACK: FULLY SUPPORTED"

3. **测试覆盖**
   - backend_preference 显式指定时不被自动选择覆盖
   - 未指定时会调用 backend_selector 并得出可解释结果
   - 长任务/需监控/coding 任务倾向 tmux
   - 短任务/简单任务倾向 subagent
   - tmux 路径文档/配置口径不再自相矛盾

4. **文档更新**
   - README / CURRENT_TRUTH / 接入指南中明确"默认怎么选"和"tmux 定位"

### Out of Scope
- 修改 backend_selector.py 的核心推荐算法（已有完整实现）
- 破坏现有 production 路径
- 修改 callback/receipt/dispatch 真值链

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| 自动推荐覆盖显式偏好 | High | 代码审查确保 user_preference 检查在最前；测试覆盖 |
| 破坏现有 dispatch 路径 | High | 向后兼容测试；渐进式 rollout |
| Tmux 口径修正引入歧义 | Medium | 明确区分"桥脚本"与"backend 本身"；文档审查 |
| 推荐逻辑不可解释 | Medium | 强制 reason/factors 落到 dispatch metadata |

## Rollback Plan

1. **代码回退**: Git revert 本次提交
2. **配置回退**: 设置 `FORCE_BACKEND=subagent` 环境变量可绕过自动推荐
3. **文档回退**: 恢复旧版本文档

## Implementation Plan

### Phase 1: Backend Selector 接入 (P0)
**文件:** `runtime/orchestrator/core/dispatch_planner.py`

**改动:**
1. 导入 `backend_selector.recommend_backend`
2. 在 `create_plan()` 中，当 `backend=DispatchBackend.SUBAGENT` (默认) 且无显式偏好时：
   - 从 `task_preview` / `continuation` 提取任务特征
   - 调用 `recommend_backend()` 获取推荐
   - 根据推荐结果设置 `backend` 和 `backend_plan`
   - 将推荐理由写入 `orchestration_contract["backend_selection"]`

**代码示例:**
```python
from backend_selector import recommend_backend

# 在 create_plan() 中
if backend == DispatchBackend.SUBAGENT and not explicit_backend_preference:
    task_preview = continuation.get("task_preview", "")
    rec = recommend_backend(
        task_description=task_preview,
        estimated_duration_minutes=None,  # 可从 metadata 提取
        requires_monitoring=None,  # 可从关键词推断
    )
    
    # 应用推荐（但保留显式偏好优先）
    if rec.backend == "tmux":
        backend = DispatchBackend.TMUX
    
    # 记录推荐理由
    orchestration_contract["backend_selection"] = {
        "recommended_backend": rec.backend,
        "confidence": rec.confidence,
        "reason": rec.reason,
        "factors": rec.factors,
        "explicit_override": False,
    }
```

### Phase 2: Tmux 口径收紧 (P0)
**文件:** 
- `runtime/orchestrator/entry_defaults.py`
- `runtime/orchestrator/continuation_backends.py`
- `runtime/scripts/orchestrator_dispatch_bridge.py`

**改动:**
1. 将"COMPAT-ONLY" / "legacy" 改为 "DUAL-TRACK: FULLY SUPPORTED"
2. 明确说明：
   - 桥脚本 (`orchestrator_dispatch_bridge.py`) 保留兼容层是为了平滑迁移
   - tmux backend 本身是一等公民，与 subagent 并列
3. 更新注释和文档字符串

**口径对照表:**
| 旧口径 | 新口径 |
|--------|--------|
| "COMPAT-ONLY legacy path" | "DUAL-TRACK: FULLY SUPPORTED backend" |
| "legacy tmux backend" | "tmux backend (interactive_observable)" |
| "NEW DEVELOPMENT MUST USE subagent" | "DEFAULT: subagent for automation; tmux for interactive" |

### Phase 3: 测试覆盖 (P0)
**文件:** `tests/orchestrator/test_backend_selector_integration.py`

**测试用例:**
1. `test_explicit_backend_preference_not_overridden()`
2. `test_auto_recommendation_called_when_not_specified()`
3. `test_long_task_recommends_tmux()`
4. `test_short_task_recommends_subagent()`
5. `test_coding_task_with_monitoring_recommends_tmux()`
6. `test_documentation_task_recommends_subagent()`
7. `test_backend_selection_metadata_recorded()`

### Phase 4: 文档更新 (P1)
**文件:**
- `docs/CURRENT_TRUTH.md`
- `docs/BACKEND_SELECTION_GUIDE.md` (新增)
- `README.md`

**内容:**
1. Backend 选择决策树
2. Tmux 定位说明
3. 配置示例

## Acceptance Criteria

- [x] 设计摘要完成
- [ ] Phase 1 完成：backend_selector 接入 dispatch_planner
- [ ] Phase 2 完成：tmux 口径收紧
- [ ] Phase 3 完成：测试覆盖全部通过
- [ ] Phase 4 完成：文档更新
- [ ] 提交并 push 到 origin/main

## Success Metrics

1. **功能正确性**: 所有测试用例通过
2. **向后兼容**: 现有 dispatch 路径不受影响
3. **可解释性**: dispatch metadata 中包含 backend_selection 字段
4. **口径一致**: 文档/代码/注释不再自相矛盾

---

**Next Steps:** 开始 Phase 1 实施
