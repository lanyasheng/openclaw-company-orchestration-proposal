# Failure Closeout Guarantee Policy (P0-4 Batch 4)

> **生效日期**: 2026-03-24
>
> **状态**: ✅ 已实现
>
> **相关模块**: `runtime/orchestrator/closeout_guarantee.py`, `runtime/orchestrator/completion_ack_guard.py`

---

## 1. 问题陈述

### 1.1 现状

当前系统已有成功 completion 的 user-visible closeout guarantee，但 ad-hoc subagent / ACP 任务失败时，仍可能出现：

- 系统内部知道失败（`status.json` 显示 `state=failed`）
- 但老板/父会话没有及时收到标准化失败回报
- 导致"静默失败"，用户不知道任务已失败，也无法采取兜底行动

### 1.2 目标

为失败路径定义最小 failure closeout / guarantee 机制，确保：

1. **任务失败已知** → 系统内部记录失败状态
2. **用户已感知失败** → 用户收到标准化失败通知
3. **区分两者** → 如果 (1) 但非 (2)，触发兜底机制

---

## 2. 核心设计

### 2.1 状态机

```
pending ──────────────────────┐
  │                           │
  │ (ack sent + delivery)     │ (user confirmed)
  ↓                           ↓
fallback_needed ──────────→ guaranteed
  │                           │
  │ (failure notified)        │ (closeout complete)
  └───────────────────────────┘
```

**状态定义**:
- `pending`: 等待用户确认（ack 已发送或 dispatch 已触发）
- `fallback_needed`: 需要兜底（ack 未发送 且 dispatch 未触发）
- `guaranteed`: 用户可见闭环已形成（成功或失败场景都适用）
- `blocked`: 兜底被阻止（配置禁用等）

### 2.2 失败场景 Contract

为失败路径定义的最小 guarantee 字段（通过 `metadata` 传递）：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `failure_summary` | string | 失败摘要（人类可读） | `"Subagent crashed without completion callback"` |
| `failure_stage` | string | 失败阶段 | `"planning" \| "execution" \| "closeout" \| "callback"` |
| `truth_anchor` | string | 真值锚点（机器可读） | `"status.json:state=failed\|exit_code=1"` |
| `fallback_action` | string | 兜底行动建议 | `"Retry with subagent backend instead of tmux"` |
| `user_visible_failure_closeout` | bool | 用户是否已感知失败 | `true \| false` |

### 2.3 兜底规则

```python
# 伪代码
if has_user_visible_closeout:
    return "guaranteed"

if ack_status == "sent" and delivery_status == "sent":
    return "pending"  # 等待用户确认

if dispatch_status == "triggered":
    return "pending"  # dispatch 已触发，等待 continuation（不误报）

# 需要兜底：ack 未发送 且 dispatch 未触发
if ack_status != "sent" and dispatch_status != "triggered":
    return "fallback_needed"

# 其他情况
return "pending"
```

**关键边界**:
- dispatch 已触发时，不误报为 `fallback_needed`（等待 continuation callback）
- ack 已发送但 delivery 失败时，触发 `fallback_needed`
- 用户确认失败通知后，状态从 `fallback_needed` 转为 `guaranteed`

---

## 3. 薄层接入

### 3.1 接入点

在 `completion_ack_guard.py` 的 `_finalize_ack()` 函数中，每个 completion ack 自动 emit guarantee：

```python
# P0-4 Final Mile: User-Visible Closeout Guarantee
guarantee_artifact = emit_closeout_guarantee(
    batch_id=batch_id,
    ack_status=ack_status,
    delivery_status=delivery_status,
    dispatch_status=dispatch_status,
    has_user_visible_closeout=False,  # Initial: not yet confirmed
    artifacts={
        "ack_receipt_path": str(receipt_path),
        "ack_audit_path": str(audit_path),
    },
    metadata={
        "scenario": scenario,
        "decision_action": decision_action,
        "conclusion": conclusion,
        "blocker": blocker,
        "next_step": next_step,
        "next_action": next_action,
        "delivery_reason": delivery_reason,
        # P0-4 Batch 4: Failure fields (optional)
        "failure_summary": "...",  # If applicable
        "failure_stage": "...",    # If applicable
        "fallback_action": "...",  # If applicable
    },
)
```

### 3.2 落盘位置

```
~/.openclaw/shared-context/orchestrator/closeout_guarantees/
├── guarantee-{batch_id}.json    # Guarantee artifact
└── guarantee_index.json          # Index for lookup
```

### 3.3 失败场景处理

Guarantee emit 失败不阻塞主 ack 流程：

```python
try:
    guarantee_artifact = emit_closeout_guarantee(...)
    result["closeout_guarantee"] = { ... }
except Exception as e:
    # Guarantee emit failure should not block main ack flow
    result["closeout_guarantee"] = {
        "status": "failed",
        "error": str(e),
        "note": "Closeout guarantee emit failed; ack receipt still persisted",
    }
```

---

## 4. 测试覆盖

### 4.1 测试文件

`tests/orchestrator/test_failure_closeout_guarantee.py`

### 4.2 覆盖场景

