# 官方 Lobster 接入方案（batch1 冻结）

## 结论先行

**可以进入下一步 `chain-basic` 官方 runtime 切换准备，但还不建议直接宣称“已完成全面官方化”。**

本批次冻结结论如下：

1. **接入形态冻结为 CLI-first、SDK-second。**
   - 默认走官方 `lobster` CLI：`lobster run --mode tool --file <workflow> --args-json <json>`。
   - SDK 暂不作为默认执行路径，只保留为后续需要更深嵌入时的候选。
2. **版本 pin 冻结为 repo-local Node 依赖精确锁定。**
   - 当前 repo-local wrapper 先 pin：`@clawdbot/lobster@2026.1.24`。
   - 同时记录官方源码审计基线：`openclaw/lobster` 默认分支 `main`，当前核验 `HEAD=1d2b7ee6be9d5c3b6b21235afa181927a2693366`。
3. **获取方式冻结为 repo-local 安装，不做 vendored snapshot / submodule。**
   - 批次 1 目标是尽快证明官方 runtime 可接入；因此先在 `poc/official_lobster_bridge/` 内本地安装官方包，不把 Lobster 整仓 vendoring 进 proposal repo。
4. **回退方式冻结为“随时退回现有 POC harness”。**
   - 若官方 CLI 不可用、包版本漂移、workflow file 能力不满足，则继续使用 `poc/lobster_minimal_validation/` 作为基线执行器。
5. **最小 repo-local bridge 已落点。**
   - 新增 `poc/official_lobster_bridge/`，只覆盖 `chain-basic`，不触碰 human-gate / subagent / failure-branch。

---

## 1. 当前事实核验

### 1.1 官方仓现状（核验于本次任务）

- GitHub 仓库：`https://github.com/openclaw/lobster`
- 仓库描述：`OpenClaw-native workflow shell`
- 默认分支：`main`
- 本次核验时源码 HEAD：`1d2b7ee6be9d5c3b6b21235afa181927a2693366`

### 1.2 官方仓公开信息里可确认的能力

根据官方 README / package.json / 源码目录，可确认：

- CLI 存在：`lobster`
- 工作流文件执行存在：`lobster run --file path/to/workflow.lobster --args-json '{...}'`
- tool 模式存在：`--mode tool`
- SDK 导出存在：`./sdk`、`./core`
- 工作流文件语义存在：`command/run`、`stdin`、`approval`、`pipeline`
- Node 要求：`>=20`

### 1.3 需要明确记账的现实偏差

本次核验发现一个必须写清楚的偏差：

- `openclaw/lobster` 当前源码 `package.json` 显示版本为 `2026.1.21-1`，且 README 提到 `openclaw.invoke` / `clawd.invoke` shim。
- 但 npm 上当前可直接安装的 `@clawdbot/lobster` 最新版为 `2026.1.24`，安装后主要 bin 只有 `lobster`。

**结论**：
- “GitHub 官方源码口径”与“npm 可安装包口径”当前并非完全同构。
- 所以 batch1 不去绑定 `openclaw.invoke`，只绑定已经实测可用的 `lobster` CLI 主入口。
- 后续若要把 OpenClaw tool/action 直接嵌进官方 workflow，再专门做一轮 `openclaw.invoke` 口径核对。

---

## 2. 为什么本批次选择 CLI-first，而不是 SDK-first

### 2.1 选择 CLI-first 的原因

1. **与当前 proposal repo 边界最匹配**
   - 本仓当前主体是文档 + Python POC。
   - CLI 调用比把 SDK 深度嵌入 Python/Node 混合执行器更薄。

2. **更利于精确回退**
   - CLI 路径失败时，直接回到现有 Python harness 即可。
   - 不需要先处理 SDK API 漂移、运行时对象模型、resume token 兼容等问题。

3. **更贴近后续 workflow file 资产化**
   - 本项目真正要沉淀的是“官方 workflow 文件 + repo-local bridge”，而不是一段藏在代码里的 fluent SDK 构造逻辑。

### 2.2 SDK 在 batch1 的定位

SDK 不是不可用，而是**先不作为默认路径**：

- 保留理由：
  - 后续若要做更细颗粒度的 programmatic composition，SDK 可能更合适。
- 暂不默认理由：
  - 当前目标只是 `chain-basic` 的官方 runtime 切换准备；CLI 已足够完成 batch1。

---

## 3. 版本 pin / 获取方式 / 回退方式（冻结口径）

### 3.1 版本 pin

**冻结方案：**

- **执行 pin（batch1 真正跑的版本）**：`@clawdbot/lobster@2026.1.24`
- **源码审计 pin（文档记录）**：`openclaw/lobster@1d2b7ee6be9d5c3b6b21235afa181927a2693366`

### 3.2 获取方式

**冻结方案：repo-local install**

在 `poc/official_lobster_bridge/` 下执行：

```bash
cd poc/official_lobster_bridge
npm install
```

理由：

- 安装路径局部、可删、可回退；
- 不污染 repo 根；
- 不需要现在就引入 submodule / vendored snapshot 的维护负担；
- 足够支撑 `chain-basic` 的官方 smoke。

### 3.3 暂不采用的方式

#### A. submodule
不选原因：
- 本批次目标不是长期同步 Lobster 源码开发；
- 会提高仓库维护复杂度；
- 当前收益不如 CLI-first repo-local install 直接。

