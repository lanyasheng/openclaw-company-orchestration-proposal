# 现成方案 Shortlist：Lobster vs Temporal vs LangGraph vs taskwatcher

---

## 快速对比

| 方案 | 优先级 | 类型 | 适合位置 | 关键判断 |
|------|--------|------|----------|----------|
| **Lobster** | P0/P1 | Thin orchestration | OpenClaw-native layer | 最优先评估的 typed macro engine |
| **Temporal** | P2+ | Durable execution | 关键高 SLA 流程 | 成熟但短期成本过高 |
| **LangGraph** | 按需 | Agent graph | Agent 内部子图 | checkpoint/HITL/reasoning |
| **taskwatcher** | 保留 | Watcher/reconciler | External async 任务 | **不是 backbone** |

---

## 1. Lobster（P0/P1 最优先）

### 是什么

GitHub: `openclaw/lobster`

OpenClaw-native typed local-first workflow shell / macro engine。

### 核心能力

- **Typed workflows**：类型安全的工作流定义
- **Local-first**：本地执行优先，低侵入
- **Macro engine**：macro-based composition，轻量编排
- **Subagent spawning**：原生支持 `sessions_spawn` 模式
- **Recovery semantics**：执行收据、幂等、恢复

### 为什么 P0/P1 优先

| 优势 | 说明 |
|------|------|
| OpenClaw-native | 与现有 `subagent`/`browser`/`message` 资产兼容 |
| 低侵入 | 不需要 worker/namespace 新基础设施 |
| 轻量 | 不是完整 DAG 平台，是 thin orchestration layer |
| 可快速验证 | 一周内可 POC，验证实际需求 |

### 适合场景

- 受限 workflow templates（chain/parallel/join）
- subagent/browser/message 的统一 thin layer
- P0/P1 快速落地，不引入过重基础设施

### 外部证据

- **GitHub**: `openclaw/lobster` — typed local-first workflow shell
- **X**: Lobster 与 deterministic workflows / orchestration / subagent spawning 强关联
- **Moltbook**: workflow engines / local-first / execution receipts 讨论支持

---

## 2. Temporal（P2+ 关键流程）

### 是什么

GitHub: `temporal-community/temporal-ai-agent`

业界最成熟的 durable workflow execution platform。

### 核心能力

- **Durable execution**：跨天/跨 crash 的持续执行
- **Timers/Signals**：超时、定时、信号机制
- **Retry/Compensation**：精细化重试和补偿策略
- **Audit/Recovery**：完整 history、可回放、可审计
- **Determinism**：确定性约束，版本化 workflow

### 为什么 P2+

| 代价 | 说明 |
|------|------|
| 基础设施成本 | worker/queue/namespace/运维体系 |
| 改造成本 | subagent/browser/message 需 activity 化 |
| 新复杂度 | determinism/versioning/history 方法论 |
| 迁移风险 | 全量迁移短期 ROI 不高 |

### 适合场景

- 跨天审批流程
- 强 SLA 要求的关键链路
- 需要 timer/signal/compensation 的复杂流程
- 强审计/回放需求

### 不适合场景

- 简单短任务
- 一次性 subagent 执行
- 轻量 browser/message 调用
- 纯 agent 内部 reasoning（给 LangGraph）

### 外部证据

- **GitHub**: `temporal-community/temporal-ai-agent` — Temporal 作为 agent orchestration backbone
- **X**: Temporal + durable execution / agent orchestration 被社区采用
- **Moltbook**: durable execution / state machines / recovery engineering 讨论

---

## 3. LangGraph（仅 Agent 内部）

### 是什么

LangChain 团队的 agent graph 编排框架。

### 核心能力

- **Graph-based**：节点-边图结构表达 agent 流程
- **Checkpoint**：状态保存与恢复
- **HITL (Human-in-the-loop)**：人工断点与介入
- **Tool routing**：工具调用链编排

### 为什么仅内部使用

| 限制 | 说明 |
|------|------|
| 认知编排 ≠ 执行编排 | 解决 agent reasoning，不解决公司级 durable execution |
| 跨 runtime 弱 | 不天然支持 subagent/browser/message 作为 activity |
| 幂等/审计弱 | checkpoint ≠ execution receipts / audit trail |
| 容易误用 | 把 agent 思考流错当成公司执行总线 |

### 适合场景

