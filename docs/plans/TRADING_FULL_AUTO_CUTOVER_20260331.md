# Trading Full-Auto Cutover Plan (2026-03-31)

> **状态**: ready-for-execution  
> **作者**: Zoe (subagent)  
> **目标**: 把 trading_roundtable 线程从半手工链路切到 `orch_product onboard/run/status` 产品入口模式

---

## 1. 一句话结论

**立即停用所有旧 sessions_spawn 手工续推链，统一收口到 `orch_product onboard/run/status` 三件套。**

新链路：
```
老板/频道消息 → main 只做 dispatch/dashboard/gate → orch_product (onboard/run/status) → control plane → executor
```

旧链路：
```
老板/频道消息 → main 手工 sessions_spawn → 口头状态追踪 → 手工续推 → 聊天记忆维持 next-step
```

---

## 2. 背景与证据

### 2.1 用户明确要求

- 用户明确要求"不要再要半自动手工链路"
- 当前 docs 已简化为产品入口三件套：onboard / run / status
- 当前问题不在文档，而在 trading lane 仍混用旧 sessions_spawn 手工续推链

### 2.2 当前文档状态

已完成的 canonical 文档：
- ✅ `docs/orch_product_guide.md` — 产品使用指南
- ✅ `docs/design/orch-product-entry-design-2026-03-30.md` — 设计摘要
- ✅ `docs/plans/trading-control-plane-integration-v1-2026-03-30.md` — trading 控制面集成方案
- ✅ `docs/plans/trading-current-chain-mapping-v1-2026-03-30.md` — 当前链路映射
- ✅ `docs/plans/trading-first-five-control-plane-task-list-v1-2026-03-30.md` — 首批任务列表

### 2.3 当前实现状态

已实现的 canonical 入口：
- ✅ `runtime/scripts/orch_product.py` — 产品化三件套入口
  - `onboard` — 生成频道接入建议
  - `run` — 触发执行
  - `status` — 查看状态
- ✅ `runtime/orchestrator/entry_defaults.py` — 默认配置推导
- ✅ `runtime/orchestrator/unified_execution_runtime.py` — 统一执行入口

### 2.4 旧链路问题证据

根据 `trading-control-plane-integration-v1-2026-03-30.md`：

**当前问题**:
1. 任务派发逻辑散落在 repo 内外
2. 状态推进依赖聊天上下文和人工记忆
3. dashboard 不是主真值，而是旁路信息
4. callback / closeout / next-step 没有统一 task schema
5. trading repo 同时承担"调度仓 + 业务仓"，导致治理失控

**核心裁决**:
> 当前真正缺的不是更多功能，而是**统一控制面 + 单一真值状态机**。

---

## 3. 旧链路停用清单

### 3.1 立即停用的模式

| 旧模式 | 问题 | 替代方案 |
|--------|------|----------|
| 手工 `sessions_spawn` 续推 | 状态不持久化，依赖聊天记忆 | `orch_product run` 自动注册 observability card |
| 口头 next-step 追踪 | 无真值锚点，压缩后丢失 | `closeout.next_step` + `dashboard` |
| 手工 callback 处理 | 容易遗漏，无标准 closeout | `orchestrator_callback_bridge.py complete` |
| 聊天状态同步 | 非结构化，不可查询 | `orch_product status` + observability board |
| trading repo 持有 control plane | 职责混杂，治理失控 | control plane 接管，trading 退回业务叶子层 |

### 3.2 旧代码路径处理

**保留**（作为 business leaf）:
- `workspace-trading/research/v2_portfolio/*` — 研究/回测核心
- `workspace-trading/research/data_portal/*` — 数据契约
- `skills/trading-quant/scripts/intraday_monitor.py` — runtime tool
- `skills/trading-quant/scripts/macro_linkage.py` — runtime tool

**降级/归档**:
- `search-kol-sources-20260322` — 不进主线，归档
- `feat/wire-alerts-to-trading-spider` — 不进主线，归档
- `feat/real-theme-source-minimal-20260322` — 仅最小救援式提取
- `tmp/*` — 清理

**控制平面收口**:
- 任务派发 → `orch_product run`
- 状态追踪 → `orch_product status`
- 续推决策 → control plane closeout + next_step
- Dashboard → observability card board

---

## 4. 新链路设计

### 4.1 产品入口三件套

#### Onboard — 查看频道接入建议

```bash
# trading_roundtable 场景
python3 runtime/scripts/orch_product.py onboard \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --owner "trading"

# 输出：
# - adapter: trading_roundtable
# - scenario: trading_roundtable_phase1
# - owner: trading
# - backend: subagent (auto-recommended)
# - gate_policy: stop_on_gate
```

#### Run — 触发执行

