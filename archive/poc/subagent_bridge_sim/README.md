# Subagent Bridge Simulator

这个 POC 现在覆盖两段 repo-local 最小闭环：

```text
subagent.spawn
  -> await terminal
  -> bridge.ingest_subagent_terminal
  -> task_registry.patch(state)
  -> [optional] callback stage patch(callback_status)
```

它不会接真实 OpenClaw gateway，也不会监听真实 `subagent_ended` 或真实 callback provider。当前范围只用 sample JSON 模拟：

1. `subagent_spawn()` 模拟 `sessions_spawn(runtime="subagent")`
2. `await_terminal()` 阻塞等待 waiter 文件
3. `ingest_subagent_terminal()` 用 sample terminal event 触发 `state` 回写
4. `ingest_callback_stage()` 用 sample callback event 触发 `callback_status` 回写
5. `task_registry.patch()` 把同一 `task_id` 更新到终态与 callback 真值

## 运行

### 只跑 terminal bridge

在仓库根目录执行：

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event.json \
  --output-dir poc/subagent_bridge_sim/demo-run
```

### 跑 callback success path

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event.json \
  --callback-input poc/subagent_bridge_sim/inputs/callback-events-success.json \
  --output-dir poc/subagent_bridge_sim/demo-run-success
```

### 跑 callback failure path

```bash
python3 -m poc.subagent_bridge_sim.run_poc \
  --spawn-input poc/subagent_bridge_sim/inputs/spawn-request.json \
  --terminal-input poc/subagent_bridge_sim/inputs/terminal-event-failed.json \
  --callback-input poc/subagent_bridge_sim/inputs/callback-events-failed.json \
  --output-dir poc/subagent_bridge_sim/demo-run-failed
```

## 产物

运行后会写出两类目录：

- `runtime/`
  - `tasks/<task_id>.json`
  - `by-child-session/<child_session_key>.json`
  - `events/<task_id>.terminal.json`
  - `events/<task_id>.final_callback_sent.json`
  - `events/<task_id>.callback_receipt_acked.json`
  - `events/<task_id>.final_callback_failed.json`
  - `waiters/<task_id>.terminal.json`
- `output/`
  - `spawn-response.json`
  - `terminal-envelope.json`
  - `await-terminal.json`
  - `callback-envelope.<stage>.json`
  - `callback-sequence.json`
  - `registry.patched.json`
- `expected/`
  - `terminal-envelope.json`
  - `registry.patched.json`
  - `registry.callback-acked.json`
  - `registry.callback-failed.json`

`output/registry.patched.json` 是 reviewer 最关心的最终证明：

- terminal event 已成功回写到 registry
- callback_status 只会在 callback stage 里推进
- `state` 与 `callback_status` 严格分离
