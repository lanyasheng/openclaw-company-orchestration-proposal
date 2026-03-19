# 官方 Lobster 最小 bridge（batch1）

> 目标：先把 `chain-basic` 接到官方 Lobster runtime，验证 **repo-local wrapper + 官方 CLI** 这条最小真链路可跑；不在这一批里扩到 human-gate / subagent / failure-branch。

## 目录说明

- `package.json`：repo-local 官方 Lobster 依赖 pin
- `workflows/chain-basic.lobster`：`chain-basic` 的官方 workflow 文件
- `inputs/chain-basic.args.json`：最小 smoke 输入
- `run_official.py`：薄 runner，负责调用官方 CLI，并把结果收敛成当前 proposal repo 认得的 `registry/callback` 产物

## 安装

```bash
cd poc/official_lobster_bridge
npm install
```

> 当前 pin：`@clawdbot/lobster@2026.1.24`

## 本地 smoke

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json
```

默认输出目录：`poc/official_lobster_bridge/runs/chain-basic/`

产物：
- `registry.json`
- `callback.json`
- `lobster-envelope.json`
- `lobster-command.json`

## 边界

- 只覆盖 `chain-basic`
- 只依赖官方 `lobster` CLI，不直接耦合 SDK
- 不改写现有 `poc/lobster_minimal_validation/`
- 如果官方 CLI 不可用，可直接回退到现有 POC harness：

```bash
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json
```
