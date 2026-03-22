# Universal Partial-Completion Continuation Framework v7
## Bridge Consumption of sessions_spawn Request

> **版本**: v7 (2026-03-22)
>
> **定位**: 通用 orchestration kernel capability，trading 仅作为首个消费者
>
> **核心**: Bridge consumer 消费 V6 生成的 sessions_spawn request，生成 execution envelope

---

## 0. Executive Summary

v7 推进 v6 的 request artifact 到：
- **Bridge consumer**（消费 sessions_spawn request）
- **Consumed artifact / execution envelope**（可执行的统一入口）
- **Status tracking**（consumed | skipped | blocked | failed）

关键设计原则：
1. **Adapter-agnostic**: 不绑定 trading / channel / 任何特定场景
2. **Canonical artifacts**: 真实落盘，可被下游消费
3. **Linkage integrity**: dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id
4. **Simulate-only default**: 默认生成 execution envelope，不真正调用 sessions_spawn（需上层 bridge 集成）

---

## 1. What's New in v7

### 1.1 bridge_consumer.py（新增）

**目标**: 消费 V6 生成的 sessions_spawn request，生成 canonical consumed artifact。

**核心字段**:
```python
{
    "consumed_version": "bridge_consumed_v1",
    "consumed_id": "consumed_abc123",
    "source_request_id": "req_xyz789",
    "source_receipt_id": "receipt_def456",
    "source_execution_id": "exec_ghi789",
    "source_spawn_id": "spawn_jkl012",
    "source_dispatch_id": "dispatch_mno345",
    "source_registration_id": "reg_pqr678",
    "source_task_id": "task_stu901",
    "consumer_status": "consumed",  # consumed | skipped | blocked | failed
    "consumer_reason": "Policy evaluation passed; request consumed",
    "consumer_time": "2026-03-22T12:00:00",
    "execution_envelope": {
        "sessions_spawn_params": {
            "runtime": "subagent",
            "cwd": "/path/to/workspace",
            "task": "Orchestration continuation for task task_stu901",
            "label": "orch-task_stu901",
            "metadata": {
                "dispatch_id": "dispatch_mno345",
                "spawn_id": "spawn_jkl012",
                "execution_id": "exec_ghi789",
                "receipt_id": "receipt_def456",
                "scenario": "generic",
                "orchestration_continuation": True
            }
        },
        "execution_context": {
            "request_id": "req_xyz789",
            "receipt_id": "receipt_def456",
            "execution_id": "exec_ghi789",
            "spawn_id": "spawn_jkl012",
            "dispatch_id": "dispatch_mno345",
            "registration_id": "reg_pqr678",
            "task_id": "task_stu901",
            "scenario": "generic",
            "owner": "test_owner"
        },
        "consume_mode": "simulate",  # simulate | execute
        "ready_for_dispatch": false
    },
    "dedupe_key": "consumed_dedupe:req_xyz789",
    "policy_evaluation": {...},
    "metadata": {...}
}
```

**Policy 检查**:
- `require_request_status`: 要求的 request status（默认 "prepared"）
- `prevent_duplicate`: 防止重复消费（默认 True）
- `simulate_only`: 仅模拟消费，不真正调用 sessions_spawn（默认 True）
- `require_metadata_fields`: 要求的 metadata 字段列表（默认 `["dispatch_id", "spawn_id"]`）

**使用方式**:
```bash
# 消费单个 request
python bridge_consumer.py consume <request_id>

# 列出 consumed artifacts
python bridge_consumer.py list [--status <status>] [--scenario <scenario>]

# 获取 consumed artifact 详情
python bridge_consumer.py get <consumed_id>

# 通过 request_id 查找
python bridge_consumer.py by-request <request_id>

# 查看消费 summary
python bridge_consumer.py summary [--scenario <scenario>]
```

### 1.2 Full Pipeline (V1 → V7)

完整链路现在包含 7 层：

```
V1: task_registration (registration_id)
       ↓
V2: auto_dispatch (dispatch_id)
       ↓
V3: spawn_closure (spawn_id)
       ↓
V4: spawn_execution (execution_id)
       ↓
V5: completion_receipt (receipt_id)
       ↓
V6: sessions_spawn_request (request_id)
       ↓
V7: bridge_consumer (consumed_id) ← 新增
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
                                      bridge_consumer                            (close artifact)
                                                    ↓
                                      (consumed artifact / execution envelope)
                                                    ↓
                                      [OpenClaw bridge 可执行]
```

### 2.2 Adapter-Agnostic Design

