# Thin Orchestration Layer 设计

---

## 什么是 Thin Orchestration Layer

**不是**完整的 workflow engine / DAG 平台。

**是**轻量级控制层，负责：
- 统一 task registry（谁在跑、什么状态）
- 受限 workflow templates（覆盖 80% 场景）
- 幂等 callback / notification
- 跨-runtime 统一 timeline/audit

```
┌─────────────────────────────────────────┐
│  Control Plane (OpenClaw main)          │
│  - 用户入口、路由、权限、人审            │
└─────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────┐
│  Thin Orchestration Layer (NEW)         │
│  ┌──────────────────────────────────┐  │
│  │ Task Registry                    │  │
│  │ - task_id, state, owner          │  │
│  │ - evidence, timestamps           │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │ Workflow Templates (受限)         │  │
│  │ - chain, parallel, join          │  │
│  │ - human-gate, failure-branch     │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │ Adapter Layer                     │  │
│  │ - subagent, browser, message     │  │
│  │ - cron, external                 │  │
│  └──────────────────────────────────┘  │
└─────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────┐
│  Execution Plane                        │
│  - subagent (默认主链)                  │
│  - browser, message, cron               │
│  - Temporal (P2+ 关键流程)              │
│  - LangGraph (agent 内部)               │
└─────────────────────────────────────────┘
```

---

## P0 该做什么

| 能力 | 说明 | 优先级 |
|------|------|--------|
| **统一 task registry** | 记录 task_id、state、owner、runtime、evidence | P0 |
| **受限 templates** | chain/parallel/join/human-gate/failure-branch | P0 |
| **幂等 callback** | task_id + state + content_hash + target | P0 |
| **subagent adapter** | `sessions_spawn` 封装为 activity | P0 |
| **统一 timeline** | 跨-runtime 状态变化记录 | P0 |

## P0 不该做什么

| 能力 | 为什么不做 |
|------|-----------|
| 通用 DAG 引擎 | 过重，需求未验证 |
| 动态图节点 | 复杂度高，覆盖场景少 |
| 自研 workflow platform | 维护成本高，先用现成方案 |
| Temporal 全迁 | 短期成本过高 |
| LangGraph backbone | 不适合公司级 durable execution |

---

## 受限 Workflow Templates

**只支持 5 种模式，不做通用图引擎：**

### 1. CHAIN（顺序执行）

```
A → B → C
```

- 最简单，最常用
- 适合：编码 → 测试 → 部署

### 2. PARALLEL（并行执行）

```
    ┌→ B
A →─┤
    └→ C
     ↓
      D
```

- 多个任务并行执行
- 适合：多源数据采集、批量处理

### 3. JOIN（等待汇聚）

```
A ─┐
   ├──→ C
B ─┘
```

- 等待多个前置任务全部完成
- 适合：多依赖聚合、条件触发

### 4. HUMAN-GATE（人工关卡）

```
A → [等待人工确认] → B
```

- 需要人工审批/确认
- 适合：发布审批、关键决策

### 5. FAILURE-BRANCH（失败分支）

```
      ┌→ [成功] → B
A ────┤
      └→ [失败] → C → [重试或人工]
```

- 根据执行结果分支
- 适合：错误处理、降级策略

### 为什么受限？

| 优势 | 说明 |
|------|------|
| 覆盖 80% 场景 | 5 种模式足够大多数业务 |
| 实现简单 | 无需复杂图算法、调度器 |
| 易于测试 | 路径有限，可穷举验证 |
| 易于审计 | timeline 清晰，可回放 |
| 避免过度设计 | 按需扩展，不 premature abstraction |

---

## Task Registry Schema

```json
{
  "task_id": "tsk_20260319_xxx",
  "request_id": "req_xxx",
  "owner": "main|zoe|...",
  "runtime": "subagent|browser|message|temporal|...",
  "adapter": "subagent-run|browser-job|message-send|...",
  "current_state": "queued|running|waiting_human|retrying|completed|failed|timeout|cancelled|degraded",
  "terminal_state": "",
  "retry_count": 0,
  "retryable": true,
  "needs_human_input": false,
  "reply_channel": "discord|slack|...",
  "reply_to": "thread:...",
  "state_version": 1,
  "evidence": {
    "run_dir": "/path/to/run",
    "output_url": "...",
    "test_results": "..."
  },
  "timestamps": {
    "created": "2026-03-19T05:00:00Z",
    "started": "2026-03-19T05:00:10Z",
    "completed": "..."
  },
  "delivery": {
    "callback_dispatched": true,
    "callback_delivered": true,
    "idempotency_key": "task_id + state + hash"
  }
}
```

---

## Adapter Contract

每个 adapter 必须声明：

```json
{
  "name": "subagent-run",
  "can_retry": true,
  "idempotency_key": "task_id + activity_name",
  "source_of_truth": "run_dir|session_file|dom|api",
  "states": ["started", "heartbeat", "completed", "failed", "timeout"],
  "human_gate": ["login_required", "approval_required"],
  "timeout_policy": {
    "stall_threshold": "30m",
    "total_timeout": "4h"
  },
  "retry_policy": {
    "max_attempts": 3,
    "backoff": "exponential"
  }
}
```

