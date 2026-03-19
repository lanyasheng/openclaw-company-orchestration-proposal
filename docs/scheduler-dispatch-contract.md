# 最小 Scheduler / Dispatcher Contract（Batch1）

## 结论先行

这一批已经把 **task registry library + 顺序 scheduler/dispatcher core** 连成最小闭环，但范围严格收口：

- **只支持顺序链**，不做 DAG / parallel / join
- **顶层 registry 仍冻结为 6 字段**，不为了 `waiting_subagent` 改 schema
- `waiting_subagent` 这类暂停态，**只写进 `evidence.scheduler.waiting_for`**；顶层 `state` 仍保持 `running`
- `callback_status` 继续与 `state` 分离，callback 失败**不会**回写业务终态

对应代码：

- `orchestration_runtime/task_registry.py`
- `orchestration_runtime/scheduler.py`
- `orchestration_runtime/builtin_handlers.py`
- `scripts/run_minimal_scheduler.py`
- `examples/workflows/chain-basic.scheduler.json`

---

## 1. 设计边界

### 做什么

1. 提供 repo-local、JSON file based 的最小 task registry library
   - `ensure`
   - `upsert`
   - `patch`
   - atomic write
   - `evidence` deep merge
2. 提供顺序 dispatcher
   - 按 `workflow.steps[]` 顺序执行
   - step 完成后推进到下一步
   - step 返回 `waiting` 时暂停，不误推进
   - resume 后从同一个 waiting step 继续
3. 提供最小内置 handler
   - `control.init_registry`
   - `control.inline_payload`
   - `subagent.await_terminal`
   - `callback.send_once`
4. 让 `chain-basic` 可以跑在这套 core 上

### 明确不做

- 不做 cron / 长期排程
- 不做优先级队列
- 不做通用表达式引擎
- 不做动态 fan-out / join
- 不做 trading pilot 的真实 adapter 绑定
- 不做 timeline 平台化 UI

---

## 2. Registry Contract

顶层记录仍保持：

```json
{
  "task_id": "tsk_xxx",
  "owner": "zoe",
  "runtime": "lobster|subagent|human",
  "state": "queued|running|waiting_human|completed|failed|degraded",
  "evidence": {},
  "callback_status": "pending|sent|acked|failed"
}
```

### 2.1 为什么不新增 `waiting_subagent`

因为 P0 文档已经冻结顶层状态枚举；这一批如果硬扩 schema，会把范围从“最小主干打通”又拉回“平台口径重写”。

所以这次采用：

- 顶层：
  - `runtime=subagent`
  - `state=running`
- 细节：
  - `evidence.scheduler.waiting_for = {step_id, kind}`

这就足够表达：

> 任务已经 handoff 给 subagent，但控制面现在停在等待 terminal 的位置。

---

## 3. Dispatcher Contract

### 3.1 Workflow Definition（本批最小口径）

```json
{
  "workflow_id": "chain-basic.scheduler.v1",
  "owner": "zoe",
  "mode": "chain-basic",
  "steps": [
    {"id": "init_registry", "type": "control.init_registry"},
    {"id": "step_a", "type": "control.inline_payload"},
    {"id": "final_callback", "type": "callback.send_once"}
  ]
}
```

### 3.2 Step Handler 返回值

step handler 只需要返回两类结果：

- `completed`
- `waiting`

其中 `waiting` 会让 dispatcher：

1. 停在当前 step
2. 写入 `evidence.scheduler.waiting_for`
3. 直接返回，不继续跑下一步

resume 时再次调用 `dispatch(...)`，并带上 `signal`；dispatcher 会从同一个 waiting step 继续，而不是跳到后面。

### 3.3 Scheduler Evidence

dispatcher 在 `evidence.scheduler` 下维护：

- `workflow_id`
- `cursor`
- `current_step_id`
- `waiting_for`
- `steps`
- `outputs`
- `timeline`

这部分是 **step-level 调度真值**，不是新的顶层 schema。

---

## 4. 当前已打通的最小链路

### 4.1 chain-basic

已提供示例：

- `examples/workflows/chain-basic.scheduler.json`
- `scripts/run_minimal_scheduler.py`

运行方式：

```bash
python3 scripts/run_minimal_scheduler.py \
  --workflow examples/workflows/chain-basic.scheduler.json \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json \
  --run-dir /tmp/chain-basic-scheduler-run
```

产物：

- `runtime/tasks/<task_id>.json`
- `dispatch-result.json`
- `callback.json`（如果已发送 final callback）

### 4.2 trading pilot 所需的暂停/恢复语义

这批已经有最小支持：

- `subagent.dispatch` 可以作为自定义 handler 注入
- `subagent.await_terminal` 已支持 `waiting -> resume`
- `collect_and_classify` 可以作为自定义 handler 注入
- `callback.send_once` 已支持终态后的单次回调

换句话说，**scheduler core 已具备 trading pilot 需要的顺序推进骨架**；还没做的是 trading repo 的真实业务 adapter。

---

## 5. 和现有 POC 的关系

`poc/subagent_bridge_sim/` 已切到新的 `FileTaskRegistry`，说明 registry 不再只是 POC 内部类，而是开始形成可复用模块。

本批没有强行重写：

- `poc/lobster_minimal_validation/`
- `poc/official_lobster_bridge/`

原因很简单：先把主干抽出来，再逐步迁移，不在这一批制造大回归面。

---

## 6. 接 trading pilot 还缺什么

只差业务绑定层，不差 core：

1. **真实 `subagent.dispatch` adapter**
   - 把 `sessions_spawn(runtime="subagent")` 的入参与回执接进 dispatcher
2. **真实 `await_terminal` ingest**
   - 用 child session key 对齐 terminal envelope
3. **真实 `collect_and_classify` 规则**
   - 读取 `workspace-trading` acceptance artifact / manifest / checklist
   - 映射 `completed / degraded / failed`
4. **真实 callback transport**
   - 目前 `callback.send_once` 只是 core 里的状态推进，还没接外部 delivery
5. **pilot workflow definition 落成 runtime 版**
   - 把 `docs/workflows/workspace-trading-pilot-workflow.yaml` 对齐成真正可执行 definition

---

## 7. 本批验收标准

满足以下条件即可认为 Batch1 core 成立：

- registry 支持 `upsert / patch / atomic write`
- `chain-basic` 能自动跑到终态
- `await_terminal` 无 signal 时不会误推进下一步
- resume 后能继续执行 classify / callback
- callback 状态与业务终态分离

这批的目标不是“平台化完成”，而是：

> **把官方底座 + registry + scheduler 的主干先连起来。**
