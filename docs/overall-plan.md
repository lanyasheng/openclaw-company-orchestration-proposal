# 整体计划（2026-03-21）

> 用途：给 proposal repo 一个**统一阅读入口**，把“当前真值、下一阶段计划、明确边界”放在一页里。
>
> 注意：这个 repo 是**架构方案仓 / 阅读入口**，不是 runtime 真代码仓；runtime 真接线与 live 行为仍以 OpenClaw 主仓和相关运行仓为准。

---

## 1. 当前真值

### 1.1 已经定下来的口径

1. **gstack-style planning 已作为全局默认 planning method 落地。**
   默认顺序是：`problem reframing -> scope/product review -> engineering review -> execution/test plan`。
   这解决的是“先想清楚再开跑”，不是“把 gstack 升成 control plane”。

2. **TEAM_RULES 已 codify planning default 与 heartbeat boundary。**
   当前默认已经不是“想到就直接循环”，而是：
   - 非 trivial 任务先出 planning artifact；
   - 长任务/编码任务走 subagent 主链；
   - heartbeat 只做 wake / liveness / 巡检 / 催办 / 告警，不做 terminal state 或 next dispatch。

3. **外部框架策略已经收口。**
   - **OpenClaw 持有 control plane**：入口、`sessions_spawn`、launch/completion hook、callback bridge、scenario adapter、watcher/reconcile 边界、heartbeat 治理边界，都继续由 OpenClaw 持有。
   - **外部框架只进叶子层 / benchmark / 局部方法层**：DeepAgents、SWE-agent、LangGraph、Temporal 都不能替代公司级 orchestration 主链。

4. **当前 live 真值仍然是 thin bridge / allowlist / safe semi-auto。**
   - `channel_roundtable` 与 `trading_roundtable` 已证明 continuation 不是纸面设计；
   - 但默认仍是 allowlist、条件触发、可回退；
   - `tmux` 已是正式可选 backend，但不代表已经进入全局自动闭环。

### 1.2 为什么 agent 做完就停

这不是单一问题，而是两层问题叠加：

| 层 | 当前真因 | 结果 |
|---|---|---|
| agent 内部 | 做完当前 step 就交卷，缺少默认 planning ledger、closeout checklist、next-step policy | 改完一个文件/跑完一轮测试就停 |
| 公司级主链 | `summary -> decision -> dispatch` 还没被统一成默认 continuation contract | 子任务结束后，系统知道“结束了”，但不知道“下一步该由谁按什么条件继续” |

所以“agent 做完就停”**不是因为循环不够多**，而是因为：
- 前面没有统一 planning artifact；
- 中间没有统一 handoff contract；
- 后面没有统一 `stopped_because / next_step / owner` 字段；
- 外环 heartbeat 也不该代替主链去硬推下一跳。

### 1.3 这一阶段怎么修

先修 contract，再谈自动推进：

1. **先把 planning 变成默认输入**：执行层不再从零猜需求。
2. **先把 continuation contract 冻结**：任务结束后必须说明为什么停、谁接、下一步是什么。
3. **先给 coding issue lane 一个稳定 baseline**：让 issue-to-patch 这类任务有统一输入输出。
4. **先把 heartbeat 边界钉死**：避免为了“自动化”再造半套错误状态机。

一句话：**先规划、先 contract、再自动推进；不是盲目加循环。**

---

## 2. 整体计划

### P0：默认 planning + continuation contract + issue lane baseline + heartbeat boundary freeze

**目标**：先把“为什么停、停在哪、下一步怎么接”这件事讲清并定成默认。

**本阶段必交付：**
1. **gstack-style planning default**
   - 非 trivial feature / bugfix / workflow 设计先产出 planning artifact；
   - 下游执行、review、QA 默认消费该 artifact。
2. **continuation contract v1**
   - 每个任务 closeout 至少带：`summary`、`decision`、`stopped_because`、`next_step`、`next_owner`、`dispatch_readiness`。
3. **coding issue lane baseline**
   - 先冻结 `issue_to_patch.v1` 这类窄 lane 的输入输出；
   - 先解决单 issue、单仓、单 acceptance 的稳定 handoff。
