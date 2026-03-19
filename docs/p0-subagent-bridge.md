# P0-4《subagent bridge 最小接线图》

## 0. 目标与边界

这份文档只回答一件事：**Lobster 在 P0 怎么把一个 `sessions_spawn(runtime="subagent")` 子任务真正接进来，并且等到终态后再收尾。**

不做：
- 多 subagent 并发
- parallel/join
- 通用 durable engine
- taskwatcher 主链接管
- 完整 receipt / retry / replay

P0 只验证一条最小闭环：

```text
Lobster workflow
  -> spawn 1 个 subagent
  -> 拿到 child_session_key
  -> 等 core subagent terminal event
  -> 回写 minimal task registry
  -> 再发 final callback
```

---

## 1. 先定死：P0 只走这一条线

### 1.1 责任边界

| 层 | P0 负责什么 | P0 不负责什么 |
|---|---|---|
| **Lobster** | 编排顺序、决定何时 spawn / await / final callback / failure-branch | 自己实现 subagent runtime |
| **subagent core（复用现有 OpenClaw）** | `sessions_spawn(runtime="subagent")`、requester/controller 绑定、`subagent_ended` / completion announce | minimal task registry 持久化 |
| **subagent bridge（P0 新增薄层）** | 把非 action 型 `sessions_spawn` 包成 Lobster 可调接口；把 terminal event 映射回 registry | 做 watcher / poller backbone |
| **minimal task registry（P0 新增最小台账）** | 存 6 个字段：`task_id/owner/runtime/state/evidence/callback_status` | 做复杂控制面 / UI / fan-out |
| **taskwatcher** | 这条链路里**不做 primary path**；最多 shadow observe / legacy compatibility | 内部 subagent 主状态推进 |

### 1.2 为什么不能直接让 Lobster 调 `sessions_spawn`

因为当前 Lobster 强项是 `tool + action + args-json` 这类同步步骤；而 `sessions_spawn` 真正难的不是“发起”，而是：

1. 拿到稳定关联键（`child_session_key`）
2. 等终态
3. 把终态 evidence 回写同一个 `task_id`
4. 防止“发出即算完成”

所以 P0 必须补一层很薄的 bridge，但**只补到单 subagent handoff 为止**。

---

## 2. P0 最小目录与文件落点

P0 不上数据库，先用 repo-local 文件落地：

```text
tmp/p0-subagent-bridge/
  tasks/
    <task_id>.json                    # minimal task registry 最新态
  by-child-session/
    <child_session_key>.json          # child_session_key -> task_id 反查
  waiters/
    <task_id>.terminal.json           # await_terminal 的解阻文件
  events/
    <task_id>.terminal.json           # 归一化 terminal envelope
```

### 2.1 registry 单条记录固定只保留 6 个字段

```json
{
  "task_id": "tsk_p0_subagent_001",
  "owner": "lobster",
  "runtime": "subagent",
  "state": "running",
  "evidence": {
    "workflow": "subagent-handoff-basic",
    "child_session_key": "agent:main:subagent:uuid",
    "spawned_at": "2026-03-19T08:00:00Z"
  },
  "callback_status": "pending"
}
```

### 2.2 P0 约束

- `child_session_key`、`terminal_state`、`artifacts` 都先塞进 `evidence`
- **不**在 P0 扩大 registry schema
- `callback_status` 只认：`pending | sent | acked | failed`
- 如果上游没有 receipt，P0 停在 `sent`

---

## 3. Lobster 如何触发单个 subagent

## 3.1 推荐时序

```text
(1) Lobster 生成 task_id
(2) task_registry.upsert(state=queued, callback_status=pending)
(3) subagent.spawn(...)
(4) bridge 内部调用 sessions_spawn(runtime="subagent")
(5) bridge 拿到 child_session_key
(6) registry.patch(runtime=subagent, state=running, evidence.child_session_key=...)
(7) Lobster 进入 subagent.await_terminal(...)
```

## 3.2 最小接口草案：`subagent.spawn`

> 这是 P0 必须新增的 adapter。目的只有一个：把 `sessions_spawn` 包成 Lobster 能稳定调用的 action 形态。

