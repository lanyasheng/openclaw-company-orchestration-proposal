# OpenClaw 公司级编排架构审查报告 (2026-03-24)

> **审查类型**: 架构阶段收官审查  
> **审查日期**: 2026-03-24  
> **审查者**: Zoe (CTO & Chief Orchestrator)  
> **审查范围**: Temporal vs LangGraph / OpenClaw 公司级编排架构主线  
> **目标**: 系统性回答"我们现在到底做到了什么、还没做到什么、真正的复杂度在哪、主要风险是什么、为什么当前选择是合理的"

---

## 执行摘要

### 核心结论

**当前架构值得继续沿主线推进。**

**理由**:
1. ✅ **控制面主链已打通**: 注册 → 派发 → 执行 → receipt → callback 完整链路已验证
2. ✅ **测试覆盖充分**: 468 个测试全部通过 (100% 通过率)
3. ✅ **双轨后端策略清晰**: subagent (默认) + tmux (兼容) 边界明确
4. ✅ **生产验证就绪**: trading continuation 真实执行路径已验证
5. ⚠️ **成熟度边界清晰**: safe semi-auto / thin bridge / allowlist，非"全域全自动"

**不推荐引入 Temporal/LangGraph 作为 backbone 的原因**:
- 当前复杂度主要在 **Agent 交接的显式 contract**，而非 durable execution 或 reasoning graph
- OpenClaw 原生原语已足够支撑控制面，外部框架只应进入叶子执行层
- 重型基础设施的引入时机应在高价值 durable 场景被识别后，而非当前阶段

---

## 1. 背景与问题定义

### 1.1 核心问题

> **当一个任务完成后，系统如何知道下一步该做什么——并且安全地继续推进？**

这个问题看起来简单，但在真实多 Agent 系统中表现为：

| 症状 | 根因 |
|------|------|
| 一个任务结束了，但没人知道谁拥有下一步 | 归属模糊 (owner vs executor 未分离) |
| 多个子任务都回来了，但没有 clean fan-in 点 | 缺少显式 handoff contract |
| 系统能生成计划，却不能安全地自动派发下一步 | 缺少 continuation contract 与 gate 机制 |
| callback 发出去了，但没有正确回到父会话或用户可见频道 | callback ≠ 状态转移，混在一起产生歧义 |
| 业务归属和执行归属混在一起 | 缺少 owner/executor 解耦设计 |

### 1.2 为什么这不是普通 prompt orchestration

**普通 prompt orchestration 的典型模式**:
```
用户请求 → Prompt → Agent 运行 → Callback → 结束
```

**这种模式对单轮任务有效，对多步工作流会失效，原因**:

| 缺口 | 症状 | 我们的方案 |
|------|------|-----------|
| **没有显式收口** | Agent 完成但系统不知道"为什么停" | Continuation contract 带 `stopped_because` |
| **没有归属分离** | 业务逻辑与执行逻辑混在一起 | Owner/Executor 解耦 |
| **没有 readiness 追踪** | 前提条件未满足就派发下一步 | Registration + readiness check |
| **没有安全门** | 自动续推没有白名单控制 | 白名单 gate policy |
| **没有可追溯性** | 无法从结果追溯到决策 | 完整 artifact linkage 链 |

**关键洞察**: 真实的多 Agent 系统很少因为"模型无法回答"而失败。它们失败是因为**任务间的过渡没有被显式表达**。

### 1.3 为什么需要控制面

```
┌─────────────────────────────────────────────────────────────┐
│ 没有控制面                                                  │
│                                                             │
│   Agent A → 完成 → "完了？"                                │
│              ↓                                              │
│   Agent B → ？？？（谁触发？谁拥有？）                      │
│                                                             │
│   结果：静默失败、孤儿任务、手工胶水                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 有控制面                                                    │
│                                                             │
│   Agent A → 完成 → Receipt → Callback → 决策               │
│                                      ↓                      │
│   Registration → Readiness → Gate Check → Dispatch → B     │
│                                                             │
│   结果：显式过渡、可追溯、安全自动化                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. 当前架构分层与真实运行路径

### 2.1 分层模型

```
┌─────────────────────────────────────────────────────────────┐
│ 业务场景层                                                  │
│ - Trading Roundtable                                        │
│ - Channel Roundtable                                        │
│ - 未来领域适配器                                            │
└─────────────────────────────────────────────────────────────┘
                          ↓ 使用
