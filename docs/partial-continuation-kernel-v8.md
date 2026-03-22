# Universal Partial-Completion Continuation Framework v8
## Real Execute Mode + Auto-Trigger Consumption

> **版本**: v8 (2026-03-22)
>
> **定位**: 通用 orchestration kernel capability，trading 仅作为首个消费者
>
> **核心**: Bridge consumer 支持真实执行 + request prepared 后自动触发消费

---

## 0. Executive Summary

v8 在 v7 的 bridge consumption layer 基础上，新增：

1. **Real Execute Mode**: `simulate_only=False` 时真正执行 sessions_spawn
2. **Auto-Trigger Consumption**: request prepared 后自动触发消费（带 dedupe/guard）
3. **状态扩展**: `prepared | consumed | executed | failed | blocked`
4. **技术债务收口**: 明确记录已知优化点，避免丢失

关键设计原则：
1. **Adapter-agnostic**: 不绑定 trading / channel / 任何特定场景
2. **Canonical artifacts**: 真实落盘，可被下游消费
3. **Guard / Dedupe**: 自动触发带防护，避免重复/误触发
4. **最小闭环**: 优先实现 trading happy path，不追求全域自动

---

## 1. What's New in v8

### 1.1 Execute Mode（新增）

**bridge_consumer.py** 新增 execute mode 支持：

```python
@dataclass
class BridgeConsumerPolicy:
    require_request_status: str = "prepared"
    prevent_duplicate: bool = True
    simulate_only: bool = True
    execute_mode: Literal["simulate", "execute", "dry_run"] = "simulate"  # V8 新增
    require_metadata_fields: List[str] = field(default_factory=lambda: ["dispatch_id", "spawn_id"])
    
    def is_execute_mode(self) -> bool:
        """检查是否为真实执行模式"""
        return self.execute_mode == "execute" and not self.simulate_only
```

**执行流程**:
```
consume request
    ↓
evaluate policy
    ↓
build execution envelope
    ↓
[IF execute_mode] → _execute_sessions_spawn() → ExecutionResult
    ↓
update consumer_status: consumed | executed | failed
    ↓
write artifact
```

**ExecutionResult**（V8 新增数据结构）:
```python
@dataclass
class ExecutionResult:
    executed: bool = False
    execute_time: Optional[str] = None
    execute_mode: str = "simulate"
    sessions_spawn_result: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    output: Optional[str] = None
```

**使用方式**:
```python
from bridge_consumer import BridgeConsumer, BridgeConsumerPolicy

# Execute mode policy
policy = BridgeConsumerPolicy(
    simulate_only=False,
    execute_mode="execute",
)

consumer = BridgeConsumer(policy)
artifact = consumer.consume(request)

# 检查结果
if artifact.consumer_status == "executed":
    print(f"Executed: {artifact.execution_result.session_id}")
    print(f"Output: {artifact.execution_result.output}")
```

---

### 1.2 Auto-Trigger Consumption（新增）

**sessions_spawn_request.py** 新增 auto-trigger 机制：

**核心函数**:
```python
def auto_trigger_consumption(
    request_id: str,
    consumer_policy: Optional[Any] = None,
) -> tuple[bool, str, Optional[str]]:
    """
    V8 新增：自动触发 consumption。
    
    Returns:
        (triggered, reason, consumed_id)
    """
```

**Auto-Trigger Guard**:
```python
def _should_auto_trigger(request: SessionsSpawnRequest) -> tuple[bool, str]:
    """
    评估是否应该自动触发 consumption。
    
    Checks:
    1. Auto-trigger enabled (config)
    2. Not already triggered (dedupe)
    3. Request status == "prepared"
    4. Scenario allowlist/denylist
    5. Manual approval required
    """
```

**配置管理**:
```python
def configure_auto_trigger(
    enabled: Optional[bool] = None,
    allowlist: Optional[List[str]] = None,
    denylist: Optional[List[str]] = None,
    require_manual_approval: Optional[bool] = None,
) -> Dict[str, Any]:
    """配置 auto-trigger"""
```

**CLI 命令**:
```bash
# 手动触发单个 request
python sessions_spawn_request.py auto-trigger <request_id>

# 配置 auto-trigger
python sessions_spawn_request.py auto-trigger-config --enable --no-manual-approval
python sessions_spawn_request.py auto-trigger-config --disable
python sessions_spawn_request.py auto-trigger-config --allowlist trading,channel

# 查看状态
python sessions_spawn_request.py auto-trigger-status
```

**状态查询**:
```python
def get_auto_trigger_status() -> Dict[str, Any]:
    """
    Returns:
        {
            "config": {...},
            "triggered_count": int,
            "pending_requests": [...],
        }
    """
```

---

### 1.3 状态扩展

v7 状态：`consumed | skipped | blocked | failed`

v8 状态：`prepared | consumed | executed | failed | blocked`

**状态转换**:
```
prepared → [policy eval] → consumed (simulate mode)
prepared → [policy eval + execute] → executed (execute mode)
prepared → [policy eval failed] → blocked
prepared → [execute error] → failed
```

---

### 1.4 技术债务收口

新增 `docs/technical-debt-2026-03-22.md`，收敛已知优化点：

**高优先级 (P0)**:
1. `trading_roundtable.py` 职责过大（建议拆分）
2. Continuation v1-v7 模块收口
3. `CURRENT_TRUTH.md` / `README.md` 去重瘦身
4. Deprecated / Legacy 路径清理

