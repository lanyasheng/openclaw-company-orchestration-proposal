# Trading First Five Control-Plane Task List v1 (2026-03-30)

> 状态: ready-for-dispatch
> 目标: 把 trading 当前最关键的 5 条主线任务，先映射成 control-plane 可消费的标准任务。

---

## 总原则

这 5 条任务不是“功能愿望清单”，而是当前最该先进入 control plane 的真主线：

1. 数据契约修正
2. 策略 acceptance 复跑
3. 主仓治理与分支收口
4. 最小 adapter 救援
5. runtime ownership 拆分

默认策略：
- gate_policy = `stop_on_gate`
- business/live 相关一律不自动越过 gate
- main 只做 dispatch / dashboard / next-step / gate

---

## Task 1 — Capital Flow Contract Hardening

```json
{
  "task_id": "trading_cp_20260330_001",
  "scenario": "trading_roundtable",
  "task_type": "engineering",
  "truth_domain": "data",
  "owner": "trading",
  "executor": "claude_code",
  "backend_preference": "subagent",
  "priority": "P0",
  "title": "Harden capital-flow runtime contract",
  "goal": "把历史资金流不可得从硬错误改成标准 degrade/warning 语义，并把 real/proxy/realtime_only 明确写入 runtime contract",
  "inputs": [
    "research/v2_portfolio/portfolio_backtest.py",
    "research/v2_portfolio/strategy_context.py",
    "research/v2_portfolio/strategy_templates.py",
    "tests/v2_portfolio/test_multifactor_swing_strategy.py",
    "tests/v2_portfolio/test_capital_flow_filtered_empty_contract.py"
  ],
  "deliverables": [
    "code diff",
    "targeted test results",
    "updated runtime contract behavior summary"
  ],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "dispatch trading acceptance rerun",
  "next_step_on_fail": "open follow-up data contract fix task"
}
```

### 成功判定
- targeted tests 通过
- contract 中能区分 `real / proxy / realtime_only`
- proxy 数据自动降权
- 无 fake 历史资金流逻辑

---

## Task 2 — Strategy Acceptance Rerun Under Corrected Contract

```json
{
  "task_id": "trading_cp_20260330_002",
  "scenario": "trading_roundtable",
  "task_type": "research",
  "truth_domain": "strategy",
  "owner": "trading",
  "executor": "subagent",
  "backend_preference": "subagent",
  "priority": "P0",
  "title": "Rerun strategy acceptance under corrected capital-flow semantics",
  "goal": "在修正后的资金流契约下重新跑 frozen candidate acceptance，分离 data blocker 与真实 business blocker",
  "inputs": [
    "capital-flow contract fixed code",
    "Phase A frozen set artifacts",
    "acceptance harness config",
    "benchmark comparison artifacts"
  ],
  "deliverables": [
    "acceptance rerun report",
    "scenario verdict summary",
    "data blocker vs business blocker separation note"
  ],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "dispatch strategy redesign or candidate reset decision",
  "next_step_on_fail": "dispatch acceptance diagnostics follow-up"
}
```

### 成功判定
- 复跑结果真实落盘
- 明确区分：
  - 数据契约问题是否已收敛
  - turnover/cost/net-benchmark 是否仍失败
- 不允许只给聊天口头结论

---

## Task 3 — Repo Closure & Branch Recovery

```json
{
  "task_id": "trading_cp_20260330_003",
  "scenario": "trading_roundtable",
  "task_type": "governance",
  "truth_domain": "repo",
  "owner": "main",
  "executor": "subagent",
  "backend_preference": "subagent",
  "priority": "P0",
  "title": "Close dirty repo state and recover minimal branch truth",
  "goal": "把 workspace-trading 当前脏状态、tmp 污染和未回收分支整理成可治理状态，形成单一主线边界",
  "inputs": [
    "workspace-trading git status",
    "tonight-kol-source-correction worktree",
    "feat/real-theme-source-minimal-20260322",
    "search-kol-sources-20260322",
    "feat/wire-alerts-to-trading-spider"
  ],
  "deliverables": [
    "repo closure checklist update",
    "keep/drop decision table",
    "branch recovery recommendation",
    "archive/drop list"
  ],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "dispatch selective rescue for theme adapter branch",
  "next_step_on_fail": "pause merge and request manual repo gate decision"
}
```

