# P0 最小 Task Registry（6 字段冻结版）

## 1. 目标

这份文档只定义 **P0 最小 task registry**，目的不是做平台，而是给 Lobster POC 和 OpenClaw 的 subagent 主链一个**最小可追踪、可验收、可回调**的统一真值。

P0 顶层字段**只允许**这 6 个：

1. `task_id`
2. `owner`
3. `runtime`
4. `state`
5. `evidence`
6. `callback_status`

对应 schema：`schemas/minimal-task-registry.schema.json`

对应样例：`examples/task-registry-sample.json`

---

## 2. 字段定义

| 字段 | 必填 | 约束 | 用途 |
|---|---|---|---|
| `task_id` | 是 | 字符串，建议 `tsk_` 前缀 | 全局稳定主键；把 Lobster 节点、subagent 回执、final callback 串成同一条任务链 |
| `owner` | 是 | 字符串 | 责任归属，P0 只保留一个 owner 槽，不再拆更多治理字段 |
| `runtime` | 是 | `lobster` / `subagent` / `human` | 当前执行主体；用来表达“现在是谁在推进这条任务” |
| `state` | 是 | `queued` / `running` / `waiting_human` / `completed` / `failed` / `degraded` | 统一状态机；P0 不再扩更多中间态 |
| `evidence` | 是 | 非空字符串或 JSON object | 最小证据槽；run dir、session id、人工决定、错误原因都塞这里，不新增顶层字段 |
| `callback_status` | 是 | `pending` / `sent` / `acked` / `failed` | final callback 是否已向上游发送并确认 |

---

## 3. 状态约束

### 3.1 固定枚举

P0 只接受以下 `state`：

- `queued`
- `running`
- `waiting_human`
- `completed`
- `failed`
- `degraded`

P0 只接受以下 `callback_status`：

- `pending`
- `sent`
- `acked`
- `failed`

P0 只接受以下 `runtime`：

- `lobster`
- `subagent`
- `human`

### 3.2 推荐状态流转

### 普通链路

`queued -> running -> completed`

### 人工闸门链路

`queued -> running -> waiting_human -> completed|failed|degraded`

### 失败分支链路

`queued -> running -> failed|degraded`

### subagent handoff 链路

`queued -> running(runtime=lobster) -> running(runtime=subagent) -> completed|failed`

### 3.3 P0 口径

- `completed` / `failed` / `degraded` 视为终态。
- 终态后，`callback_status` 不应长期停留在 `pending`。
- P0 不在 registry 顶层表达 retry、timestamps、adapter、delivery_attempts、runtime_ref 等更多字段。
- 如果需要更多上下文，只能先写进 `evidence`，等 P1 再评估是否升级 schema。

---

## 4. 为什么这 6 个字段就够 P0

这 6 个字段刚好覆盖 P0 最小闭环：

- **谁**：`owner`
- **哪条任务**：`task_id`
- **现在谁在执行**：`runtime`
- **执行到哪**：`state`
- **拿什么验收**：`evidence`
- **是否已经回报调用方**：`callback_status`

这已经足够回答 P0 最关键的问题：

1. 任务有没有被创建并持续追踪？
2. 当前是在 Lobster、subagent 还是人工闸门？
3. 任务最终有没有收敛，而不是卡在 running？
4. 有没有证据证明真的执行过？
5. final callback 到底发没发、有没有被确认？

---

## 5. 如何配合 Lobster POC

Lobster 在 P0 里不是完整编排平台，而是 **thin orchestration shell**。这份最小 registry 为 Lobster 提供统一落点：

1. **创建任务时**
   - 生成 `task_id`
   - 写入：`runtime=lobster`、`state=queued`、`callback_status=pending`

2. **进入执行时**
   - Lobster 启动节点
   - 更新：`state=running`
   - 把节点证据写入 `evidence`

3. **进入人工闸门时**
   - 更新：`runtime=human`、`state=waiting_human`
   - 把 `decision=approve|reject` 写入 `evidence`

4. **进入失败分支时**
   - 保留同一个 `task_id`
   - 把失败点和降级说明写入 `evidence`
   - 收敛到 `failed` 或 `degraded`

5. **发送 final callback 时**
   - 更新 `callback_status=sent|acked|failed`
   - 避免“任务完成了，但调用方没收到回执”的假闭环

重点是：**Lobster 只需要维护这 6 个字段，就能证明一条流程是可追踪、可收尾的。**

---

## 6. 如何配合 subagent 主链

当前口径已经收敛为：**内部长任务默认主链是 `sessions_spawn(runtime="subagent")`，不是 taskwatcher。**

因此最小 registry 与 subagent 主链的配合方式应当是：

1. control plane / Lobster 先创建一条 registry 记录
2. 记录 `task_id`
3. 当任务 handoff 给 subagent 时，把 `runtime` 切到 `subagent`
4. 把 `subagent_session_id`、产物路径、终态摘要写进 `evidence`
5. subagent 完成后，主链把同一个 `task_id` 更新到终态
6. 最后再更新 `callback_status`

这意味着：

- **subagent 是执行主链**
- **registry 是状态真值**
- **taskwatcher 最多做 shadow observe / external watcher，不是内部主状态 owner**

P0 的关键不是“发出一个子任务”，而是：

- handoff 后还能追踪到同一个 `task_id`
- subagent 完成后能回写到原任务
- final callback 只在真正终态后发出

---

## 7. 真实样例说明

样例文件：`examples/task-registry-sample.json`

这个样例直接采用本轮 P0 文档子任务的真实语义：

- `task_id = tsk_p0_subagent_registry_docs_20260319_1614`
- `owner = main`
- `runtime = subagent`
- `state = completed`
- `callback_status = acked`
- `evidence` 里记录了：
  - Lobster 的 handoff 节点语义
  - 当前 subagent session id
  - 本次交付产物路径

它表达的是：

> Lobster/控制平面把任务交给 subagent；subagent 产出 schema、样例和说明文档；主链确认完成后，callback 已被确认。

这正好覆盖 P0 最想验证的闭环：

- 同一个 `task_id` 可追踪
- handoff 不丢链
- evidence 可验收
- callback_status 可见

---

## 8. 明确不做

这份 P0 文档明确 **不做**：

- 通用平台 schema
- 更多顶层字段
- 完整 delivery receipt 系统
- retry / timer / SLA / audit 全量治理
- 多 runtime 全兼容抽象
- 数据库与分布式持久化设计

如果后续需要扩展，先证明这 6 字段版本已经足够支撑：

- chain
- human gate
- failure branch
- subagent handoff

在这四条 P0 流程都跑通前，不扩 schema。
