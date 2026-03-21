# Continuation Contract v1

## 结论先行

这版先落一个 **最小可执行 baseline**：

- task registry 顶层继续保持原来的 6 个必填控制字段；
- 额外新增一个 **可选顶层 `continuation` object**，专门承载 closeout / stop reason / next-step contract；
- scheduler 在 **waiting / terminal / callback failed** 三类停点自动回填 continuation；
- `callback.send_once` 会把 continuation 一并带进 final callback payload，避免“任务结束了，但上游不知道为什么停、下一步该谁接”。

当前实现位置：

- `orchestration_runtime/task_registry.py`
- `orchestration_runtime/scheduler.py`
- `orchestration_runtime/builtin_handlers.py`
- `examples/workflows/chain-basic.scheduler.json`
- `examples/workflows/workspace-trading.acceptance-harness.scheduler.json`

---

## 1. Contract v1 最小字段

`continuation` 结构固定为：

```json
{
  "next_step": "review_acceptance_result_and_decide_dispatch",
  "next_owner": "main",
  "next_backend": "manual",
  "auto_continue_if": [
    "business_overall_verdict=PASS",
    "whitelist_allows_triggered_dispatch"
  ],
  "stop_if": [
    "business_overall_verdict!=PASS",
    "artifacts_incomplete",
    "human_override_stop"
  ],
  "stopped_because": "acceptance_result_ready_for_dispatch_decision"
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `next_step` | 当前停住后，下一步应该做什么 |
| `next_owner` | 下一步默认由谁接（如 `main` / `human` / `subagent` / `callback_plane`） |
| `next_backend` | 下一步准备走哪个 backend（如 `manual` / `subagent` / `human` / `callback`） |
| `auto_continue_if` | 满足哪些条件时，允许自动续跑 |
| `stop_if` | 满足哪些条件时，必须停住，不得继续派发 |
| `stopped_because` | 这次为什么停在这里；它是 closeout 的主解释字段 |

v1 约束：

- `stopped_because` 必填且不能为空；
- `auto_continue_if` / `stop_if` 统一归一化为 string list；
- `next_step` / `next_owner` / `next_backend` 允许为空，但字段必须存在；
- v1 先做 **可读 contract**，不是可执行规则引擎。

---

## 2. 为什么放在顶层 `continuation`

当前 registry 主干仍是：

```json
{
  "task_id": "tsk_xxx",
  "owner": "main",
  "runtime": "lobster",
  "state": "running|completed|failed|degraded|...",
  "evidence": {},
  "callback_status": "pending|sent|acked|failed"
}
```

这 6 个字段分别回答：

- 任务是谁；
- 当前 runtime 是谁；
- 业务状态是否 terminal；
- 证据放哪；
- final callback 有没有真的发出去。

但它们**不回答**：

> 为什么停？下一步谁接？按什么条件能继续？

所以 v1 采取最小增量方案：

- 不重写 `state` / `callback_status`；
- 不把 continuation 塞进 `evidence` 的松散 blob；
- 直接增加一个可校验、可读、可转发的顶层 `continuation` object。

---

## 3. 和 orchestration / callback / dispatch 的关系

### 3.1 和 orchestration 的关系

`continuation` 是 **control-plane closeout contract**，不是 watcher 派生字段。

- 谁写：`orchestration_runtime/scheduler.py`
- 何时写：
  - step `waiting`
  - 业务终态成立（`completed / degraded / failed`）
  - callback transport 失败
- 它服务的是：**“停在这里以后，控制层下一步怎么接”**

也就是说：

- `state` 说明任务业务上到了哪；
- `continuation` 说明控制面接下来该怎么接。

### 3.2 和 callback 的关系

`callback_status` 仍然只表示 **final callback delivery 真值**：

- `pending`
- `sent`
- `acked`
- `failed`

它**不替代** continuation。

v1 里的接线是：

1. `callback.send_once` 在发 final callback 前，先拿到当前 continuation；
2. continuation 被塞进 final callback payload；
3. 如果 callback delivery 失败，registry 顶层 continuation 会被改写成：
   - `next_step = retry_final_callback_delivery`
   - `next_owner = callback_plane`
   - `next_backend = callback`
   - `stopped_because = final_callback_delivery_failed`

所以：

- `callback_status` 回答“回执发没发成”；
- `continuation` 回答“现在该怎么接”。

### 3.3 和 dispatch 的关系

v1 **只冻结 contract，不自动放大全局 auto-dispatch**。

当前语义是：

- `continuation` 可以声明 **下一步意图**；
- `auto_continue_if` / `stop_if` 只是 control-plane 条件说明；
- 是否真的 dispatch 下一跳，仍然由上层 orchestration policy / allowlist / human gate 决定。

换句话说：

> continuation v1 先解决“说清楚”，不直接承诺“自动派发”。

这也和当前 live truth 保持一致：

- trading / channel 只有白名单和收紧条件下的最小 auto-dispatch；
- 不是所有任务都默认根据 continuation 自动 spawn 下一轮。

---

## 4. 当前实现到什么程度

### 4.1 registry schema / validation

`task_registry.py` 新增：

- `normalize_continuation_contract(...)`
- `build_continuation_contract(...)`
- `FileTaskRegistry.patch(..., continuation=...)`

效果：registry 顶层 continuation 现在是可校验的，不再只是文档口径。

### 4.2 scheduler 自动回填 baseline

`scheduler.py` 现在有三类默认 continuation：

1. **waiting subagent**
   - `stopped_because = waiting_for_subagent_terminal`
2. **waiting human**
   - `stopped_because = waiting_for_human_decision`
3. **terminal**
   - `workflow_completed`
   - `workflow_degraded`
   - `workflow_failed`
4. **callback failed**
   - `stopped_because = final_callback_delivery_failed`
   - `next_step = retry_final_callback_delivery`

### 4.3 callback adapter 接线

`builtin_handlers.py::callback_send_once_handler(...)` 已做最小接线：

- final callback payload 自动带 `continuation`
- 若 workflow step 自己配置了 `continuation` 模板，优先用显式配置
- 若没配，回退到 record 上已有 continuation 或默认 terminal continuation

这意味着现在 final callback 至少可以把：

- 为什么停
- 谁接
- 下一步是什么

一起发给上游。

---

## 5. 示例

### 5.1 chain-basic

`examples/workflows/chain-basic.scheduler.json` 的 `final_callback` 已显式声明 continuation：

- `next_step = review_result_and_decide_followup_dispatch`
- `next_owner = main`
- `next_backend = manual`
- `stopped_because = workflow_completed`

### 5.2 workspace-trading acceptance dry-run

`examples/workflows/workspace-trading.acceptance-harness.scheduler.json` 的 `final_callback` 已显式声明 continuation：

- `next_step = review_acceptance_result_and_decide_dispatch`
- `next_owner = main`
- `next_backend = manual`
- `auto_continue_if` 只表达“PASS + allowlist 才允许继续”的意图
- `stop_if` 明确把 `!=PASS` / `artifacts_incomplete` / `human_override_stop` 写出来

这和当前 **safe semi-auto** 口径一致：

- contract 先写清楚；
- 真 dispatch 仍由策略层决定，不直接扩大自动权限。

---

## 6. 当前边界 / 还没做的

v1 仍然刻意收口：

1. **不是规则引擎**
   - `auto_continue_if` / `stop_if` 还只是规范化条件文本，不做通用表达式求值。
2. **不是全局 auto-dispatch 开关**
   - 不会因为 continuation 存在，就自动 spawn 下一轮。
3. **没有 timeline 平台化联动**
   - 当前只保证 registry 与 callback payload 有 continuation。
4. **没有把所有旧 POC 全量迁移**
   - 先覆盖 scheduler core / callback adapter / trading sample 两条线。

---

## 7. 验收口径

本轮 baseline 的验收不是“全自动编排完成”，而是：

- waiting 时能结构化说明为什么停；
- terminal 时能结构化说明下一步谁接；
- callback failed 时能结构化落到 retry callback；
- final callback payload 不再只带 `state`，还能带 `continuation`。

这就是 continuation contract v1 的最小可执行基线。
