# 官方 Lobster bridge（`chain-basic` canonical path）

> 目标：把 `chain-basic` 正式收敛到 **repo-local wrapper + 官方 Lobster CLI** 这条最小真链路；本轮不扩到 `human-gate / subagent / failure-branch`。

## 结论先行

- **canonical path**：`poc/official_lobster_bridge/`
- **fallback path**：`poc/lobster_minimal_validation/`
- **切换范围**：只切 `chain-basic`
- **当前推荐命令**：

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json
```

如果想在官方 runtime 不可用时由同一入口自动回退，可显式加：

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json \
  --fallback-to-poc
```

---

## 目录说明

- `package.json`：repo-local 官方 Lobster 依赖 pin
- `workflows/chain-basic.lobster`：`chain-basic` 的官方 workflow 文件
- `inputs/chain-basic.args.json`：官方路径 smoke 输入
- `run_official.py`：canonical runner；默认走官方 Lobster CLI，必要时可显式回退 legacy POC harness

## 安装

```bash
cd poc/official_lobster_bridge
npm install
```

> 当前 pin：`@clawdbot/lobster@2026.1.24`

## canonical 运行

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

成功时：
- `registry.evidence.official_runtime.mode = official`
- `callback.summary.runtime = official-lobster-cli`
- `callback.summary.fallback = false`

## fallback 运行

legacy fallback 仍然保留，但不再是默认入口：

```bash
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json
```

如果想由 canonical runner 在失败时自动退回 legacy harness：

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json \
  --fallback-to-poc
```

fallback 时：
- `registry.evidence.official_runtime.mode = fallback-poc`
- `callback.summary.runtime = legacy-poc-fallback`
- `callback.summary.fallback = true`

## 最小自动化测试

```bash
python3 -m unittest tests.test_official_lobster_bridge_runner -v
```

覆盖点：
- fake lobster binary 下的 artifact 收敛
- 请求 fallback 时回退到 legacy POC harness
- 本地已安装官方 Lobster CLI 时的真实 smoke

## 边界

- 只覆盖 `chain-basic`
- 只依赖官方 `lobster` CLI，不直接耦合 SDK
- 不把 `human-gate / subagent / failure-branch` 一起拉进这次切换
- `poc/lobster_minimal_validation/` 继续保留，作为 fallback 基线而不是默认主入口