### 成功判定
- 哪些分支保留/放弃有明确裁决
- tmp/实验/临时文件与主线边界明确
- 不要求一次性全部 merge，只要求真值收口

---

## Task 4 — Theme Source Minimal Rescue

```json
{
  "task_id": "trading_cp_20260330_004",
  "scenario": "trading_roundtable",
  "task_type": "integration",
  "truth_domain": "adapter",
  "owner": "trading",
  "executor": "claude_code",
  "backend_preference": "subagent",
  "priority": "P1",
  "title": "Rescue minimal reusable code from real-theme-source branch",
  "goal": "只提取对 selector/theme adapter 主线真正有用的最小代码，不整体 merge feature branch",
  "inputs": [
    "feat/real-theme-source-minimal-20260322",
    "research/v2_portfolio/selector/*",
    "theme adapter related files",
    "repo closure decision table"
  ],
  "deliverables": [
    "minimal file keep list",
    "code extraction diff",
    "non-merge archive note"
  ],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "dispatch adapter validation task",
  "next_step_on_fail": "archive branch without merge"
}
```

### 成功判定
- 只救最小必要代码
- 不把任务报告/示例/一次性文档带回主线
- adapter 进入主线后仍保持可插拔

---

## Task 5 — Runtime Ownership Split

```json
{
  "task_id": "trading_cp_20260330_005",
  "scenario": "trading_roundtable",
  "task_type": "integration",
  "truth_domain": "ops",
  "owner": "main",
  "executor": "subagent",
  "backend_preference": "subagent",
  "priority": "P1",
  "title": "Split runtime tool ownership from research core",
  "goal": "把 intraday monitor / macro linkage 等 runtime tools 从 trading core 中分离出清晰 ownership，并映射到 control-plane task model",
  "inputs": [
    "skills/trading-quant/scripts/intraday_monitor.py",
    "skills/trading-quant/scripts/macro_linkage.py",
    "dashboard/observability contracts",
    "trading control-plane integration v1"
  ],
  "deliverables": [
    "runtime-vs-core ownership note",
    "tool ownership mapping",
    "future dispatch model for runtime tools"
  ],
  "gate_policy": "stop_on_gate",
  "next_step_on_success": "dispatch dashboard field integration for trading lane",
  "next_step_on_fail": "fallback to manual runtime ownership freeze"
}
```

### 成功判定
- runtime tools 不再被当成交易主线本体
- owner / executor / backend 归属明确
- 后续能直接接 control plane dispatch

---

## 首批任务执行顺序

### Batch A（立即）
1. `trading_cp_20260330_001` — Capital Flow Contract Hardening
2. `trading_cp_20260330_003` — Repo Closure & Branch Recovery

### Batch B（A 完成后）
3. `trading_cp_20260330_002` — Strategy Acceptance Rerun
4. `trading_cp_20260330_004` — Theme Source Minimal Rescue

### Batch C（收口）
5. `trading_cp_20260330_005` — Runtime Ownership Split

---

## 统一 next-step 规则

- Task 1 完成后，默认派发 Task 2
- Task 3 完成后，决定 Task 4 是否继续
- Task 5 只在前四项收口后推进
- 若任一任务命中 business/runtime/repo gate，进入 `waiting_gate`

---

## 一句话结论

> 这 5 条任务不是继续“加功能”，而是把 trading 主线从混乱仓库状态，收成一个可被 control plane 接管、可被 dashboard 持续跟踪、可被 next-step 自动规划的业务叶子系统。
