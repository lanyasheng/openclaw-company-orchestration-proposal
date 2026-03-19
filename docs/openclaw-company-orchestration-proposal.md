# OpenClaw 公司级编排架构 Proposal v2

> 日期：2026-03-19
> 状态：v2（基于新真值重写）
> 更新：删除旧口径，明确 subagent 主链，收敛 taskwatcher，纳入 Lobster

---

## 1. 问题定义（v2 修正）

### 当前已明确的真值

| 事实 | 说明 | v1 旧口径 |
|------|------|-----------|
| **默认执行主链** | `sessions_spawn(runtime="subagent")` | 模糊提及 ACP/subagent |
| **taskwatcher** | external async watcher/reconciler | 作为编排 backbone 候选 |
| **Lobster** | P0/P1 最优先评估的 thin orchestration | 未纳入 shortlist |
| **外部证据** | GitHub + X + Moltbook 已验证 | 仅 GitHub |

### 当前核心问题

1. **状态分散**：subagent、browser、message、cron 各自为政
2. **重试口径不统一**：不同 runtime 的 retry/timeout 语义不一致
3. **人工介入缺协议**：有人审能力，但缺标准 HITL 状态机
4. **观测不连续**：缺单个公司级任务的完整 timeline
5. **编排层过重风险**：容易误判为需要「自研 DAG 平台」

### 关键认知转变

> **不是「选哪个框架替换 OpenClaw」，而是「在 OpenClaw 现有资产上，加一层 thin orchestration」。**

---

## 2. 方案比较结论（v2 更新）

### 2.1 选型结论

**推荐路线：Thin Orchestration Layer + 分层选型**

```
P0/P1: Lobster (最优先评估) → Thin orchestration layer
       └─ 受限 templates (chain/parallel/join/human-gate/failure-branch)

P2+:   Temporal (关键高 SLA 流程) → Durable execution backbone

LangGraph: 仅 agent 内部 (checkpoint/HITL/reasoning)

taskwatcher: 仅 external async watcher (不是 backbone)
```

### 2.2 为什么 Lobster 优先

| 优势 | 说明 |
|------|------|
| OpenClaw-native | 与现有 `subagent`/`browser`/`message` 兼容 |
| Typed macro engine | 类型安全，local-first |
| 低侵入 | 不需要 worker/namespace 新基础设施 |
| 快速验证 | 一周内可 POC |
| 外部证据 | X/Moltbook/GitHub 已验证与 orchestration 强关联 |

### 2.3 为什么不是 LangGraph-first

| LangGraph 适合 | LangGraph 不适合 |
|---------------|-----------------|
| 单 agent 认知流 | 公司级 durable execution |
| checkpoint/HITL | 跨 runtime 统一审计 |
| tool routing | 强 SLA 异步总线 |
| reasoning graph | subagent/browser 统一编排 |

**结论**：只做叶子层 agent 内部子图，不做公司级 backbone。

### 2.4 为什么不是 Temporal-first

| Temporal 适合 | Temporal 不适合（短期） |
|-------------|---------------------|
| 跨天/长事务 | 简单短任务 |
| 强 retry/timer | 一次性 subagent |
| 强审计/恢复 | 轻量 browser/message |
| 高 SLA 流程 | 全量迁移（成本过高） |

**结论**：P2+ 关键流程选择性接入，不替代控制平面。

### 2.5 为什么不是自研 DAG 平台

| 自研成本 | 风险 |
|---------|------|
| scheduler/executor | 长期维护负担 |
| versioning/recovery | 方法论成熟度 |
| state store | 运维复杂度 |
| 需求验证 | 未经验证的过早抽象 |

**结论**：先用现成方案（Lobster/Temporal）验证，再决定自研。

---

## 3. 推荐架构（v2）

