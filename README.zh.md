# OpenClaw Orchestration Control Plane

> 一个构建在 OpenClaw 之上的多 Agent 工作流控制层。
> 默认执行路径：**subagent**。兼容执行路径：**tmux**。
> 首个真实验证场景：**trading continuation**。

## 语言

- English: [`README.md`](README.md)
- 中文：`README.zh.md`

---

## 这个仓库是什么

这个仓库要回答的不是“模型能不能回答问题”，而是一个更偏系统的问题：

> **当一个任务做完一跳之后，系统怎么知道后面该继续做什么，并且能稳定推进下去？**

这个仓库的定位是：
- 以 **OpenClaw** 为运行时基础，
- 在其上补一层清晰、薄但明确的 **workflow control plane**，
- 把 dispatch、callback、continuation、execution 这些能力做成显式 contract，
- 先在真实业务场景里验证，
- 再决定哪些部分值得进一步重型化。

它不是 prompt 集合，也不是单个 demo。
它是一个真实的工程仓库，里面已经包含：
- orchestration contract
- continuation / handoff / registration
- callback / receipt / ack 机制
- dispatch planning
- execution handoff
- real `sessions_spawn` integration
- subagent / tmux 双轨执行策略

---

## 这个仓库到底解决什么问题

它解决的是这一类问题：

> **在多 agent / 多执行器 / 多轮回调的系统里，怎么让任务做完一轮后，后面的事情继续正确推进，而不是做完就停。**

典型问题包括：
- 一个任务结束了，但没人知道谁拥有下一步
- 多个子任务都回来了，但没有 clean fan-in 点
- 系统能生成计划，却不能安全地自动派发下一步
- callback 发出去了，但没有正确回到父会话或用户可见频道
- owner 和 executor 混在一起，导致角色边界混乱
- 系统不断叠脚本，却没有稳定的 control plane

所以这个仓库的核心不是“再做一个 agent runner”，而是把下面这些事情变成一等对象：
- **怎么继续**
- **怎么注册**
- **怎么判断能不能继续**
- **怎么派发**
- **怎么回流**
- **怎么在不丢真值的情况下推进下一步**

这也是为什么核心对象不是只有 prompt 和 runner，而是：
- continuation contract
- handoff schema
- registration / readiness
- dispatch plan
- bridge consumption
- execution request
- receipt / ack separation

---

## 为什么它不只是 harness engineering

harness engineering 确实是这个仓库的一部分，但**不是整个仓库的全部**。

### harness engineering 属于执行层
这一层关心的是：
- Claude Code 怎么被调用
- subagent 怎么拉起
- tmux 怎么作为兼容路径继续可用
- execution artifact 怎么落盘
- 长任务怎么保持可观测

### 这个仓库还做了更上层的事情
这个仓库还在做 **workflow control-plane engineering**：
- 任务在执行前怎么被建模
- owner 和 executor 怎么解耦
- fan-out / fan-in 怎么表达
- continuation 什么时候继续，什么时候停在 gate
- callback / receipt / ack 怎么分离
- 一批任务回来后，下一批怎么继续触发

一句话说：

> **harness engineering 解决的是“这个任务怎么跑”。**
>
> **这个仓库还解决“任务开始分叉、回流、交接之后，整个 workflow 怎么继续正确推进”。**

所以更准确的定位是：
- **它首先是 control-plane engineering**
- **execution harness 只是它的执行层组成部分之一**

---

## 它是怎么工作的

### 1）分层：控制面在上，执行面在下

```text
┌──────────────────────────────────────────────┐
│ 业务场景层                                   │
│ trading / channel / 未来其他场景             │
└──────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ 控制面                                       │
│ contract / planning / registration           │
│ readiness / callback / dispatch / continuation │
└──────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ 执行层                                       │
│ subagent / Claude Code / tmux / browser      │
└──────────────────────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────┐
│ OpenClaw runtime 基础层                      │
│ sessions / tools / hooks / channels / messaging │
└──────────────────────────────────────────────┘
```

关键点是：
- **控制面** 决定下一步怎么走
- **执行层** 真正去跑
- OpenClaw 提供原始运行时能力

