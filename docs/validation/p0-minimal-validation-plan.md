# P0-2：Lobster 最小验证 POC 设计

> **Historical / superseded note（2026-03-20）**：这是一份 pre-live 的 P0 设计稿，保留作为原始假设与验证计划证据。当前仓库默认口径已推进到 trading/channel 两条真实场景，并补入 clean PASS 条件触发与 `tmux` backend 边界；请优先看 `../CURRENT_TRUTH.md` 与 `../validation-status.md`。

## 0. 目标与边界

- [ ] 目标：验证 Lobster 能否作为 **thin orchestration shell**，先跑通最小编排闭环
- [ ] 只验证 4 项：`chain` / `human-gate` / `failure-branch` / `subagent handoff`
- [ ] 通过标准：
  - [ ] 每条流程都有 `task_id`
  - [ ] 每条流程都能落最小 registry
  - [ ] 每条流程都有 evidence
  - [ ] 每条流程最终 `callback_status` 可见
  - [ ] 不出现重复 final callback
- [ ] P0 只做最小可验证，不做完整平台

---

## 1. 最小 Task Registry

> 只保留 6 个字段，够追踪、够验收、够回调。

| 字段 | 必填 | 示例 | 说明 |
|---|---|---|---|
| `task_id` | 是 | `tsk_p0_chain_001` | 全局唯一任务 ID，用于串联状态、evidence、callback |
| `owner` | 是 | `main` / `zoe` / `ops` | 谁负责该任务 |
| `runtime` | 是 | `lobster` / `subagent` / `human` | 当前执行主体 |
| `state` | 是 | `queued` / `running` / `waiting_human` / `completed` / `failed` / `degraded` | 当前状态，P0 不扩太多枚举 |
| `evidence` | 是 | `run_dir=/tmp/...`、`decision=approve`、`error=timeout` | 最小证据槽；可先用字符串/JSON blob |
| `callback_status` | 是 | `pending` / `sent` / `acked` / `failed` | 是否已向上游/调用方回报 |

### P0 约束

- [ ] registry 先允许 **单文件 / 本地 JSONL / 内存 + dump**，不要求数据库
- [ ] `evidence` 先允许弱结构，P1 再标准化
- [ ] `callback_status` 只解决“是否发过 final”，不做完整 receipt 系统

---

## 2. 验证项 1：CHAIN

### 输入

- [ ] workflow：`chain-basic`
- [ ] 输入 payload：`{"topic":"hello","target":"internal-demo"}`
- [ ] 步骤节点：`step_a -> step_b -> final_callback`

### 步骤

1. [ ] 创建 `task_id=tsk_p0_chain_001`，registry 写入：`state=queued`、`callback_status=pending`
2. [ ] Lobster 启动 `step_a`，更新：`runtime=lobster`、`state=running`
3. [ ] `step_a` 成功后写入 evidence：`step_a=ok`
4. [ ] 进入 `step_b`
5. [ ] `step_b` 成功后写入 evidence：`step_b=ok`
6. [ ] 触发 `final_callback`
7. [ ] registry 更新：`state=completed`、`callback_status=sent/acked`

### 预期输出

- [ ] 两个步骤按顺序执行，无跳步
- [ ] registry 至少可见：`queued -> running -> completed`
- [ ] evidence 至少包含：`step_a=ok`、`step_b=ok`
- [ ] final callback 只发送一次

### 失败条件

- [ ] `step_b` 在 `step_a` 未完成前启动
- [ ] state 没有落库/落文件
- [ ] evidence 缺失，无法证明执行过
- [ ] final callback 重复发送

---

## 3. 验证项 2：HUMAN-GATE

### 输入

- [ ] workflow：`human-gate-basic`
- [ ] 输入 payload：`{"change":"deploy-demo","requires_approval":true}`
- [ ] 人工动作：`approve` 或 `reject`

### 步骤

1. [ ] 创建 `task_id=tsk_p0_human_001`
2. [ ] Lobster 先执行预检查节点，写 evidence：`precheck=ok`
3. [ ] 流程进入人工闸门，registry 更新：`runtime=human`、`state=waiting_human`
4. [ ] 记录人工决定到 evidence：`decision=approve|reject`
5. [ ] 若 `approve`：恢复流程，执行后续完成节点
6. [ ] 若 `reject`：直接结束为 `degraded` 或 `failed`（二选一，P0 固定一种即可）
7. [ ] 更新 `callback_status`

### 预期输出

