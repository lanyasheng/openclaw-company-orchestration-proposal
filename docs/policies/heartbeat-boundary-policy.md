# Heartbeat Boundary Policy（2026-03-24）

## 结论先行

**heartbeat 是治理外环，不是 workflow owner。**

本 policy 明确 heartbeat 的能力边界，防止 heartbeat 越界接管 workflow 主链职责。核心原则：

> **heartbeat 只能发现异常、告警、催办、巡检；不能直接写 terminal truth、不能直接 dispatch 下一跳、不能直接接管 gate 决策。**

---

## 1. 背景与问题

### 1.1 为什么需要 heartbeat 边界

在 WS3 事故和后续 waiting integrity policy 中，我们明确了：

- waiting 必须是活跃绑定（active wait binding）
- heartbeat 只负责发现 `waiting + active=0` 等异常
- heartbeat 不能代替主链 owner 写业务终态

但在实际代码路径中，heartbeat / liveness / guardian 的职责边界仍然模糊，存在以下风险：

1. **heartbeat 可能越界写 terminal truth**：直接修改任务状态为 completed/failed
2. **heartbeat 可能越界 dispatch**：直接触发下一跳任务派发
3. **heartbeat 可能越界接管 gate**：代替 roundtable / decision maker 做 continuation 决策

本 policy 的目标是从架构上收口这些越界路径。

### 1.2 Heartbeat 的正规定位

从本 policy 起，heartbeat 的定位固定为：

> **heartbeat 是 observer / signaler / escalator，不是 actor / owner / decider。**

具体职责分工：

| 角色 | 职责 | heartbeat 是否能做 |
|------|------|-------------------|
| Observer（观察者） | 发现异常、收集证据 | ✅ 是，这是 heartbeat 的主责 |
| Signaler（信号发送者） | 发出告警、催办请求 | ✅ 是，这是 heartbeat 的主责 |
| Escalator（升级者） | 将异常升级到主链 owner | ✅ 是，这是 heartbeat 的主责 |
| Actor（执行者） | 直接写 terminal truth | ❌ 否，这是 workflow owner 的职责 |
| Owner（所有者） | 决定 continuation / closeout | ❌ 否，这是 roundtable / decision maker 的职责 |
| Decider（决策者） | 决定 dispatch 下一跳 | ❌ 否，这是 dispatch planner 的职责 |

---

## 2. Heartbeat 边界清单

### 2.1 允许的行为（Allow List）

heartbeat **可以**做以下事情：

| 编号 | 行为 | 说明 | 代码路径示例 |
|------|------|------|-------------|
| A1 | **Wake / Liveness 检查** | 检查任务/批次是否仍有活跃执行 | `waiting_guard.detect_waiting_task_anomaly()` |
| A2 | **巡检（Patrol）** | 定期扫描 waiting / running 任务，发现异常 | `waiting_guard.reconcile_batch_waiting_anomalies()` |
| A3 | **告警（Alert）** | 发现异常后发出告警信号 | `alerts/` 模块 |
| A4 | **催办（Nudge）** | 催促主链 owner 执行 closeout / continuation | `completion_ack_guard.py` |
| A5 | **收集证据** | 读取 status.json / callback-status.json / runner artifacts | `waiting_guard._probe_status_evidence()` |
| A6 | **标记 anomaly** | 将异常状态标记为 anomaly，等待主链处理 | `waiting_guard.detect_waiting_task_anomaly()` |
| A7 | **请求 reconcile** | 请求主链 owner 执行 reconcile / hard-close | `waiting_guard.reconcile_batch_waiting_anomalies()` |

### 2.2 禁止的行为（Deny List）

heartbeat **不可以**做以下事情：

| 编号 | 行为 | 为什么禁止 | 守卫方式 |
|------|------|-----------|---------|
| D1 | **直接写 terminal truth** | terminal truth 必须由业务主链（callback / closeout）写入，heartbeat 没有业务上下文 | 代码 guard：heartbeat 路径不得调用 `update_state(..., TaskState.COMPLETED/FAILED)` |
| D2 | **直接 dispatch 下一跳** | dispatch 决策需要完整的 packet / roundtable 上下文，heartbeat 只有观测数据 | 代码 guard：heartbeat 路径不得调用 `dispatch_planner.*` / `task_registration.*` |
| D3 | **直接接管 gate 决策** | gate 决策（PASS/FAIL/CONDITIONAL）需要业务逻辑判断，heartbeat 只能告警 | 代码 guard：heartbeat 路径不得修改 `packet.overall_gate` / `roundtable.conclusion` |
| D4 | **直接写 continuation contract** | continuation contract 是主链契约，必须由 roundtable / decision maker 生成 | 代码 guard：heartbeat 路径不得调用 `ContinuationContract.*` 写入操作 |
| D5 | **直接 closeout** | closeout 是业务终态收口，必须由 closeout owner 执行 | 代码 guard：heartbeat 路径不得调用 `closeout_generator.*` / `closeout_tracker.emit_closeout()` |
| D6 | **覆盖主链 owner 决策** | 主链 owner（trading / channel_roundtable）的决策优先级高于 heartbeat | 架构约束：heartbeat 只能 emit alert/nudge，不能覆盖 owner 状态 |

---

## 3. 代码侧守卫