### Adapter 列表

| Adapter | Runtime | Status |
|---------|---------|--------|
| subagent-run | subagent | P0 |
| browser-job | browser | P0 |
| message-send | message | P0 |
| cron-trigger | cron | P1 |
| temporal-workflow | Temporal | P2+ |

---

## 幂等 Callback 机制

### 幂等键设计

```
idempotency_key = sha256(task_id + current_state + content_hash + target)
```

### 为什么需要幂等

| 场景 | 风险 | 幂等保护 |
|------|------|----------|
| watcher 重复扫描 | 重复通知用户 | 同一 state 只 callback 一次 |
| network retry | 重复触发 action | content_hash 相同则忽略 |
| 状态回退 | 旧 state 误发 | state_version 检查 |

### Callback 流程

```
状态变化
    ↓
生成 idempotency_key
    ↓
检查是否已处理
    ├→ 已处理 → 跳过
    └→ 未处理 → callback
                    ↓
              记录 delivery
                    ↓
              确认收到 → 标记完成
```

---

## Timeline / Observability

### 统一 Event Model

```
TaskCreated
TaskPlanned
TaskDispatched
ActivityStarted
ActivityHeartbeat
MilestoneRaised
ExternalStateObserved
HumanSignalReceived
RetryScheduled
ValidationPassed
ValidationFailed
CallbackDispatched
CallbackDelivered
TaskCompleted
TaskFailed
TaskTimedOut
TaskCancelled
```

### Timeline 视图

```
时间轴 ────────────────────────────────────────>

[05:00:00] TaskCreated (subagent-run)
[05:00:01] TaskDispatched
[05:00:02] ActivityStarted
[05:05:00] MilestoneRaised (50%)
[05:10:00] ActivityHeartbeat
[05:15:00] MilestoneRaised (100%)
[05:15:01] ValidationPassed
[05:15:02] CallbackDispatched
[05:15:03] CallbackDelivered
[05:15:04] TaskCompleted
```

---

## Subagent 默认主链

### 明确真值

- **默认内部长任务执行主链 = `sessions_spawn(runtime="subagent")`**
- 不是旧 ACP 主链
- 不是 taskwatcher backbone

### 架构图

```
User Request
    ↓
Control Plane (main session)
    ↓ sessions_spawn(runtime="subagent")
┌─────────────────────┐
│ Subagent Runtime    │ ← 默认主链
│ - run dir           │
│ - profile           │
│ - milestone         │
│ - terminal semantics│
└─────────────────────┘
    ↓ 状态写入
Run Dir (status.json)
    ↓ 被消费
TaskWatcher (external)
    ↓ callback
User Notification
```

---

## Task Watcher 定位

### 明确：不是 backbone

| 特性 | Task Watcher | Orchestration Backbone |
|------|-------------|----------------------|
| 持有 state | ❌ 消费外部状态 | ✅ 是 state-of-truth |
| durable execution | ❌ 无 | ✅ 核心能力 |
| recovery | ❌ reconcile only | ✅ 完整回放 |
| audit trail | ❌ 局部 | ✅ 跨-runtime |

### 正确职责

- 消费 run dir / session file 状态变化
- 触发 callback / notification
- 执行 reconcile / escalation
- **不替代 registry 的状态管理**

---

## Lobster 集成设计

### Lobster 位置

```
Thin Orchestration Layer
    ┌─────────────────┐
    │ Lobster (候选)   │ ← typed macro engine
    │ - chain         │
    │ - parallel      │
    │ - join          │
    │ - human-gate    │
    │ - failure-branch│
    └─────────────────┘
            ↓
    Adapter Layer
            ↓
    Execution Plane
```

### 评估要点

1. Lobster 如何封装 `sessions_spawn`?
2. Lobster 如何集成 browser/message/cron?
3. Lobster 的 recovery/幂等机制?
4. Lobster vs 自研 thin layer 的对比?

---

## 一周内落地路线图

### Day 1-2：基线

- [ ] 确认 `subagent` 为默认主链
- [ ] 收敛 `taskwatcher` 为 external watcher
- [ ] 定义受限 templates（5 种）

### Day 3-4：Registry

- [ ] 设计 task registry schema
- [ ] 实现 subagent adapter
- [ ] 幂等 callback 机制

### Day 5-7：Integration

- [ ] browser/message adapter
- [ ] timeline 基线视图
- [ ] Lobster POC 评估

---

## 质量门

### P0 完成标准

- [ ] subagent 流程能在 registry 中追踪
- [ ] 重复 watcher 不会重复 callback
- [ ] 人工确认能进入 `waiting_human` 状态
- [ ] chain/parallel 模板能正常工作
- [ ] 幂等键可验证（重复内容不重复处理）

### 回退方案

- 新 layer 失败时，回退到原生 `sessions_spawn` + watcher
- 保留 feature flag 控制新旧路径
- 关键流程保留手动 fallback 机制