### 请求

```json
{
  "task_id": "tsk_p0_subagent_001",
  "label": "p0-subagent-demo",
  "cwd": "/repo",
  "task": "请完成 demo 子任务",
  "timeout_ms": 1800000,
  "owner": "lobster"
}
```

### bridge 内部动作

1. 调用 OpenClaw 原生能力：
   `sessions_spawn({ runtime: "subagent", task, cwd, label })`
2. 从返回结果里抽取/归一化：
   - `child_session_key`（P0 主关联键）
   - `requester_session_key`（如果拿得到就记到 `evidence`）
   - `spawned_at`
3. 写反查文件：
   `tmp/p0-subagent-bridge/by-child-session/<child_session_key>.json`
4. patch registry：
   - `runtime = "subagent"`
   - `state = "running"`
   - `evidence.child_session_key = ...`
   - `evidence.spawn_request = { label, cwd }`

### 返回

```json
{
  "accepted": true,
  "task_id": "tsk_p0_subagent_001",
  "child_session_key": "agent:main:subagent:uuid",
  "state": "running",
  "callback_status": "pending"
}
```

## 3.3 spawn 之后 registry 应该长什么样

```json
{
  "task_id": "tsk_p0_subagent_001",
  "owner": "lobster",
  "runtime": "subagent",
  "state": "running",
  "evidence": {
    "workflow": "subagent-handoff-basic",
    "child_session_key": "agent:main:subagent:uuid",
    "spawned_at": "2026-03-19T08:00:00Z",
    "spawn_request": {
      "label": "p0-subagent-demo",
      "cwd": "/repo"
    }
  },
  "callback_status": "pending"
}
```

---

## 4. 如何等待终态

## 4.1 P0 的等待原则

**不走 taskwatcher 轮询，不走 generic-exec，不靠 `status.json` 轮询当 primary path。**

P0 直接复用：
- OpenClaw core 的 `subagent_ended` / completion announce
- child session 与 requester/controller 的已有绑定

但是 Lobster 本身还没有现成“订阅 subagent terminal event”的接口，所以 bridge 要补第二个最小 adapter：`subagent.await_terminal`。

## 4.2 最小接口草案：`subagent.await_terminal`

### 请求

```json
{
  "task_id": "tsk_p0_subagent_001",
  "child_session_key": "agent:main:subagent:uuid",
  "timeout_ms": 1800000
}
```

### 行为

`await_terminal` 不自己发明 runtime；它只做两件事：

1. 等 `tmp/p0-subagent-bridge/waiters/<task_id>.terminal.json`
2. 或读取同一 `task_id` 的 registry，直到 `state in [completed, failed, degraded]`

**推荐主路径**：等 waiter 文件。  
**registry 读取** 只作为 bridge 自己的兜底，不作为公司级 watcher 方案。

## 4.3 谁来写 waiter 文件

由 bridge 内部的 terminal ingest 钩子负责：

### 内部接口：`bridge.ingest_subagent_terminal(event)`

输入来源：OpenClaw core 的 `subagent_ended` / completion announce。

内部动作：
1. 通过 `child_session_key` 反查 `task_id`
2. 归一化 terminal envelope
3. patch registry 到终态
4. 落盘：
   - `events/<task_id>.terminal.json`
   - `waiters/<task_id>.terminal.json`
5. 解阻 `subagent.await_terminal`

### 归一化 terminal envelope（建议）

```json
{
  "task_id": "tsk_p0_subagent_001",
  "child_session_key": "agent:main:subagent:uuid",
  "state": "completed",
  "terminal_state": "completed",
  "completed_at": "2026-03-19T08:12:00Z",
  "summary": "child task completed",
  "artifacts": {
    "final_summary_path": null,
    "final_report_path": null
  },
  "raw_event_ref": "tmp/p0-subagent-bridge/events/tsk_p0_subagent_001.terminal.json"
}
```

> 说明：`final_summary_path/final_report_path` 在 P0 里是**可选**。只有 child 明确走现有 `subagent_claude_v1` runner 路线时，bridge 才去带这些 artifact 路径；否则只要求最小 terminal summary。

