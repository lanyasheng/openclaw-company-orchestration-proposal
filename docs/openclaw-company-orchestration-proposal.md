# OpenClaw 公司级 Workflow Engine 总方案

> 日期：2026-03-19  
> 状态：v3，主线重置版  
> 目标：把 `openclaw-company-orchestration-proposal` 固化为 **workflow engine 方案仓**，而不是 human-gate / POC 主导仓。

---

## 0. 结论先行

### 最终判断

**OpenClaw 现阶段最优路线，不是自研通用 DAG 平台，也不是让 Temporal / LangGraph / taskwatcher 中任一方案单独接管全局，而是建立一套“五层架构 + 薄控制层 + 业务先落地”的 workflow engine 方案。**

核心决策如下：

1. **官方底座层**：以 `OpenClaw 原生能力 + Lobster 官方 workflow shell` 为基础资产
2. **编排控制层**：由我们定义公司级 `task registry / state machine / callback / timeline / retry / escalation` 协议
3. **执行层**：`subagent` 继续作为默认内部长任务主链，`browser / message / cron` 作为标准 activity，外部异步与高 SLA 任务按需扩展
4. **业务场景层**：先只服务 `workspace-trading`，用真实业务校验边界
5. **可选安全层**：human-gate、审计、环境隔离、幂等与回退作为横切能力，随业务风险逐步增强

### 这份方案要解决什么

它要解决的不是“再造一个框架”，而是：
- 如何把 OpenClaw 现有原生能力接成**公司级 workflow engine**
- 如何定义**统一控制面**，避免 runtime 各说各话
- 如何在**不重做引擎**的前提下，把真实业务流程跑通
- 如何明确**已验证 / 未验证 / 现在为什么选这条路**

---

## 1. 仓库主线重置

### 1.1 新定位

这个仓库以后是：

> **OpenClaw 公司级 workflow engine 架构、接口、路线图与验证边界的主方案仓。**

### 1.2 不再允许的主线偏移

以下内容仍可保留，但不能继续盖过仓库主线：
- human-gate 某个插件的局部实现细节
- 单条 POC 的实现报告
- 某一次 bridge simulator 的局部结论
- 把 watcher / callback adapter 误写成 backbone

### 1.3 新的仓库叙事顺序

以后评审这仓库时，应按这个顺序理解：

1. **总方案是什么**
2. **分层边界是什么**
3. **现在为什么选这条路**
4. **哪些结论已经有证据，哪些仍未验证**
5. **P0 / P1 / P2 怎么推进**
6. **验证资产在什么位置**

而不是先看 human-gate、再看 callback、再看某个 POC 文档拼主线。

---

## 2. 设计原则

### 2.1 四条原则

| 原则 | 含义 |
|------|------|
| **复用优先** | 先复用 OpenClaw 原生能力与 Lobster 官方能力，不轻易重造 |
| **控制层最小化** | 只补公司级统一协议，不上来做通用图平台 |
| **业务倒逼边界** | 先服务 `workspace-trading`，让真实流程定义需求 |
| **可回退** | 每一层都必须保留 feature flag、旁路和回退路径 |

### 2.2 明确非目标

当前阶段不做：
- 通用 DAG 编译器
- 任意动态图调度器
- 全量 Temporal 化
- LangGraph 公司级 backbone
- “一个引擎统一一切”的平台叙事

---

## 3. 五层架构

## 3.1 总图

```text
┌────────────────────────────────────────────────────────────┐
│  业务场景层                                                │
│  - workspace-trading（首个落地）                           │
│  - future: research / ops / content / service             │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  编排控制层                                                │
│  - workflow templates                                      │
│  - task registry / state machine                           │
│  - callback / outbox / delivery audit                      │
│  - timeline / observability                                │
│  - routing / retry / escalation                            │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  执行层                                                    │
│  - subagent（默认内部主链）                                │
│  - browser / message / cron                                │
│  - external async / ACP                                    │
│  - selective Temporal workers（P2 以后）                   │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  官方底座层                                                │
│  - OpenClaw session / channel / tool / plugin primitives   │
│  - Lobster workflow shell / approval / invoke bridge       │
└────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════╗
║  可选安全层（横切）                                        ║
║  - policy / human-gate / audit / env isolation            ║
║  - idempotency / rollback / allowlist / secrets boundary  ║
╚════════════════════════════════════════════════════════════╝
```

---

## 3.2 官方底座层：OpenClaw 原生能力 + Lobster 官方能力

### 这一层负责什么

这一层只回答一个问题：

> **官方已经给了我们哪些可靠原语，可以直接拿来构建 workflow engine？**

### 组成

