# Trading Control-Plane Integration v1 (2026-03-30)

> 状态: draft-v1 / 待执行
> 角色定位: 把 `workspace-trading` 从“半调度半业务仓”收成 **业务执行叶子层**，把任务派发/状态推进/dashboard/next-step 全部接入 OpenClaw orchestration control plane。

---

## 1. 一句话结论

**以后 trading repo 不再持有 control plane。**

新的默认工作方式:

```text
老板 / 频道消息
  -> main(大龙虾) 只做 planning / dispatch / dashboard / next-step
  -> OpenClaw orchestration control plane
  -> Unified Execution Runtime (subagent / tmux)
  -> workspace-trading 作为业务执行仓
```

目标不是“把 trading repo 修成万能系统”，而是：

1. 用 control plane 接管任务编排
2. 用 dashboard 接管状态真值
3. 用 callback / receipt / gate 接管继续推进逻辑
4. 让 trading repo 退回 research / backtest / adapter / execution artifact 容器

---

## 2. 当前问题（为什么必须改）

### 2.1 当前结构混杂

`workspace-trading` 当前至少混有四条主线:

1. **研究/回测主线**: `research/v2_portfolio`, `research/data_portal`
2. **运行脚本主线**: `skills/trading-quant/scripts/*`
3. **业务接入主线**: news / theme / KOL / alerts
4. **实验与临时主线**: `tmp/*`, `v9`, `phase3`, health reports

### 2.2 现象

- 任务派发逻辑散落在 repo 内外
- 状态推进依赖聊天上下文和人工记忆
- dashboard 不是主真值，而是旁路信息
- callback / closeout / next-step 没有统一 task schema
- trading repo 同时承担“调度仓 + 业务仓”，导致治理失控

### 2.3 核心裁决

> 当前真正缺的不是更多功能，而是**统一控制面 + 单一真值状态机**。

---

## 3. 目标 operating model

## 3.1 角色边界

### main (大龙虾)
只负责:
- task planning
- dispatch
- dashboard 读取
- next-step 规划
- human/business/runtime gate 决策

不再默认负责:
- 长任务亲自执行
- 在 trading repo 里散改脚本
- 用聊天口头维持状态机

### orchestration control plane
负责:
- task registry
- state machine
- auto-dispatch
- callback / receipt
- failure closeout guarantee
- dashboard / observability
- backend selection

### workspace-trading
负责:
- research / backtest
- data contract
- strategy implementation
- business adapters
- execution artifacts

不再负责:
- 公司级调度中枢
- continuation owner
- 主任务状态真值

---

## 4. v1 范围

## 4.1 In Scope

1. 建立 **trading task schema v1**
2. 建立 **trading stage model v1**
3. 建立 **trading dashboard fields v1**
4. 建立 **trading callback / closeout / next-step contract v1**
5. 把现有 trading 链路映射到 control plane
6. 定义 repo 瘦身边界（control plane vs business repo）

## 4.2 Out of Scope

1. 立即删除所有旧脚本
2. 一次性重写 trading 全部代码
3. live trading 全自动化
4. 直接把所有 feature branch 并回 main
5. 引入新的重型 workflow 引擎替代现有 control plane

---

## 5. Trading Task Schema v1

每个 trading task 必须进入统一 schema。

```json
{
  "task_id": "trading_20260330_xxx",
  "scenario": "trading_roundtable",
  "task_type": "research|engineering|integration|governance|execution_prep",
  "owner": "main|trading",
  "executor": "subagent|claude_code|tmux",
  "backend_preference": "subagent|tmux|auto",
  "truth_domain": "strategy|data|repo|ops|adapter",
  "priority": "P0|P1|P2",
  "title": "...",
  "goal": "...",
  "inputs": ["artifact path", "doc path", "branch", "config"],
  "deliverables": ["report", "diff", "test result", "artifact"],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "...",
  "next_step_on_fail": "..."
}
```

### 5.1 task_type 枚举

| 类型 | 含义 | 示例 |
|------|------|------|
| `research` | 回测/验证/诊断/比较 | acceptance rerun, factor audit |
| `engineering` | 代码修改/重构/修复 | capital-flow contract fix |
| `integration` | adapter/control-plane 接线 | theme source wiring |
| `governance` | 分支回收/归档/清理/状态治理 | repo closure |
| `execution_prep` | live 前置检查，但不触发 live | readiness review |

### 5.2 truth_domain 枚举

| truth_domain | 说明 |
|-------------|------|
| `strategy` | 策略候选 / acceptance / benchmark |
| `data` | 数据源 / contract / freshness / coverage |
| `repo` | 分支 / worktree / 文档 / archive |
| `ops` | cron / dashboard / monitor / health |
| `adapter` | news/theme/sentiment/alert 等输入增强 |

---

## 6. Trading Stage Model v1

统一状态机：

```text
planned
-> dispatched
-> running
-> completed | failed | blocked
-> closeout_recorded
-> next_step_decided
-> auto_dispatched | waiting_gate | archived
```

### 6.1 阶段说明

| stage | 含义 | 必须产物 |
|------|------|---------|
| `planned` | 已定义任务但未发出 | task schema |
| `dispatched` | 已交给 executor | dispatch artifact |
| `running` | 执行中 | heartbeat / runtime card |
| `completed` | 执行成功 | result + artifacts |
| `failed` | 执行失败 | failure summary + truth anchor |
| `blocked` | 命中 gate 或依赖阻塞 | blocked reason |
| `closeout_recorded` | 已写 stopped_because / next_step | closeout payload |
| `next_step_decided` | main 已做下一步决策 | continuation contract |
| `auto_dispatched` | 自动续推已触发 | request / receipt / dispatch linkage |
| `waiting_gate` | 需要人审/业务判断 | gate decision pending |
| `archived` | 已结束且归档 | archive marker |

