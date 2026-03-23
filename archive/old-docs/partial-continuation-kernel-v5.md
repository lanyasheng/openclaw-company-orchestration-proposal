# Universal Partial-Completion Continuation Framework v5

> **当前阶段**: ✅ **v5 完整闭环已完成** (2026-03-22)
> 
> `proposal -> registration -> auto-dispatch -> spawn closure -> spawn execution artifact -> completion receipt`

---

## 1. 概述

v5 是 Continuation Kernel 的第五层，也是当前主线的最后一层。它完成了从 **spawn closure** 到 **completion receipt** 的真实闭环。

### 1.1 v5 核心能力

| 模块 | 文件 | 核心能力 |
|------|------|---------|
| **Spawn Execution** | `runtime/orchestrator/spawn_execution.py` | 消费 spawn closure，生成 execution artifact |
| **Completion Receipt** | `runtime/orchestrator/completion_receipt.py` | 消费 execution，生成 receipt artifact |

### 1.2 完整链路

```
Task Registration (v2)
       ↓
Auto-Dispatch (v3)
       ↓
Spawn Closure (v4)
       ↓
Spawn Execution (v5)  ← 本阶段新增
       ↓
Completion Receipt (v5)  ← 本阶段新增
```

---

## 2. Spawn Execution (v5.1)

### 2.1 目标

把 v4 的 spawn closure 推进到 **real spawn execution artifact**。

### 2.2 核心能力

1. 消费 spawn closure artifact / spawn payload
2. 生成 canonical spawn execution artifact
3. 字段包括：
   - `spawn_execution_status`: started | skipped | blocked | failed
   - `spawn_execution_reason`: 执行/跳过/阻塞/失败的原因
   - `spawn_execution_time`: 执行时间戳
   - `spawn_execution_target`: 执行目标（runtime / owner / scenario / task preview）
4. Linkage 到 `dispatch_id` / `spawn_closure_id`
5. 去重机制（同一 spawn closure 不重复执行）
6. Policy guard（白名单场景 / status 检查 / payload 检查）

### 2.3 Artifact 结构

```json
{
  "execution_version": "spawn_execution_v1",
  "execution_id": "exec_607e018c9785",
  "spawn_id": "spawn_18a59d08fbcd",
  "dispatch_id": "dispatch_get_test",
  "registration_id": "reg_get_test",
  "task_id": "task_get_test",
  "spawn_execution_status": "started",
  "spawn_execution_reason": "Policy evaluation passed; execution started (simulated)",
  "spawn_execution_time": "2026-03-22T22:18:51.596430",
  "spawn_execution_target": {
    "runtime": "subagent",
    "owner": "",
    "scenario": "trading_roundtable_phase1",
    "task_preview": "",
    "cwd": "~/.openclaw/workspace"
  },
  "dedupe_key": "exec_dedupe:spawn_18a59d08fbcd:dispatch_get_test",
  "execution_payload": { ... },
  "execution_result": {
    "execution_mode": "simulated",
    "ready_for_downstream": true
  },
  "policy_evaluation": { ... }
}
```

### 2.4 存储位置

- **目录**: `~/.openclaw/shared-context/spawn_executions/`
- **索引**: `~/.openclaw/shared-context/spawn_executions/execution_index.json`（去重用）

### 2.5 使用方式

```python
from spawn_execution import execute_spawn, SpawnExecutionPolicy

# 执行 spawn
execution = execute_spawn(
    spawn_id="spawn_18a59d08fbcd",
    policy=SpawnExecutionPolicy(
        scenario_allowlist=["trading_roundtable_phase1"],
        simulate_execution=True,  # 当前阶段默认模拟
    )
)

print(f"Execution ID: {execution.execution_id}")
print(f"Status: {execution.spawn_execution_status}")
```

---

## 3. Completion Receipt (v5.2)

### 3.1 目标

实现 spawn execution 后的 **completion receipt closure** 闭环。

### 3.2 核心能力

1. 消费 spawn execution artifact
2. 生成 canonical completion receipt artifact
3. 字段包括：
   - `receipt_status`: completed | failed | missing
   - `source_spawn_execution_id`: 来源 execution ID
   - `source_dispatch_id`: 来源 dispatch ID
   - `result_summary`: 结果摘要
   - `business_result`: 业务结果（trading 场景特定等）
4. Linkage 回 source task/batch
5. 去重机制（同一 execution 不重复创建 receipt）

### 3.3 Artifact 结构

```json
{
  "receipt_version": "completion_receipt_v1",
  "receipt_id": "receipt_6d6f97ce0e10",
  "source_spawn_execution_id": "exec_607e018c9785",
  "source_spawn_id": "spawn_18a59d08fbcd",
  "source_dispatch_id": "dispatch_get_test",
  "source_registration_id": "reg_get_test",
  "source_task_id": "task_get_test",
  "receipt_status": "completed",
  "receipt_reason": "Execution started and completed (simulated)",
  "receipt_time": "2026-03-22T22:18:51.596997",
  "result_summary": "Simulated execution for task task_get_test",
  "business_result": {
    "execution_mode": "simulated",
    "downstream_ready": true,
    "dispatch_id": "dispatch_get_test",
    "registration_id": "reg_get_test",
    "task_id": "task_get_test"
  },
  "metadata": {
    "source_execution_status": "started",
    "scenario": "trading_roundtable_phase1"
  }
}
```

### 3.4 存储位置