| 组件 | 角色 | 现在的判断 |
|------|------|------------|
| OpenClaw session / tool / channel | 原生运行与调用底座 | 必须复用 |
| `sessions_spawn(runtime="subagent")` | 默认内部长任务执行原语 | 已是事实主链 |
| `browser / message / cron` | 原生 activity 原语 | 继续保留 |
| Lobster | 官方 workflow shell 候选 | 适合作为薄编排壳 |
| plugin system | 能力接入点 | 用于补业务插件，但不替代控制层 |

### 对 Lobster 的口径修正

Lobster 的定位应被写清楚：

- **它不是我们所有问题的终极引擎**
- **它也不是已经验证完备的公司级 backbone**
- **它是官方底座层中最值得复用的 workflow shell / macro engine**

当前适合承接的能力：
- 顺序 chain
- approval / resume
- OpenClaw tool invoke bridge
- 轻量、本地优先、低侵入的 workflow 外壳

当前不应提前承诺的能力：
- 真并发 parallel
- 真 join / barrier
- 原生 failure-branch
- 全局 durable execution

---

## 3.3 编排控制层：公司级 workflow engine 的真正主语

### 为什么必须单独有这一层

因为真正缺的不是“又一个执行器”，而是：
- 统一任务对象
- 统一状态机
- 统一 callback 语义
- 统一 timeline / 审计
- 统一人审 / 超时 / 回退口径

### 这一层的职责

| 能力 | 说明 |
|------|------|
| Task Registry | 记录 task_id、owner、runtime、evidence、delivery |
| State Machine | 统一 created / queued / running / waiting_human / completed 等状态 |
| Workflow Templates | 只提供受限模板，不提供任意图 |
| Callback Plane | terminal / sent / acked 分离，支持 outbox 与幂等 |
| Timeline | 跨 runtime 统一审计事件 |
| Routing & Retry | 统一重试、升级、失败分支与降级 |

### 控制层的核心对象

#### 1. task registry

最少必须统一以下字段：
- `task_id`
- `workflow_type`
- `scene`
- `runtime`
- `current_state`
- `terminal_state`
- `evidence`
- `callback_status`
- `next_action`
- `owner / assignee`
- `timestamps`

#### 2. 统一状态机

推荐基线：

```text
created
  -> queued
  -> running
  -> waiting_external
  -> waiting_human
  -> retrying
  -> validating
  -> completed / failed / timeout / cancelled / degraded
```

必须明确：
- **terminal state** 与 **callback delivery state** 不是一个字段
- **业务终态** 与 **通知终态** 必须分离
- **human-gate** 不是插件细节，而是控制层协议的一部分

#### 3. 受限 workflow templates

P0 / P1 只允许以下模板进入主方案：
- `CHAIN`
- `HUMAN_GATE`
- `FAILURE_BRANCH`
- `PARALLEL`（仅在真实能力确认后纳入）
- `JOIN`（仅在真实能力确认后纳入）

**注意**：现在不能把 `parallel / join` 写成已解决，只能写成“保留模板方向，待验证后纳入”。

---

## 3.4 执行层：真正跑任务的地方

### 这一层负责什么

执行层回答的是：

> **控制层发出的任务，具体由谁来跑？**

### 当前执行层分工

| 执行单元 | 角色 | 当前定位 |
|----------|------|----------|
| `subagent` | 默认内部长任务主链 | P0 / P1 核心 |
| `browser` | 页面交互 / 数据提取 / 需要渲染的操作 | 标准 activity |
| `message` | 对外消息副作用、通知、审批入口 | 标准 activity |
| `cron` | 定时触发、预定执行 | 标准 activity |
| ACP / external async | 外部系统接入、CI、人审等 | 边缘接入，不是默认主链 |
| Temporal workers | 高 SLA durable execution | P2 以后选择性引入 |

### 关于 `subagent`

这里必须明确记一句真值：

> **默认内部长任务执行主链 = `sessions_spawn(runtime="subagent")`。**

因此：
- `subagent` 不是备胎，是当前事实主链
- `taskwatcher` 只负责观察与回调，不持有 state-of-truth
- ACP 不是默认内部执行主链，只是外部接入手段之一

---

## 3.5 业务场景层：`workspace-trading` 作为首个落地

### 为什么必须先指定业务场景

如果不指定首个业务场景，这个仓库会重新滑回“概念正确、工程失焦”。

### 为什么选 `workspace-trading`

| 原因 | 说明 |
|------|------|
| 真实约束强 | 盘前、盘中、盘后流程都不是玩具场景 |
| 自带 human-gate | 风险与审批点天然存在 |
| 对审计要求高 | 需要 timeline、回执、终态区分 |
| 自动化边界清晰 | 很适合验证控制层与安全层 |

### 当前 live 真值补充（2026-03-20）

