# 验证状态：已验证什么 / 未验证什么 / 为什么现在选这个方向

## 结论先行

**当前方向不是“猜出来的”，而是基于已有验证结果做的收敛；但它也不是“全部证实后才写”的。我们已经有足够证据重置主线，但还没有足够证据承诺重型能力。**

---

## 1. 已验证的内容

### 1.1 Lobster 的薄工作流能力成立

| 主题 | 当前结论 | 证据位置 |
|------|----------|----------|
| 顺序 chain | 成立 | `docs/validation/p0-lobster-feasibility-review.md` |
| approval / resume | 成立 | `docs/validation/p0-lobster-feasibility-review.md` |
| OpenClaw tool bridge | 成立 | `docs/validation/p0-lobster-feasibility-review.md` |

**结论**：Lobster 适合放在官方底座层，作为薄 workflow shell 复用。

### 1.2 `subagent` 是默认内部长任务主链

| 主题 | 当前结论 | 证据位置 |
|------|----------|----------|
| 默认内部执行主链 | `sessions_spawn(runtime="subagent")` | `README.md`、`docs/openclaw-company-orchestration-proposal.md`、既有 P0 结论 |
| watcher 定位 | watcher / reconciler，不是 backbone | `docs/validation/p0-readiness-review.md`、`docs/validation/p0-final-readiness-review.md` |

**结论**：控制层必须围绕 `subagent` 建模，而不是围绕 watcher 建模。

### 1.3 callback 语义必须拆分

| 主题 | 当前结论 | 证据位置 |
|------|----------|----------|
| terminal != sent != acked | 成立 | `docs/validation/p0-5-callback-status.md`、`tests/test_callback_status_semantics.py` |
| callback plane 需要幂等 | 成立 | `docs/validation/p0-6-callback-integration.md` |

**结论**：task 终态与消息投递终态不能混成一个字段。

### 1.4 human-gate / failure-branch / bridge 已有最小验证资产

| 主题 | 当前结论 | 证据位置 |
|------|----------|----------|
| human-gate 最小验证 | 成立 | `docs/validation/p0-poc-implementation-status.md` |
| failure-branch 最小验证 | 成立，但偏 adapter 路线 | `docs/validation/p0-poc-implementation-status.md` |
| subagent bridge 模拟 | 成立 | `docs/validation/p0-5-bridge-simulator.md` |

**结论**：这些资产足以支撑路线判断，但还不能自动升级为平台级“已完成能力”。

### 1.5 trading / channel roundtable 已进入最小 live integration

| 主题 | 当前结论 | 证据位置 |
|------|----------|----------|
| `trading_roundtable` continuation | 已最小落地，但仍是 safe semi-auto | runtime repo commits `b1f44b4` |
| `channel_roundtable` 通用适配器 | 已落地，其他频道可按最小契约接入 | runtime repo commits `171944e` |
| 当前架构频道 demo | `Temporal vs LangGraph｜OpenClaw 公司级编排架构` 已成为第二个真实场景 | runtime repo commits `2383487` |
| 白名单默认 auto-dispatch | 当前频道 dispatch plan 默认 `triggered`，其他频道仍默认 `skipped` | runtime repo commits `482fe03` |

**结论**：proposal 主线已经有两条真实场景可对照，但它们仍处在 **thin bridge + allowlist + safe semi-auto** 阶段，不能误写成“通用全自动编排已完成”。

---

## 2. 未验证的内容

| 主题 | 当前状态 | 当前口径 |
|------|----------|----------|
| Lobster → 真实 `subagent` 端到端闭环 | 未完成真实接线 | 只能写“候选方向”，不能写“已落地” |
| 真并发 `parallel` | 未证实 | 不进入 P0 默认承诺 |
| 真 `join` / barrier | 未证实 | 不进入 P0 默认承诺 |
| 原生 `failure-branch` | 未证实 | 当前更接近 adapter / 控制层策略 |
| Trading 通用 workflow engine 化 | `trading_roundtable` continuation 已最小落地，但仍是 safe semi-auto | 不能把单点最小接线升级表述为 trading 全面 workflow 化 |
| channel_roundtable 跨频道 rollout | 通用适配器虽已落地，但默认 auto-dispatch 只对白名单当前频道开启 | 其他频道继续默认 `skipped` |
| 何时需要 Temporal | 业务证据不足 | P2 再决策 |
| 安全层策略系统化 | 仅有方向，无系统实现 | P1/P2 再补 |

---

## 3. 为什么现在选这个方向

### 3.1 因为现在已经足够排除错误方向

目前至少已经可以排除：
- `taskwatcher-first backbone`
- `LangGraph-first company backbone`
- `Temporal-first all-in`
- `自研 DAG-first`

### 3.2 因为已有资产足够支撑“先建控制层”

已具备：
- OpenClaw 原生 runtime 与 tool primitives
- `subagent` 主链事实
- Lobster 薄 workflow shell 候选
- callback / bridge / human-gate 的最小验证资产

因此现在最合理的是：

> **先把控制层定义清楚，并让它在 `workspace-trading` 中跑出真实价值。**

### 3.3 因为业务验证比框架争论更重要

如果 `workspace-trading` 跑不起来：
- 架构再漂亮也没有意义
- security / durability / observability 的优先级就无法排序
- 是否需要 Temporal 也无法得到真实答案

---

## 4. 对文档口径的约束

以后仓库主文档必须同时写出：
1. **已验证什么**
2. **未验证什么**
3. **为什么仍然选择这条路线**

禁止只写“推荐方案”，不写边界。

---

## 5. 最终口径

**我们现在选“五层架构 + 薄控制层 + Trading 首落地”，不是因为它已经全部被证明，而是因为它是当前“已验证事实最多、未验证风险最可控、与现有资产最连续”的方向。**

补一句当前成熟度口径：**仓库已从纯方案 / POC 推进到 trading + current-channel 两个真实场景的最小接线，但仍明确停留在 thin bridge、allowlist、safe semi-auto，而不是默认全自动。**
