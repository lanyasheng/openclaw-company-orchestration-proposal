# Spawn-Interceptor Live Bridge 说明

> 目的：说明 callback-driven orchestrator v1 在 **proposal repo** 与 **runtime repo** 之间的分工边界，以及当前 live bridge 的真实落点。

---

## 结论先行

这轮 callback-driven orchestrator v1 的**生产接线落点不在 proposal repo**，而在 runtime 侧的 **`spawn-interceptor`**。

proposal 仓保留的是：
- 原型快照：`prototype/callback_driven_orchestrator_v1/`
- 状态流转、batch fan-in、summary、decision 的最小可读实现
- 对 live integration 边界的明确文档化

runtime 仓保留的是：
- 真正拦截 live spawn / callback 的 hook
- 与运行时生命周期、feature flag、灰度、安全边界相关的补丁
- 是否把决策继续接成下一轮真实派发的生产策略

一句话：

> **proposal 仓放“原型与边界”，runtime 仓放“live patch 与运行时接线”。**

---

## 1. 为什么 live bridge 落在 `spawn-interceptor`

`spawn-interceptor` 是当前最合适的 live bridge 落点，原因有四个：

1. **它最接近真实任务派发入口**
   - 能看见任务何时被创建、带什么 metadata 被派发
   - 能在不改业务 workflow 书写方式的前提下，统一插入状态登记与批次关联

2. **它天然处在 callback / completion 信号回流路径旁边**
   - 适合把“任务终态”与“callback 已收到”分开记账
   - 适合把 batch fan-in 汇总挂到真实运行时事件上，而不是只跑离线脚本

3. **它比把逻辑塞进 proposal repo 更符合职责边界**
   - proposal repo 主要回答“应该怎样设计”
   - runtime repo 负责“今天生产里到底接在哪里、怎么灰度、怎么回退”

4. **它更利于渐进接线**
   - 先把状态与汇总接进去
   - 再观察实际数据和异常面
   - 最后才决定是否开放自动下一轮 dispatch

---

## 2. 当前已经接上的 live 能力

当前 live bridge 已经对齐到 callback-driven orchestrator v1 的三段主线：

### 2.1 task state

live runtime 已能把真实任务事件映射到原型中的核心状态语义，包括但不限于：
- task 创建 / 派发
- callback 收到
- failed / timeout / close 等终态

也就是说，proposal 仓里的 `state_machine.py` 不只是概念模型，而是已经对应到 live runtime 里真实需要记录的状态切面。

### 2.2 batch summary

live bridge 已能把同一批次下的 task 结果做 fan-in 归并，形成 batch 级视图：
- 成功 / 失败 / 超时统计
- common blocker 提取
- summary 文本或等价汇总产物

这和原型里的 `batch_aggregator.py` 对齐，说明 batch callback → summary 这条线已经不是纯 proposal 文字，而是有 live 映射点的。

### 2.3 decision

在 batch 完成后，runtime 侧已经能接上“基于 summary 产出 decision”的决策层：
- all success → proceed
- common blocker → fix_blocker
- partial failure → retry
- major failure → abort

这对应原型里的 `orchestrator.py` 决策规则集合。

### 2.4 当前新增的最小真实场景

截至 2026-03-20，live bridge 之上又补了两条最小真实接线：

1. **`trading_roundtable` continuation**
   - 已最小落地
   - 但仍明确是 **safe semi-auto**，不是默认无人值守自动续跑
   - trading 当前策略更收紧：**仅 clean PASS 默认 `triggered`，其余结果默认 `skipped`**

2. **`channel_roundtable` 通用适配器**
   - 已落地为最小契约
   - 当前 `Temporal vs LangGraph｜OpenClaw 公司级编排架构` 频道已成为第二个真实场景
   - 当前频道在白名单内，dispatch plan 默认 `triggered`
   - 其他频道默认仍为 `skipped`

3. **`tmux` continuation backend**
   - 已进入正式可选 backend 口径
   - 适合需要中间态可见性、可 attach、可人工介入的 continuation 场景
   - 但 trading real run 当前仍只到 **dry-run**
   - 真实 artifact-backed clean PASS 仍缺，因此不能写成“tmux 已完成 trading 真实自动闭环”

这说明 runtime 已经从“只有原型映射点”推进到“少量 live scene 可对照”，但范围仍被故意限制在 allowlist 与条件触发内。

---

## 3. 当前**不做全局自动 spawn**；只保留白名单最小 auto-dispatch

这是刻意设计，不是遗漏。

当前 live patch **没有**把 decision 无条件接成下一轮真实 `spawn`。最新真值是：**只在白名单内保留最小 auto-dispatch**，而不是对所有 channel / workflow 默认放开。