在不改这份主方案主线的前提下，runtime 侧已经出现两条最小真实接线：

- `trading_roundtable` continuation 已最小落地，但口径仍是 **safe semi-auto**
- `channel_roundtable` 通用适配器已落地，其他频道后续可按最小契约接入
- 当前 `Temporal vs LangGraph｜OpenClaw 公司级编排架构` 频道已成为第二个真实场景
- 当前频道已进入白名单默认 auto-dispatch：dispatch plan 默认 `triggered`
- 其他频道仍默认 `skipped`
- 回退仍简单：移出白名单、关闭 auto-dispatch，或退回手动 continuation

这里要特别强调：这仍然是**薄桥接线**，不是把 runtime 做了一轮大 refactor，也不是把公司级编排直接升级成默认全自动闭环。

### 首批建议落地流程

#### 流程 A：盘前 preflight

```text
触发 → 环境检查 → 数据源检查 → 风险门 → 人工确认（可选） → 开盘前回执
```

验证价值：
- chain
- evidence aggregation
- callback semantics
- human-gate

#### 流程 B：盘中风险守门

```text
策略信号 → 风险判断 → 等待人工确认 / 拒绝 / 超时降级 → 发出结果
```

验证价值：
- waiting_human
- timeout / reject / degrade
- delivery audit

#### 流程 C：盘后总结

```text
收集执行结果 → 生成总结 → 投递消息 → 等 ack → 入库审计
```

验证价值：
- callback sent / acked
- timeline
- evidence linking

---

## 3.6 可选安全层：横切而不是抢主线

### 为什么叫“可选安全层”

因为安全能力应该随着业务风险升级，而不是在 P0 阶段把所有路径都拖进重治理。

### 这一层覆盖什么

| 能力 | 说明 |
|------|------|
| Human Gate | 审批、拒绝、超时、撤回 |
| Policy | 哪些 workflow 允许自动跑、哪些必须人工过门 |
| Allowlist | 工具、目标频道、目标系统、命令边界 |
| Env Isolation | 不同执行路径的权限 / 密钥 / 环境隔离 |
| Audit | 谁发起、谁批准、谁执行、谁投递 |
| Outbox / Idempotency | 防止重复副作用 |
| Rollback | 出错后的停机、撤回、旁路与 feature flag |

### 当前原则

- P0 先定义边界与最小契约
- P1 再做默认化治理
- P2 才考虑策略系统、强审计与分级权限

---

## 4. 已验证什么 / 未验证什么 / 为什么现在选这条路

## 4.1 已验证什么

### A. Lobster 作为薄 workflow shell 有现实价值

已验证：
- 顺序链可行
- approval / resume 可行
- OpenClaw tool invoke bridge 可行

结论：
- 适合作为官方底座层的一部分
- 不足以单独承担公司级控制面

### B. `subagent` 是事实主链

已验证：
- 当前内部长任务真正依赖的是 `sessions_spawn(runtime="subagent")`
- `taskwatcher` 更像消费状态、做 callback 的 watcher / reconciler

结论：
- 控制层必须围绕 `subagent` 建模
- 不能再用“ACP / watcher / plugin”拼出主线叙事

### C. callback 语义需要独立建模

已验证：
- `terminal`、`callback sent`、`callback acked` 是不同阶段
- 如果不拆开，状态机会产生误导

结论：
- 编排控制层必须有 delivery/outbox 设计

### D. human-gate 与 failure-branch 已有最小验证资产

已验证：
- repo-local POC 与测试已能证明基本方向
- 但它们目前仍是验证资产，不是平台级事实能力

结论：
- 可以支撑方案选型
- 不能拿来替代真实业务闭环验证

---

## 4.2 未验证什么

| 主题 | 现在的真实状态 | 处理原则 |
|------|----------------|----------|
| Lobster → 真实 `subagent` 闭环 | 未真正打穿 | 不口头升级为已完成 |
| 真并发 / 真 join | 未证实 | 不纳入 P0 承诺 |
| 原生 failure-branch | 未证实 | 先走 adapter / 控制层策略 |
| Trading 通用 workflow engine 化 | `trading_roundtable` continuation 已最小落地，但仍是 safe semi-auto | 继续把 trading 从单点最小接线推进到更通用、可复用 workflow |
| channel_roundtable 跨频道 rollout | 通用适配器已落地；当前架构频道默认 `triggered`，其他频道仍 `skipped` | 继续保持 allowlist + 最小契约，不默认全频道放开 |
| 何时必须上 Temporal | 业务证据不足 | P2 再决策 |
| 安全层策略化 | 只有原则，无完整实施 | 分阶段补齐 |

---

## 4.3 为什么现在选这条路

原因非常具体：

