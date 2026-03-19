# OpenClaw Company Orchestration Proposal v2

> Temporal vs LangGraph vs Lobster vs taskwatcher：公司级编排架构选型方案

---

## 一句话结论

**第一步不该自研 workflow engine，也不该直接用 Temporal/LangGraph 全盘替换。当前应走「Thin Orchestration Layer」路线：**

| 组件 | 位置 | 说明 |
|------|------|------|
| **subagent** | 默认内部执行主链 | 长任务默认走 `sessions_spawn(runtime="subagent")` |
| **Lobster** | P0/P1 优先评估 | OpenClaw-native thin orchestration candidate，typed local-first macro engine |
| **taskwatcher** | external watcher/reconciler | 对外部异步/轮询型任务的 callback adapter，**不是编排 backbone** |
| **Temporal** | P2+ 或关键高 SLA 流程 | 成熟的 durable execution backbone |
| **LangGraph** | agent 内部专用 | 适合 checkpoint/HITL/reasoning graph，**不是公司级 durable backbone** |

---

## 读法顺序

1. `docs/executive-summary.md` — 5 分钟快速浏览
2. `docs/shortlist-existing-options.md` — 现成方案对比（Lobster/Temporal/LangGraph/taskwatcher）
3. `docs/thin-orchestration-layer.md` — Thin Orchestration Layer 设计
4. `docs/openclaw-company-orchestration-proposal.md` — 完整方案（含路线图、质量门）

---

## 代码归属（新增）

- `plugins/human-gate-message/`：**human-gate 插件源码归这个 orchestration repo**
- runtime repo：只保留最小 glue（加载插件、接入 message/browser/UI、回写 verdict）
- `poc/`：repo-local validation / contract harness，不承载 runtime 主语义

---

## 当前推荐路线

```
P0（本周可落地）：
├── 明确 subagent 是默认内部执行主链
├── 评估 Lobster 作为 thin orchestration layer
├── 把 taskwatcher 收敛为 external async watcher
└── 受限 workflow templates（chain/parallel/join/human-gate/failure-branch）

P1（1-2 周）：
├── Lobster 接入现有 subagent/browser/message/cron
├── 统一 task registry + 幂等 callback
└── timeline/observability 基线

P2+（关键高 SLA 流程）：
├── Temporal 选择性接入跨天/强重试/强审计流程
└── LangGraph 仅用于 agent 内部 reasoning graph
```

---

## 为什么不是这些

| 误区 | 为什么不是 |
|------|-----------|
| **第一步自研 DAG 平台** | 工程成本过高，维护负担重；应先用现成方案验证需求 |
| **taskwatcher 当 backbone** | watcher 是轮询/回调组件，不是 durable execution 主链；state/receipt/idempotency 才是核心 |
| **LangGraph-first** | LangGraph 擅长 agent 内部 reasoning，不是公司级跨-runtime durable execution |
| **Temporal-first 全迁** | 短期改造成本过高，worker/namespace/determinism 引入大量新复杂度 |

---

## 关键真值（v2 修正）

1. **默认内部执行主链 = `sessions_spawn(runtime="subagent")`** — 不是旧 ACP 主链
2. **taskwatcher = external async watcher/reconciler** — 不应被视为公司级 orchestration backbone
3. **Lobster 是 P0/P1 最值得优先评估的 candidate** — OpenClaw-native typed macro engine
4. **X/Moltbook/GitHub 外部证据已纳入** — Lobster 与 deterministic workflows/orchestration 强关联

---

## 外部证据来源

- **GitHub**: `openclaw/lobster` — typed local-first workflow shell
- **GitHub**: `temporal-community/temporal-ai-agent` — Temporal 作为 durable workflow backbone
- **X**: Lobster 与 subagent spawning/recovery/orchestration 关联；Temporal 被用于 durable execution
- **Moltbook**: workflow engines、state machines、execution receipts、idempotency 讨论

---

## 状态

- **版本**: v2
- **日期**: 2026-03-19
- **更新**: 删除旧 ACP 主链口径，明确 Lobster 位置，收敛 taskwatcher 职责