```bash
# 触发首批任务 1: Capital Flow Contract Hardening
python3 runtime/scripts/orch_product.py run \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --task "Harden capital-flow runtime contract: 把历史资金流不可得从硬错误改成标准 degrade/warning 语义" \
  --workdir /Users/study/.openclaw/workspace-trading \
  --type coding \
  --duration 60 \
  --owner "trading"

# 输出：
# - task_id: trading_20260331_xxx
# - dispatch_id: dispatch_xxx
# - backend: subagent
# - session_id: subagent-xxx
# - callback_path: ~/.openclaw/shared-context/dispatches/dispatch_xxx-callback.json
```

#### Status — 查看状态

```bash
# 查看 trading 场景状态
python3 runtime/scripts/orch_product.py status \
  --scenario "trading_roundtable_phase1" \
  --owner "trading" \
  --output json

# 输出：
# - summary: { total, active, completed, failed }
# - active_tasks: [...]
# - completed_tasks: [...]
# - blockers: [...]
# - next_steps: [...]
```

### 4.2 Single-Writer + Auto-Continue + Closeout Contract

#### Single-Writer (per truth-domain)

根据 `entry_defaults.py` 和 `trading-control-plane-integration-v1`:

```python
# truth_domain 枚举
{
  "strategy": "策略候选 / acceptance / benchmark",
  "data": "数据源 / contract / freshness / coverage",
  "repo": "分支 / worktree / 文档 / archive",
  "ops": "cron / dashboard / monitor / health",
  "adapter": "news/theme/sentiment/alert 等输入增强"
}

# Single-writer guard: 每个 truth_domain 在同一时间只允许一个 active writer
# 防止并发修改导致的状态冲突
```

#### Auto-Continue (whitelist-based)

根据 `trading_roundtable.py`:

```python
# 默认策略：safe semi-auto
# - 总是持久化 summary / decision / dispatch plan
# - 默认只对白名单的 clean PASS continuation 自动续跑
# - 其余仍保持 skipped

# 白名单条件:
# 1. overall_gate == "PASS"
# 2. truth_anchor 完整 (artifact/report/commit)
# 3. continuation whitelist 命中
# 4. gate_policy != "stop_on_gate" 或显式 allow_auto_dispatch=true
```

#### Closeout Contract (4 字段最小)

根据 `trading-control-plane-integration-v1`:

```json
{
  "stopped_because": "completed|failed|blocked|waiting_gate",
  "truth_anchor": "artifact/report/status path",
  "next_step": "下一步明确动作",
  "next_owner": "main|trading|subagent|tmux|human_gate"
}
```

**规则**:
- 没有 `truth_anchor`，不得宣称完成
- 没有 `next_step`，不得自动续跑
- 命中 gate 时必须写 `waiting_gate`
- `closeout_recorded` 之后，才允许 `next_step_decided`

---

## 5. 最小执行命令示例

### 5.1 Onboard (首次接入)

```bash
# 查看 trading_roundtable 接入建议
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py onboard \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --owner "trading" \
  --output json | jq '.recommendation'
```

### 5.2 Run (首批任务)

```bash
# Task 1: Capital Flow Contract Hardening
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py run \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --task "Harden capital-flow runtime contract: 把历史资金流不可得从硬错误改成标准 degrade/warning 语义，并把 real/proxy/realtime_only 明确写入 runtime contract" \
  --workdir /Users/study/.openclaw/workspace-trading \
  --type coding \
  --duration 60 \
  --owner "trading"

# Task 3: Repo Closure & Branch Recovery (可与 Task 1 并发)
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py run \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --task "Close dirty repo state and recover minimal branch truth: 把 workspace-trading 当前脏状态、tmp 污染和未回收分支整理成可治理状态" \
  --workdir /Users/study/.openclaw/workspace-trading \
  --type documentation \
  --duration 45 \
  --owner "main"
```

### 5.3 Status (监控进度)

```bash
# 查看 trading 场景状态
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py status \
  --scenario "trading_roundtable_phase1" \
  --limit 10

# JSON 输出用于程序化处理
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py status \
  --scenario "trading_roundtable_phase1" \
  --output json | jq '.summary'
```

### 5.4 续推 (Closeout 完成后)

```bash
# Task 2: Strategy Acceptance Rerun (Task 1 完成后)
python3 /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/scripts/orch_product.py run \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --task "Rerun strategy acceptance under corrected capital-flow semantics: 在修正后的资金流契约下重新跑 frozen candidate acceptance" \
  --workdir /Users/study/.openclaw/workspace-trading \
  --type research \
  --duration 90 \
  --owner "trading"
```

---

## 6. Cutover 步骤

### Phase 1 — Contract First (立即执行)

1. ✅ 完成设计摘要（本文件）
2. ⏳ main 在 trading_roundtable 频道宣布 cutover 决定
3. ⏳ 用 `orch_product onboard` 生成第一个接入建议
4. ⏳ 用 `orch_product run` 派发首批任务（Task 1 + Task 3）

### Phase 2 — Scenario Wiring (Phase 1 完成后)

