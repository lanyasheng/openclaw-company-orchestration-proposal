# Universal Partial-Completion Continuation Framework v4 — Downstream Spawn Closure

**版本**: v4  
**日期**: 2026-03-22  
**状态**: Main branch (limited emission / intent-only)

## 执行摘要

v4 把 v3 的 `dispatch intent` 推进到 **downstream spawn closure**（可执行的 spawn artifact）。核心能力：

1. **Spawn closure kernel**: 从 dispatch artifact 生成 canonical spawn closure artifact
2. **去重/防重复发起**: 同一 dispatch 不重复 emit spawn closure
3. **Policy guard**: blocked / duplicate / missing payload 不能 emit，白名单场景控制
4. **Downstream 可消费**: 产出 spawn command / spawn payload，operator/main 可以继续消费

**当前阶段**: `dispatch -> spawn closure intent / limited emission`（不是全域自动外部执行）

## 核心概念

### Dispatch Artifact (v3)

```json
{
  "dispatch_id": "dispatch_abc123",
  "registration_id": "reg_xyz789",
  "task_id": "task_def456",
  "dispatch_status": "dispatched",
  "dispatch_target": {
    "scenario": "trading_roundtable_phase1",
    "adapter": "trading_roundtable",
    "owner": "trading"
  },
  "execution_intent": {
    "recommended_spawn": {
      "runtime": "subagent",
      "task": "Continuation task description",
      "cwd": "/workspace",
      "metadata": {...}
    }
  }
}
```

### Spawn Closure Artifact (v4 新增)

```json
{
  "spawn_version": "spawn_closure_v1",
  "spawn_id": "spawn_abc123",
  "dispatch_id": "dispatch_abc123",
  "registration_id": "reg_xyz789",
  "task_id": "task_def456",
  "spawn_status": "ready | skipped | blocked | emitted",
  "spawn_reason": "Policy evaluation passed",
  "spawn_target": {
    "runtime": "subagent",
    "owner": "trading",
    "scenario": "trading_roundtable_phase1",
    "task_preview": "Task title",
    "cwd": "/workspace"
  },
  "dedupe_key": "dedupe:dispatch_abc123:reg_xyz789:task_def456",
  "emitted_at": "2026-03-22T12:00:00",
  "spawn_command": "sessions_spawn(...)",
  "spawn_payload": {
    "runtime": "subagent",
    "task": "...",
    "cwd": "...",
    "metadata": {...}
  },
  "policy_evaluation": {...},
  "metadata": {...}
}
```

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Partial Continuation v4                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐ │
│  │   Dispatch   │────▶│    Spawn     │────▶│  Downstream     │ │
│  │  Artifact    │     │   Closure    │     │  Consumer       │ │
│  │   (v3)       │     │   Kernel     │     │  (optional)     │ │
│  └──────────────┘     └──────────────┘     └─────────────────┘ │
│         │                    │                       │          │
│         │                    │                       │          │
│         ▼                    ▼                       ▼          │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐ │
│  │ execution_   │     │ spawn_status │     │ spawn_command   │ │
│  │ intent.      │     │ spawn_reason │     │ spawn_payload   │ │
│  │ recommended_ │     │ spawn_target │     │ (sessions_spawn)│ │
│  │ _spawn       │     │ dedupe_key   │     │                 │ │
│  └──────────────┘     └──────────────┘     └─────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## 核心流程

### 1. Dispatch -> Spawn Closure

```python
from spawn_closure import emit_spawn_closure, SpawnPolicy

# 从 dispatch artifact 生成 spawn closure
artifact = emit_spawn_closure(
    dispatch_id="dispatch_abc123",
    policy=SpawnPolicy(
        scenario_allowlist=["trading_roundtable_phase1"],
        require_dispatch_status="dispatched",
        require_execution_intent=True,
        prevent_duplicate=True,
    ),
)

# artifact.spawn_status: ready | skipped | blocked | emitted
# artifact.spawn_command: downstream 可消费的 spawn command
# artifact.spawn_payload: downstream 可消费的 spawn payload
```

### 2. Policy Evaluation

Spawn policy 检查：