- [ ] 可以明确停在 `waiting_human`
- [ ] 人工决定能被记录并驱动后续路径
- [ ] `approve` 与 `reject` 至少有 1 条被实际验证
- [ ] final callback 能带上人工决定结果

### 失败条件

- [ ] 流程无法停住，直接穿过 gate
- [ ] 人工决定未写 evidence
- [ ] `approve/reject` 后无法恢复或收尾
- [ ] callback 看不出最终人工结果

---

## 4. 验证项 3：FAILURE-BRANCH

### 输入

- [ ] workflow：`failure-branch-basic`
- [ ] 输入 payload：`{"mode":"force_fail_step_b"}`
- [ ] 失败节点：`step_b`
- [ ] 补偿分支：`fallback_step -> final_callback`

### 步骤

1. [ ] 创建 `task_id=tsk_p0_fail_001`
2. [ ] 执行 `step_a`，预期成功
3. [ ] 执行 `step_b`，通过测试开关强制失败
4. [ ] 写 evidence：`error=forced_failure_at_step_b`
5. [ ] Lobster 不直接崩溃，转入 `failure-branch`
6. [ ] 执行 `fallback_step`（例如：写降级结果/通知人工）
7. [ ] registry 更新为 `degraded` 或 `failed`（P0 需事先固定口径）
8. [ ] 发送 final callback

### 预期输出

- [ ] 主链失败后能进入 fallback 分支
- [ ] evidence 能定位失败点
- [ ] 最终状态不是“卡在 running”
- [ ] final callback 能区分“成功完成”与“降级完成/失败结束”

### 失败条件

- [ ] `step_b` 失败后整个流程直接丢失
- [ ] failure-branch 未触发
- [ ] registry 仍停在 `running`
- [ ] callback 没有失败原因或降级说明

---

## 5. 验证项 4：SUBAGENT HANDOFF

### 输入

- [ ] workflow：`subagent-handoff-basic`
- [ ] 输入 payload：`{"task":"generate_demo_summary"}`
- [ ] 目标 runtime：`sessions_spawn(runtime="subagent")`

### 步骤

1. [ ] 创建 `task_id=tsk_p0_subagent_001`
2. [ ] Lobster 执行 handoff 节点，写 registry：`runtime=subagent`、`state=running`
3. [ ] 调用 `sessions_spawn(runtime="subagent")` 启动子任务
4. [ ] 记录 evidence：`subagent_session_id=...`
5. [ ] 等待子任务 completion event / 回执
6. [ ] 收到回执后写 evidence：`subagent_result=ok|failed`
7. [ ] Lobster 收尾并发送 final callback
8. [ ] registry 更新：`completed` 或 `failed`

### 预期输出

- [ ] handoff 后有可追踪的 `subagent_session_id`
- [ ] 子任务结果能回写到同一个 `task_id`
- [ ] Lobster 知道任务何时完成，而不是“发出即算完成”
- [ ] final callback 只在 subagent 终态后触发

### 失败条件

- [ ] handoff 后丢失关联关系（找不到 session_id）
- [ ] subagent 已完成，但主任务不收敛
- [ ] 主任务提前 callback，造成假完成
- [ ] subagent 失败原因没有写回 evidence

---

## 6. P0 明确不做项

- [ ] 不做通用 DAG 引擎
- [ ] 不做动态节点生成
- [ ] 不做 `parallel` / `join`（本 POC 不覆盖）
- [ ] 不做 browser / message / cron 全量 adapter
- [ ] 不做自动 retry policy / timer / signal / compensation
- [ ] 不做 dead-letter queue
- [ ] 不做 dashboard / 可视化看板
- [ ] 不做数据库持久化标准化（本地 registry 先够用）
- [ ] 不做完整 receipt / 幂等回执系统
- [ ] 不做 Temporal 接入或迁移
- [ ] 不做公司级多租户权限、审计、SLA

---

## 7. P0 出口标准

- [ ] 上述 4 条流程各跑通 1 次
- [ ] 每条流程都能看到最小 registry 记录
- [ ] 每条流程都有 evidence
- [ ] 每条流程都有 final callback 状态
- [ ] 至少证明 1 条人工暂停恢复、1 条失败分支收敛、1 条 subagent 回写闭环

## 8. 一句话结论

- [ ] P0 不是做平台；P0 只是证明：**Lobster 能不能用最小代价把 OpenClaw 的 chain / human gate / failure branch / subagent handoff 串起来，并且可追踪、可收尾。**