┌─────────────────────────────────────────────────────────────┐
│ 控制面层（本仓库）                                          │
│ - Contracts & Planning (handoff_schema, contracts)          │
│ - Registration & Readiness (task_registry, state_machine)   │
│ - Dispatch & Continuation (dispatch_planner, auto_dispatch) │
│ - Callbacks & Receipts (callback_router, completion_receipt)│
└─────────────────────────────────────────────────────────────┘
                          ↓ 调度
┌─────────────────────────────────────────────────────────────┐
│ 执行层                                                      │
│ - subagent (默认，自动化)                                   │
│ - Claude Code (coding lane)                                 │
│ - tmux (兼容，交互可观测)                                   │
│ - Browser / Message / Cron (标准 activity)                  │
└─────────────────────────────────────────────────────────────┘
                          ↓ 基于
┌─────────────────────────────────────────────────────────────┐
│ OpenClaw Runtime 基础层                                     │
│ - Sessions / Tools / Hooks / Channels / Messaging           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 真实运行路径 (以 trading continuation 为例)

```
用户请求 (Discord #trading)
       ↓
orch_command.py (入口命令)
       ↓
trading_roundtable.py (场景适配器)
       ↓
build_planning_handoff() → PlanningHandoff
       ↓
task_registry.register() → registration_id
       ↓
readiness_check() + gate_policy_check()
       ↓
   ┌──────────────────────────────────────┐
   │ Gate 通过？                          │
   ├──────────────────────────────────────┤
   │ ✅ Yes → 自动派发                    │
   │   ↓                                  │
   │ dispatch_planner.create_dispatch()   │
   │   ↓                                  │
   │ sessions_spawn_bridge.spawn()        │
   │   ↓                                  │
   │ subagent 执行 (Claude Code)          │
   │   ↓                                  │
   │ completion_receipt.generate()        │
   │   ↓                                  │
   │ callback_bridge.emit()               │
   │   ↓                                  │
   │ 下一步决策 (continuation/terminal)   │
   │   ↓                                  │
   │ 有下一步 → 注册下一批                │
   │ 无下一步 → closeout                 │
   └──────────────────────────────────────┘
       ↓
   ❌ No → wait_at_gate
       ↓
   人工决策 (Discord 消息)
```

### 2.3 Artifact 链路 (追溯性保证)

```
registration_id (任务注册)
       ↓
dispatch_id (派发计划)
       ↓
spawn_id (sessions_spawn 请求)
       ↓
execution_id (执行记录)
       ↓
receipt_id (完成回执)
       ↓
request_id (执行请求)
       ↓
consumed_id (bridge consumption)
       ↓
api_execution_id (childSessionKey / runId)
```

**任何 ID 都可用于查询完整链路状态。**

---

## 3. 已验证能力 vs 未闭环能力

### 3.1 已验证能力 (有真值锚点)

| 能力 | 证据位置 | 状态 |
|------|----------|------|
| **控制面主链打通** | `tests/orchestrator/` (468 tests), `runtime/orchestrator/` | ✅ 已验证 |
| **Trading continuation** | `~/.openclaw/shared-context/` 中的真实执行 artifact | ✅ 已验证 |
| **双轨后端策略** | `docs/migration/migration-retirement-plan.md`, `continuation_backends.py` | ✅ 已确立 |
| **Owner/Executor 解耦** | `docs/plans/owner-executor-decoupling.md`, `handoff_schema.py` | ✅ 已实现 |
| **Auto-trigger consumption** | `sessions_spawn_request.py`, `bridge_consumer.py` | ✅ 已实现 |
| **Complete artifact 链路** | `callback_auto_close.py`, `sessions_spawn_bridge.py` | ✅ 已验证 |
| **测试覆盖** | 468 个测试，100% 通过率 | ✅ 已验证 |
| **架构健康度** | `docs/reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md` (95/100) | ✅ 已审查 |

### 3.2 未闭环能力 (有明确边界)

| 能力 | 当前状态 | 说明 |
|------|----------|------|
| **完整 Git push 自动续推** | ⚠️ 内部模拟闭环 | 真实 push 执行器待实现 |
| **CLI 集成** | ⚠️ Mock API call | OpenClaw CLI `sessions_spawn` 命令需确认 |
| **Auto-trigger 配置版本控制** | ⚠️ 本地 JSON | 见 `docs/technical-debt/technical-debt-2026-03-22.md` D5 |
| **全域全自动无人续跑** | ❌ 范围外 | 不是设计目标 |
| **Temporal/LangGraph 集成** | ❌ 不进入主链 | 仅高价值 durable pilot 时考虑 |

