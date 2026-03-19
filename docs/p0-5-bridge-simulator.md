# P0.5-1《subagent bridge 最小可运行模拟器》

## 结论先行

这个 repo-local prototype 已经把下面这条链条跑成**可执行、可测试、可落盘审阅**的最小闭环：

```text
subagent.spawn
  -> await terminal
  -> bridge.ingest_subagent_terminal
  -> task_registry.patch
```

范围刻意收缩到 P0.5-1：

- **只做模拟闭环**
- **不接真实 gateway / core event bus**
- **不改 OpenClaw 主仓**
- **只在 proposal repo 内新增 `poc/subagent_bridge_sim/`**

最终证明不是口头描述，而是 repo-local 文件产物：

- `runtime/tasks/<task_id>.json`：被 patch 后的 task registry 真值
- `runtime/events/<task_id>.terminal.json`：归一化 terminal envelope + raw event
- `runtime/waiters/<task_id>.terminal.json`：`await_terminal` 的解阻文件
- `output/registry.patched.json`：最终给 reviewer 看的 patched registry 副本

---

## 1. 目标

验证以下最小语义是否成立：

1. `subagent.spawn` 能创建并登记同一个 `task_id`
2. spawn 后 registry 能回写 `child_session_key`
3. `await_terminal` 不是“发出即完成”，而是真的等待 terminal 落盘
4. `bridge.ingest_subagent_terminal` 能用 `child_session_key -> task_id` 反查
5. `task_registry.patch` 能把 terminal evidence 写回原任务

只要这 5 条成立，就说明 P0 的 bridge 概念不是空图，而是已经有最小可运行接线。

---

## 2. 新增目录

```text
poc/subagent_bridge_sim/
  __init__.py
  poc_runner.py
  run_poc.py
  README.md
  inputs/
    spawn-request.json
    terminal-event.json
```

以及对应测试：

```text
tests/test_subagent_bridge_sim.py
```

---

## 3. 模拟器设计

## 3.1 `subagent_spawn()`

`subagent_spawn()` 在 POC 里扮演 `sessions_spawn(runtime="subagent")` 的薄包装器。

它做四件事：

1. 创建最小 registry：
   - `task_id`
   - `owner`
   - `runtime=lobster`
   - `state=queued`
   - `callback_status=pending`
2. 生成/接收一个模拟的 `child_session_key`
3. patch registry 到：
   - `runtime=subagent`
   - `state=running`
   - `evidence.child_session_key=...`
   - `evidence.spawn_request=...`
4. 写出 `by-child-session/<child>.json` 反查索引

这一步证明：**spawn 不会把任务从 registry 真值里甩出去。**

## 3.2 `await_terminal()`

`await_terminal()` 不轮询 gateway，也不碰真实 runtime；它只做 P0 最小动作：

- 等 `waiters/<task_id>.terminal.json`
- 一旦 bridge 写入 waiter 文件，就返回 terminal envelope
- 如果超时，则把 registry 诚实地 patch 成 `degraded`

这里故意把等待对象缩成 repo-local 文件，是为了验证**等待语义本身**，而不是验证具体传输层。

## 3.3 `ingest_subagent_terminal()`

这个方法模拟未来 bridge 对 core `subagent_ended` / completion announce 的消费动作。

输入是 sample terminal event JSON。

内部流程：

1. 读取 `child_session_key`
2. 查 `by-child-session/<child>.json`
3. 反查得到 `task_id`
4. 归一化 terminal envelope
5. 调 `task_registry.patch(...)`
6. 写出：
   - `events/<task_id>.terminal.json`
   - `waiters/<task_id>.terminal.json`
7. 解阻 `await_terminal()`

这一步是整条链的关键：**terminal 事件真正回到了原始任务，而不是只停留在 child session 自己的上下文里。**

## 3.4 `task_registry.patch()`

P0 仍然坚持 6 字段冻结版：

- `task_id`
- `owner`
- `runtime`
- `state`
- `evidence`
- `callback_status`

terminal 回写时，只把新增信息 merge 进 `evidence`，例如：

- `terminal_state`
- `completed_at`
- `summary`
- `artifacts`
- `raw_event_ref`

因此这个模拟器同时也验证了一个 schema 口径：**P0 不需要新增顶层字段，也能承载 subagent terminal 回写。**

---

## 4. Sample 输入

## 4.1 spawn request

文件：`poc/subagent_bridge_sim/inputs/spawn-request.json`