- **目录**: `~/.openclaw/shared-context/completion_receipts/`
- **索引**: `~/.openclaw/shared-context/completion_receipts/receipt_index.json`（去重用）

### 3.5 使用方式

```python
from completion_receipt import create_completion_receipt

# 创建 receipt
receipt = create_completion_receipt(
    execution_id="exec_607e018c9785"
)

print(f"Receipt ID: {receipt.receipt_id}")
print(f"Status: {receipt.receipt_status}")
```

---

## 4. 完整 Pipeline

### 4.1 一键运行完整闭环

```python
from completion_receipt import run_full_pipeline

result = run_full_pipeline(
    spawn_id="spawn_18a59d08fbcd",
    simulate=True  # 模拟执行
)

print(f"Spawn: {result['spawn'].spawn_id}")
print(f"Execution: {result['execution'].execution_id}")
print(f"Receipt: {result['receipt'].receipt_id}")
```

### 4.2 Trading 场景最小 Happy Path

```
registered task
      ↓
auto-dispatch
      ↓
spawn closure (emitted)
      ↓
spawn execution (started)
      ↓
completion receipt (completed)
```

**Linkage 验证**:
- `execution.spawn_id == spawn.spawn_id` ✅
- `execution.dispatch_id == spawn.dispatch_id` ✅
- `receipt.source_spawn_execution_id == execution.execution_id` ✅
- `receipt.source_spawn_id == spawn.spawn_id` ✅

---

## 5. 测试

### 5.1 测试命令

```bash
cd ~/.openclaw/workspace/orchestrator
python3 test_v5 闭环.py
```

### 5.2 测试覆盖

| 测试项 | 描述 | 状态 |
|--------|------|------|
| Happy path | spawn closure -> execution -> receipt | ✅ |
| Blocked spawn | blocked/duplicate/missing payload 不执行 | ✅ |
| Duplicate prevention | 去重机制 | ✅ |
| Linkage 验证 | dispatch_id / spawn_closure_id / task_id / batch_id | ✅ |

### 5.3 测试结果示例

```
============================================================
V5 Continuation Kernel 测试套件
============================================================
  ✅ PASS: Happy path
  ✅ PASS: Blocked spawn
  ✅ PASS: Duplicate prevention

总计：3/3 通过
🎉 所有测试通过!
```

---

## 6. 当前阶段边界

### 6.1 已完成

- ✅ Spawn execution artifact 真实落盘
- ✅ Completion receipt artifact 真实落盘
- ✅ Trading 场景最小 happy path 跑通
- ✅ Linkage 正确（dispatch_id / spawn_closure_id / task_id）
- ✅ 去重机制正常工作
- ✅ Policy guard 正常工作

### 6.2 当前限制

- ⚠️ **执行模式**: 当前默认 `simulate_execution=True`，只输出 artifact，不真正调用 `sessions_spawn`
- ⚠️ **真实执行**: 需要后续集成 `sessions_spawn` 才能真正发起 subagent 执行
- ⚠️ **Callback 闭环**: receipt 生成后，尚未自动触发 state_machine 更新

### 6.3 下一步（非本轮优先）

1. **真实执行集成**: 将 `simulate_execution=False` 并接入 `sessions_spawn`
2. **Callback 闭环**: receipt 生成后自动更新 state_machine / batch_aggregator
3. **多场景扩展**: 添加更多场景到白名单（channel_roundtable 等）

---

## 7. 模块关系

```
┌─────────────────────────────────────────────────────────────┐
│                    Continuation Kernel                       │
├─────────────────────────────────────────────────────────────┤
│  v1: Partial Continuation (partial_continuation.py)          │
│  v2: Task Registration (task_registration.py)                │
│  v3: Auto Dispatch (auto_dispatch.py)                        │
│  v4: Spawn Closure (spawn_closure.py)                        │
│  v5: Spawn Execution (spawn_execution.py)         ← 本阶段   │
│      Completion Receipt (completion_receipt.py)   ← 本阶段   │
└─────────────────────────────────────────────────────────────┘

Trading 场景接入:
  trading_roundtable.py → spawn_closure → spawn_execution → receipt
```

---

## 8. 快速参考

### 8.1 查询 artifacts

```bash
# 查询 spawn executions
cd ~/.openclaw/workspace/orchestrator
python3 -c "from spawn_execution import list_spawn_executions; print(list_spawn_executions(limit=5))"

# 查询 completion receipts
python3 -c "from completion_receipt import list_completion_receipts; print(list_completion_receipts(limit=5))"
```

### 8.2 文件位置

| Artifact 类型 | 目录 |
|--------------|------|
| Spawn Closures | `~/.openclaw/shared-context/spawn_closures/` |
| Spawn Executions | `~/.openclaw/shared-context/spawn_executions/` |
| Completion Receipts | `~/.openclaw/shared-context/completion_receipts/` |

---

## 9. 变更日志

### v5.0.0 (2026-03-22)

- ✅ 新增 `spawn_execution.py`: Spawn execution kernel
- ✅ 新增 `completion_receipt.py`: Completion receipt kernel
- ✅ 新增 `test_v5 闭环.py`: v5 完整闭环测试
- ✅ 测试通过：happy path / blocked spawn / duplicate prevention
- ✅ 文档：本文件

---

**详细设计**: 各模块源码的 docstring 提供了更详细的实现说明。

**上游文档**: 
- v4 spawn closure: `partial-continuation-kernel-v4.md`（如有）
- 总体计划：`overall-plan.md`
- 当前真值：`CURRENT_TRUTH.md`