---

## 7. Dashboard Truth v1

Dashboard 必须成为 trading 默认视图，不再依赖聊天记忆。

### 7.1 卡片最小字段

每个 task 至少显示：

- `task_id`
- `scenario`
- `task_type`
- `truth_domain`
- `owner`
- `executor`
- `backend`
- `stage`
- `heartbeat`
- `promised_eta`
- `truth_anchor`
- `stopped_because`
- `next_step`
- `next_owner`
- `gate_status`

### 7.2 trading dashboard 默认分组

1. **按 truth_domain 分组**
   - strategy
   - data
   - repo
   - ops
   - adapter

2. **按 owner 分组**
   - main
   - trading
   - subagent / tmux executor

3. **按 stage 分组**
   - running
   - blocked
   - failed
   - waiting_gate
   - auto_dispatched

### 7.3 P0 看板问题

当前 dashboard 更多是通用 observability 看板，缺 trading-specific 视图：
- 看不出哪些任务属于 strategy 主线
- 看不出哪个 task 在阻塞 live readiness
- 看不出下一个业务决策点

### 7.4 v1 方案

不新造真值链，只在现有 observability card 基础上增加 trading 约定字段，并在 dashboard 上增加 trading filter / grouping。

---

## 8. Callback / Closeout / Next-Step Contract v1

每个 trading task 完成后必须写 4 个最小字段：

```json
{
  "stopped_because": "completed|failed|blocked|waiting_gate",
  "truth_anchor": "artifact/report/status path",
  "next_step": "下一步明确动作",
  "next_owner": "main|trading|subagent|tmux|human_gate"
}
```

### 8.1 规则

- 没有 `truth_anchor`，不得宣称完成
- 没有 `next_step`，不得自动续跑
- 命中 gate 时必须写 `waiting_gate`
- `closeout_recorded` 之后，才允许 `next_step_decided`

### 8.2 失败保证

沿用现有 closeout guarantee 机制：
- 系统内部知道失败 != 用户可见失败
- trading lane 必须把失败写成标准 closeout，并进入 dashboard

---

## 9. Gate Policy v1

Trading lane 继续使用：

```text
stop_on_gate
```

### 9.1 gate 类型

| gate | 说明 | 是否可自动通过 |
|------|------|--------------|
| `human_gate` | 老板需要决策 | 否 |
| `business_gate` | 策略/收益/风控未达标 | 否 |
| `runtime_gate` | callback / receipt / lineage 不完整 | 否 |
| `repo_gate` | 分支脏/冲突/无真值锚点 | 否 |

### 9.2 默认自动推进范围

允许自动推进：
- research
- engineering
- integration
- governance
- 非 live execution_prep

禁止默认自动推进：
- live trading
- 不可逆资金动作
- business gate 未过的策略升级

---

## 10. 现有链路映射到 control plane

## 10.1 应保留为 business leaf 的部分

### workspace-trading core
- `research/v2_portfolio/*`
- `research/data_portal/*`
- 必要 adapter 代码

### runtime tools
- `skills/trading-quant/scripts/intraday_monitor.py`
- `skills/trading-quant/scripts/macro_linkage.py`

这些仍可存在，但只作为 executor 叶子层或工具层，不再拥有 orchestration ownership。

## 10.2 应降级/归档的部分

### 直接不进主线（作为历史分支归档）
- `search-kol-sources-20260322`
- `feat/wire-alerts-to-trading-spider`

### 仅最小救援式提取
- `feat/real-theme-source-minimal-20260322`
  - 仅评估真正有助于 selector / theme adapter 的代码
  - 不整体 merge

### 应移出主线视野
- `tmp/*`
- 实验脚本
- 一次性任务报告
- 非 canonical docs

---

## 11. Implementation Phases

## Phase 1 — Contract First

目标：让 trading task 先能被 control plane 表达清楚。

交付：
1. trading task schema v1
2. trading stage model v1
3. trading closeout contract v1
4. trading dashboard field contract v1

## Phase 2 — Scenario Wiring

目标：让 `trading_roundtable` 成为正式 control-plane scenario。

交付：
1. `orch_command --context trading_roundtable` 生成标准 contract
2. trading task 默认字段注入（truth_domain/task_type/gate policy）
3. callback / receipt / dispatch linkage 对齐

## Phase 3 — Unified Runtime

目标：把 trading 执行统一接到 backend selector + unified execution runtime。

交付：
1. subagent / tmux 都走统一 `run_task(...)`
2. trading task 根据 profile 自动推荐 backend
3. callback / wake / observability 自动接线

## Phase 4 — Repo Slimming

目标：让 `workspace-trading` 只剩业务主线。

交付：
1. archive 临时/实验内容
2. 回收或放弃 feature branches
3. 保留 core research / adapter / runtime tool 必要最小集

---

## 12. Success Criteria

v1 成功标准不是“自动赚钱”，而是：

1. trading task 全部可进入统一 schema
2. trading task 状态全部可在 dashboard 上看见
3. 完成/失败/blocked 都有 closeout truth
4. next-step 不再靠聊天记忆维持
5. main 只做 dispatch / dashboard / next-step / gate
6. workspace-trading 不再兼任 orchestration owner

---

## 13. 一句话裁决

> **把 trading repo 从“半调度半业务仓”降回业务执行叶子层，把任务编排、状态推进、dashboard 和记忆从 repo 内部抽离到 OpenClaw orchestration control plane。**