v7 的 bridge consumer 不绑定任何特定场景：

```python
# 通用 policy（不绑定 trading）
BridgeConsumerPolicy(
    require_request_status="prepared",
    prevent_duplicate=True,
    simulate_only=True,
    require_metadata_fields=["dispatch_id", "spawn_id"],
)

# 通用 consumed artifact（任何场景均可消费）
BridgeConsumedArtifact(
    consumer_status="consumed",
    execution_envelope={
        "sessions_spawn_params": {
            "metadata": {
                "scenario": "generic",  # 或 "trading_roundtable_phase1" / "channel_roundtable"
                "owner": "any_owner",
            }
        }
    }
)
```

### 2.3 Linkage Integrity

完整链路（10 个 ID）：
```
registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id
```

每个 artifact 都包含完整的 source linkage，支持：
- 正向追踪：从 registration 到 consumed
- 反向查询：从任意 ID 找到完整链路

---

## 3. Trading as First Consumer

Trading 场景是 v7 的**首个消费者/样例**，不是特化目标。

### 3.1 Trading Happy Path

```
trading task registered → auto-dispatch → spawn closure → spawn execution → completion receipt
                                                                                   ↓
                                                                 sessions_spawn_request (trading metadata)
                                                                                   ↓
                                                                 bridge_consumer (consumed)
                                                                                   ↓
                                                                 execution envelope ready for dispatch
```

### 3.2 No Trading-Only Fields

v7 不新增 trading 私有字段：
- `execution_envelope.sessions_spawn_params.metadata.scenario` = "trading_roundtable_phase1"（只是值不同，字段通用）
- `consumed_artifact.metadata.scenario` = "trading_roundtable_phase1"（只是值不同，字段通用）

所有字段都是通用的，任何场景都可以使用。

---

## 4. Integration Points

### 4.1 OpenClaw Bridge（待集成）

v7 生成的 `execution_envelope` 可被 OpenClaw bridge 直接执行：

```python
# 伪代码：OpenClaw bridge 执行 consumed artifact
from bridge_consumer import get_consumed_by_request

consumed = get_consumed_by_request("req_abc123")
if consumed.consumer_status == "consumed":
    envelope = consumed.execution_envelope
    params = envelope["sessions_spawn_params"]
    
    # 调用 sessions_spawn
    result = sessions_spawn(
        task=params["task"],
        runtime=params["runtime"],
        cwd=params["cwd"],
        label=params["label"],
        metadata=params["metadata"],
    )
    
    # 更新 consumed artifact（标记为 executed）
```

### 4.2 Operator/Main Query

operator/main 可以通过 linkage 查询消费状态：

```python
from bridge_consumer import get_consumed_by_request, build_consumption_summary

# 通过 request_id 查找 consumed
consumed = get_consumed_by_request(request_id="req_abc123")
if consumed:
    print(f"Consumer status: {consumed.consumer_status}")
    print(f"Execution envelope: {consumed.execution_envelope}")

# 查看整体 summary
summary = build_consumption_summary(scenario="trading_roundtable_phase1")
print(f"Total consumed: {summary['total_consumed']}")
print(f"By status: {summary['by_status']}")
```

---

## 5. Testing

### 5.1 Test Files

- `tests/orchestrator/test_bridge_consumer.py`: bridge_consumer 测试

### 5.2 Test Commands

```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

# bridge_consumer 测试
python3 -m pytest tests/orchestrator/test_bridge_consumer.py -v

# 组合测试（包括 v5/v6/v7）
python3 -m pytest tests/orchestrator/ -v -k "spawn or receipt or request or close or consumed"
```

### 5.3 Coverage

**bridge_consumer**:
- ✅ Happy path: consume prepared request
- ✅ Blocked: request status 不符不消费
- ✅ Duplicate: 同一 request 不重复消费
- ✅ Missing: request 不存在抛出错误
- ✅ Linkage: 完整 linkage 记录（10 个 ID）
- ✅ List/filter: 按 scenario / status 过滤
- ✅ Summary: 消费统计 summary

---

## 6. File Locations

### 6.1 Runtime Modules

```
runtime/orchestrator/
├── bridge_consumer.py         # v7: bridge consumption layer (NEW)
├── sessions_spawn_request.py  # v6.1: sessions_spawn-compatible request
├── callback_auto_close.py     # v6.2: callback auto-close bridge
├── spawn_execution.py         # v5.1: spawn execution artifact
├── completion_receipt.py      # v5.2: completion receipt artifact
├── spawn_closure.py           # v4: spawn closure artifact
├── auto_dispatch.py           # v3: auto-dispatch
├── task_registration.py       # v2: task registration
└── partial_continuation.py    # v1: partial continuation
```

