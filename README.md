# OpenClaw Workflow Engine 方案仓

> 这个仓库的主线已经重置：**它不是 human-gate 插件仓，也不是零散 POC 收纳箱，而是 OpenClaw 公司级 workflow engine 的架构方案仓。**

## 结论先行

**当前推荐方向不是自研通用 DAG 平台，也不是直接让 Temporal / LangGraph 接管全局。**

我们选择一条更工程化、风险更低、与现有 OpenClaw 资产更连续的路线：

1. **官方底座层**优先复用 `OpenClaw 原生能力 + Lobster 官方工作流壳`
2. 在其上补一层**公司自己的编排控制层**，统一 task registry / state machine / callback / timeline
3. **执行层**继续以 `subagent` 为默认内部主链，`browser / message / cron` 为标准 activity，外部异步再按需接 ACP / watcher / Temporal
4. **业务场景层**先只打穿 `workspace-trading`，不一上来追求“平台通吃”
5. **可选安全层**作为横切能力，逐步补强审批、审计、隔离、幂等与回退

一句话：**先做“薄控制、强边界、可回退”的 workflow engine 方案仓，再决定哪里需要重型 durable execution。**

---

## 仓库定位

这个仓库现在只服务一个核心目标：

> **给 OpenClaw 建立公司级 workflow engine 总方案，并沉淀从 P0 到 P2 的落地路线。**

因此主线关注的是：
- 分层架构
- 控制平面与执行平面的边界
- 官方能力与自定义能力的接口
- 已验证 / 未验证 / 风险 / 路线图
- 首个业务落地（`workspace-trading`）

而不是：
- 某一个 human-gate 插件本身
- 某个局部 POC 的实现细节
- 单次实验的临时验证笔记

这些内容仍然保留，但被明确下沉到 **`docs/validation/`** 或 **`plugins/`**，不再盖过主线。

---

## 五层架构总图

```text
┌────────────────────────────────────────────────────────────┐
│  业务场景层                                                │
│  - workspace-trading（首个落地）                           │
│  - 未来可扩到研究、运营、内容、客服等                      │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  编排控制层                                                │
│  - workflow templates                                      │
│  - task registry / state machine                           │
│  - callback / delivery / timeline                          │
│  - router / retry / escalation / observability             │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  执行层                                                    │
│  - subagent（默认内部主链）                                │
│  - browser / message / cron                                │
│  - external async / ACP / future Temporal workers          │
└────────────────────────────────────────────────────────────┘
                            ▲
┌────────────────────────────────────────────────────────────┐
│  官方底座层                                                │
│  - OpenClaw 原生 session / tool / channel / plugin 能力    │
│  - Lobster 官方 workflow shell / approval / invoke bridge  │
└────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════╗
║  可选安全层（横切）                                        ║
║  - human-gate / policy / allowlist / env isolation        ║
║  - audit / outbox / idempotency / rollback                ║
╚════════════════════════════════════════════════════════════╝
```

---

## 为什么现在选这个方向

### 1. 已验证事实已经足够把主线收敛

我们已经验证到：
- **`subagent` 才是默认内部长任务主链**，不是旧 ACP 主链
- **taskwatcher 更像 external watcher / reconciler**，不是 backbone
- **Lobster 适合做薄工作流壳**，尤其是顺序链、approval、OpenClaw tool bridge
- **真实缺口在控制层统一**：task registry、状态机、幂等 callback、timeline、回退协议

### 2. 现阶段最缺的不是“再来一个引擎”，而是“统一边界”

如果没有控制层统一：
- `subagent / browser / message / cron` 各自讲自己的状态语言
- terminal、callback、delivery、ack 容易混淆
- human-gate、失败分支、重试策略无法沉淀为公司协议
- 业务方无法复用 workflow，只能复制脚本

### 3. 直接上重型方案的 ROI 还不成立

- **Temporal-first**：基础设施、worker、determinism、版本化成本太高
- **LangGraph-first**：更适合 agent 内部 reasoning，不适合公司级 durable backbone
- **自研 DAG-first**：需求还没稳定，过早抽象风险最高

所以现在最优解是：

> **先把 OpenClaw 原生能力与 Lobster 官方能力吃干榨净，再在上层建立我们自己的控制协议。**

---

## 已验证 / 未验证

### 已验证

| 主题 | 当前结论 |
|------|----------|
| Lobster 顺序链 | 可作为 P0/P1 的薄工作流壳 |
| Lobster approval / resume | 可直接服务 human-gate 类流程 |
| OpenClaw tool bridge | `message / browser` 接线难度低 |
| `subagent` 默认主链 | 是当前内部长任务执行事实 |
| callback status 语义 | `terminal ≠ callback sent ≠ acked` 已明确 |
| human-gate / failure-branch 最小 POC | 已有 repo-local harness 与测试 |

### 未验证

| 主题 | 当前状态 |
|------|----------|
| Lobster → 真实 `subagent` 闭环 | 仍需真实接线，不可口头替代 |
| 真并发 / 真 join / 原生 failure-branch | 还未证明，不应提前承诺 |
| workspace-trading 首条真实工作流 | 还未作为业务首例跑通 |
| 跨天 / 强恢复 / 强审计流程 | 暂未证明需要 Temporal |
| 安全层的完整策略化 | 仍停留在原则与局部验证 |

详细见：`docs/validation-status.md`

---

## `chain-basic` 当前 canonical 运行路径

`chain-basic` 这一条现在已经正式收敛为：

### 1. canonical 官方路径（默认）

```bash
python3 poc/official_lobster_bridge/run_official.py chain-basic \
  --input poc/official_lobster_bridge/inputs/chain-basic.args.json
```