- 单 agent 内部复杂 reasoning graph
- 多步 tool routing / retrieval / reflection
- 需要 checkpoint/HITL 的 agent 子流程

### 不适合场景

- 公司级跨-runtime orchestration backbone
- subagent/browser/message 的统一编排层
- 强 SLA / 强审计 / 跨天流程

### 外部证据

- **GitHub**: LangGraph issues 聚焦 checkpoint/HITL/graph state
- **X**: LangGraph 被用于 agent reasoning，而非 durable workflow backbone
- **Moltbook**: 对 LangGraph 作为 backbone 的讨论较少，共识是认知编排

---

## 4. taskwatcher（External Watcher 定位）

### 是什么

OpenClaw 现有组件，负责消费外部任务状态。

### 核心能力

- **Poll/Callback**：轮询或回调外部任务状态
- **Consume status.json/milestones**：消费 subagent 状态文件
- **Reconcile**：状态对齐与补偿
- **Notify**：回原频道/线程通知

### 为什么不是 backbone

| watcher 实际 | backbone 需要 |
|-------------|--------------|
| 消费状态文件 | 持有 state-of-truth |
| 轮询/回调外部 | durable execution 语义 |
| script-first reconciler | deterministic replay |
| 局部真值消费 | 跨-runtime 统一 timeline |

**watcher 是「通知接收器」，不是「执行底座」**。state/receipt/idempotency 才是 backbone 核心。

### 正确位置

- External async 任务的 watcher/reconciler/callback adapter
- 消费 subagent/browser 状态变化
- 触发 callback / escalation
- **不替代 orchestration layer 的状态管理**

### 与 subagent 关系

```
subagent (执行主链)
    ↓ 产生状态
watcher (消费状态)
    ↓ callback
control plane (通知用户)
```

---

## 5. 方案选型决策矩阵

| 场景 | 推荐方案 | 理由 |
|------|----------|------|
| P0/P1 thin layer | **Lobster** | OpenClaw-native、低侵入、快速验证 |
| 跨天/强 SLA 流程 | **Temporal** | Durable execution、强审计、强恢复 |
| Agent 内部 reasoning | **LangGraph** | checkpoint/HITL/tool routing |
| External async callback | **taskwatcher** | 轮询/回调/通知，**不是 backbone** |
| 简单 chain/parallel | **Lobster** | 受限 templates 足够 |
| 复杂 DAG 动态图 | Temporal/LangGraph | 但需评估是否真的需要 |

---

## 6. 为什么第一步不应自研

| 自研成本 | 现成方案（Lobster/Temporal） |
|---------|---------------------------|
| scheduler/executor | Lobster/Temporal 已有 |
| state store | 复用现有或 Temporal |
| recovery/versioning | 需长期投入 | Temporal 成熟 |
| maintenance burden | 成为团队瓶颈 | 社区维护 |
| validation time | 无法快速验证需求 | 一周内 POC |

**结论**：先用现成方案验证需求，再决定是否自研。自研 DAG 平台是 P2+ 甚至 P3 的选项。

---

## 7. 外部证据汇总

| 来源 | 关键证据 | 支撑结论 |
|------|----------|----------|
| GitHub: `openclaw/lobster` | Typed local-first workflow shell | Lobster 是 OpenClaw-native candidate |
| GitHub: `temporal-community/temporal-ai-agent` | Temporal 用于 durable workflow backbone | Temporal 适合关键高 SLA 流程 |
| X: Lobster + orchestration | Lobster 与 deterministic workflows/orchestration 关联 | Lobster P0/P1 优先 |
| X: Temporal + durable execution | Temporal 被社区用于 durable execution | Temporal P2+ 关键流程 |
| X: task watcher | 搜索 `task watcher orchestration` 无显著结果 | watcher 不是主流 backbone |
| Moltbook | workflow engines/state machines/idempotency | durable/state/receipt 更关键 |

---

## 8. 最终 Shortlist 结论

1. **Lobster 第一优先**：P0/P1 评估 Lobster 作为 thin orchestration layer
2. **Temporal 择机**：P2+ 或关键高 SLA 流程才引入
3. **LangGraph 内部化**：只用于 agent 内部 reasoning，**不出现在公司级边界**
4. **watcher 收敛**：明确定位为 external async watcher/reconciler，**不作为 backbone 候选**
5. **不自研第一步**：先用现成方案验证，避免过早自研 DAG 平台