### 2）单任务 continuation 主链

```text
request
  ↓
planning artifact
  ↓
handoff contract
  ↓
registration
  ↓
readiness + safety_gates + truth_anchor
  ↓
dispatch decision
  ├─ skipped / blocked / wait_at_gate
  └─ triggered
       ↓
execution request
       ↓
real execution (subagent / Claude Code / tmux)
       ↓
completion receipt
       ↓
next decision
```

核心原则：
**一个任务不是在执行停下时结束，而是在“下一步状态被明确表达”之后才真正收口。**

### 3）批量任务怎么收回再推进下一批

```text
parent task
  ↓
fan-out plan
  ├─ child A
  ├─ child B
  └─ child C

child receipts return
  ├─ A = done
  ├─ B = blocked
  └─ C = done

fan-in aggregation
  ↓
aggregate readiness / blockers / ownership
  ↓
next batch decision
  ├─ trigger next batch
  ├─ stop at gate
  └─ request human/business decision
```

这里真正重要的不是“能不能并发”，而是：
**收回时有没有一个可信的 fan-in 点来判断下一批是否该继续。**

### 4）owner 和 executor 分开

```text
owner      = 业务归属 / 判断 / 验收
executor   = 真正执行的人或执行器

例子：
- owner=trading, executor=claude_code
- owner=main, executor=subagent
- owner=content, executor=tmux
```

这也是为什么 coding lane 可以默认走 Claude Code，而不要求业务角色 agent 自己扛执行。

### 5）contract 里到底装了什么

一份 contract 里通常会包含：
- entry context
- adapter / scenario
- owner
- executor / execution_profile
- continuation fields（`stopped_because` / `next_step` / `next_owner`）
- readiness / safety_gates / truth_anchor
- handoff / registration / execution intent

这保证系统不是“口头答应继续”，而是能真的落出一个下一步可消费的对象。

---

## 为什么不直接套现有框架

这个仓库不是因为“没看过现成框架”才自己做，而是因为问题不只在单个 agent 执行层。

实际要解决的还包括：
- 场景路由
- business ownership
- fan-out / fan-in
- continuation gating
- callback / receipt / ack 分离
- 用户可见闭环和内部状态真值的一致

### 框架边界总结

| 路线 | 借鉴什么 | 为什么不直接拿来当 backbone |
|---|---|---|
| **OpenClaw native** | sessions / hooks / messaging / runtime primitives | 这是基础层，不是要替换的对象 |
| **Temporal** | durable workflow、lifecycle、retry 思维 | 当前阶段太重，不适合直接当默认 backbone |
| **LangGraph** | graph transition、组合式 reasoning flow | 更适合作叶子层，不适合作公司级 control plane |
| **DeepAgents** | execution profile、delegation、context hygiene | 更适合执行层，不足以承担完整 control plane |
| **OpenSWE / SWE-agent** | issue-to-patch lane、execution envelope | 更适合作 coding lane，而不是全局 orchestration backbone |
| **tmux orchestration** | 可观测性、可介入性 | 适合兼容路径，不适合继续做默认主路径 |

### 实际设计选择

所以我们真正的选择是：
- 用 **OpenClaw** 做 runtime foundation
- 在这个仓库里保留一层清晰的 **control plane**
- 把 **subagent / Claude Code / tmux** 看成执行器选择
- 只在真正有价值的局部引入更重的框架

因此，最准确的理解是：

> **这是一个 execution-aware orchestration control plane，而不是某个框架的 wrapper。**

---

## 我们当前在做什么

当前仓库已经具备：
- continuation contract
- planning handoff schema
- registration / readiness tracking
- bridge consumer auto-trigger decision
- execution request generation
- real `sessions_spawn` integration
- dual-track backend：
  - **subagent** 作为默认路径
  - **tmux** 作为兼容路径
- owner / executor 解耦
- coding lane 默认 Claude Code

换句话说，这个仓库不再只是一个 proposal，而是已经有：
- 真实 trading continuation 验证
- 通用 channel 接入入口
- callback / dispatch / execution 的真实主链

