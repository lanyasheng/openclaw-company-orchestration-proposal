# Universal scenario onboarding seam — 2026-03-22

## 当前做到哪一步
还不是 zero-config 全自动，但已经把“新 scenario 怎么接”推进成一个更通用的最小 seam：

> operator-facing 最小接入包入口：`orchestrator/examples/generic_channel_roundtable_onboarding_kit.md`

- `orch_command.py` 现在会输出 machine-readable `onboarding`；
- 新的 **非 trading** scenario 默认复用 `channel_roundtable` adapter；
- payload 允许 `channel_roundtable` / `generic_roundtable` 两个 scope；
- tmux completion → callback 现在会自动补齐 channel 最小 packet，减少额外 payload 映射；
- contract 里的 channel metadata 统一成 `id/channel_id`、`name/channel_name`、`topic`。

## 当前仍然 scenario-specific 的部分
### trading_roundtable
- richer packet / richer gate
- artifact/report/commit/test/repro/tradability truth 仍然必需
- 默认 auto-dispatch 只对白名单 clean PASS continuation 放开

### channel_roundtable
- 已成为当前最小通用 seam
- 新的非 trading scenario 只需给最小 channel packet + roundtable closure
- callback / ack / dispatch 可直接复用
- 但默认 allowlist 仍未对所有频道自动打开

## 新 scenario 现在最少需要什么
### 非 trading 场景
1. contract 至少给 `scenario`
2. payload 用 `channel_roundtable` 或 `generic_roundtable`
3. `packet` 最小字段：
   - `packet_version`
   - `scenario`
   - `channel_id`
   - `topic`
   - `owner`
   - `generated_at`
4. `roundtable` 五字段：
   - `conclusion`
   - `blocker`
   - `owner`
   - `next_step`
   - `completion_criteria`

## 默认可推导字段
- `adapter`
- `batch_key`
- `owner`
- `backend_preference`
- `callback_payload_schema`
- `auto_execute`
- `gate_policy`
- ambient channel/session metadata

## 可直接复用的 runtime 逻辑
- `scripts/orchestrator_callback_bridge.py complete`
- `orchestrator/completion_ack_guard.py`
- `summary -> decision -> dispatch plan`
- `scripts/orchestrator_dispatch_bridge.py complete`

## 边界
- 这不是“所有新 scenario 都不需要 adapter”
- 当前只是把多数非 trading/channel 型场景压到同一个 `channel_roundtable` seam 上
- trading 仍保留专用 richer adapter，不假装已经 fully generic
