# Lobster 最小验证 POC

## 结论先行

这份 POC 已把 **chain / human-gate / failure-branch** 三条最小流程落成可审阅样例，并补了一个本地可运行 harness 来验证最小 registry、evidence、final callback 的收敛。

- **legacy fallback baseline**：`chain-basic`（当前 canonical 官方路径已切到 `poc/official_lobster_bridge/`）
- **repo-local 最小真实闭环**：`human-gate-basic`（不再直接吃 CLI verdict，而是读取统一 `decision payload` 文件）
- **可跑但带 stub**：`failure-branch-basic`（failure branch 用 adapter stub 明示补位）
- **明确未做**：真实 message/browser provider、并发 / join、真实 callback delivery、真实 subagent handoff

## 目录

- `inputs/`：示例输入与 human-gate decision payload
- `examples/`：每个 workflow 的输入、命令、步骤、预期输出
- `expected/`：一次标准运行后的样例输出
- `run_poc.py`：本地执行入口
- `adapters.py`：P0 占位 adapter / stub
- `poc_runner.py`：最小 registry + evidence + callback 收敛实现

## 运行方式

在仓库根目录执行：

```bash
# chain-basic 现在是 fallback 用法；默认请改走 official_lobster_bridge
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json

python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-approve.json

python3 -m poc.lobster_minimal_validation.run_poc failure-branch \
  --input poc/lobster_minimal_validation/inputs/failure-branch-basic.json
```

`chain-basic` 的 canonical 官方路径：

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json
```

其他 human-gate verdict 可替换为：

- `inputs/human-gate-decision-reject.json`
- `inputs/human-gate-decision-timeout.json`
- `inputs/human-gate-decision-withdraw.json`

## 设计口径

1. **registry 最小化**：只保留 `task_id / owner / runtime / state / evidence / callback_status`
2. **evidence 可审阅**：每条流程都落 `registry.json` + `callback.json`
3. **callback 只发一次**：重复发送会抛错
4. **stub 显式标注**：不能原生证明的能力，一律在 adapter 返回里标 `native=false`
5. **human-gate 统一 payload**：`approve / reject / timeout / withdraw` 全部由统一 decision payload 驱动，并回写到 `evidence.human_gate.request/decision/resolution`

## 限定说明

- 这不是 Lobster 全功能实现，只是对 P0 假设做最小可运行验证。
- `human-gate` 当前仍是 repo-local harness：审批输入来自 JSON 文件，但字段结构已经对齐真实 message/browser 后续要产出的 payload。
- `expected/` 目录是一次标准运行产物，方便 reviewer 快速比对，不代表持久化协议已定稿。
