# Waiting anomaly hard-close（2026-03-21）

## 背景

最小 runtime 以前允许任务停在 `waiting_for=subagent_terminal`，只要还没收到 terminal signal 就继续返回 `waiting`。
这会留下一个空洞：如果派发侧已经没有活跃执行（例如 `active_task_count=0`、run handle 已掉到 dropped/failed 一类状态、或连 child session 绑定都丢了），registry 仍可能长期表现成“还在等”。

## 本次最小 guard

落点：`orchestration_runtime/scheduler.py`

新增约束：

1. `waiting_for=subagent_terminal` 只能在 **仍有活跃执行证据** 时继续保留。
2. 若检测到以下任一异常，则不再继续写 `waiting`，而是立即 hard-close：
   - 缺少 `child_session_key`
   - 缺少 dispatch / run handle 证据
   - `active_task_count <= 0`
   - `run_handle.status` 已落入 `failed / timeout / cancelled / dropped / rejected / exited ...`
3. hard-close 时强制补齐 closeout 证据：
   - `stopped_because`
   - `next_step`
   - `next_owner`
   - `dispatch_readiness`

## 结果语义

- 调度器把异常等待收敛为 `failed`
- `scheduler.steps[await_terminal].status` 记为 `dropped`
- `evidence.waiting_anomaly` 记录异常原因
- `evidence.closeout.dispatch_readiness=blocked`
- continuation 指向 `rerun_subagent_dispatch_with_fresh_session`

## trading 相关最小影响

该 guard 直接覆盖 `workspace-trading.acceptance-harness.scheduler.v1` 这条 trading 相关 continuation 路径：
如果 subagent 已经没有活跃执行，就不会再把它当成“仍在 waiting 的正常任务”。
