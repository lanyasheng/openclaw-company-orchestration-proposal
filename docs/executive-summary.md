# 执行摘要 v2

## 一句话结论

**OpenClaw 公司级编排不应「第一步自研 DAG 平台」或「全盘替换为 Temporal/LangGraph」。推荐路线是「Thin Orchestration Layer + 受限 templates + 分层选型」：**

```
subagent（默认内部主链）
    ↓
Lobster（P0/P1 thin orchestration layer）
    ↓
Temporal（P2+ 关键高 SLA 流程）

LangGraph（仅 agent 内部）
taskwatcher（仅 external async watcher）
```

---

## 核心修正（v2 vs v1）

| 维度 | v1（旧口径） | v2（新真值） |
|------|-------------|-------------|
| **默认执行主链** | 模糊提及 ACP/subagent | **明确 `sessions_spawn(runtime="subagent")`** |
| **taskwatcher 位置** | 作为编排 backbone 候选 | **收敛为 external async watcher/reconciler**，不是 backbone |
| **Lobster** | 未纳入 shortlist | **P0/P1 最优先评估的 OpenClaw-native 方案** |
| **第一步建议** | 「OpenClaw Native+」增强 | **「Thin Orchestration Layer」**，不自研 DAG |
| **外部证据** | 仅 GitHub | **GitHub + X + Moltbook 全纳入** |

---

## 现成方案 Shortlist（按优先级）

| 方案 | 优先级 | 适合位置 | 关键判断 |
|------|--------|----------|----------|
| **Lobster** | P0/P1 | Thin orchestration layer | OpenClaw-native typed macro engine，local-first，低侵入 |
| **Temporal** | P2+ | Durable execution backbone | 跨天/强重试/强 SLA 流程，但短期成本过高 |
| **LangGraph** | 按需 | Agent 内部子图 | checkpoint/HITL/reasoning，**不是公司级 backbone** |
| **taskwatcher** | 保留 | External async watcher | 对外部任务的 callback/reconcile，**不是 backbone** |

---

## 为什么 taskwatcher 不能当 backbone

| watcher 实际能力 | backbone 需要的能力 |
|-----------------|-------------------|
| 轮询/回调外部任务 | durable state + execution receipts |
| 消费 status.json / milestones | idempotency + recovery semantics |
| script-first reconciler | deterministic replay + audit trail |
| 局部真值消费 | 跨-runtime 统一 timeline |

**结论**：watcher 是外部任务的「通知接收器」，不是公司级编排的「状态/执行底座」。state/receipt/idempotency 才是 backbone 核心。

---

## 为什么第一步不该自研 workflow engine

1. **工程成本高**：DAG 平台需要 scheduler、executor、state store、recovery、versioning
2. **维护负担重**：自研方案需要长期投入，容易成为瓶颈
3. **需求验证优先**：先用现成方案（Lobster/Temporal）验证实际需求，再决定是否需要自研
4. **OpenClaw 已有资产**：`subagent`、`taskwatcher`、`browser`、`message` 已经构成「thin layer」雏形，不需要重造

---

## Thin Orchestration Layer：P0 该做什么

### 该做（thin layer）

| 能力 | 说明 |
|------|------|
| **统一 task registry** | 记录谁在跑、什么状态、谁负责 |
| **受限 workflow templates** | chain / parallel / join / human-gate / failure-branch |
| **幂等 callback** | task_id + state + content_hash + target |
| **timeline/observability** | 跨-runtime 统一 audit trail |
| **adapter 层** | subagent/browser/message/cron 统一接入 |

### 不该做（避免过重）

| 能力 | 说明 |
|------|------|
| 通用 DAG 引擎 | 图编排、动态节点、复杂依赖解析 |
| 自研 workflow platform | worker pool、namespace、determinism 验证 |
| LangGraph backbone | 让 LangGraph 接管公司级执行总线 |
| Temporal 全迁 | 短期全量迁移，引入过高复杂度 |

---

## 受限 Workflow Templates（v2 新增）