- 官方 workflow / runner 位置：`poc/official_lobster_bridge/`
- 输出目录默认：`poc/official_lobster_bridge/runs/chain-basic/`
- 这是当前仓库对 `chain-basic` 的**默认、推荐、canonical** 路径
- 本轮只切 `chain-basic`；`human-gate / subagent / failure-branch` 不在这次切换范围

### 2. legacy fallback 路径（保留，不再默认）

```bash
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json
```

- 位置：`poc/lobster_minimal_validation/`
- 用途：官方 runtime 不可用时的回退基线
- 口径：**fallback only**，不再作为 `chain-basic` 主入口

### 3. 最小自动化验证

```bash
python3 -m unittest tests.test_official_lobster_bridge_runner -v
```

这组测试同时覆盖：
- 官方 runner 的 artifact 收敛
- 请求 fallback 时退回 legacy POC harness
- 本地已安装官方 Lobster CLI 时的真实 smoke

---

## 新增：最小 scheduler / dispatcher core（Batch1）

这批已经把 **registry library + 顺序 dispatcher** 抽成可复用模块：

- `orchestration_runtime/task_registry.py`
- `orchestration_runtime/scheduler.py`
- `orchestration_runtime/builtin_handlers.py`
- `scripts/run_minimal_scheduler.py`
- `examples/workflows/chain-basic.scheduler.json`

关键口径：

- 只支持 **顺序链**，不做 DAG / parallel / join
- 顶层 registry 仍冻结为 6 字段
- `waiting_subagent` 不新增顶层 state，而是写进 `evidence.scheduler.waiting_for`
- `callback_status` 与业务终态继续分离

快速 sample：

```bash
python3 scripts/run_minimal_scheduler.py \
  --workflow examples/workflows/chain-basic.scheduler.json \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json \
  --run-dir /tmp/chain-basic-scheduler-run
```

详细 contract：`docs/scheduler-dispatch-contract.md`

---

## 全局路线图

### P0：重置主线，打通最小闭环

目标：**先把仓库和方案口径统一，再做一条真实业务闭环。**

- 明确五层架构与仓库主线
- 固化 task registry / state machine / callback 语义
- 用官方底座层 + 编排控制层打穿一条最小 workflow
- 让 `workspace-trading` 成为首个落地对象（先 dry-run / shadow-run）

### P1：补齐控制层与执行适配器

目标：**让 workflow engine 从“可讲清楚”走到“可复用”。**

- 完成 `subagent / browser / message / cron` adapter contract
- 补齐 templates：chain / human-gate / failure-branch 为先；parallel / join 仅在真实验证后纳入
- 建立 timeline / observability / retry / escalation 基线
- 让 `workspace-trading` 成为稳定 pilot

### P2：只把真正值得重型化的部分升级

目标：**Selective durability，而不是全量重做。**

- 只有跨天、强恢复、强审计、强 SLA 流程才考虑 Temporal
- 安全层从“可选”进入“策略化”
- 再评估是否需要更重的 workflow runtime，而不是反过来迁就工具

详细见：`docs/roadmap.md`

---

## 文档结构（重构后）

### 主线文档

1. `docs/executive-summary.md` — 给老板和评审的 5 分钟版本
2. `docs/openclaw-company-orchestration-proposal.md` — 仓库主方案文档
3. `docs/architecture-layering.md` — 五层架构拆解与接口边界
4. `docs/validation-status.md` — 已验证 / 未验证 / 选择理由
5. `docs/roadmap.md` — P0 / P1 / P2 路线图

### 支撑文档

- `docs/supporting/shortlist-existing-options.md`
- `docs/supporting/thin-orchestration-layer.md`

### 验证与 POC 文档（已下沉）

- `docs/validation/` 下保留历史评审、契约、桥接模拟、P0 readiness 文档
- `plugins/human-gate-message/` 保留插件代码与局部说明
- `poc/` 保留最小验证 harness 与样例

**原则：主线文档只回答“总方案是什么”；验证文档只回答“某一段证据是什么”。**

---

## 首个落地：workspace-trading

这个仓库不再做抽象架构空转，首个落地对象明确为：

> **`workspace-trading` 的 workflow engine 化。**

第一批建议聚焦三类流程：
1. 盘前 preflight / 环境检查
2. 盘中风险守门 / 人工确认点
3. 盘后汇总 / 回执 / 审计沉淀

原因很直接：
- 场景真实、约束强、风险高，能逼出正确边界
- 既有自动化，也天然需要 human-gate
- 对 timeline、delivery、rollback 的要求高，适合验证控制层价值

---

## 这仓库现在不做什么

- 不把 `taskwatcher` 包装成公司级 backbone
- 不把 `human-gate` 插件误写成仓库主线
- 不把 POC 成果直接升格为平台能力
- 不默认承诺并发、join、跨天 durability 已解决
- 不在 P0 就自研通用 DAG engine

---

## 推荐阅读顺序

### 想 5 分钟抓住主线
1. `docs/executive-summary.md`
2. `docs/validation-status.md`
3. `docs/roadmap.md`

### 想完整评审方案
1. `docs/openclaw-company-orchestration-proposal.md`
2. `docs/architecture-layering.md`
3. `docs/supporting/shortlist-existing-options.md`
4. `docs/supporting/thin-orchestration-layer.md`

### 想追验证细节
- 进入 `docs/validation/`
- 再看 `plugins/` 与 `poc/`

---

## 当前仓库状态

- **主线口径**：已重置为 workflow engine 总方案仓
- **首个落地场景**：`workspace-trading`
- **默认内部执行主链**：`sessions_spawn(runtime="subagent")`
- **重型引擎策略**：仅在 P2 选择性引入
- **human-gate / POC 定位**：验证资产，不再主导仓库叙事