### 3.3 诚实总结

> **已不只是方案稿，但也还没重到可以叫"通用 workflow 平台"。**

**当前成熟度**: safe semi-auto / thin bridge / allowlist / trading 生产验证

---

## 4. 关键机制现状

### 4.1 User-Visible Closeout

**定义**: Closeout artifact 交付到用户可见频道 (如 Discord 消息)。

**现状**:
- ✅ Terminal closeout: 无下一步时最终交付给用户
- ✅ Continuation closeout: 有下一步时告知用户"已自动续推"
- ⚠️ User-visible closeout 与 terminal closeout 的分离已设计，但未完全自动化

**证据**:
- `completion_receipt.py`: 生成 completion receipt artifact
- `callback_auto_close.py`: 生成 callback close artifact
- `trading_roundtable.py`: 注入 closeout 状态到 orchestration_contract

### 4.2 Truth Anchor

**定义**: 所有其他状态引用的规范状态记录 (Task Registry Entry)。

**现状**:
- ✅ Task Registry 已实现 (`task_registry.py`)
- ✅ registration_id 作为所有 artifact 的根引用
- ✅ 支持通过任意 ID 反向查询完整链路

**证据**:
- `runtime/orchestrator/core/task_registry.py`
- `docs/CURRENT_TRUTH.md` (当前真值入口)

### 4.3 Owner-Executor Decoupling

**定义**: 业务归属 (owner) 与执行归属 (executor) 分离。

**现状**:
- ✅ `PlanningHandoff` 包含 `owner` / `executor` / `backend_preference` / `execution_profile`
- ✅ Coding lane 默认 `executor=claude_code`
- ✅ Non-coding lane 默认 `executor=subagent`
- ✅ 自动推导规则已实现 (`_resolve_executor_from_profile_and_task()`)

**证据**:
- `docs/plans/owner-executor-decoupling.md`
- `runtime/orchestrator/core/handoff_schema.py`
- `tests/orchestrator/test_owner_executor_decoupling.py` (23 tests)

### 4.4 Continuation

**定义**: 任务完成后"下一步怎么走"的显式 contract。

**现状**:
- ✅ `ContinuationContract` 包含 `stopped_because` / `next_step` / `next_owner` / `readiness`
- ✅ Trading continuation 真实执行路径已验证
- ✅ Channel roundtable 通用适配器就绪
- ⚠️ 默认仍是 allowlist / 条件触发 / 可回退

**证据**:
- `runtime/orchestrator/contracts.py`
- `runtime/orchestrator/trading_roundtable.py`
- `runtime/orchestrator/channel_roundtable.py`

### 4.5 Gate

**定义**: 可以阻止自动派发的安全检查点。

**现状**:
- ✅ Allowlist gate: 场景不在白名单中
- ✅ Readiness gate: 前提条件未满足
- ✅ Manual approval gate: 需要人工决策
- ✅ Policy gate: 策略评估失败
- ✅ Gate policy 配置：`stop_on_gate` (默认)

**证据**:
- `runtime/orchestrator/auto_dispatch.py`
- `runtime/orchestrator/entry_defaults.py`
- `docs/policies/waiting-integrity-hard-close-policy-2026-03-21.md`

---

## 5. 为什么不把 Temporal / LangGraph 直接当 backbone

### 5.1 Trade-Off 分析

| 框架 | 优势 | 为什么不是我们的 backbone |
|------|------|------------------------|
| **Temporal** | Durable execution、worker 管理、版本控制 | 重型基础设施；我们需要的是 Agent 交接的薄控制面，不是企业 workflow engine |
| **LangGraph** | Agent 内部 reasoning graph | 擅长单 Agent reasoning；我们需要的是跨多 Agent 的公司级编排 |
| **DAG Engine** | 通用工作流组合 | 我们的模式不是纯 DAG；我们需要显式的 handoff contracts，不是图遍历 |

### 5.2 我们的决策

```
┌─────────────────────────────────────────────────────────────┐
│ 控制面策略                                                  │
│                                                             │
│ OpenClaw Native (控制面):                                   │
│   - 入口 (orch_command.py)                                 │
│   - sessions_spawn 集成                                    │
│   - Launch/completion hooks                                │
│   - Callback bridge                                        │
│   - 场景适配器                                             │
│   - Watcher/reconcile 边界                                 │
│                                                             │
│ 外部框架（仅叶子层）：                                      │
│   - DeepAgents: coding subagent profile                    │
│   - SWE-agent: issue-to-patch lane                         │
│   - LangGraph: 局部 analysis graphs（如需要）              │
│   - Temporal: durable pilots（未来，仅高价值）             │
└─────────────────────────────────────────────────────────────┘
```

