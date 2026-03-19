# 架构分层说明：官方底座层 / 编排控制层 / 执行层 / 业务场景层 / 可选安全层

## 结论先行

**这套方案的关键不是“再选一个框架”，而是把不同职责拆到正确层级。**

如果层级不拆清楚，就会反复出现三类错误：
1. 把 watcher 误写成 backbone
2. 把插件误写成平台主线
3. 把局部 POC 误写成公司级能力

---

## 1. 分层总览

```text
业务场景层
  ↑ 使用 workflow engine，承接真实业务
编排控制层
  ↑ 统一控制协议、状态、模板、回执
执行层
  ↑ 真正执行任务的 runtime / adapter
官方底座层
  ↑ OpenClaw 原生能力 + Lobster 官方能力

可选安全层：横切于控制层与执行层之间
```

---

## 2. 官方底座层

### 定义

官方底座层 = **OpenClaw 原生能力 + Lobster 官方 workflow shell 能力**。

### 包含内容

| 类别 | 组件 |
|------|------|
| OpenClaw 原语 | session / tool / channel / plugin / message / browser / cron |
| 默认执行原语 | `sessions_spawn(runtime="subagent")` |
| 官方 workflow 壳 | Lobster 的 workflow / approval / invoke bridge |

### 不包含内容

- 公司级 task registry
- 公司级状态机
- 业务级 workflow 模板治理
- 业务线级策略、回退、审计口径

### 这一层的意义

它决定了：
- 我们不从零写 runtime
- 我们优先围绕已有官方能力做增量设计
- Lobster 被视为“可复用官方能力”，不是“我们所有编排语义的唯一来源”

---

## 3. 编排控制层

### 定义

编排控制层 = **公司自己的 workflow control plane**。

### 必须承担的职责

| 能力 | 为什么必须在这一层 |
|------|------------------|
| task registry | 需要统一 state-of-truth |
| state machine | 不同 runtime 不能各讲各的状态语言 |
| workflow templates | 不能让每条业务自己发明流程形态 |
| callback / outbox | 终态与投递必须分离 |
| timeline / observability | 需要跨 runtime 统一审计 |
| retry / escalation | 需要公司级一致策略 |

### 这一层不应该做的事

- 抢执行层的工作，自己去跑任务
- 变成一个重型通用 DAG 平台
- 强依赖某一个插件或某一条 POC 才成立

---

## 4. 执行层

### 定义

执行层 = **被控制层调度的具体执行单元**。

### 当前建议纳入的执行单元

| 执行单元 | 用途 | 当前地位 |
|----------|------|----------|
| subagent | 默认内部长任务 | 主链 |
| browser | 页面操作 / 抓取 / 交互 | 标准 activity |
| message | 对外通知 / 审批交互 | 标准 activity |
| cron | 触发器 | 标准 activity |
| ACP / external async | 外部系统 / CI / 审核接入 | 边缘接入 |
| Temporal worker | 高 SLA durable execution | P2 以后按需引入 |

### 必须强调的边界

- `taskwatcher` 不在执行层里充当 state-of-truth
- `subagent` 是执行主链，不是候选项
- ACP 不是默认内部执行主链

---

## 5. 业务场景层

### 定义

业务场景层 = **真正使用 workflow engine 的业务域**。

### 首个落地为什么必须是 `workspace-trading`

| 原因 | 价值 |
|------|------|
| 风险真实 | 能逼出 human-gate 与回退边界 |
| 流程完整 | 有盘前、盘中、盘后链路 |
| 结果可审计 | 适合验证 timeline / delivery / evidence |
| 自动化与人工混合 | 非常适合 workflow engine 验证 |

### 业务场景层的规则

- 先有真实业务，再讨论抽象扩展
- 每新增一个抽象，都要能回溯到 Trading 的真实需求
- 没有业务收益的抽象，不进 P0 / P1

---

## 6. 可选安全层

### 定义

可选安全层 = **覆盖控制层与执行层的横切治理能力**。

### 主要内容

- human-gate
- policy / allowlist
- env isolation
- audit / approval trail
- idempotency / outbox
- rollback / kill switch

### 为什么叫“可选”

因为不同业务风险等级不同：
- P0 先定义边界和插槽
- P1 对 Trading 默认开启必要治理
- P2 再考虑策略系统化与分级控制

---

## 7. 层间接口

### 官方底座层 → 编排控制层

输入：原生 runtime 能力与 Lobster 原语  
输出：统一 adapter contract 可消费的最小能力集

### 编排控制层 → 执行层

输入：workflow template / task registry / state transition  
输出：标准化 dispatch / callback / retry / audit

### 编排控制层 → 业务场景层

输入：可复用的 workflow 模板与控制协议  
输出：业务流程实例化

### 可选安全层 → 控制层 / 执行层

输入：策略、审批、审计要求  
输出：守门、隔离、幂等与回退能力

---

## 8. 当前最容易犯的架构错误

1. **把 Lobster 当成完整公司级 backbone**
2. **把 taskwatcher 当成 orchestration state-of-truth**
3. **把 human-gate 插件当成仓库主线**
4. **把执行问题和控制问题混在一起**
5. **不先绑定 `workspace-trading` 就继续抽象**

---

## 9. 最终口径

**官方底座层负责“有什么原语”；编排控制层负责“怎么统一管理 workflow”；执行层负责“谁来跑”；业务场景层负责“先在哪个真实业务落地”；可选安全层负责“在什么风险等级下加哪些护栏”。**