---

## 5. 如何把 evidence / callback_status 回写到 minimal task registry

## 5.1 回写时机必须分两段

### A. child 终态到了，先回写 evidence 和 state

此时**不要**提前把 `callback_status` 改成 `sent`。

先写：
- `runtime = subagent`
- `state = completed | failed | degraded`
- `evidence.terminal_state = ...`
- `evidence.completed_at = ...`
- `evidence.summary = ...`
- `evidence.artifacts = ...`

示例：

```json
{
  "task_id": "tsk_p0_subagent_001",
  "owner": "lobster",
  "runtime": "subagent",
  "state": "completed",
  "evidence": {
    "workflow": "subagent-handoff-basic",
    "child_session_key": "agent:main:subagent:uuid",
    "spawned_at": "2026-03-19T08:00:00Z",
    "terminal_state": "completed",
    "completed_at": "2026-03-19T08:12:00Z",
    "summary": "child task completed",
    "artifacts": {
      "final_summary_path": null,
      "final_report_path": null
    }
  },
  "callback_status": "pending"
}
```

### B. Lobster 发 final callback 后，再改 `callback_status`

只有在 Lobster 的 final step 真正执行完后，才回写：

- 成功：`callback_status = sent`
- 有外部 receipt：再升 `acked`
- 回调发送失败：`callback_status = failed`

## 5.2 最小接口草案：`task_registry.patch`

### 请求

```json
{
  "task_id": "tsk_p0_subagent_001",
  "state": "completed",
  "evidence_merge": {
    "terminal_state": "completed",
    "completed_at": "2026-03-19T08:12:00Z",
    "summary": "child task completed"
  },
  "callback_status": "pending"
}
```

### 返回

```json
{
  "ok": true,
  "task_id": "tsk_p0_subagent_001"
}
```

## 5.3 为什么 callback_status 不能在 terminal ingest 阶段就改成 sent

否则会出现典型假完成：

```text
child 已经结束
-> registry 提前写 callback_status=sent
-> 但 Lobster 的 final callback step 其实还没执行 / 执行失败
-> 外部看到的是“已回报”，实际没人收到
```

P0 必须把两件事拆开：
- **终态成立** = `state` 变 terminal
- **终态已回报** = `callback_status` 变 `sent|acked`

---

## 6. 失败时最小 failure-branch 怎么走

P0 只保留一条最短失败路径：

```text
spawn 失败 / child 失败 / await 超时
  -> patch registry 到 failed 或 degraded
  -> 把错误证据写进 evidence
  -> 执行 1 次 final failure callback
  -> 停止 workflow
```

## 6.1 Case A：spawn 当场失败

### 触发条件
- `sessions_spawn(...)` 返回 rejected / error
- 没拿到 `child_session_key`

### registry 回写

```json
{
  "task_id": "tsk_p0_subagent_001",
  "owner": "lobster",
  "runtime": "subagent",
  "state": "failed",
  "evidence": {
    "spawn_error": "...",
    "failed_at_stage": "spawn"
  },
  "callback_status": "pending"
}
```

### Lobster failure-branch

1. 生成失败摘要
2. 发一次 final failure callback
3. 成功则 `callback_status=sent`，失败则 `callback_status=failed`
4. workflow 结束，不自动重试

## 6.2 Case B：child 终态 = failed

### 触发条件
- `bridge.ingest_subagent_terminal()` 收到失败终态

### registry 回写
- `state = failed`
- `evidence.terminal_state = failed|process_exit|timeout_total|timeout_stall`
- `evidence.summary = ...`
- `callback_status = pending`

### Lobster failure-branch
- 直接消费 `await_terminal` 的失败结果
- 发 final failure callback
- 然后结束

## 6.3 Case C：await 自身超时，但没有 terminal event

这是 P0 唯一保留的“未知失败”分支。

### registry 回写
- `state = degraded`
- `evidence.await_timeout = true`
- `evidence.failed_at_stage = await_terminal`
- `callback_status = pending`

### 为什么不是直接 completed/failed

因为这类情况说明：
- child 可能还在跑
- 或 event bridge 漏了
- 或反查关系丢了