1. ⏳ 验证 `orch_product run` 触发的任务能正常进入 control plane
2. ⏳ 验证 callback / ack / dispatch artifacts 正常生成
3. ⏳ 验证 `orch_product status` 能正确返回状态
4. ⏳ 验证 closeout 4 字段完整写入

### Phase 3 — Unified Runtime (Phase 2 完成后)

1. ⏳ 所有 trading task 都通过 `orch_product run` 派发
2. ⏳ 所有状态查询都通过 `orch_product status`
3. ⏳ 所有续推都通过 closeout + auto-continue 机制
4. ⏳ 不再使用手工 sessions_spawn 续推

### Phase 4 — Repo Slimming (Phase 3 完成后)

1. ⏳ archive 临时/实验内容
2. ⏳ 回收或放弃 feature branches
3. ⏳ 保留 core research / adapter / runtime tool 必要最小集
4. ⏳ 更新 trading repo README 明确新边界

---

## 7. 成功标准

v1 cutover 成功标准不是"自动赚钱"，而是：

1. ✅ trading task 全部可进入统一 schema
2. ✅ trading task 状态全部可在 dashboard 上看见
3. ✅ 完成/失败/blocked 都有 closeout truth
4. ✅ next-step 不再靠聊天记忆维持
5. ✅ main 只做 dispatch / dashboard / next-step / gate
6. ✅ workspace-trading 不再兼任 orchestration owner
7. ✅ 不再使用手工 sessions_spawn 续推链
8. ✅ 统一使用 `orch_product onboard/run/status` 三件套

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| **旧链路依赖未完全切断** | 新旧混用导致状态分裂 | main 明确宣布 cutover，不再使用手工 sessions_spawn |
| **closeout 字段缺失** | auto-continue 无法触发 | 验证 closeout 4 字段完整写入后再续推 |
| **observability card 缺失** | status 返回空结果 | run 命令自动注册 card，检查创建是否成功 |
| **gate 策略配置错误** | 不该停的停了/该停的没停 | 默认 `stop_on_gate`，显式 `allow_auto_dispatch` 覆盖 |
| **trading repo 职责不清** | 又回到半调度半业务仓 | 明确 trading repo 只做 business leaf，control plane 在 orchestration monorepo |

---

## 9. 回退方案

如果新入口出现问题：

1. **立即回退**: 恢复使用 `orch_command.py contract` + 手工 dispatch
2. **真值不受影响**: 新入口不修改现有 state 文件 / card 文件 / dispatch 文件
3. **已有任务继续运行**: subagents / tmux sessions 不受影响，继续通过原有 callback 机制完成

**回退命令**:
```bash
# 恢复使用旧入口
python3 runtime/scripts/orch_command.py contract \
  --context "trading_roundtable" \
  --scenario "trading_roundtable_phase1" \
  --owner "trading"
```

---

## 10. 附录：完整任务 Schema 示例

```json
{
  "task_id": "trading_20260331_001",
  "scenario": "trading_roundtable_phase1",
  "task_type": "engineering",
  "truth_domain": "data",
  "owner": "trading",
  "executor": "claude_code",
  "backend_preference": "subagent",
  "priority": "P0",
  "title": "Harden capital-flow runtime contract",
  "goal": "把历史资金流不可得从硬错误改成标准 degrade/warning 语义",
  "inputs": [
    "research/v2_portfolio/portfolio_backtest.py",
    "research/v2_portfolio/strategy_context.py"
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

---

## 11. 参考文档

- [`docs/orch_product_guide.md`](../orch_product_guide.md) — 产品使用指南
- [`docs/design/orch-product-entry-design-2026-03-30.md`](design/orch-product-entry-design-2026-03-30.md) — 设计摘要
- [`docs/plans/trading-control-plane-integration-v1-2026-03-30.md`](trading-control-plane-integration-v1-2026-03-30.md) — trading 控制面集成方案
- [`docs/plans/trading-current-chain-mapping-v1-2026-03-30.md`](trading-current-chain-mapping-v1-2026-03-30.md) — 当前链路映射
- [`docs/plans/trading-first-five-control-plane-task-list-v1-2026-03-30.md`](trading-first-five-control-plane-task-list-v1-2026-03-30.md) — 首批任务列表

---

## 12. 总结

**一句话裁决**:

> **把 trading_roundtable 从半手工链路切到 `orch_product onboard/run/status` 产品入口，trading repo 退回业务执行叶子层，control plane 接管任务编排/状态推进/dashboard/next-step。**

**最小行动**:

```bash
# 1. 查看接入建议
orch_product.py onboard --context "trading_roundtable"

# 2. 触发首批任务
orch_product.py run --context "trading_roundtable" --task "..." --workdir /path/to/trading

# 3. 查看状态
orch_product.py status --scenario "trading_roundtable_phase1"
```

其他都是细节。