第一步只支持以下受限模式，不做通用图引擎：

```
CHAIN:     A → B → C
PARALLEL:  A → [B, C] → D
JOIN:      [A, B] → C (等待全部完成)
HUMAN-GATE: A → [等待人工] → B
FAILURE-BRANCH: A → [成功:B | 失败:C]
```

**为什么受限？**
- 覆盖 80% 实际场景
- 实现简单，无需复杂图算法
- 易于测试、审计、恢复
- 避免过度设计

---

## Task Watcher / Subagent / ACP 职责边界（v2 明确）

```
┌─────────────────────────────────────────────────────────┐
│  Control Plane (OpenClaw main)                          │
│  - 用户入口、路由、权限、人审                            │
└─────────────────────────────────────────────────────────┘
                            ↓ sessions_spawn(runtime="subagent")
┌─────────────────────────────────────────────────────────┐
│  Execution Plane                                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │ subagent    │  │ browser     │  │ message/cron    │ │
│  │ (默认主链)   │  │ (外部操作)   │  │ (副作用通道)     │ │
│  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────┘
                            ↓ 状态变化
┌─────────────────────────────────────────────────────────┐
│  Watcher Layer (External)                               │
│  - taskwatcher: 消费状态、callback、reconcile            │
│  - 不是 backbone，只是 external async 通知层             │
└─────────────────────────────────────────────────────────┘
```

**关键边界**：
- **subagent**：默认内部长任务执行主链
- **taskwatcher**：外部异步任务的 watcher/callback，不持有 state-of-truth
- **ACP**：外部系统接入（CI/人审），走 session bridge，**不是默认内部主链**

---

## 一周内可落地路线图

### Day 1-2：明确真值
- [ ] 确认 `subagent` 为默认内部执行主链
- [ ] 更新文档删除 ACP 主链旧口径
- [ ] 收敛 `taskwatcher` 为 external watcher

### Day 3-5：评估 Lobster
- [ ] 阅读 `openclaw/lobster` README
- [ ] 评估 Lobster 作为 thin orchestration layer 的可行性
- [ ] 设计 Lobster → subagent/browser/message 的 adapter

### Week 1 结束：受限 templates
- [ ] 实现/评估 chain/parallel/join/human-gate/failure-branch
- [ ] 统一 task registry schema
- [ ] 幂等 callback 机制

---

## 外部证据来源

| 来源 | 证据 | 结论 |
|------|------|------|
| **GitHub** | `openclaw/lobster` | OpenClaw-native typed macro engine |
| **GitHub** | `temporal-community/temporal-ai-agent` | Temporal 作为 durable workflow backbone |
| **X** | Lobster + orchestration/subagent spawning | Lobster 与 deterministic workflows 强关联 |
| **X** | Temporal + durable execution/agent orchestration | Temporal 被社区用于 durable execution |
| **Moltbook** | workflow engines/state machines/idempotency | durable/state/receipt 比 watcher 更关键 |

---

## 最终建议（5 条内）

1. **Lobster 优先**：P0/P1 最优先评估 Lobster 作为 thin orchestration layer
2. **subagent 主链**：明确 `sessions_spawn(runtime="subagent")` 是默认内部执行主链
3. **watcher 收敛**：taskwatcher 只作为 external async watcher/reconciler，不是 backbone
4. **Temporal 择机**：P2+ 或关键高 SLA 流程才考虑 Temporal
5. **LangGraph 内部化**：只用于 agent 内部 reasoning/checkpoint/HITL

---

## 删除的旧口径

- ❌ "ACP 是主链之一" → ✅ "subagent 是默认内部主链"
- ❌ "taskwatcher 作为编排 backbone 候选" → ✅ "taskwatcher 是 external watcher"
- ❌ "第一步 OpenClaw Native+ 增强" → ✅ "第一步 Thin Orchestration Layer"
- ❌ "LangGraph 公司级总编排候选" → ✅ "LangGraph 仅 agent 内部"