### 5.3 设计原则

> **OpenClaw 持有控制面；外部框架只进入叶子执行层、benchmark 层、或局部方法层。**

### 5.4 何时重新评估

| 场景 | 考虑 |
|------|------|
| 跨天 durable execution | Temporal pilot 用于高价值工作流 |
| 复杂单 Agent reasoning | LangGraph 用于 analysis graphs |
| 企业合规要求 | 重新评估 durable execution guarantees |

---

## 6. 当前系统最脆弱的环节

### 6.1 P0 级脆弱点

| 脆弱点 | 风险 | 缓解措施 |
|--------|------|---------|
| **trading_roundtable.py 职责过大** | 1500 行，职责混杂 (adapter/business/dispatch/status)，难以测试和维护 | 技术债务 D1: 拆分为 adapter.py / business_rules.py / dispatch.py / status.py / main.py |
| **真实 Git push 执行器未实现** | 当前使用 `simulate_push_success()` 模拟，production 环境需真实 push | P1 项：实现真实 git push 执行器 + 失败回滚机制 |
| **Auto-trigger 配置缺少版本控制** | 使用本地 JSON 文件，缺少审计日志 | 技术债务 D5: 集成到 OpenClaw 配置系统 |

### 6.2 P1 级脆弱点

| 脆弱点 | 风险 | 缓解措施 |
|--------|------|---------|
| **Continuation v1-v8 模块收口** | 模块间耦合度高，链路追踪复杂 | 技术债务 D2: 创建 `continuation_kernel.py` 统一入口 |
| **文档去重瘦身** | CURRENT_TRUTH.md 与 README.md 内容有重叠 | 技术债务 D3: README 保留 5 分钟快速开始，CURRENT_TRUTH 聚焦当前迭代真值 |
| **缺少端到端集成测试** | 缺少从 handoff → registration → dispatch → execution → receipt 的完整链路测试 | 测试改进：添加 E2E 测试 |

### 6.3 系统性风险

| 风险 | 说明 |
|------|------|
| **过早重型化** | 在模式稳定前引入 Temporal/LangGraph 会导致过度工程化 |
| **静默失败** | 没有显式 closeout contract 会导致任务结束后不知道"为什么停" |
| **归属模糊** | owner/executor 未分离会导致业务逻辑与执行逻辑混在一起 |
| **不可追溯** | 缺少 artifact linkage 会导致出问题时无法追溯完整决策链 |

---

## 7. 真实成熟度判断

### 7.1 成熟度矩阵

| 方面 | 状态 | 说明 |
|------|------|------|
| **后端策略** | ✅ 双轨兼容 | subagent（默认）+ tmux（兼容） |
| **Trading continuation** | ✅ 生产验证 | 真实执行路径已验证 |
| **Channel roundtable** | ✅ 最小适配器 | 通用频道接入 |
| **控制面主链** | ✅ 已打通 | 注册 → 派发 → 执行 → receipt → callback |
| **测试** | ✅ 468 个通过 | 100% 通过率 |
| **自动续推** | ⚠️ safe semi-auto | 白名单、条件触发、可回退 |
| **Git push 自动续推** | ⚠️ 尚未完全自动 | 内部模拟闭环已通；真实 push 执行器待实现 |
| **CLI 集成** | ⚠️ Mock API call | OpenClaw CLI 集成需确认 |
| **Auto-trigger 配置** | ⚠️ 本地 JSON | 版本控制待完成（见 technical debt） |

### 7.2 哪些是真的 vs. 哪些还没闭环

| 声称 | 证据 | 状态 |
|------|------|------|
| Trading continuation 有效 | `~/.openclaw/shared-context/` 中的真实执行 artifact | ✅ 已验证 |
| 控制面主链打通 | 468 个测试通过，artifact 生成 | ✅ 已验证 |
| Auto-trigger consumption | 可配置的 guards、去重机制 | ✅ 已实现 |
| 完整 Git push 自动续推 | 仅内部模拟 | ⚠️ 未完全闭环 |
| 通用全自动无人续跑 | 不是设计目标 | ❌ 范围外 |