4. **heartbeat boundary freeze**
   - heartbeat 只保留 wake / liveness / 巡检 / 催办 / 告警；
   - 禁止 heartbeat 写 terminal truth、直接 dispatch 下一跳、接管 gate。

**P0 完成标准：**
- 默认回答“为什么停”不再靠聊天猜；
- 主链知道下一步该由谁接；
- coding continuation 至少有一条窄 lane 可标准化；
- heartbeat 不再被误当 workflow owner。

### P1：DeepAgents / SWE-agent 叶子 pilot + planning->execution handoff 标准化 + stopped_because/next_step contract

**目标**：在不碰 control plane 的前提下，验证叶子执行增强是否真有收益。

**本阶段必交付：**
1. **DeepAgents / SWE-agent leaf pilots**
   - DeepAgents 风格 profile 只进 `coding-subagent` 内部；
   - SWE-agent 只进 `issue_to_patch` 窄 lane。
2. **planning -> execution handoff standardization**
   - planning artifact 字段稳定，执行层、review、QA 能直接消费；
   - 不再每层各自重写一遍任务定义。
3. **`stopped_because / next_step / owner` 成为标准 closeout 字段**
   - 让 operator/main 一眼看懂：当前为何停、谁该接、要不要 gate。

**P1 完成标准：**
- 叶子执行质量提升，但 control plane 没被破坏；
- callback 更结构化；
- 人工补洞成本下降。

### P2：只做高价值 durable / analysis-graph selective pilot

**目标**：只在真的值得重型化的地方试，而不是把全仓迁到新 runtime。

**本阶段必交付：**
1. 识别**跨天、强恢复、强审计**的少数高价值 durable 场景；
2. 识别**单 agent 内确实复杂**、值得 graph 化的 analysis 场景；
3. 只做 fenced pilot，继续观察 **LangGraph / Temporal**，不进主链。

**P2 完成标准：**
- durable/graph 只服务高价值少数场景；
- 任何试点都可 rollback；
- OpenClaw control plane 仍是主链 owner。

---

## 3. 边界

### 3.1 明确不做什么

1. **不把 gstack 当 control plane。**
   gstack 只作为 planning method / review-readiness 脚手架，不替代 OpenClaw 主链。

2. **不把 DeepAgents / SWE-agent / LangGraph / Temporal 抬成公司级 orchestration backbone。**
   它们最多进入叶子层、benchmark 层、局部 analysis graph、少数 durable pilot。

3. **不把 heartbeat 做成状态机。**
   heartbeat 只负责发现问题、提醒问题、请求重查；不负责业务终态与下一跳。

4. **不靠“多加循环”掩盖 contract 缺口。**
   没有 planning、没有 handoff、没有 owner 时，循环越多越容易噪音化。

5. **不把 proposal repo 写成 runtime 已完成。**
   这个 repo 负责统一阅读入口、计划与真值索引；不伪装成 live runtime 真代码仓。

### 3.2 本轮默认决策口径

- **先规划，再执行；**
- **先 contract，再自动推进；**
- **先修边界，再加能力；**
- **先叶子 pilot，再决定是否扩大。**

---

## 4. 建议的自动推进顺序

1. **先做 P0 的 contract 基线**
   - planning default
   - continuation contract
   - issue lane baseline
   - heartbeat boundary freeze
2. **再做 P1 的 leaf pilots**
   - DeepAgents profile
   - SWE-agent issue lane
   - closeout 字段标准化
3. **最后才评估 P2 的 selective heavy pilot**
   - 只在 durable / analysis-graph 高价值场景试
   - LangGraph / Temporal 继续观察，不进主链

---

## 5. 一句话总口径

**proposal repo 现在的统一说法是：OpenClaw 继续持有 control plane；gstack 作为 planning method 已落地；下一阶段先把 planning、contract、issue lane、heartbeat boundary 定成默认，再用 DeepAgents / SWE-agent 做叶子 pilot，最后才对少数高价值 durable / analysis-graph 场景做 selective 试点。**
