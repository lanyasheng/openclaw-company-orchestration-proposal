# tmux trading business callback — 第二刀审计说明（2026-03-21）

## 结论
已补上 tmux 路径的第二刀：
- tmux completion 不再只能落 generic completion report；
- trading_roundtable 会优先读取 **真实 business callback payload**；
- 如果 tmux 产物不足以支撑真实 phase1 packet，则桥接层会生成 **blocked/degraded trading callback payload**，明确写出 blocker 与 missing fields，而不是伪装成 clean PASS。

## 最小 contract
bridge 现在约定 tmux 任务可在 dispatch 对应的固定路径写出：
- `shared-context/orchestrator/tmux_receipts/<dispatch>.business-callback.json`

Trading 场景最小结构：
- top-level: `summary`, `verdict`, optional `closeout`, optional `orchestration`
- scoped: `trading_roundtable.packet`, `trading_roundtable.roundtable`

优先级：
1. 固定 business payload 文件
2. completion report 内嵌 payload（`business_callback_payload` / `structured_callback_payload` / `callback_payload` / scoped payload）
3. 若都没有，则自动生成 blocked trading payload

## blocked fallback 语义
blocked fallback 至少会给出：
- `packet_version=trading_phase1_packet_v1`
- `phase_id=trading_phase1`
- `owner/generated_at/overall_gate/primary_blocker`
- `packet.tmux_bridge.status=blocked`
- `packet.tmux_bridge.missing_business_fields=[...]`
- `roundtable.conclusion=FAIL`
- `roundtable.blocker=<tmux stopped_because>`

这保证：
- 不会把 generic tmux report 当成真实交易业务结论；
- 但 roundtable / summary / decision / dispatch 仍能拿到结构化 blocked 真值。

## 接线位置
- `orchestrator/tmux_terminal_receipts.py`
  - 增加 business payload 探测、优先读取、blocked fallback 生成
- `scripts/orchestrator_dispatch_bridge.py`
  - dispatch reference 写明 business callback 输出路径与 contract
- `scripts/orchestrator_callback_bridge.py complete -> orchestrator/trading_roundtable.py`
  - 继续复用既有处理链，无需大改

## 还没做的部分
tmux 路径要真正做到“自动推进下一跳”，还差最后一小段执行纪律落地：
1. tmux continuation prompt /执行者必须稳定写出真实 business callback payload，而不是只写 generic completion report；
2. 如需更高自动化，可再补针对 trading repo artifact 的 ETL/backfill，但当前版本仍坚持“无真值不伪造”；
3. 若后续要覆盖 channel_roundtable 之外更多 adapter，再把同样的 business payload 优先策略抽成通用层。