| Check | 描述 | 失败处理 |
|-------|------|---------|
| dispatch_status | 必须是 `dispatched` | blocked |
| execution_intent | 必须存在 | blocked |
| recommended_spawn | 必须在 execution_intent 中 | blocked |
| scenario_allowlist | 必须在白名单中 | blocked |
| prevent_duplicate | 同一 dispatch 不重复 | blocked |

### 3. Dedupe / 防重复发起

```python
from spawn_closure import _generate_dedupe_key, _is_duplicate_spawn

# 生成 dedupe key
dedupe_key = _generate_dedupe_key(dispatch_id, registration_id, task_id)
# 结果: "dedupe:dispatch_abc123:reg_xyz789:task_def456"

# 检查是否已存在
is_dup = _is_duplicate_spawn(dedupe_key)  # True/False
```

### 4. Trading 场景接入

```python
from spawn_closure import create_trading_spawn_closure

# Trading 场景特定的 spawn closure 创建
artifact = create_trading_spawn_closure(
    dispatch_id="dispatch_trading123",
)

# artifact.spawn_target.scenario == "trading_roundtable_phase1"
# artifact.metadata.truth_anchor 包含 batch_id 等信息
# artifact.spawn_payload.metadata.trading_context 包含 trading 特定上下文
```

## 文件结构

```
runtime/orchestrator/
├── spawn_closure.py          # v4 核心模块
├── auto_dispatch.py          # v3 dispatch artifact
└── partial_continuation.py   # v1/v2 closeout/registration

tests/orchestrator/
└── test_spawn_closure.py     # v4 测试（24 个测试用例）

docs/
├── partial-continuation-kernel-v4.md  # 本文档
└── CURRENT_TRUTH.md          # 更新 v4 状态
```

## 状态机

```
                    ┌─────────────┐
                    │  Dispatch   │
                    │  Artifact   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Spawn     │
                    │   Closure   │
                    │   Kernel    │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │  ready   │ │  blocked │ │  skipped │
       └────┬─────┘ └────┬─────┘ └────┬─────┘
            │            │            │
            ▼            │            │
       ┌──────────┐      │            │
       │  emitted │◀─────┘            │
       └──────────┘
```

## 当前限制

### 不是全域自动执行

- **当前阶段**: 只输出 canonical spawn artifact + downstream command/intent
- **不强求**: 一定真的调用外部 `sessions_spawn`
- **允许**: operator/main 手动消费 spawn command / payload

### 白名单场景

- 默认只允许 `trading_roundtable_phase1`
- 其他场景需要显式添加到 `SpawnPolicy.scenario_allowlist`

### Limited Emission

- 当前是 `dispatch -> spawn closure intent / limited emission`
- 不是全域无人值守自动执行
- 需要 operator/main 确认或进一步处理

## 测试

```bash
# 运行 v4 测试
python3 -m pytest tests/orchestrator/test_spawn_closure.py -v

# 运行所有 orchestrator 测试
python3 -m pytest tests/orchestrator -q -k "spawn or dispatch or partial"
```

### 测试覆盖

- ✅ Happy path: dispatch artifact -> spawn closure artifact
- ✅ Duplicate dispatch 不重复 emit
- ✅ Missing payload / blocked path 不 emit
- ✅ Trading 场景具体 spawn closure 输出
- ✅ Policy guard (blocked dispatch / missing intent / non-allowlist scenario)
- ✅ Dedupe key generation
- ✅ List / get spawn closures

## 向后兼容

- v1 (partial closeout): 保持兼容
- v2 (auto-registration): 保持兼容
- v3 (auto-dispatch): 保持兼容，v4 是 v3 的自然延伸

## 下一步（可选）

1. **自动外部执行**: 真正调用 `sessions_spawn` 执行 spawn payload
2. **更多场景接入**: channel_roundtable / ainews / macro 等
3. **执行回执**: spawn closure -> completion receipt 闭环
4. **执行状态追踪**: emitted -> running -> completed/failed

## 相关文档

- v1: `partial-continuation-kernel-v1.md` (partial closeout / auto-replan)
- v2: `partial-continuation-kernel-v2.md` (auto-registration layer)
- v3: `partial-continuation-kernel-v3.md` (auto-dispatch execution framework)
- v4: 本文档 (downstream spawn closure)
- `CURRENT_TRUTH.md`: 整体真值状态
