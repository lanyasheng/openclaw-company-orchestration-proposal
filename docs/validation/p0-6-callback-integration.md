# P0.6-1《callback 真集成最小闭环》

## 结论先行

在 `poc/subagent_bridge_sim/` 现有 terminal bridge POC 之上，这一版已经把 **callback_status 真值语义** 真正接进 repo-local prototype，补成下面两条最小可运行链路：

```text
A. success path
subagent.spawn
  -> await terminal
  -> bridge.ingest_subagent_terminal
  -> registry.state = completed|failed|degraded
  -> final_callback_sent
  -> callback_receipt_acked

B. callback delivery failure path
subagent.spawn
  -> await terminal
  -> bridge.ingest_subagent_terminal
  -> registry.state = completed|failed|degraded
  -> final_callback_failed
```

关键点只有两个：

1. **`state` 继续只表示任务执行终态**
2. **`callback_status` 只表示 final callback 的发送/确认真值**

这意味着：

- terminal ingest 只改 `state`
- callback stage 只改 `callback_status`
- 两者现在在同一个 repo-local simulator 里被分阶段落盘、测试、审阅

范围仍然严格收缩：

- 只做 repo-local 闭环
- 不碰真实 provider / webhook / queue / gateway
- 不改 OpenClaw 主仓

---

## 1. 这次新增了什么

## 1.1 新增 callback stage

`SubagentBridgeSimulator` 新增显式 callback stage ingest：

- `final_callback_sent`
- `callback_receipt_acked`
- `final_callback_failed`

它们的合法流转被硬编码为：

```text
pending --final_callback_sent--> sent
sent --callback_receipt_acked--> acked
pending --final_callback_failed--> failed
```

并且只有当 registry 已经进入 terminal state（`completed / failed / degraded`）后，才允许执行 callback stage。

## 1.2 registry 中 `state` 与 `callback_status` 严格分离

现在 simulator 内部有两条不同 patch 逻辑：

### terminal ingest 负责

- `state`
- `runtime`
- terminal evidence（`terminal_state` / `completed_at` / `artifacts` / `raw_event_ref`）

### callback ingest 负责

- `callback_status`
- callback evidence（`evidence.callback.last_stage/history/...`）

**callback stage 不会覆盖 `state`。**

例如：

- `completed + pending`
- `completed + sent`
- `completed + acked`
- `failed + pending`
- `failed + failed`

这些组合都可以在同一模拟器中被正确表达。

## 1.3 repo-local 产物新增 callback 落盘

除了原有 terminal 文件，现在还会额外写出：

```text
runtime/events/<task_id>.final_callback_sent.json
runtime/events/<task_id>.callback_receipt_acked.json
runtime/events/<task_id>.final_callback_failed.json
output/callback-envelope.<stage>.json
output/callback-sequence.json
```

最终 reviewer 仍然只需要看一份主真值：

```text
output/registry.patched.json
```

---

## 2. 现在的最小状态机

## 2.1 success path

```text
queued / pending
-> running / pending
-> completed / pending
-> completed / sent
-> completed / acked
```

## 2.2 callback delivery failure path

```text
queued / pending
-> running / pending
-> failed / pending
-> failed / failed
```

注意第二条路径中的两个 `failed` 语义不同：

- `state = failed`：任务执行失败
- `callback_status = failed`：final callback 发送失败

这正是本次 P0.6-1 要强制守住的边界。

---

## 3. 输入样例

新增输入文件：

```text
poc/subagent_bridge_sim/inputs/
  callback-events-success.json
  callback-events-failed.json
  terminal-event-failed.json
```

### 3.1 success callback sequence

文件：`poc/subagent_bridge_sim/inputs/callback-events-success.json`