P0 不做自动 reconcile / reaper，只做**诚实降级**：
- 把任务标成 `degraded`
- 发 failure callback，告诉上游“终态未确认”
- 留待人工补账

---

## 7. 哪些部分必须是 adapter / stub，哪些可以直接复用

## 7.1 必须新增的 adapter / stub

| 组件 | 为什么必须新增 | P0 最小形态 |
|---|---|---|
| `subagent.spawn` | Lobster 不能直接优雅消费非 action 型 `sessions_spawn` | 一个薄 wrapper，负责 spawn + 关联键归一化 + registry patch |
| `subagent.await_terminal` | Lobster 没有现成 subagent terminal 订阅接口 | 一个阻塞等待器，等 waiter 文件或 terminal registry 状态 |
| `bridge.ingest_subagent_terminal` | 需要把 core terminal event 映射回 `task_id` | 用 `child_session_key -> task_id` 反查，再 patch registry |
| `task_registry.patch/upsert` | P0 需要最小 source-of-truth，而不是继续塞 taskwatcher | repo-local JSON 文件原子写入即可 |
| `by-child-session` 反查索引 | terminal event 回来时要定位同一个 `task_id` | 一个轻量文件索引即可 |

## 7.2 可以直接复用的 OpenClaw 现有能力

| 现有能力 | P0 如何复用 |
|---|---|
| `sessions_spawn(runtime="subagent")` | 作为真正的 child launch primitive |
| core `subagent_ended` / completion announce | 作为真正的 terminal source，不另造 watcher 主链 |
| subagent requester/controller 绑定 | 继续沿用，不在 bridge 里重做 |
| `message.send` 等 action 工具 | Lobster final callback 如果要对外播报，可直接走现有 action bridge |
| 现有 subagent runner 产物（`final-summary.json` / `final-report.md`） | **仅当 child 明确走 `subagent_claude_v1` 路线时**，可作为可选 artifact evidence |

## 7.3 明确不要在 P0 里复用成 primary path 的东西

| 组件 | 为什么不用作主链 |
|---|---|
| `taskwatcher` / `generic-exec` | 这是 external watcher / compatibility 层，不该接管内部 subagent 主状态 |
| ACP poller / ACP bridge | 这条文档只解决 `runtime=subagent`，不是 ACP |
| 轮询 child `status.json` | 只能作为 debug 兜底，不是 P0 的终态真值来源 |

---

## 8. 一张工程接线图

```text
Lobster workflow
  |
  | 1. task_registry.upsert(task_id, queued)
  v
subagent.spawn adapter
  |
  | 2. sessions_spawn(runtime="subagent")           [复用 OpenClaw core]
  | 3. return child_session_key
  | 4. task_registry.patch(state=running, evidence.child_session_key=...)
  | 5. write by-child-session/<child>.json
  v
subagent.await_terminal adapter
  |
  | 6. wait waiters/<task_id>.terminal.json
  |
  +-------------------------------+
                                  |
                                  | 7. core emits subagent_ended / completion announce
                                  v
                        bridge.ingest_subagent_terminal
                                  |
                                  | 8. reverse lookup child_session_key -> task_id
                                  | 9. task_registry.patch(state=completed|failed|degraded,
                                  |                        evidence.terminal_*)
                                  | 10. write events/<task_id>.terminal.json
                                  | 11. write waiters/<task_id>.terminal.json
                                  v
                         await_terminal returns terminal envelope
                                  |
                                  | 12. Lobster final callback / failure callback
                                  | 13. task_registry.patch(callback_status=sent|failed|acked)
                                  v
                                End
```

---

## 9. P0 验收口径

跑通以下四个断点就算这个 bridge 接上了：

1. **spawn 后 registry 能看到 `child_session_key`**
2. **child 完成后，Lobster 不是“发出即完成”，而是真的等到 terminal**
3. **同一个 `task_id` 里能看到 terminal evidence 回写**
4. **`callback_status` 只有在 final callback 真发出后才变化**

如果这四条都成立，就说明 P0 的 subagent bridge 已经不是空谈，而是最小可验证闭环。