# OpenClaw Company Orchestration Proposal

Temporal vs LangGraph vs OpenClaw 原生编排的公司级架构方案。

## 这份仓库回答什么问题

如果 OpenClaw 要从“多个 session / subagent / ACP / watcher / cron / message / browser 的组合”升级为**可审计、可恢复、可扩展的公司级编排系统**，应该如何选型与分阶段落地？

## 最终建议

**不建议 LangGraph-first，也不建议 Temporal-first 全量替换。**

推荐路线：

> **P0 / P1：先做 OpenClaw Native+**
> - 统一状态机
> - Task Registry
> - Callback / Event Bus
> - 统一终态语义、重试、人工介入协议
>
> **P2：再选择性引入 Temporal**
> - 只用于跨天、强重试、强审计、强 SLA 的关键长事务
>
> **LangGraph：只放在 agent 内部子图**
> - 用于复杂推理 / 工具调用 / 人审断点
> - 不作为公司级总编排底座

## 为什么是这条路线

- **不是 LangGraph-first**：它更像认知编排，不是 durable execution 底座
- **不是 Temporal-first 全迁**：长期强，但短期改造和迁移成本过高
- **不是 pure native forever**：短期最省，但会撞上状态分散、补偿困难、统一 SLA 与审计能力不足的天花板
- **最佳路线是分阶段 Hybrid**：先把现有 OpenClaw 资产标准化，再把 Temporal 接到真正高价值的关键流程上

## 仓库结构

- `docs/executive-summary.md`：适合快速浏览的执行摘要
- `docs/openclaw-company-orchestration-proposal.md`：整合后的主方案文档
- `research/raw-draft-2026-03-19.md`：原始调研稿归档

## 建议优先看

1. `docs/executive-summary.md`
2. `docs/openclaw-company-orchestration-proposal.md`

## 当前决策口径

### 现在先做什么
- 统一 `orchestration_task` schema
- 统一 task state machine
- 统一 subagent / ACP / browser / cron / message 的状态接入方式
- 统一 callback / delivery 幂等键
- 先把观测、重试、人工介入、升级机制做成标准件

### 暂时不做什么
- 不直接把 LangGraph 升成公司级总编排器
- 不直接把 Temporal 作为唯一新底座强推全迁

## 适用场景

这份方案适合：
- OpenClaw 多 agent 公司级编排
- 编码 / 调研 / 审核 / 发布 / 通知 等异步链路
- 需要人审断点、补偿、回调、SLA、审计的执行系统
