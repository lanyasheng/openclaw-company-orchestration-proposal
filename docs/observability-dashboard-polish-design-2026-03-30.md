# Observability Dashboard 收口设计（2026-03-30）

## 范围
本次只收口 **observability dashboard** 的两个现实问题，不改 canonical truth：

1. **stale/过期任务标记**
   - 仅在 dashboard 层派生状态
   - 至少基于 `heartbeat` / `promised_eta` / `stage` 判断
   - 在看板和导出快照中明确显示 stale

2. **旧 demo/test 卡自动清理**
   - 只清理 observability cards/index
   - 仅匹配 **明确 demo/test marker** 的卡
   - 增加 TTL 规则与 dry-run 预览
   - 默认由 dashboard 在读取前执行安全清理

## 设计选择

### 1) stale 只做派生，不回写卡片
原因：
- stale 是一种 **观测性判断**，不是新的真值字段
- 避免把 dashboard 观测结果反向污染任务真值链
- 便于后续调整阈值，而不必迁移历史卡片

实现方式：
- 新增 `get_card_health()`
- 终态 `completed/failed/cancelled` 不标 stale
- 活跃阶段根据不同 stage 使用不同 heartbeat 阈值
- 若 ETA 已过期，也会标记 stale
- 导出快照附带 `dashboard_health`

### 2) demo 清理采用“显式 marker + TTL”双保险
只满足以下条件才允许清理：
- task_id / anchor / session_id 等字段出现明确 `demo` / `test` 标记
- 最近活动时间超过 TTL（默认 24h）

这样可以避免：
- 误删真实任务卡
- 刚创建的 demo/test 卡被立刻删掉
- 因为 scenario=custom 就误判为 demo

### 3) 清理范围只限 observability 层
允许动作：
- 删除 `observability/cards/*.json`
- 同步清理 `observability/index/*.jsonl` 对应 task_id

禁止动作：
- 修改 runtime truth
- 修改 dispatch / callback / completion 真实状态
- 给真实任务补写 demo/stale 真值字段

## 风险
1. **误删风险**
   - 通过“显式 marker + TTL”降低
   - 提供 dry-run 脚本先预览

2. **stale 误报风险**
   - 通过 stage-aware heartbeat 阈值降低
   - 终态任务不标 stale
   - stale 只是 dashboard 提示，不驱动 owner-level 决策

3. **空看板风险**
   - 如果当前只剩 demo 卡，清理后看板可能变空
   - 这是符合预期的：说明没有真实活动卡，而不是继续展示旧 demo 噪音

## 回退
若本次收口有问题，可快速回退：

1. 代码回退
   - 回退 `runtime/orchestrator/dashboard.py`
   - 删除 `scripts/cleanup-observability-demo-cards.py`
   - 删除新增测试

2. 数据回退
   - 本次清理仅影响 observability cards/index，不影响 canonical truth
   - 如需恢复，可从 git/备份或重新生成 observability cards

## 验证标准
- stale 任务能在 dashboard / export snapshot 中看到明确标记
- demo/test 卡能 dry-run 预览
- demo/test 卡能按 TTL 安全删除
- 不删除真实任务卡
