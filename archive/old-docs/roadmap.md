# 路线图：P0 / P1 / P2

## 结论先行

**接下来的路线图不再按“先上更多框架/更多循环”排序，而是按“先规划、先 contract、再自动推进、最后才 selective heavy pilot”排序。**

---

## P0：planning default + continuation contract + issue lane baseline + heartbeat boundary freeze

### 目标

先把系统为什么停、停在哪、下一步怎么接这件事说清楚，并变成默认协议。

### 必交付

1. **gstack-style planning default**
   - 非 trivial feature / bugfix / workflow 设计先出 planning artifact；
   - planning artifact 至少包含：目标/非目标、范围拆分、风险/失败路径、验证/测试、下一步 owner。

2. **continuation contract v1**
   - 统一 closeout 字段：`summary`、`decision`、`stopped_because`、`next_step`、`next_owner`、`dispatch_readiness`。

3. **coding issue lane baseline**
   - 先冻结 `issue_to_patch.v1` 这类窄 lane 的输入输出；
   - 让单 issue、单仓、单 acceptance 的 coding continuation 可标准化。

4. **heartbeat boundary freeze**
   - heartbeat 只用于 wake / liveness / 巡检 / 催办 / 告警；
   - 禁止 heartbeat 写 terminal truth、直接 dispatch 下一跳、接管 gate。

### P0 完成标准

- 默认回答“为什么 agent 停了”不再靠聊天猜；
- 执行层 closeout 能说明当前为何停、谁该接、是否可 dispatch；
- 至少有一条 coding 窄 lane 可被稳定 handoff；
- heartbeat 不再被误当状态机。

---

## P1：DeepAgents / SWE-agent leaf pilots + planning->execution handoff standardization + stopped_because/next_step contract

### 目标

在不动 control plane 的前提下，验证叶子执行增强是否真能提升完成质量与 handoff 质量。

### 必交付

1. **DeepAgents / SWE-agent leaf pilots**
   - DeepAgents 风格 profile 只进 `coding-subagent` 内部；
   - SWE-agent 只进 `issue_to_patch` 窄 lane。

2. **planning -> execution handoff 标准化**
   - planning artifact 字段稳定，执行、review、QA 可以直接消费；
   - 避免每层重新解释一次任务定义。

3. **closeout 标准字段落地**
   - `stopped_because / next_step / next_owner` 成为默认 closeout 字段；
   - callback 与 operator 视角都能直接读懂当前状态。

### P1 完成标准

- 叶子层完成率、artifact 完整度或 callback 清晰度明显优于现状；
- control plane 没被外部框架接管；
- 人工补洞成本下降。

---

## P2：selective durable / analysis-graph pilot（LangGraph/Temporal 继续观察，不进主链）

### 目标

只在高价值少数场景试重型能力，不把全仓迁成 durable/graph-first。

### 必交付

1. 识别跨天、强恢复、强审计的高价值 durable 场景；
2. 识别单 agent 内确实复杂、值得 graph 化的 analysis 场景；
3. 只对这些场景做 fenced pilot，继续观察 LangGraph / Temporal。

### 明确不做什么

- 不把 LangGraph 抬成公司级 control plane；
- 不做 Temporal-first 全局迁移；
- 不因为“框架先进”就反向改写 OpenClaw 主链。

### P2 完成标准

- durable/graph 只进入高价值少数场景；
- 任一 pilot 都可 rollback；
- OpenClaw 仍持有 control plane。

---

## 最终节奏

```text
P0：先把 planning、contract、issue lane、heartbeat boundary 定成默认
P1：再用 DeepAgents / SWE-agent 做叶子 pilot，补齐 handoff 标准
P2：最后只对少数高价值 durable / analysis-graph 场景做 selective 试点
```

**先规划，先 contract，再自动推进；最后才 selective heavy pilot。**