1. **已有资产足够支撑“薄控制层 + 真实落地”**
   - OpenClaw 原生能力已足够跑起来
   - Lobster 足够承担轻量 workflow shell 角色

2. **现阶段最缺的是统一协议，不是重型 runtime**
   - 没有统一控制层，任何工具都会被各自实现方式撕裂

3. **业务验证窗口已经成熟**
   - `workspace-trading` 提供了真实且高价值的首个场景

4. **这条路风险最可控**
   - 既不自研重平台，也不被重型基础设施锁死
   - 每一步都有回退路径

---

## 5. 路线图

## 5.1 P0：重置主线，打通最小真实闭环

### 目标

**把仓库与方案叙事彻底收敛，并在 trading / channel 两类真实场景上继续把最小闭环做实。**

> 进度口径更新（2026-03-20）：`trading_roundtable` continuation 与当前架构频道 `channel_roundtable` 已完成最小 live 接线；但仍属于 thin-bridge、allowlist、safe semi-auto 阶段。

### 交付

1. README / 执行摘要 / 主方案文档重写
2. 明确五层架构与仓库结构
3. 冻结 task registry / state machine / callback semantics
4. 选定 Trading 首个流程并完成 dry-run / shadow-run
5. 明确 human-gate / watcher / POC 在文档中的下沉位置

### 成功标准

- 新人进入仓库，5 分钟内能看懂主线
- 不再把 human-gate / POC 误解为仓库主语
- Trading 有一条真实流程被纳入 workflow engine 视角

---

## 5.2 P1：控制层可复用，Trading Pilot 稳定化

### 目标

**让 workflow engine 方案具备复用性，而不是只有架构图。**

### 交付

1. `subagent / browser / message / cron` adapter contract
2. CHAIN / HUMAN_GATE / FAILURE_BRANCH 模板固化
3. parallel / join 只在真实验证后补入
4. timeline / observability / escalation / retry 基线
5. Trading pilot 稳定运行并保留回退开关

### 成功标准

- 至少一个业务场景可复用模板
- 状态、证据、回执、超时语义统一
- 控制层不依赖某一个插件或某一条 POC 才成立

---

## 5.3 P2：Selective Durability + 安全层增强

### 目标

**只把真正值得重型化的链路升级，不做全量平台翻修。**

### 交付

1. 识别跨天、强恢复、强审计流程
2. 只对这些流程评估引入 Temporal
3. 安全层从“可选能力”升级为“策略化能力”
4. 明确多业务场景复用边界

### 成功标准

- 重型基础设施只服务高价值链路
- 不破坏 OpenClaw 原有入口体验
- 所有升级都有 cutover / rollback runbook

---

## 6. 风险与回退

| 风险 | 表现 | 回退策略 |
|------|------|----------|
| Lobster 能力被高估 | 并发 / join / failure branch 不成立 | 控制层只承诺已验证能力，未验证能力不进默认模板 |
| 控制层做重 | 又滑向自研平台 | 严格限制模板与对象模型，先服务 Trading |
| watcher 重新抢主线 | 文档与实现再次混淆 backbone | 强制把 watcher 写成 execution sidecar / reconciler |
| business-first 不足 | 没有真实流程验证 | P0 必须绑定 Trading 首个流程 |
| 安全层拖慢推进 | P0 被全治理卡死 | 先边界、后策略、再默认化 |

---

## 7. 仓库文档结构（重构后）

```text
README.md

docs/
├─ executive-summary.md
├─ openclaw-company-orchestration-proposal.md
├─ architecture-layering.md
├─ validation-status.md
├─ roadmap.md
├─ supporting/
│  ├─ shortlist-existing-options.md
│  └─ thin-orchestration-layer.md
└─ validation/
   ├─ ... 历史 P0 审计 / 契约 / readiness / bridge 模拟文档
   └─ ... 仅作为验证资产，不再承担仓库主线
```

这次重构的目的只有一个：

> **让总方案、分层、验证、路线图各归其位。**

---

## 8. 最终建议

### 必须坚持的五件事

1. **主线只讲 workflow engine 总方案，不再讲 human-gate 主线**
2. **五层架构必须固定写法，不再混写 runtime、watcher、plugin 与 backbone**
3. **`workspace-trading` 必须成为首个落地，不允许继续纯抽象推进**
4. **所有“已验证”结论必须和“未验证”边界成对出现**
5. **P2 前不默认引入重型 runtime，也不自研通用 DAG 平台**

### 这份方案的最终一句话

**OpenClaw 的 workflow engine 应该长成“官方底座层可复用、公司控制层可统一、执行层可替换、业务场景层可验证、安全层可渐进增强”的五层体系；`workspace-trading` 是首个落地，human-gate 与零散 POC 则回到它们应在的验证位置。**