#### B. vendored snapshot
不选原因：
- 会复制官方仓代码，增加后续升级与对齐成本；
- 当前还处于“证明最小官方 runtime 可接入”的阶段，不值得。

#### C. GitHub 源码直接安装
当前不作为默认：
- 官方源码与 npm 发布物存在口径差异；
- 直接从 GitHub 源码安装往往还要处理 build/dist 问题；
- batch1 优先保证“可安装、可跑、可回退”。

### 3.4 回退方式

**冻结方案：保留现有 POC harness 作为金丝雀基线。**

回退命令：

```bash
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json
```

回退触发条件：

- 官方 `lobster` CLI 安装失败；
- 官方 workflow file 无法稳定表达当前 `chain-basic`；
- npm 包行为与官方源码说明继续出现明显漂移；
- 后续 `chain-basic` 切换时发现输出契约无法对齐当前 registry/callback 基线。

---

## 4. repo-local wrapper / runner 设计（batch1 最小落点）

## 4.1 目录落点

```text
poc/official_lobster_bridge/
├── README.md
├── __init__.py
├── package.json
├── workflows/
│   └── chain-basic.lobster
├── inputs/
│   └── chain-basic.args.json
└── run_official.py
```

### 4.2 设计原则

- **只做一层薄 wrapper**：负责调用官方 CLI、解析 envelope、落回本仓现有产物形态。
- **不碰大重构**：不改现有 `poc/lobster_minimal_validation/`。
- **只覆盖 `chain-basic`**：human-gate / subagent / failure-branch 不在 batch1 范围内。
- **保留当前 registry/callback 口径**：便于下一步做“执行器替换”而不是“整套协议重写”。

### 4.3 runner 职责边界

`run_official.py` 只负责：

1. 定位 `lobster` 可执行文件
   - 优先 `poc/official_lobster_bridge/node_modules/.bin/lobster`
   - 其次 `--lobster-bin`
   - 再其次系统 `PATH`
2. 调用官方命令：
   - `lobster run --mode tool --file ... --args-json ...`
3. 解析官方 JSON envelope
4. 把结果收敛为 proposal repo 当前认得的：
   - `registry.json`
   - `callback.json`
   - `lobster-envelope.json`
   - `lobster-command.json`

### 4.4 为什么这层 wrapper 是必要的

因为 proposal repo 当前真实真值不是“Lobster 原始输出”，而是：

- task registry 结构
- callback status 语义
- evidence 字段口径

所以即便官方 runtime 已可执行，仍需要一层最薄 adapter，把“官方输出”翻译回“本仓已冻结的最小真值格式”。

---

## 5. 当前最小 smoke 路径（已具备）

### 5.1 安装

```bash
cd poc/official_lobster_bridge
npm install
```

### 5.2 执行

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json
```

### 5.3 期望输出

默认写入：`poc/official_lobster_bridge/runs/chain-basic/`

包含：

- `registry.json`
- `callback.json`
- `lobster-envelope.json`
- `lobster-command.json`

### 5.4 这条 smoke 证明了什么

它证明：

- proposal repo 已能通过 **官方 Lobster CLI** 跑起一个 repo-local workflow file；
- 该结果已能被收敛为当前 proposal repo 现有的 `registry/callback` 输出物；
- 因此下一步可以开始把 `chain-basic` 的执行器，从 `poc/lobster_minimal_validation` 切到 `poc/official_lobster_bridge`。

### 5.5 这条 smoke 还没有证明什么

它**还没有**证明：

- `human-gate` 已切到官方 runtime；
- `subagent` handoff 已切到官方 runtime；
- `failure-branch` 有官方原生 fallback 语义；
- `openclaw.invoke` shim 口径已完全稳定。

---

## 6. 对下一步 `chain-basic` 官方切换的判断

## 6.1 已具备的条件

- 有官方 CLI 可调用路径；
- 有 repo-local workflow 文件落点；
- 有 repo-local runner；
- 有最小 smoke 路径；
- 有明确回退方案。

## 6.2 仍需在下一步完成的事

1. 把 `chain-basic` 的对外入口，从“POC harness”切到“official bridge”
2. 对齐 `expected/chain-basic` 基线产物（必要时补一个官方版 expected fixture）
3. 决定是否保留 `official_runtime` 这类新增 evidence 字段，还是做成可选扩展
4. 若要继续推进 human-gate / subagent，再补对应 workflow file 与 bridge 适配

## 6.3 readiness 结论

**结论：具备进入下一步 `chain-basic` 官方运行切换的条件。**

但口径必须保持克制：

- 可以说：`chain-basic` 已具备“切到官方 runtime”的前置条件；
- 不可以说：整个 proposal repo 已完成官方 Lobster 真接入。

---

## 7. 后续建议（只列最小必要项）

1. **E1-T3 先只切 `chain-basic`**，不要顺手把 human-gate / subagent 一起拉进来。
2. 切换时优先保证：
   - `registry/callback` 契约不破；
   - 出问题可一键回退到现有 POC harness。
3. 等 `chain-basic` 跑稳，再决定是否：
   - 上 `openclaw.invoke` 直连；
   - 引入 SDK-first 层；
   - 处理 human-gate / subagent / callback 更深闭环。