也就是说：
- 当前架构频道可以默认生成 `triggered` 的 dispatch plan
- 其他频道默认仍是 `skipped`
- trading 侧也只是 continuation 已最小落地，口径仍是 safe semi-auto
- trading 只对 **clean PASS** 保持默认 `triggered`；其余结果继续默认 `skipped`
- `tmux` 虽已进入正式可选 backend，但 trading real run 当前仍只到 dry-run
- 回退方式仍保持简单：移出白名单、关闭 auto-dispatch、收紧 clean PASS 条件，或退回手动 continuation / summary-only

主要原因如下：

1. **安全边界还没完全收敛**
   - 自动下一轮派发会把系统从“可观测原型”升级成“主动扩散执行器”
   - 在幂等、限流、审批、回退、异常 stop 条件未完全收紧前，不应默认打开

2. **需要先验证 decision 质量，而不是直接放权**
   - 目前更重要的是验证 summary 与 decision 是否稳定、是否能解释
   - 如果 decision 还在调规则，直接自动派发会放大错误成本

3. **批次边界 / 人工 gate / 策略路由还未统一**
   - 哪些 batch 可以自动续跑
   - 哪些必须人工确认
   - 哪些应该切到 retry / escalation / abort
   这些还属于 runtime policy，不应在 proposal 原型里假装已经定稿

4. **proposal 仓此轮目标是“证明闭环切面成立”，不是“承诺无人值守生产闭环”**
   - 这轮已经证明：task state → batch summary → decision 成立
   - 但“decision → real spawn”仍明确保留为下一阶段 live runtime 开关

所以当前口径应写成：

> **live bridge 已经接到 decision，但不做全局默认自动 spawn；当前只有白名单内的最小 auto-dispatch，且仍属于 thin bridge / safe semi-auto。**

---

## 4. 为什么 proposal 仓放原型，runtime 仓放 live patch

这是为了把“方案真值”和“运行时真值”拆开，避免两个仓互相污染。

### proposal 仓负责什么

proposal 仓负责：
- 记录 callback-driven orchestrator v1 的最小原型
- 让评审者直接看到状态机、batch 汇总、decision 规则长什么样
- 给后续设计讨论提供稳定、轻量、可审阅的参考实现
- 清楚写出哪些已接、哪些未接、哪些是故意不做

适合放在 proposal 仓的内容：
- `prototype/callback_driven_orchestrator_v1/`
- 说明文档
- 架构边界、阶段性口径、验证状态

### runtime 仓负责什么

runtime 仓负责：
- live hook / interceptor / plugin 生命周期代码
- feature flag、灰度开关、回退路径
- 真实运行时状态落盘、事件来源、异常处理、观测与运维约束
- 白名单 auto-dispatch 的生产策略与默认值（如当前频道 `triggered`、其他频道 `skipped`）
- 后续是否进一步打开自动下一轮 spawn 的生产策略

适合放在 runtime 仓的内容：
- `spawn-interceptor` live patch
- callback 与 dispatch 的真实 wiring
- 生产防护与运行时治理

### 这样分仓的好处

1. **proposal 仓不会被 runtime 细节淹没**
2. **runtime 仓不用为了讲方案保留一堆评审性文字资产**
3. **原型可以稳定引用，live patch 可以继续快速迭代**
4. **评审口径与生产口径分离，减少“文档说已完成、运行时其实还在灰度”的混淆**

---

## 5. 当前应如何阅读这两部分资产

建议按下面顺序理解：

1. 先读原型：`prototype/callback_driven_orchestrator_v1/README.md`
   - 看最小闭环：state → summary → decision
2. 再读本说明：`docs/runtime-integration/spawn-interceptor-live-bridge.md`
   - 看 live bridge 落在哪里、已接到哪一段、为何故意没继续自动 spawn
3. 最后再去 runtime 仓看实际 patch
   - 看生产接线、灰度、防护、回退

---

## 6. 当前仓库口径（可直接引用）

- callback-driven orchestrator v1 的**原型快照**已进入 proposal 仓
- live runtime bridge 的真实落点是 **`spawn-interceptor`**
- 当前 live 已接上：**task state / batch summary / decision**
- 当前 live 已有两条最小真实场景：`trading_roundtable` continuation + 当前架构频道 `channel_roundtable`
- 当前 live **不做全局默认自动 spawn**；仅白名单当前频道默认 `triggered`，其他频道默认 `skipped`
- trading 当前只对 **clean PASS** 默认 `triggered`；其余结果继续默认 `skipped`
- `tmux` 已是正式可选 continuation backend，但 trading real run 当前仍只到 dry-run，真实 artifact-backed clean PASS 仍缺
- proposal 仓负责**原型与边界**，runtime 仓负责**live patch 与生产接线**