```
┌──────────────────────────────────────────────────────────────┐
│  Control Plane (OpenClaw main)                               │
│  - 用户入口、线程/频道、权限、人审                            │
└──────────────────────────────────────────────────────────────┘
                              ↓ sessions_spawn(runtime="subagent")
┌──────────────────────────────────────────────────────────────┐
│  Thin Orchestration Layer (P0/P1)                            │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Lobster (P0 优先评估)                                   │ │
│  │ ┌─────────────────┐ ┌─────────────────┐              │ │
│  │ │ Task Registry   │ │ Workflow        │              │ │
│  │ │ - task_id       │ │ Templates       │              │ │
│  │ │ - state         │ │ (受限 5 种)      │              │ │
│  │ │ - evidence      │ │                 │              │ │
│  │ └─────────────────┘ └─────────────────┘              │ │
│  │ ┌────────────────────────────────────────────────────┐ │ │
│  │ │ Adapter Layer                                       │ │ │
│  │ │ subagent | browser | message | cron                 │ │ │
│  │ └────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Callback / Event Bus (幂等)                             │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Execution Plane                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │ subagent │ │ browser  │ │ message  │ │ cron     │      │
│  │ (主链)    │ │          │ │          │ │          │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Temporal (P2+ 关键流程)                                 │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Watcher Layer (External)                                    │
│  - taskwatcher: 消费状态、callback、reconcile                  │
│  - 不是 backbone，只是 external async 通知层                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. 分层定义

### 4.1 控制平面（保留 OpenClaw 原生）

负责：
- 用户入口与路由
- 会话/线程语义
- 权限与审批
- 人机交互
- 最终回执

### 4.2 Thin Orchestration Layer（P0 新增）

核心组件：
- **Task Registry**：统一 task schema、state machine
- **Lobster**：typed macro engine，受限 workflow templates
- **Adapter 层**：subagent/browser/message/cron 统一接入
- **Event Bus**：幂等 callback、delivery audit

### 4.3 执行平面

- **subagent**：默认内部长任务主链
- **browser/message/cron**：标准 activity adapter
- **Temporal**：P2+ 关键高 SLA 流程

### 4.4 Watcher 层（External）

- **taskwatcher**：消费状态变化、trigger callback、escalation
- **明确**：不是 backbone，只是 external async 通知层

---

## 5. 受限 Workflow Templates（v2 新增）

**P0 只支持 5 种受限模式，不做通用图引擎。**

| Template | 模式 | 示例 |
|----------|------|------|
| **CHAIN** | A → B → C | 编码 → 测试 → 部署 |
| **PARALLEL** | A → [B,C] → D | 多源数据采集 |
| **JOIN** | [A,B] → C | 多依赖聚合 |
| **HUMAN-GATE** | A → [人工] → B | 发布审批 |
| **FAILURE-BRANCH** | A → [成功:B/失败:C] | 错误处理 |

### 为什么受限？

- 覆盖 80% 实际场景
- 实现简单，无需复杂调度器
- 易于测试、审计、恢复
- 避免过度设计

---

## 6. 统一状态机

### 6.1 状态定义

```
created
  -> queued
  -> running
  -> waiting_external (等 ACP/browser/cron)
  -> waiting_human (等人审)
  -> retrying
  -> validating
  -> completed / failed / timeout / cancelled / degraded
```

### 6.2 终态语义

终态必须携带：
- `task_id`
- `owner`
- `runtime`
- `evidence` (日志、输出、测试报告)
- `report_path`
- `delivery_status`
- `next_action`

---

## 7. Task Watcher / Subagent / ACP 职责边界

### 7.1 明确真值

| 组件 | 职责 | 边界 |
|------|------|------|
| **subagent** | 默认内部执行主链 | 长任务走 `sessions_spawn` |
| **taskwatcher** | external async watcher | **不是 backbone**，只消费状态 |
| **ACP** | 外部系统接入 | CI/人审，走 session bridge |

### 7.2 架构图

```
Control Plane
    ↓
sessions_spawn(runtime="subagent")
    ↓
┌─────────────┐
│ subagent    │ ← 默认主链
│ (执行)       │
└─────────────┘
    ↓
Run Dir (status.json)
    ↓
┌─────────────┐
│ taskwatcher │ ← 消费状态（不是 backbone）
│ (callback)   │
└─────────────┘
    ↓