```json
{
  "task_id": "tsk_p0_subagent_bridge_sim_001",
  "label": "p0-5-subagent-bridge-sim",
  "cwd": "/repo/openclaw-company-orchestration-proposal",
  "task": "请完成 repo-local subagent bridge 最小闭环验证",
  "timeout_ms": 1800000,
  "owner": "lobster",
  "workflow": "subagent-handoff-basic",
  "simulated_child_session_key": "agent:main:subagent:sim-001",
  "spawned_at": "2026-03-19T08:00:00Z"
}
```

## 4.2 terminal event

文件：`poc/subagent_bridge_sim/inputs/terminal-event.json`

```json
{
  "child_session_key": "agent:main:subagent:sim-001",
  "terminal_state": "completed",
  "completed_at": "2026-03-19T08:12:00Z",
  "summary": "child task completed and wrote final report",
  "artifacts": {
    "final_summary_path": "runs/p0-5-subagent-bridge-sim/final-summary.json",
    "final_report_path": "runs/p0-5-subagent-bridge-sim/final-report.md"
  },
  "source": "subagent_ended"
}
```

---

## 5. 如何运行

在仓库根目录执行：

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event.json \
  --output-dir poc/subagent_bridge_sim/demo-run
```

运行后会生成：

```text
poc/subagent_bridge_sim/demo-run/
  runtime/
    tasks/tsk_p0_subagent_bridge_sim_001.json
    by-child-session/agent__main__subagent__sim-001.json
    events/tsk_p0_subagent_bridge_sim_001.terminal.json
    waiters/tsk_p0_subagent_bridge_sim_001.terminal.json
  output/
    spawn-response.json
    terminal-envelope.json
    await-terminal.json
    registry.patched.json
```

其中 `output/registry.patched.json` 是最重要的最终证据。

---

## 6. 最终 patched registry 长什么样

运行后最终 registry 关键字段应为：

```json
{
  "task_id": "tsk_p0_subagent_bridge_sim_001",
  "owner": "lobster",
  "runtime": "subagent",
  "state": "completed",
  "evidence": {
    "workflow": "subagent-handoff-basic",
    "child_session_key": "agent:main:subagent:sim-001",
    "spawned_at": "2026-03-19T08:00:00Z",
    "spawn_request": {
      "label": "p0-5-subagent-bridge-sim",
      "cwd": "/repo/openclaw-company-orchestration-proposal",
      "task": "请完成 repo-local subagent bridge 最小闭环验证",
      "timeout_ms": 1800000
    },
    "terminal_state": "completed",
    "completed_at": "2026-03-19T08:12:00Z",
    "summary": "child task completed and wrote final report",
    "artifacts": {
      "final_summary_path": "runs/p0-5-subagent-bridge-sim/final-summary.json",
      "final_report_path": "runs/p0-5-subagent-bridge-sim/final-report.md"
    },
    "raw_event_ref": "runtime/events/tsk_p0_subagent_bridge_sim_001.terminal.json"
  },
  "callback_status": "pending"
}
```

注意：

- `state=completed` 代表 child terminal 已回写成功
- `callback_status` 仍然是 `pending`
- 这正好符合 P0 口径：**terminal 成立 ≠ final callback 已发出**

---

## 7. 测试覆盖

测试文件：`tests/test_subagent_bridge_sim.py`

当前覆盖两件事：

1. **主链闭环测试**
   - `run_simulation()` 内部先 spawn
   - 并发启动 `await_terminal()`
   - 再 ingest terminal event
   - 最后断言 await 被解阻、registry 被 patch 到 `completed`

2. **落盘产物测试**
   - 断言 `output/registry.patched.json` 一定被写出
   - 断言里面的最终状态确实是 `completed`

运行命令：

```bash
python3 -m unittest tests.test_subagent_bridge_sim
```

---

## 8. 这版已经证明了什么

这版模拟器已经证明：

1. **spawn 后可拿到稳定 `child_session_key`**
2. **bridge 能通过 child session 反查回原 `task_id`**
3. **await 不是假等待，而是会被 terminal ingest 真正解阻**
4. **terminal evidence 能回写到同一条 registry**
5. **patched registry 可落盘、可测试、可审阅**

换句话说，P0.5-1 需要的“最小闭环”已经成立。

---

## 9. 还没做什么

为了守住范围，这版明确没做：

- 真实 `sessions_spawn(runtime="subagent")` 对接
- 真实 `subagent_ended` 订阅
- gateway / message bus / watcher 接线
- callback `sent/acked` 的真实推进
- 多 subagent / join / replay / retry

所以它的价值不是“上线可用”，而是：

> 在不动主仓、不碰真实 runtime 的前提下，把 P0 bridge 假设压缩成一个最小、可执行、可测试的 repo-local proof。
