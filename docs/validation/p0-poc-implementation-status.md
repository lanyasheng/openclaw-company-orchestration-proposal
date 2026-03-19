# P0 POC 实施状态

## 结论先行

当前仓库已经补出一套 **可审阅、可本地跑、边界明确** 的 Lobster 最小验证资产：

- **已切为 canonical 官方路径**：`chain-basic`（`poc/official_lobster_bridge/`）
- **保留 legacy fallback**：`chain-basic` 的旧 POC harness（`poc/lobster_minimal_validation/`）
- **可本地跑，但依赖 placeholder/stub**：`human-gate-basic`、`failure-branch-basic`
- **明确未做**：并发 / join、真实 message/browser/human 接线、真实 subagent handoff、真实 callback delivery

换句话说，P0 已经从“只有方案文档”推进到“有最小实现样例 + 本地 harness + 测试 + 样例输出”，但还没有进入大平台接线阶段。

## 产物位置

- `poc/official_lobster_bridge/README.md`
- `poc/official_lobster_bridge/run_official.py`
- `poc/official_lobster_bridge/workflows/`
- `poc/official_lobster_bridge/inputs/`
- `poc/lobster_minimal_validation/README.md`
- `poc/lobster_minimal_validation/run_poc.py`
- `poc/lobster_minimal_validation/poc_runner.py`
- `poc/lobster_minimal_validation/adapters.py`
- `poc/lobster_minimal_validation/examples/`
- `poc/lobster_minimal_validation/inputs/`
- `poc/lobster_minimal_validation/expected/`
- `tests/test_lobster_minimal_validation.py`
- `tests/test_official_lobster_bridge_runner.py`

## 分项状态

| Workflow | 当前状态 | 是否真实可跑 | Stub / Placeholder | 说明 |
|---|---|---:|---|---|
| `chain-basic` | 已切到官方 canonical path；legacy POC 仍保留 | 是 | 无 | 默认走 `poc/official_lobster_bridge/`；旧 `poc/lobster_minimal_validation/` 仅作 fallback |
| `human-gate-basic` | 已实现 | 是 | `HumanDecisionAdapterStub` | 用 CLI 参数模拟人工决定；真实消息/表单/审批通道未接 |
| `failure-branch-basic` | 已实现 | 是 | `FailureBranchAdapterStub` | 用 adapter stub 显式模拟 fallback 分支；避免误报为 Lobster 原生能力 |

## 已验证的最小能力

1. `task_id` 串联 registry / evidence / callback
2. `callback_status` 从 `pending -> sent -> acked`
3. `chain` 严格按顺序执行
4. `human-gate` 能停在 `waiting_human` 再继续或降级结束
5. `failure-branch` 在主链失败后仍能收敛到 fallback + final callback
6. final callback 有重复发送保护

## 仍然是 stub 的部分

### 1. 人工审批输入通道

当前只通过 `--decision approve|reject` 模拟人工结果。

缺口：
- 没接 OpenClaw `message`
- 没接 browser 表单/按钮
- 没接真实 `resumeToken` / 审批回填协议

### 2. failure branch 原生语义

当前用 `FailureBranchAdapterStub` 明确表示：
- P0 只证明“可通过 adapter 收敛”
- 还没有证明 Lobster 现阶段具备原生 `on_error` / `catch` / `fallback` DSL

### 3. callback delivery

当前 callback 只是本地 `callback.json`，用于证明：
- final callback 只发一次
- 终态结果可被持久化

未做：
- Discord / Telegram / session callback 真发送
- delivery retry / idempotency key / outbox

## Blocker

| Blocker | 影响 | 当前处理 |
|---|---|---|
| 仓库内未 vendored Lobster runtime | 不能直接证明真实 Lobster CLI 端到端执行 | 先用本地 harness 固化最小状态机和输出物 |
| Lobster 原生 failure branch 能力未证实 | 不能把 failure-branch 标成 native | 显式保留 `FailureBranchAdapterStub` |
| 人工审批通道未接真实 OpenClaw 工具 | 不能验证 message/browser/human 真闭环 | 显式保留 `HumanDecisionAdapterStub` |
| 真实 callback plane 未接 | 不能证明跨渠道送达与重试 | 当前只验证本地 callback artifact |

## 建议下一步

1. 先把 `chain-basic` 映射成真实 Lobster workflow 文件
2. 再把 `human-gate-basic` 接到最薄的 `message` 审批 adapter
3. 为 `failure-branch-basic` 决定路线：
   - 要么补 Lobster DSL 小扩展
   - 要么固定走 adapter contract
4. 等这三步稳定后，再考虑 `subagent handoff`