---

## 它能带来什么

如果你在做 agent workflow，这个仓库真正带来的价值是：

1. **把“后续怎么继续”变成一等问题**
2. **把 owner / executor / callback / receipt / dispatch 分开**
3. **在不马上引入重型引擎的情况下，先获得一条可靠主链**
4. **用真实场景（trading）而不是纸面 POC 来验证**
5. **在迁移 forward 的同时保留 tmux 兼容路径**

---

## 它借鉴了什么

### OpenClaw native runtime
这是基础层，仓库直接建立在：
- sessions
- tools
- callbacks
- subagents
- messaging
- plugin hooks
之上。

### Temporal
借鉴 durable workflow、retry、lifecycle 这类思路，
但**没有**把 Temporal 作为当前 backbone。

### LangGraph
借鉴 graph-shaped control flow 和 node transition 的思路，
但它只适合叶子层，不适合直接拿来当公司级 control plane。

### Lobster / workflow-shell 风格工具
借鉴 approval boundary、thin shell、invoke bridge、显式 contract 的思路。

### DeepAgents
借鉴：
- coding-heavy execution profile
- orchestration policy 和 leaf execution 的分离
- 长任务可观测性
- 在不上重型基础设施前，先把执行面做稳

但它不是这个仓库的 orchestration backbone。

### OpenSWE / SWE-agent 路线
借鉴：
- issue-to-patch lane
- engineering-task packaging
- reproducible execution envelope

但它们更适合叶子执行层，不适合承担整个 control plane。

---

## 它不是什么

- 不是 generic DAG 平台
- 不是 OpenClaw 替代品
- 不是 LangGraph wrapper
- 不是 Temporal 部署模板
- 不是 DeepAgents fork
- 不是 OpenSWE / SWE-agent 的替代品
- 不是单纯 trading bot repo
- 也不再是一堆孤立 POC

更准确地说：

> **这是一个构建在 OpenClaw 之上的、可复用的 workflow control-plane，先在 trading continuation 上验证，但设计目标保持通用。**

---

## 当前状态

### 已确认
- trading continuation 已进入真实执行路径
- control-plane 主链已打通
- subagent 是默认路径
- tmux 仍是兼容路径
- 过时 docs / POC / stale tests 已清理
- 仓库已达到对外开源可读状态

### 当前 backend 策略
- **默认**：subagent
- **兼容**：tmux
- **新开发**：优先 subagent
- **交互/可观测场景**：tmux 仍可用

### 当前成熟度
一个准确的描述是：

> **thin bridge / explicit contracts / safe semi-auto / production-validated on one real scenario**

它已经不只是方案稿，但也还没有重到可以叫“通用 workflow 平台”。

---

## 仓库结构

```text
openclaw-company-orchestration-proposal/
├── README.md
├── README.zh.md
├── docs/
├── runtime/
├── tests/
├── archive/
└── scripts/
```

### docs/
阅读入口：
- current truth
- architecture
- migration / retirement
- release materials
- batch summaries

### runtime/
实现真值：
- contracts
- continuation handling
- dispatch planning
- bridge consumer
- sessions spawn integration
- backend strategy

### tests/
行为真值：
- 核心行为由测试证明，而不只是文案说明

### archive/
历史资料，仅供参考，不是主路径

---

## 从哪里开始

### 想快速了解
- [`docs/executive-summary.md`](docs/executive-summary.md)
- [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md)

### 想理解架构
- [`docs/architecture-layering.md`](docs/architecture-layering.md)

### 想看发布材料
- [`docs/release/open-source-release-kit.md`](docs/release/open-source-release-kit.md)

### 想看迁移和保留边界
- [`docs/migration/migration-retirement-plan.md`](docs/migration/migration-retirement-plan.md)
- [`docs/technical-debt/technical-debt-2026-03-22.md`](docs/technical-debt/technical-debt-2026-03-22.md)

---

## 一句话记住它

> **这是一个构建在 OpenClaw 之上的工作流控制层：默认执行走 subagent，兼容保留 tmux，trading 是第一个真实验证场景。**