User Notification
```

### 7.3 为什么 taskwatcher 不是 backbone

| watcher 实际 | backbone 需要 |
|-------------|--------------|
| 消费外部状态 | 持有 state-of-truth |
| 轮询/回调 | durable execution |
| reconcile | deterministic replay |
| 局部真值 | 跨-runtime 统一 timeline |

---

## 8. 失败恢复与补偿

### 8.1 失败分类

- **可重试**：网络波动、外部服务偶发失败
- **需人工**：审批卡住、权限不足
- **不可恢复**：输入错误、配置缺失

### 8.2 恢复策略

| Runtime | 策略 |
|---------|------|
| subagent | profile/stall 语义 + retry count |
| ACP | session 文件超时 → timeout/waiting_human |
| browser | 登录失效 → waiting_human |
| message | 指数退避 + dead-letter |

### 8.3 幂等策略

```
幂等键 = task_id + state + content_hash + target
```

---

## 9. 质量门

### 9.1 P0 质量门

- [ ] 状态契约已冻结（schema/state/event）
- [ ] 幂等键可验证（重复不会重复 final）
- [ ] 端到端回放可验证（timeline 完整）
- [ ] 失败分类清晰（timeout/failed/cancelled/degraded）
- [ ] 人工断点可验证（approve/reject/revise/timeout）
- [ ] chain/parallel 模板可工作

### 9.2 上线质量门

| Gate | 要求 |
|------|------|
| Gate 0 | schema + adapter contract review 通过 |
| Gate 1 | shadow mode：只记录不 callback |
| Gate 2 | canary：仅 1 条流程真实投递 |
| Gate 3 | 增加到 10~20% 流量 |
| Gate 4 | 默认启用，保留 feature flag 回退 |

---

## 10. 路线图

### P0（1-2 周）：Thin Orchestration Layer 基线

目标：**不引入新基础设施，先统一状态与观测。**

交付：
1. 确认 `subagent` 为默认主链
2. 收敛 `taskwatcher` 为 external watcher
3. 评估 Lobster 作为 thin orchestration layer
4. `orchestration_task` schema v1
5. unified state machine v1
6. subagent / browser / message adapter
7. callback 幂等与 delivery audit
8. task timeline viewer 最小版

成功标准：
- subagent 流程能在 registry 中追踪
- 重复 watcher 不会重复 final
- chain/parallel 模板能工作

### P1（2-6 周）：完整 Thin Layer

目标：**Lobster 全面接入，受限 templates 完整。**

交付：
1. Lobster 全面接入 subagent/browser/message/cron
2. 受限 templates（5 种）完整实现
3. human-in-the-loop 标准协议
4. retry policy registry
5. dead-letter + escalation
6. company-level observability board

成功标准：
- 3 类以上 runtime 能统一追踪
- 失败分类与补偿策略标准化
- 人工介入 SLA 有明确定义

### P2+（关键高 SLA 流程）：Selective Temporal

目标：**只迁移真正值得迁移的流程。**

优先迁移：
- 跨天审批流程
- 需要 timer/signal/compensation 的流程
- 强审计、强恢复需求

不迁移：
- 简单短任务
- 一次性 subagent
- 轻量 browser/message
- 单 agent reasoning（给 LangGraph）

成功标准：
- 至少 1 条关键流程在 Temporal 跑通
- 不影响 OpenClaw 入口体验
- 有清晰 cutover/rollback runbook

---

## 11. 最终建议

### 应该做的

- 明确 `subagent` 为默认内部执行主链
- 评估 Lobster 作为 P0/P1 thin orchestration layer
- 受限 workflow templates（5 种）
- 统一 Task Registry + 状态机 + Event Bus
- 收敛 `taskwatcher` 为 external async watcher
- 只把关键高 SLA 流程接给 Temporal
- LangGraph 只用于 agent 内部子图

### 不应该做的

- 第一步自研 DAG 平台
- 把 `taskwatcher` 当作编排 backbone
- 让 LangGraph 接管公司级总线
- Temporal 一步到位全迁
- 通用图引擎（过早抽象）

---

## 12. 外部证据来源（v2 新增）

| 来源 | 关键证据 | 支撑结论 |
|------|----------|----------|
| **GitHub: openclaw/lobster** | Typed local-first workflow shell | Lobster 是 P0/P1 最优先候选 |
| **GitHub: temporal-community/temporal-ai-agent** | Temporal 用于 durable workflow backbone | Temporal P2+ 关键流程 |
| **X: Lobster + orchestration** | Lobster 与 deterministic workflows/orchestration/subagent spawning 强关联 | Lobster P0 优先 |
| **X: Temporal + durable execution** | Temporal 被社区用于 durable execution | Temporal P2+ |
| **X: task watcher** | 搜索无显著结果 | watcher 不是主流 backbone |
| **Moltbook** | workflow engines/state machines/execution receipts/idempotency | durable/state/receipt 比 watcher 更关键 |

---

## 13. 删除的旧口径

| 旧口径 | 新真值 |
|--------|--------|
| "ACP 是主链之一" | **subagent 是默认内部主链** |
| "taskwatcher 作为编排 backbone 候选" | **taskwatcher 是 external async watcher，不是 backbone** |
| "第一步 OpenClaw Native+ 增强" | **第一步 Thin Orchestration Layer，评估 Lobster** |
| "LangGraph 公司级总编排候选" | **LangGraph 仅 agent 内部** |
| "未考虑 Lobster" | **Lobster P0/P1 最优先** |
| "仅 GitHub 证据" | **GitHub + X + Moltbook 全纳入** |

---

## 14. 结论

> **OpenClaw 未来的最优架构，不是「自研 DAG 平台」，也不是「单框架替换」，而是「Thin Orchestration Layer + Lobster 优先 + Temporal 择机 + LangGraph 内部化 + taskwatcher 收敛」的分层方案。**