### 7.3 诚实总结

> **已不只是方案稿，但也还没重到可以叫"通用 workflow 平台"。**

**当前正确理解**:
- ✅ 已有真实 continuation 场景 (trading / channel)
- ✅ 控制面主链已打通 (注册 → 派发 → 执行 → receipt → callback)
- ✅ 测试覆盖充分 (468 个测试，100% 通过率)
- ⚠️ 但总体仍停留在 **thin bridge / allowlist / safe semi-auto**
- ⚠️ 外部框架讨论的是下一阶段增强点，不是当前主链 owner

---

## 8. 结论：当前架构是否值得继续沿主线推进

### 8.1 推荐继续推进

**理由**:

1. **控制面主链已验证**: 注册 → 派发 → 执行 → receipt → callback 完整链路已打通，468 个测试全部通过
2. **生产验证就绪**: trading continuation 真实执行路径已验证，channel roundtable 通用适配器就绪
3. **架构健康**: 架构健康度 95/100，无关键/高优先级问题
4. **边界清晰**: 双轨后端策略明确，external framework 只进叶子层
5. **技术债务可管理**: 已知债务已收敛到 `docs/technical-debt/technical-debt-2026-03-22.md`，优先级清晰

### 8.2 不推荐引入重型框架

**理由**:

1. **当前复杂度不在 durable execution**: 主要复杂度在 Agent 交接的显式 contract，而非 temporal 的强项
2. **当前复杂度不在 reasoning graph**: 主要复杂度在跨多 Agent 的公司级编排，而非 langgraph 的单 agent reasoning
3. **OpenClaw 原生原语已足够**: sessions_spawn / hooks / callback bridge 已足够支撑控制面
4. **过早重型化风险**: 在模式稳定前引入重型框架会导致过度工程化

### 8.3 下一阶段重点

**P0: Contract 基线**
- gstack-style planning default
- Continuation contract v1
- Issue lane baseline
- Heartbeat boundary freeze

**P1: 叶子 Pilots**
- DeepAgents / SWE-agent leaf pilots
- Planning → execution handoff 标准化
- `stopped_because / next_step / owner` 标准化

**P2: 选择性重型 Pilots**
- 仅在高价值 durable 场景试点 Temporal
- 仅在复杂 analysis 场景试点 LangGraph
- 继续观察，不进主链

### 8.4 最终判定

> **当前架构值得继续沿主线推进。**

**推荐策略**: 
1. 继续 OpenClaw native 控制面
2. 外部框架只进叶子层 / benchmark / 局部方法层
3. 先规划、先 contract、再自动推进
4. 先叶子 pilot，再决定是否扩大

---

## 附录 A: 关键文档索引

| 文档 | 路径 | 目的 |
|------|------|------|
| **当前真值** | `docs/CURRENT_TRUTH.md` | 了解"今天系统实际如何工作" |
| **架构分层** | `docs/architecture-layering.md` | 五层架构说明 |
| **整体计划** | `docs/plans/overall-plan.md` | P0/P1/P2 阶段目标 |
| **Owner/Executor 解耦** | `docs/plans/owner-executor-decoupling.md` | 业务归属与执行归属分离 |
| **技术债务** | `docs/technical-debt/technical-debt-2026-03-22.md` | 已知优化点与债务清单 |
| **验证状态** | `docs/validation-status.md` | 已验证/未验证边界 |
| **架构健康度** | `docs/reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md` | 架构审查结果 (95/100) |
| **主线验证** | `docs/review/orchestration-overall-review-2026-03-24.md` | 主线框架完整性审查 |

---

## 附录 B: 测试命令参考

```bash
# 运行全部测试
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/ -v

# 运行 Owner/Executor 解耦测试
python3 -m pytest tests/orchestrator/test_owner_executor_decoupling.py -v

# 运行 Handoff Schema 测试
python3 -m pytest tests/orchestrator/test_handoff_schema.py -v

# 运行 Trading Dispatch Chain 测试
python3 -m pytest tests/orchestrator/test_trading_dispatch_chain.py -v

# 运行 Continuation Backends Lifecycle 测试
python3 -m pytest tests/orchestrator/test_continuation_backends_lifecycle.py -v
```

---

**报告生成时间**: 2026-03-24 19:00 GMT+8  
**审查者**: Zoe (CTO & Chief Orchestrator)  
**Git HEAD**: (待 commit 后填充)  
**下次审查建议**: 2026-04-07 (双周审查) 或 重大变更后
