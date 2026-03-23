# Universal Partial-Completion Continuation Framework v6
## Real sessions_spawn Integration & Callback Auto-Close

> **版本**: v6 (2026-03-22)
>
> **定位**: 通用 orchestration kernel capability，trading 仅作为首个消费者
>
> **核心**: sessions_spawn-compatible request interface + callback auto-close bridge

---

## 0. Executive Summary

v6 推进 v5 的 artifact/receipt 闭环到：
- **sessions_spawn-compatible request**（可被 OpenClaw bridge 直接消费）
- **callback auto-close artifact**（闭环状态可查询）

关键设计原则：
1. **Adapter-agnostic**: 不绑定 trading / channel / 任何特定场景
2. **Canonical artifacts**: 真实落盘，可被下游消费
3. **Linkage integrity**: dispatch_id → spawn_id → execution_id → receipt_id → request_id → close_id
4. **Prepare-only default**: 默认生成 request artifact，不真正调用 `sessions_spawn`（需上层 bridge 集成）

---

## 1. What's New in v6

### 1.1 sessions_spawn_request.py（新增）

**目标**: 从 completion receipt 生成 canonical sessions_spawn-compatible request。

**核心字段**:
```python
{
    "request_id": "req_abc123",
    "source_receipt_id": "receipt_xyz789",
    "source_execution_id": "exec_def456",
    "source_spawn_id": "spawn_ghi789",
    "source_dispatch_id": "dispatch_jkl012",
    "source_registration_id": "reg_mno345",
    "source_task_id": "task_pqr678",
    "spawn_request_status": "prepared",  # prepared | emitted | blocked | failed
    "spawn_request_reason": "Policy evaluation passed",
    "spawn_request_time": "2026-03-22T10:00:00",
    "sessions_spawn_params": {
        "runtime": "subagent",
        "cwd": "/path/to/workspace",
        "task": "Orchestration continuation for task task_pqr678",
        "label": "orch-task_pqr678",
        "metadata": {
            "dispatch_id": "dispatch_jkl012",
            "registration_id": "reg_mno345",
            "spawn_id": "spawn_ghi789",
            "execution_id": "exec_def456",
            "receipt_id": "receipt_xyz789",
            "scenario": "generic",
            "orchestration_continuation": True
        }
    },
    "dedupe_key": "request_dedupe:receipt_xyz789:exec_def456",
    "policy_evaluation": {...},
    "metadata": {...}
}
```

**Policy 检查**:
- `require_receipt_status`: 要求的 receipt status（默认 "completed"）
- `require_execution_payload`: 是否要求 execution payload（默认 True）
- `prevent_duplicate`: 防止重复创建 request（默认 True）
- `prepare_only`: 仅准备 request，不真正调用 sessions_spawn（默认 True）

**使用方式**:
```bash
# 从 receipt 准备 request
python sessions_spawn_request.py prepare <receipt_id>

# 列出 requests
python sessions_spawn_request.py list [--status <status>] [--receipt <receipt_id>]

# 获取 request 详情
python sessions_spawn_request.py get <request_id>

# 获取 sessions_spawn 调用参数
python sessions_spawn_request.py call-params <request_id>
```

### 1.2 callback_auto_close.py（新增）

**目标**: 从 receipt + request 生成 canonical callback auto-close artifact。

**核心字段**:
```python
{
    "close_id": "close_stu901",
    "source_request_id": "req_abc123",  # 可选
    "source_receipt_id": "receipt_xyz789",
    "source_execution_id": "exec_def456",
    "source_spawn_id": "spawn_ghi789",
    "source_dispatch_id": "dispatch_jkl012",
    "source_registration_id": "reg_mno345",
    "source_task_id": "task_pqr678",
    "close_status": "closed",  # closed | pending | blocked | partial
    "close_reason": "Receipt completed + spawn request prepared = full close",
    "close_time": "2026-03-22T10:00:01",
    "linkage": {
        "dispatch_id": "dispatch_jkl012",
        "spawn_id": "spawn_ghi789",
        "execution_id": "exec_def456",
        "receipt_id": "receipt_xyz789",
        "request_id": "req_abc123"
    },
    "close_summary": "Task task_pqr678 (generic) fully closed: receipt completed + spawn request prepared",
    "metadata": {...}
}
```

**Close Status**:
- `closed`: Receipt completed + spawn request prepared = full close
- `partial`: Receipt completed but no spawn request yet
- `blocked`: Receipt failed or request blocked
- `pending`: Receipt missing or awaiting completion

**Linkage Index**:
支持通过任意 ID 反向查询 close：
- `by_receipt:<receipt_id>`
- `by_execution:<execution_id>`
- `by_spawn:<spawn_id>`
- `by_dispatch:<dispatch_id>`
- `by_request:<request_id>`

