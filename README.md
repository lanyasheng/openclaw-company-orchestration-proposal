# OpenClaw Company Orchestration Monorepo

> **OpenClaw 公司级编排统一入口** — 5 分钟快速开始 + 当前架构真值 + 导航

**最后更新**: 2026-03-23 | **状态**: Trading live path 已通 | Control-plane 主链已收口

---

## 🚀 5 分钟快速开始

### 1. 阅读入口（从这里开始）

| 你是 | 读这个 | 时间 |
|------|--------|------|
| **第一次了解** | [`docs/executive-summary.md`](docs/executive-summary.md) | 5 分钟 |
| **要看当前真值** | [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) | 10 分钟 |
| **要接入非 trading 频道** | [`docs/quickstart-other-channels.md`](docs/quickstart-other-channels.md) | 5 分钟 |
| **完整架构评审** | [`docs/architecture-layering.md`](docs/architecture-layering.md) | 30 分钟 |

### 2. 运行入口（从这里用）

**统一命令**（推荐）：
```bash
python3 ~/.openclaw/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

**或从本仓运行**：
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

### 3. 验证测试
```bash
python3 -m unittest tests/ -v
```

---

## 📐 当前架构（双轨策略）

### 执行后端：Subagent 为主，Tmux 为辅

```
┌─────────────────────────────────────────────────────────────┐
│  Control Plane (OpenClaw 原生)                              │
│  - sessions_spawn / callback / dispatch                     │
│  - task registry / state machine / timeline                 │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            │                               │
            ▼                               ▼
┌───────────────────────┐     ┌───────────────────────────────┐
│  Subagent Backend     │     │  Tmux Backend                 │
│  (默认主路径)          │     │  (兼容路径)                   │
│  - 编码/文档/长任务     │     │  - 需要中间状态观测            │
│  - runner 管理          │     │  - 可 SSH attach               │
│  - 自动超时/milestone  │     │  - 无自动超时                 │
│  - 完成自动通知        │     │  - 需手动轮询 status           │
└───────────────────────┘     └───────────────────────────────┘
```

**选择指南**：
- **默认选 Subagent**：编码实现、文档撰写、测试执行、长任务（>30 秒）
- **选 Tmux**：需要监控中间进度、容易卡住的任务、需要 SSH 介入调试

### 当前适用范围

| 场景 | 状态 | 说明 |
|------|------|------|
| **Trading Live Path** | ✅ 已通 | `trading_roundtable` continuation 最小落地，safe semi-auto |
| **Control-Plane 主链** | ✅ 已收口 | `channel_roundtable` 通用适配器就绪，白名单 + 条件触发 |
| **其他频道** | 🟡 可按需接入 | 默认 `allow_auto_dispatch=false`，先验证 callback/ack 稳定 |

---

## 🗺️ 文档导航

### 核心文档
- [`docs/executive-summary.md`](docs/executive-summary.md) — 5 分钟版本，给老板和评审
- [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) — 当前 live 真值、边界、计划入口
- [`docs/architecture-layering.md`](docs/architecture-layering.md) — 五层架构详解
- [`docs/quickstart-other-channels.md`](docs/quickstart-other-channels.md) — 非 trading 场景接入

### 支撑文档
- [`docs/validation-status.md`](docs/validation-status.md) — 已验证 / 未验证清单
- [`docs/technical-debt-2026-03-22.md`](docs/technical-debt-2026-03-22.md) — 技术债务与待办
- [`docs/migration-retirement-plan.md`](docs/migration-retirement-plan.md) — 迁移与退役计划

### 历史文档
- `docs/batch-summaries/` — 迭代批次总结（历史参考）
- `docs/validation/` — 验证细节与 POC 证据（下沉资产）

---

## 🏗️ 仓库结构

```
openclaw-company-orchestration-proposal/
├── docs/                      # 阅读入口：方案、真值、导航
├── runtime/                   # 实现真值：orchestrator、scripts、skills
├── orchestration_runtime/     # Runtime 库：task_registry、scheduler、handlers
├── tests/                     # 验收测试：针对 runtime 的验证
├── examples/                  # Operator-facing 示例
├── scripts/                   # 工具脚本
└── README.md                  # 本文件：唯一快速入口
```

**原则**：
- `docs/` 持阅读入口
- `runtime/` + `orchestration_runtime/` 持实现真值
- `tests/` 持验收真值
- 禁止双写：本地 workspace 副本已标记 deprecated

---

## ✅ 已验证能力

| 能力 | 状态 |
|------|------|
| Subagent 默认主链 | ✅ 已验证 |
| Lobster 顺序链 + approval | ✅ 已验证 |
| Callback status 语义分离 | ✅ 已验证 |
| Trading continuation 最小落地 | ✅ 已验证 (safe semi-auto) |
| Channel roundtable 通用适配 | ✅ 已验证 |
| Tmux backend 可选路径 | ✅ 已验证 (收紧边界) |

---

## ⚠️ 当前边界

- **总体定位**: Thin bridge / allowlist / safe semi-auto
- **Trading**: 仅 clean PASS 默认 `triggered`，其余结果默认 `skipped`
- **其他频道**: 首次接入建议 `allow_auto_dispatch=false`
- **Tmux**: 正式可选 backend，但 trading real run 仍只到 dry-run
- **重型引擎**: Temporal/LangGraph 仅进入叶子层，不接管 control plane

---

## 🔧 常用命令

### 编排命令
```bash
# 统一入口
python3 ~/.openclaw/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 查看帮助
python3 ~/.openclaw/scripts/orch_command.py --help
```

### 测试命令
```bash
# 全量测试
python3 -m unittest tests/ -v

# 单测试文件
python3 -m unittest tests/orchestrator/test_auto_dispatch.py -v
```

### Git 操作
```bash
# 查看状态
git status

# 查看最近提交
git log --oneline -10
```

---

## 📞 问题与反馈

- **文档问题**: 在对应文档目录提 issue 或直接 PR
- **Runtime 问题**: `runtime/` 或 `orchestration_runtime/` 目录提 issue
- **紧急问题**: Discord #general 频道 @main (Zoe)

---

## 📜 许可证与贡献

本仓库为 OpenClaw 公司内部项目。贡献前请阅读：
- [`AGENTS.md`](../AGENTS.md) — Agent 工作规范
- [`TEAM_RULES.md`](../shared-context/TEAM_RULES.md) — 团队共享规则

---

**最后更新**: 2026-03-23  
**维护者**: Zoe (CTO & Chief Orchestrator)  
**仓库**: `openclaw-company-orchestration-proposal` (OpenClaw workspace repo)