| 测试 | 覆盖内容 | 状态 |
|------|---------|------|
| `test_failure_scenario_task_failed_no_user_notification` | 任务失败但用户未收到通知 | ✅ |
| `test_failure_scenario_subagent_crashed` | subagent 崩溃，无 completion callback | ✅ |
| `test_failure_scenario_timeout_without_notification` | 任务超时，但用户未收到通知 | ✅ |
| `test_failure_scenario_error_with_fallback_notification_sent` | 任务失败，但失败通知已送达 | ✅ |
| `test_failure_scenario_error_user_confirmed` | 任务失败，用户已确认收到通知 | ✅ |
| `test_emit_failure_guarantee_with_failure_metadata` | emit 失败 guarantee，带 failure 元数据 | ✅ |
| `test_update_failure_guarantee_to_user_notified` | 更新失败 guarantee：用户已收到通知 | ✅ |
| `test_no_false_positive_dispatch_triggered` | 不误报：dispatch 已触发 | ✅ |
| `test_no_false_positive_ack_sent` | 不误报：ack 已发送 | ✅ |
| `test_success_path_happy_case` | 成功路径：正常完成，用户已确认 | ✅ |
| `test_success_path_pending_confirmation` | 成功路径：完成但等待用户确认 | ✅ |
| `test_failure_summary_field` | failure_summary 字段 | ✅ |
| `test_failure_stage_field` | failure_stage 字段 | ✅ |
| `test_truth_anchor_field` | truth_anchor 字段 | ✅ |
| `test_fallback_action_field` | fallback_action 字段 | ✅ |

**回归测试**: 现有 17 个测试全部通过 ✅

### 4.3 验证命令

```bash
cd <repo-root>
python3 -m pytest tests/orchestrator/test_failure_closeout_guarantee.py -v
# 输出：15 passed

python3 -m pytest tests/orchestrator/test_closeout_guarantee.py -v
# 输出：17 passed
```

---

## 5. 使用示例

### 5.1 检查 guarantee 状态

```bash
python3 runtime/orchestrator/closeout_guarantee.py check <batch_id>
```

### 5.2 Emit guarantee（带 failure 字段）

```python
from closeout_guarantee import emit_closeout_guarantee

artifact = emit_closeout_guarantee(
    batch_id="batch_failed_001",
    ack_status="fallback_recorded",
    delivery_status="failed",
    dispatch_status="not_triggered",
    has_user_visible_closeout=False,
    metadata={
        "failure_summary": "Subagent crashed without completion callback",
        "failure_stage": "execution",
        "truth_anchor": "status.json:state=failed|exit_code=1",
        "fallback_action": "Retry with subagent backend instead of tmux",
    },
)

print(f"Status: {artifact.guarantee_status}")  # fallback_needed
print(f"Fallback triggered: {artifact.fallback_triggered}")  # True
print(f"Failure summary: {artifact.failure_summary}")  # "Subagent crashed..."
```

### 5.3 更新 guarantee（用户已确认失败）

```python
from closeout_guarantee import update_closeout_guarantee

artifact = update_closeout_guarantee(
    batch_id="batch_failed_001",
    user_visible_closeout=True,
    metadata={
        "notified_at": "2026-03-24T12:00:00",
        "notification_channel": "discord",
        "user_visible_failure_closeout": True,
    },
)

print(f"Status: {artifact.guarantee_status}")  # guaranteed
print(f"User visible closeout: {artifact.user_visible_closeout}")  # True
```

---

## 6. 边界与限制

### 6.1 不做的事情

- ❌ 不自动推送失败通知（那是上层 glue 的职责）
- ❌ 不代替 workflow owner 做决策（只是记录和兜底）
- ❌ 不影响主 ack 流程（guarantee emit 失败不阻塞）

### 6.2 技术债务

- ⚠️ 当前 failure 字段通过 `metadata` 传递，未来可能需要提升到正式字段
- ⚠️ 缺少集中式 failure dashboard（当前需要手动查询 guarantee 文件）
- ⚠️ 自动失败通知集成待完善（当前依赖 completion_ack_guard 手动触发）

---

## 7. 相关文件

- `runtime/orchestrator/closeout_guarantee.py` - 实现
- `runtime/orchestrator/completion_ack_guard.py` - 接入点
- `tests/orchestrator/test_failure_closeout_guarantee.py` - 测试
- `docs/CURRENT_TRUTH.md` - 真值入口（2.2.2 节）
- `docs/policies/waiting-integrity-hard-close-policy-2026-03-21.md` - 相关等待完整性策略
- `docs/policies/heartbeat-boundary-policy.md` - Heartbeat 边界策略

---

## 8. 变更日志

### 2026-03-24 - P0 Batch 4: Initial Implementation

- ✅ 实现 failure closeout guarantee 核心逻辑
- ✅ 添加 15 个测试覆盖失败场景
- ✅ 更新 CURRENT_TRUTH.md
- ✅ 创建本策略文档
- ✅ 现有 17 个测试回归通过

---

## 9. 决策记录

### 9.1 为什么通过 `metadata` 传递 failure 字段？

**决策**: 使用 `metadata` 字典传递 failure 相关字段，而不是添加到 `CloseoutGuaranteeArtifact` 的正式字段。

**理由**:
1. 向后兼容：不影响现有 guarantee artifact schema
2. 灵活性：failure 字段是可选的，不是所有场景都需要
3. 薄层扩展：符合"不做大拆架构"的设计原则

**权衡**:
- 缺点：类型安全性较低，IDE 无法自动补全
- 优点：快速迭代，易于扩展新字段

### 9.2 为什么 guarantee emit 失败不阻塞主流程？

**决策**: Guarantee emit 失败时，记录错误但不阻塞 ack receipt 落盘。

**理由**:
1. Guarantee 是兜底机制，不应影响主流程
2. 避免单点故障：guarantee 问题不应导致 ack 丢失
3. 渐进式采用：允许 guarantee 机制在早期有不稳定期

**权衡**:
- 缺点：可能出现 guarantee 缺失的情况
- 优点：主流程更稳定，guarantee 可以逐步完善