**使用方式**:
```bash
# 创建 auto-close
python callback_auto_close.py create <receipt_id> [--request <request_id>]

# 列出 closes
python callback_auto_close.py list [--status <status>] [--task <task_id>]

# 获取 close 详情
python callback_auto_close.py get <close_id>

# 通过 linkage 查找
python callback_auto_close.py find --receipt <receipt_id>

# 查看闭环 summary
python callback_auto_close.py summary [--scenario <scenario>]
```

---

## 2. Architecture

### 2.1 Full Pipeline

```
task_registration → auto_dispatch → spawn_closure → spawn_execution → completion_receipt
                                                                      ↓
                                                    ┌─────────────────┴─────────────────┐
                                                    ↓                                   ↓
                                      sessions_spawn_request                    callback_auto_close
                                                    ↓                                   ↓
                                      (canonical request)                        (close artifact)
                                                    ↓                                   ↓
                                      [OpenClaw bridge]                          [operator/main query]
```

### 2.2 Adapter-Agnostic Design

v6 的通用层不绑定任何特定场景：

```python
# 通用 policy（不绑定 trading）
SpawnRequestPolicy(
    require_receipt_status="completed",
    require_execution_payload=True,
    prevent_duplicate=True,
    prepare_only=True,
)

# 通用 request（任何场景均可消费）
SessionsSpawnRequest(
    sessions_spawn_params={
        "runtime": "subagent",
        "metadata": {
            "scenario": "generic",  # 或 "trading_roundtable_phase1" / "channel_roundtable"
            "owner": "any_owner",
        }
    }
)

# 通用 close（任何场景均可查询）
CallbackAutoCloseArtifact(
    close_status="closed",
    linkage={...},  # 完整 linkage，支持任意 ID 查询
)
```

### 2.3 Linkage Integrity

完整链路：
```
registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → close_id
```

每个 artifact 都包含完整的 source linkage，支持：
- 正向追踪：从 registration 到 close
- 反向查询：从任意 ID 找到完整链路

---

## 3. Trading as First Consumer

Trading 场景是 v6 的**首个消费者/样例**，不是特化目标。

### 3.1 Trading Happy Path

```
trading task registered → auto-dispatch → spawn closure → spawn execution → completion receipt
                                                                                   ↓
                                                                 sessions_spawn_request (trading metadata)
                                                                                   ↓
                                                                 callback_auto_close (closed)
```

### 3.2 No Trading-Only Fields

v6 不新增 trading 私有字段：
- `sessions_spawn_params.metadata.scenario` = "trading_roundtable_phase1"（只是值不同，字段通用）
- `callback_auto_close.metadata.scenario` = "trading_roundtable_phase1"（只是值不同，字段通用）

所有字段都是通用的，任何场景都可以使用。

---

## 4. Integration Points

### 4.1 OpenClaw Bridge（待集成）

v6 生成的 `sessions_spawn_request` 可被 OpenClaw bridge 直接消费：

```python
# 伪代码：OpenClaw bridge 消费 request
from sessions_spawn_request import get_spawn_request

request = get_spawn_request("req_abc123")
if request.spawn_request_status == "prepared":
    params = request.to_sessions_spawn_call()
    # 调用 sessions_spawn
    result = sessions_spawn(
        task=params["task"],
        runtime=params["runtime"],
        cwd=params["cwd"],
        label=params["label"],
        metadata=params["metadata"],
    )
    # 更新 request status 为 "emitted"
```

### 4.2 Operator/Main Query

operator/main 可以通过 linkage 查询闭环状态：

```python
from callback_auto_close import find_close_by_linkage, build_close_summary

# 通过 receipt_id 查找 close
close = find_close_by_linkage(receipt_id="receipt_xyz789")
if close:
    print(f"Close status: {close.close_status}")
    print(f"Linkage: {close.linkage}")

# 查看整体 summary
summary = build_close_summary(scenario="trading_roundtable_phase1")
print(f"Total closes: {summary['total_closes']}")
print(f"By status: {summary['by_status']}")
```

---

## 5. Testing

### 5.1 Test Files

- `tests/orchestrator/test_sessions_spawn_request.py`: sessions_spawn_request 测试
- `tests/orchestrator/test_callback_auto_close.py`: callback_auto_close 测试

### 5.2 Test Commands

```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal

# sessions_spawn_request 测试
python3 -m pytest tests/orchestrator/test_sessions_spawn_request.py -v

# callback_auto_close 测试
python3 -m pytest tests/orchestrator/test_callback_auto_close.py -v

# 组合测试（包括 v5）
python3 -m pytest tests/orchestrator/ -v -k "spawn or receipt or request or close"
```

### 5.3 Coverage

**sessions_spawn_request**:
- ✅ Happy path: 生成 sessions_spawn-compatible request
- ✅ Blocked: receipt status 不符不生成 request
- ✅ Duplicate: 同一 receipt 不重复创建 request
- ✅ Missing payload: execution payload 缺失不生成 request
- ✅ to_sessions_spawn_call: 转换为 sessions_spawn 调用参数