**中优先级 (P1)**:
5. Auto-trigger 配置管理
6. Execute mode 真实集成
7. 测试覆盖率提升

详见 `docs/technical-debt-2026-03-22.md`。

---

## 2. Architecture

### 2.1 Full Pipeline (V1 → V8)

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
V7/V8: bridge_consumer (consumed_id)
          ↓
          ├─→ [simulate mode] → consumed
          └─→ [execute mode] → executed
```

### 2.2 Auto-Trigger Flow

```
request prepared (V6)
       ↓
auto-trigger guard check
       ↓
       ├─→ blocked (already triggered)
       ├─→ blocked (not in allowlist)
       ├─→ blocked (manual approval required)
       └─→ auto-trigger approved
              ↓
       bridge_consumer.consume()
              ↓
              ├─→ consumed (simulate mode)
              └─→ executed (execute mode)
              ↓
       record auto-trigger index
```

### 2.3 Artifact Linkage

v8 维持 10-ID 链路完整性：

```
{
    "consumed_id": "consumed_abc123",
    "source_request_id": "req_xyz789",
    "source_receipt_id": "receipt_def456",
    "source_execution_id": "exec_ghi789",
    "source_spawn_id": "spawn_jkl012",
    "source_dispatch_id": "dispatch_mno345",
    "source_registration_id": "reg_pqr678",
    "source_task_id": "task_stu901",
    "consumer_status": "executed",  # V8 新增
    "execution_result": {            # V8 新增
        "executed": true,
        "execute_time": "2026-03-22T12:00:00",
        "execute_mode": "execute",
        "session_id": "session_xyz789",
        "output": "..."
    }
}
```

---

## 3. Usage

### 3.1 Execute Mode

```python
from bridge_consumer import BridgeConsumer, BridgeConsumerPolicy
from sessions_spawn_request import get_spawn_request

# 获取 request
request = get_spawn_request("req_xyz789")

# 配置 execute mode policy
policy = BridgeConsumerPolicy(
    simulate_only=False,
    execute_mode="execute",
    require_request_status="prepared",
    prevent_duplicate=True,
)

# 消费（执行）
consumer = BridgeConsumer(policy)
artifact = consumer.consume(request)

# 检查结果
print(f"Status: {artifact.consumer_status}")
print(f"Session ID: {artifact.execution_result.session_id}")
print(f"Output: {artifact.execution_result.output}")
```

### 3.2 Auto-Trigger

```bash
# 1. 启用 auto-trigger（去掉 manual approval）
python sessions_spawn_request.py auto-trigger-config \
    --enable \
    --no-manual-approval \
    --allowlist trading

# 2. 查看状态
python sessions_spawn_request.py auto-trigger-status

# 3. 手动触发单个 request（测试）
python sessions_spawn_request.py auto-trigger req_xyz789

# 4. 查看 consumed artifact
python bridge_consumer.py by-request req_xyz789
```

### 3.3 CLI Quick Reference

```bash
# Bridge Consumer (v7/v8)
python bridge_consumer.py consume <request_id>
python bridge_consumer.py list [--status <status>] [--scenario <scenario>]
python bridge_consumer.py get <consumed_id>
python bridge_consumer.py by-request <request_id>
python bridge_consumer.py summary [--scenario <scenario>]

# Sessions Spawn Request (v8 新增)
python sessions_spawn_request.py auto-trigger <request_id>
python sessions_spawn_request.py auto-trigger-config [options]
python sessions_spawn_request.py auto-trigger-status
```

---

## 4. Testing

### 4.1 Test Coverage

v8 测试覆盖：

1. **Execute Mode Happy Path**: execute mode 下成功执行
2. **Auto-Trigger Happy Path**: 配置正确时自动触发
3. **Duplicate Prevention**: 同一 request 不重复触发
4. **Blocked Scenarios**: 配置不符时不触发

### 4.2 Test Commands

```bash
# 运行 bridge_consumer 测试（包含 v8 扩展）
python3 -m pytest tests/orchestrator/test_bridge_consumer.py -v

# 运行 sessions_spawn_request 测试
python3 -m pytest tests/orchestrator/test_sessions_spawn_request.py -v

# 运行所有 orchestrator 测试
python3 -m pytest tests/orchestrator/ -v
```

---

## 5. Migration from v7

### 5.1 Breaking Changes

- **无**: v8 向后兼容 v7
- 默认 `simulate_only=True`，行为与 v7 一致
- 新增状态 `executed` 不影响现有 `consumed` 逻辑

### 5.2 Upgrade Steps

1. 更新代码到 v8
2. 运行测试确保向后兼容
3. 按需配置 auto-trigger
4. 按需启用 execute mode

---

## 6. Known Limitations

### 6.1 Execute Mode

- 当前 execute mode 仍为模拟执行（记录执行计划，不真正调用 OpenClaw API）
- 真实集成需在后续迭代完成（见 `technical-debt-2026-03-22.md` D6）

### 6.2 Auto-Trigger

- 配置使用本地 JSON 文件，缺少版本控制
- 多环境配置同步需手动处理
- 改进方案见 `technical-debt-2026-03-22.md` D5

---

## 7. Next Steps (v9+)

1. **D1**: 拆分 `trading_roundtable.py`（P0）
2. **D2**: Continuation 模块收口（P1）
3. **D6**: Execute mode 真实集成（P1）
4. **D7**: 测试覆盖率提升（P1）

详见 `docs/technical-debt-2026-03-22.md`。

---

**版本**: v8 (2026-03-22)
**维护者**: Zoe (CTO & Chief Orchestrator)