### 6.2 Artifact Storage

```
~/.openclaw/shared-context/
├── bridge_consumed/           # v7: bridge consumed artifacts (NEW)
│   ├── consumed_abc123.json
│   └── consumed_index.json
├── spawn_requests/            # v6.1: sessions_spawn requests
│   ├── req_xyz789.json
│   └── request_index.json
├── callback_closes/           # v6.2: callback auto-closes
│   ├── close_def456.json
│   └── close_linkage_index.json
├── spawn_executions/          # v5.1: spawn executions
│   ├── exec_ghi789.json
│   └── execution_index.json
├── completion_receipts/       # v5.2: completion receipts
│   ├── receipt_jkl012.json
│   └── receipt_index.json
├── spawn_closures/            # v4: spawn closures
│   ├── spawn_mno345.json
│   └── spawn_index.json
└── dispatches/                # v3: dispatches
    ├── dispatch_pqr678.json
    └── dispatch_index.json
```

---

## 7. Maturity Boundary

### 7.1 What's Done

- ✅ **Canonical consumed artifact**: bridge-consumed artifact 真实落盘
- ✅ **Execution envelope**: 包含 sessions_spawn 参数 + 执行上下文
- ✅ **Full linkage**: registration → dispatch → spawn → execution → receipt → request → consumed
- ✅ **Dedupe prevention**: duplicate consumption prevention
- ✅ **Adapter-agnostic**: 通用 kernel，不绑定特定场景
- ✅ **Test coverage**: 14 测试覆盖 happy path / blocked / duplicate / linkage

### 7.2 What's Not Done

- ⚠️ **Execute mode**: 默认 `simulate_only=True`（生成 envelope，不真正调用 sessions_spawn）
- ⚠️ **Auto-trigger**: request 生成后尚未自动触发 consumption（需手动或上层编排）
- ⚠️ **Status update**: consumed 后尚未自动更新 close status
- ❌ **Not full auto**: 不等于"全域全自动无人续跑"

### 7.3 Next Steps

1. **Execute mode**: 支持 `simulate_only=False`，真正调用 sessions_spawn
2. **Auto-trigger**: request prepared 后自动触发 consumption
3. **Status update**: consumed 后自动更新 callback_auto_close status
4. **More adapters**: channel / generic adapter demo

---

## 8. CLI Quick Reference

```bash
# ============ bridge_consumer ============

# 消费单个 request
python bridge_consumer.py consume <request_id>

# 列出 consumed artifacts
python bridge_consumer.py list [--status consumed] [--scenario <scenario>]

# 获取 consumed artifact 详情
python bridge_consumer.py get <consumed_id>

# 通过 request_id 查找
python bridge_consumer.py by-request <request_id>

# 查看消费 summary
python bridge_consumer.py summary [--scenario <scenario>]

# ============ Full pipeline ============

# receipt → request → consumed
python bridge_consumer.py consume <request_id>

# 查看完整链路
python bridge_consumer.py get <consumed_id> | jq '.source_request_id, .source_receipt_id, ...'
```

---

## 9. Current Stage

v7 完成后的完整链路：

```
proposal -> registration -> auto-dispatch -> spawn closure -> spawn execution 
-> completion receipt -> sessions_spawn request -> bridge consumption (V7)
```

下一站（V8+）：
- **Auto-trigger**: receipt 完成后自动创建 request → 自动 consumption
- **Execute mode**: consumed 后真正调用 sessions_spawn
- **Status propagation**: consumed → close status update → full auto-close

---

## 10. Summary

v7 推进 v6 的 request artifact 到：

1. **Bridge consumer**: 消费 sessions_spawn request，生成 consumed artifact
2. **Execution envelope**: 包含 sessions_spawn 参数 + 执行上下文的统一入口
3. **Status tracking**: consumed | skipped | blocked | failed

关键特性：
- **Adapter-agnostic**: 通用 kernel，trading 仅作为首个消费者
- **Canonical artifacts**: 真实落盘，可被下游消费
- **Linkage integrity**: 完整链路（10 个 ID），支持正向追踪和反向查询
- **Simulate-only default**: 默认生成 envelope，不真正调用 sessions_spawn（需上层 bridge 集成）

**当前成熟度**: v7 bridge consumption layer 已实现，尚需 execute mode 集成才能真正调用 sessions_spawn。
