# OpenClaw Thin Orchestration Roadmap

> 配套详单：`docs/implementation-backlog.md`

## 一句话目标

把当前 proposal repo 从“P0 文档 + repo-local POC”推进到“官方 Lobster 底座 + 最小 scheduler/dispatch + state/callback 真值 + workspace-trading 首个离线 pilot workflow”。

---

## 当前基线

已具备：
- `poc/lobster_minimal_validation/`：chain / human-gate / failure-branch 最小验证
- `poc/subagent_bridge_sim/`：subagent terminal + callback status 模拟器
- `schemas/minimal-task-registry.schema.json`：6 字段 registry
- `plugins/human-gate-message/`：human-gate plugin 源码归位

尚未具备：
- 官方 Lobster 真接线
- 统一 workflow model / parser
- 可复用 scheduler / dispatch
- registry library / callback outbox
- workspace-trading 首个真实 workflow
- timeline / backlog / stuck-task 可观测性

---

## Phase 0：口径冻结（先做文档，不求重代码）

### 目标
把“边界、模板、状态、pilot 范围”一次讲清楚，避免边做边改。

### 任务
- 官方 Lobster 接入方案冻结
- Workflow model 冻结
- Scheduler / dispatch 边界冻结
- State / callback contract 冻结
- `workspace-trading` 首个 pilot 选型冻结
- Observability contract 冻结
- Guard matrix 冻结

### 完成定义
- 以上 7 类文档全部落地
- 与现有 `README.md` / `docs/executive-summary.md` / `docs/supporting/thin-orchestration-layer.md` 不冲突

---

## Phase 1：主干打通（官方底座 + registry + scheduler）

### 目标
先把最关键的一条主链跑通：

```text
official lobster
  -> workflow step dispatch
  -> subagent handoff
  -> terminal ingest
  -> callback status
```

### 任务
- 官方 Lobster wrapper 接入
- ✅ `chain-basic` 已切到官方 runtime（canonical=`poc/official_lobster_bridge/`，fallback=`poc/lobster_minimal_validation/`）
- Registry library（upsert / patch / atomic write）
- 最小 scheduler / dispatcher
- subagent dispatch adapter 升格
- terminal ingest + callback outbox

### 完成定义
- `chain-basic` 能运行在官方 runtime
- `task_id` 能跨 step / subagent / terminal / callback 保持一致
- `state` 与 `callback_status` 分离

---

## Phase 2：模板补全（human-gate / failure-branch / parallel/join）

### 目标
让薄层具备“够用而非泛化”的模板能力。

### 任务
- chain / human-gate / failure-branch 统一执行语义
- human decision payload verifier / resolver
- `parallel / join` contract + 最小实现
- external dispatch / reconcile compatibility strategy

### 完成定义
- 3 个核心模板可跑
- `parallel / join` 至少完成 contract-first 验证
- human-gate 不再依赖裸 CLI verdict string

---

## Phase 3：workspace-trading 首个 Pilot

### 目标
选一条**离线、可回退、无真实交易副作用**的 workflow 做真实试点。

### 推荐 pilot
**离线策略实验闭环**：
1. 接收实验 brief
2. 在 `workspace-trading` 派发 subagent 执行离线实验/测试
3. 收集 report / artifact
4. 可选 human gate 决定继续、降级或终止
5. 回写 callback 与 timeline

### 任务
- pilot workflow 文档冻结
- workflow definition + adapter binding
- workspace-trading 验收 harness / runbook

### 完成定义
- 能重复执行 dry-run
- 不触发 live trading / gateway side effect
- 产物、evidence、callback、回退口径都固定

---

## Phase 4：Observability 与 Optional Guards

### 目标
在试点扩大前，把“能看见问题”和“能快速止损”补齐。

### 任务
- timeline writer / assembler
- backlog / stuck-task / callback failure 视图
- feature flags / kill switch
- workspace / idempotency / duplicate guards
- timeout / manual override / degraded path

### 完成定义
- 单条 workflow 有 timeline JSON + summary
- 能识别 stuck / callback failed / terminal missing
- 能一键切回旧 harness 或禁用 pilot

---

## 推荐并行策略

### 并行 Lane A：方案冻结
文档类任务可并行推进，优先出 canonical contract。

### 并行 Lane B：主干实现
围绕 `official runtime + registry + scheduler + subagent bridge + callback` 串行推进，减少返工。

### 并行 Lane C：模板与 human-gate
在主干稳定后，可并行推进 human-gate resolver 与 `parallel/join` contract。

### 并行 Lane D：pilot 与 observability
pilot workflow 与 timeline/health report 可以条件并行，但以主干稳定为前提。

---

## 不做清单（本轮明确排除）

- 不把 taskwatcher 重新升格为 backbone
- 不做通用 DAG / 动态图引擎
- 不做 Temporal-first 全迁
- 不做 LangGraph-first 公司级编排
- 不做 live trading / 线上 gateway 变更
- 不做重型 callback platform / distributed scheduler

---

## 里程碑判断

### M1：主干闭环成立
官方 runtime + subagent + terminal + callback 已跑通

### M2：模板闭环成立
human-gate / failure-branch / parallel/join 达到最小可执行

### M3：trading pilot 成立
`workspace-trading` 首条 workflow 可重复 dry-run

### M4：试点前安全线成立
可观测性、feature flag、workspace/idempotency guards 到位