**callback_auto_close**:
- ✅ Happy path: receipt + request → closed
- ✅ Partial: receipt completed 但无 request → partial
- ✅ Blocked: receipt failed → blocked
- ✅ Linkage: 完整 linkage 记录
- ✅ Find by linkage: 通过任意 ID 反向查询

---

## 6. File Locations

### 6.1 Runtime Modules

```
runtime/orchestrator/
├── sessions_spawn_request.py    # v6.1: sessions_spawn-compatible request
├── callback_auto_close.py       # v6.2: callback auto-close bridge
├── spawn_execution.py           # v5.1: spawn execution artifact
├── completion_receipt.py        # v5.2: completion receipt artifact
├── spawn_closure.py             # v4: spawn closure artifact
├── auto_dispatch.py             # v3: auto-dispatch
├── task_registration.py         # v2: task registration
└── partial_continuation.py      # v1: partial continuation
```

### 6.2 Artifact Storage

```
~/.openclaw/shared-context/
├── spawn_requests/              # v6.1: sessions_spawn requests
│   ├── req_abc123.json
│   └── request_index.json
├── callback_closes/             # v6.2: callback auto-closes
│   ├── close_xyz789.json
│   └── close_linkage_index.json
├── spawn_executions/            # v5.1: spawn executions
│   ├── exec_def456.json
│   └── execution_index.json
├── completion_receipts/         # v5.2: completion receipts
│   ├── receipt_xyz789.json
│   └── receipt_index.json
├── spawn_closures/              # v4: spawn closures
│   ├── spawn_ghi789.json
│   └── spawn_index.json
└── dispatches/                  # v3: dispatches
    ├── dispatch_jkl012.json
    └── dispatch_index.json
```

---

## 7. Maturity Boundary

### 7.1 What's Done

- ✅ **Canonical request artifact**: sessions_spawn-compatible request 真实落盘
- ✅ **Canonical close artifact**: callback auto-close 真实落盘
- ✅ **Full linkage**: dispatch → spawn → execution → receipt → request → close
- ✅ **Dedupe prevention**: duplicate request / close prevention
- ✅ **Adapter-agnostic**: 通用 kernel，不绑定特定场景
- ✅ **Test coverage**: 100+ 测试覆盖 happy path / blocked / duplicate

### 7.2 What's Not Done

- ⚠️ **Bridge integration**: sessions_spawn request 尚未被 OpenClaw bridge 真正消费
- ⚠️ **Execute mode**: 默认 `prepare_only=True` / `simulate_execution=True`
- ⚠️ **Auto-trigger**: receipt 生成后尚未自动触发 request 创建（需手动或上层编排）
- ❌ **Not full auto**: 不等于"全域全自动无人续跑"

### 7.3 Next Steps

1. **Bridge integration**: OpenClaw bridge 消费 sessions_spawn request
2. **Auto-trigger**: receipt 完成后自动创建 request
3. **Status update**: request emitted 后自动更新 close status
4. **More adapters**: channel / generic adapter demo

---

## 8. CLI Quick Reference

```bash
# ============ sessions_spawn_request ============

# 从 receipt 准备 request
python sessions_spawn_request.py prepare <receipt_id>

# 列出 requests
python sessions_spawn_request.py list [--status prepared] [--receipt <receipt_id>]

# 获取 request 详情
python sessions_spawn_request.py get <request_id>

# 获取 sessions_spawn 调用参数
python sessions_spawn_request.py call-params <request_id>

# ============ callback_auto_close ============

# 创建 auto-close（可选带 request_id）
python callback_auto_close.py create <receipt_id> [--request <request_id>]

# 列出 closes
python callback_auto_close.py list [--status closed] [--task <task_id>]

# 获取 close 详情
python callback_auto_close.py get <close_id>

# 通过 linkage 查找
python callback_auto_close.py find --receipt <receipt_id>
python callback_auto_close.py find --dispatch <dispatch_id>

# 查看闭环 summary
python callback_auto_close.py summary [--scenario <scenario>]

# ============ Full pipeline ============

# receipt → request → close
python callback_auto_close.py pipeline <receipt_id>
```

---

## 9. Summary

v6 推进 v5 的 artifact/receipt 闭环到：

1. **sessions_spawn-compatible request**: 可被 OpenClaw bridge 直接消费的 canonical request artifact
2. **callback auto-close bridge**: 闭环状态可查询的 canonical close artifact

关键特性：
- **Adapter-agnostic**: 通用 kernel，trading 仅作为首个消费者
- **Canonical artifacts**: 真实落盘，可被下游消费
- **Linkage integrity**: 完整链路，支持正向追踪和反向查询
- **Prepare-only default**: 默认生成 artifact，不真正调用 sessions_spawn（需上层 bridge 集成）

**当前成熟度**: v6 通用层已实现，尚需 OpenClaw bridge 集成才能真正调用 sessions_spawn。