```json
{
  "events": [
    {
      "stage": "final_callback_sent",
      "occurred_at": "2026-03-19T08:13:00Z",
      "summary": "final callback delivered to repo-local receiver",
      "delivery": {
        "channel": "repo-local",
        "target": "lobster/final-callback",
        "delivery_id": "cb-sim-001"
      }
    },
    {
      "stage": "callback_receipt_acked",
      "occurred_at": "2026-03-19T08:13:05Z",
      "summary": "repo-local receiver acknowledged callback receipt",
      "receipt": {
        "ack_id": "ack-sim-001",
        "received_at": "2026-03-19T08:13:05Z"
      }
    }
  ]
}
```

### 3.2 callback delivery failure

文件：`poc/subagent_bridge_sim/inputs/callback-events-failed.json`

```json
{
  "events": [
    {
      "stage": "final_callback_failed",
      "occurred_at": "2026-03-19T08:13:00Z",
      "summary": "repo-local callback delivery failed",
      "error": {
        "code": "simulated_delivery_error",
        "message": "callback inbox unreachable"
      }
    }
  ]
}
```

---

## 4. 如何运行

## 4.1 success path

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event.json \
  --callback-input poc/subagent_bridge_sim/inputs/callback-events-success.json \
  --output-dir poc/subagent_bridge_sim/demo-run-success
```

预期最终真值：

- `state = completed`
- `callback_status = acked`

## 4.2 callback failure path

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event-failed.json \
  --callback-input poc/subagent_bridge_sim/inputs/callback-events-failed.json \
  --output-dir poc/subagent_bridge_sim/demo-run-failed
```

预期最终真值：

- `state = failed`
- `callback_status = failed`

---

## 5. 最终 registry 长什么样

## 5.1 success path

样例文件：`poc/subagent_bridge_sim/expected/registry.callback-acked.json`

关键字段：

```json
{
  "state": "completed",
  "callback_status": "acked",
  "evidence": {
    "terminal_state": "completed",
    "callback": {
      "last_stage": "callback_receipt_acked",
      "history": [
        {"stage": "final_callback_sent", "callback_status": "sent"},
        {"stage": "callback_receipt_acked", "callback_status": "acked"}
      ]
    }
  }
}
```

## 5.2 callback failure path

样例文件：`poc/subagent_bridge_sim/expected/registry.callback-failed.json`

关键字段：

```json
{
  "state": "failed",
  "callback_status": "failed",
  "evidence": {
    "terminal_state": "failed",
    "callback": {
      "last_stage": "final_callback_failed",
      "history": [
        {"stage": "final_callback_failed", "callback_status": "failed"}
      ]
    }
  }
}
```

---

## 6. 测试覆盖

测试文件：`tests/test_subagent_bridge_sim.py`

本次新增覆盖两条 callback 真值链路：

1. **`pending -> sent -> acked`**
   - terminal 先把任务推进到 `completed`
   - callback stage 再推进 `callback_status`
   - 断言 `state` 保持 `completed`

2. **`pending -> failed`**
   - terminal 先把任务推进到 `failed`
   - callback failure stage 再把 `callback_status` 改成 `failed`
   - 断言 `state` 不被 callback stage 覆盖

运行命令：

```bash
python3 -m unittest tests.test_subagent_bridge_sim tests.test_callback_status_semantics
```

---

## 7. 这版已经证明了什么

P0.6-1 现在已经证明：

1. **terminal 真值** 能稳定回写到 registry
2. **callback 真值** 能在 terminal 之后独立推进
3. **`state` 与 `callback_status` 不再混用**
4. success / failure 两条 callback 最小链路都能 repo-local 跑通
5. 最终结果可以通过固定样例 JSON + unittest 双重验收

所以这不是“文档上说要分离”，而是：

> proposal repo 里的 prototype 已经能把 `completed/pending -> completed/sent -> completed/acked`
> 和 `failed/pending -> failed/failed` 这两类状态真实跑出来。

---

## 8. 仍然没做什么

这版仍然没有做：

- 真实 callback transport/provider
- 真实 webhook/HTTP delivery
- receipt 重试 / 死信 / 幂等键
- callback resend / replay / backoff
- 多任务并发下的 delivery ordering

因此这版的定位仍然是：

> **repo-local prototype 的最小闭环证明**，不是 production callback engine。