### 3.1 守卫设计原则

1. **薄层可回退**：guard 以最小侵入方式实现，不做大爆炸改写
2. **显式边界**：heartbeat 相关代码路径必须清晰标识
3. **可配置开关**：紧急情况下可通过配置禁用 guard（用于调试/回退）

### 3.2 守卫实现位置

| 守卫点 | 文件 | 守卫内容 |
|--------|------|---------|
| G1 | `runtime/orchestrator/waiting_guard.py` | 确保 `detect_waiting_task_anomaly()` 只返回 anomaly 证据，不直接写状态 |
| G2 | `runtime/orchestrator/closeout_tracker.py` | 确保 `emit_closeout()` 只能由主链 owner 调用，heartbeat 路径无权调用 |
| G3 | `runtime/orchestrator/completion_ack_guard.py` | 确保 ack guard 只催办，不代替 owner 写终态 |
| G4 | `runtime/orchestrator/core/dispatch_planner.py` | 确保 dispatch 只能由主链触发，heartbeat 路径无权调用 |

### 3.3 守卫代码示例

```python
# waiting_guard.py: reconcile_batch_waiting_anomalies()
# 允许：检测异常 -> 返回 anomaly 列表 -> 由主链 owner 决定是否 hard-close
# 禁止：直接在 heartbeat 路径中 update_state()

def reconcile_batch_waiting_anomalies(
    *,
    batch_id: str,
    next_owner: str,      # 必须由主链传入，heartbeat 不自决
    next_step: str,       # 必须由主链传入，heartbeat 不自决
    artifact_hint: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hard-close obviously invalid waiting tasks inside a batch.
    
    HEARTBEAT BOUNDARY GUARD (P0-2 Batch 2):
    - This function only DETECTS anomalies and PREPARES closeout data
    - The actual state update is done by the caller (workflow owner)
    - Heartbeat path must NOT call update_state() directly
    """
    anomalies: List[Dict[str, Any]] = []
    for task in get_batch_tasks(batch_id):
        if str(task.get("state") or "") not in NON_TERMINAL_TASK_STATES:
            continue
        anomaly = detect_waiting_task_anomaly(task, artifact_hint=artifact_hint)
        if anomaly is None:
            continue
        # HEARTBEAT BOUNDARY: prepare closeout, but caller decides whether to apply
        closeout = {
            "stopped_because": anomaly["code"],
            "next_step": next_step,      # from owner, not from heartbeat
            "next_owner": next_owner,    # from owner, not from heartbeat
            "dispatch_readiness": "blocked",
        }
        # ... prepare result, but DO NOT call update_state() here
        anomalies.append({...})
    return anomalies  # Return to owner, owner decides
```

---

## 4. 测试覆盖

### 4.1 测试场景

| 测试编号 | 场景 | 预期结果 |
|---------|------|---------|
| T1 | heartbeat 检测到 waiting 异常 | 返回 anomaly 证据，不直接改状态 |
| T2 | heartbeat 尝试直接写 terminal | 被 guard 拦截，抛出异常或返回错误 |
| T3 | heartbeat 尝试直接 dispatch | 被 guard 拦截，抛出异常或返回错误 |
| T4 | 合法 heartbeat 行为（巡检/告警） | 不被误拦，正常执行 |
| T5 | 主链 owner 正常 closeout | 不被误拦，正常执行 |

### 4.2 测试文件

测试位于 `runtime/tests/orchestrator/test_heartbeat_boundary.py`

---

## 5. 与 Waiting Integrity Policy 的关系

本文是 `waiting-integrity-hard-close-policy-2026-03-21.md` 的补充：

- Waiting Integrity Policy 定义了 **waiting 的合法性约束**
- Heartbeat Boundary Policy 定义了 **heartbeat 的职责边界**

两者共同构成完整的 waiting / heartbeat 治理框架：

```
┌─────────────────────────────────────────────────────────┐
│                  Waiting Integrity                       │
│  - waiting 必须绑定可验证的活跃 waiter                    │
│  - 等待失真必须 hard-close                               │
│  - 依赖等级必须声明（best-effort/degraded/fatal）        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                  Heartbeat Boundary                      │
│  - heartbeat 只能发现异常、告警、催办                     │
│  - heartbeat 不能写 terminal truth / dispatch / gate     │
│  - heartbeat 是 observer，不是 owner                     │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Rollout

### 6.1 文档冻结（立即）

1. 本文成为 heartbeat 边界的正式口径
2. 后续 heartbeat / guardian / liveness 相关代码必须引用本文
3. 违反本文边界的行为视为架构违规

### 6.2 代码守卫（本批次）

1. 在 `waiting_guard.py` 中添加显式 guard 注释和断言
2. 在 `closeout_tracker.py` 中限制 emit_closeout 调用路径
3. 在 `dispatch_planner.py` 中限制 dispatch 调用路径
4. 添加测试覆盖 heartbeat 越界拦截

### 6.3 观测与治理（下一批）

1. 增加 heartbeat 越界告警指标
2. 定期审计 heartbeat 相关代码路径
3. 对违反边界的代码进行重构

---

## 7. 一句话口径

**heartbeat 是治理外环的 observer / signaler / escalator，不是 workflow 主链的 actor / owner / decider。**
