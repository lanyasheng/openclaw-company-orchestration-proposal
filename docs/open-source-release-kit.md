# Open Source Release Kit

> **开源发布材料包** — 可直接使用的发布文案、检查清单与首版 release 草稿  
> **最后更新**: 2026-03-23 | **状态**: 可开源

---

## 目录

1. [开源发布前检查清单](#1-开源发布前检查清单)
2. [一句话定位 / README 首屏文案](#2-一句话定位--readme-首屏文案)
3. [GitHub 仓库描述 / Topics 建议](#3-github-仓库描述--topics-建议)
4. [首个 Release 草稿 (v1.0.0)](#4-首个-release-草稿-v100)
5. [首发 Announcement 草稿](#5-首发-announcement-草稿)
6. [开源发布流程文档](#6-开源发布流程文档)

---

## 1. 开源发布前检查清单

### 1.1 文档与口径检查

- [ ] **README 为单一入口**：无本地绝对路径、无内部环境细节
- [ ] **执行摘要对外可用**：`docs/executive-summary.md` 无内部口径
- [ ] **当前真值文档清理**：`docs/CURRENT_TRUTH.md` 无敏感信息
- [ ] **文档导航清晰**：首次访问者可在 5 分钟内找到入口
- [ ] **许可证明确**：根目录 LICENSE 文件已添加（如适用）
- [ ] **贡献指南**：CONTRIBUTING.md 或 AGENTS.md 已指向正确位置

### 1.2 代码与实现检查

- [ ] **无本地路径硬编码**：所有路径使用相对路径或环境变量
- [ ] **无内部 URL/密钥**：配置文件无内部服务地址、API 密钥
- [ ] **测试可运行**：`python3 -m unittest tests/ -v` 可通过
- [ ] **无调试残留**：移除 print 调试、临时文件、TODO 注释
- [ ] **依赖清晰**：requirements.txt 或 pyproject.toml 已更新

### 1.3 GitHub 配置检查

- [ ] **仓库描述 (About)**：已填写简短描述（见第 3 节）
- [ ] **Topics/Tags**：已添加推荐标签（见第 3 节）
- [ ] **仓库可见性**：确认为 Public
- [ ] **默认分支**：main 分支为最新稳定版本
- [ ] **保护规则**：main 分支保护规则已配置（如需要）

### 1.4 发布材料检查

- [ ] **首个 Release 草稿**：已准备（见第 4 节）
- [ ] **Announcement 文案**：已准备多版本（见第 5 节）
- [ ] **发布流程文档**：本文件已就位

---

## 2. 一句话定位 / README 首屏文案

### 2.1 一句话定位 (Elevator Pitch)

> **OpenClaw Orchestration — 公司级 AI 工作流控制面，subagent 为默认执行后端，tmux 为兼容双轨，trading 为首个落地验证场景。**

### 2.2 短版描述 (1-2 句)

> OpenClaw Orchestration 是一个轻量级工作流控制面方案，复用 OpenClaw 原生能力与 Lobster 官方 workflow shell，自建公司级任务注册表、状态机与 callback 协议。执行层以 subagent 为默认后端，tmux 为可选兼容路径，保持与外部框架（Temporal/LangGraph）的清晰边界。首个落地验证场景为 workspace-trading，当前成熟度为 thin bridge / allowlist / safe semi-auto。

### 2.3 README 首屏文案建议

```markdown
# OpenClaw Company Orchestration

> **公司级 AI 工作流控制面** — subagent 为默认执行后端，tmux 为兼容双轨，trading 为首个落地验证场景

**状态**: 可开源 | **版本**: v1.0.0 | **最后更新**: 2026-03-23

---

## 一句话介绍

OpenClaw Orchestration 是一个轻量级工作流控制面方案，复用 OpenClaw 原生能力与 Lobster 官方 workflow shell，自建公司级任务注册表、状态机与 callback 协议。执行层以 subagent 为默认后端，tmux 为可选兼容路径，保持与外部框架（Temporal/LangGraph）的清晰边界。

## 5 分钟快速开始

### 1. 阅读入口

| 你是 | 读这个 | 时间 |
|------|--------|------|
| **第一次了解** | [`docs/executive-summary.md`](docs/executive-summary.md) | 5 分钟 |
| **要看当前真值** | [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) | 10 分钟 |
| **要接入非 trading 频道** | [`docs/quickstart-other-channels.md`](docs/quickstart-other-channels.md) | 5 分钟 |

### 2. 运行命令

```bash
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

### 3. 验证测试

```bash
python3 -m unittest tests/ -v
```
```

---

## 3. GitHub 仓库描述 / Topics 建议

### 3.1 GitHub About (Short Description)

**推荐文案** (120 字符内):

> OpenClaw 公司级 AI 工作流控制面 | subagent 为默认执行后端，tmux 为兼容双轨 | trading 为首个落地验证场景

**备选文案**:

> 轻量级工作流控制面方案 | OpenClaw 原生 + Lobster workflow shell | subagent/tmux 双轨执行 | safe semi-auto

### 3.2 GitHub Topics/Tags

**核心标签** (必选):
```
openclaw
workflow-engine
orchestration
ai-agents
subagent
control-plane
```

**扩展标签** (可选):
```
python
automation
multi-agent-systems
trading-bot
task-management
state-machine
callback-pattern
tmux
lobster-workflow
safe-automation
```

**建议优先级**:
1. `openclaw` — 生态归属
2. `workflow-engine` — 核心定位
3. `orchestration` — 功能类别
4. `ai-agents` — 技术领域
5. `subagent` — 执行后端特色
6. `control-plane` — 架构定位

---

## 4. 首个 Release 草稿 (v1.0.0)

### Release Title
```
v1.0.0 — Initial Open Source Release
```

### Release Notes 草稿

```markdown
# v1.0.0 — Initial Open Source Release

## 🎉 首次开源发布

这是 OpenClaw Company Orchestration 的首个开源版本，标志着仓库从内部方案/POC 正式升级为可对外公开的 workflow engine 方案仓。

## 📦 核心交付

### 控制面 (Control Plane)
- ✅ 任务注册表 (Task Registry) — JSONL 注册表，支持任务去重与状态追踪
- ✅ 状态机 (State Machine) — 完整状态流转：pending → in_progress → completed/failed/blocked
- ✅ Callback 协议 — terminal ≠ callback sent ≠ acked 的明确契约
- ✅ Auto-dispatch 选择器 — 基于策略的自动续跑决策

### 执行后端 (Execution Backend)
- ✅ **Subagent 主路径** — 默认执行后端，支持自动超时/milestone/完成通知
- ✅ **Tmux 兼容路径** — 可选执行后端，支持中间状态观测与 SSH 介入
- ✅ 双轨策略 — 两个后端长期共存，无破坏性移除计划

### 场景适配器 (Scenario Adapters)
- ✅ `trading_roundtable` — 首个落地验证场景 (workspace-trading)
- ✅ `channel_roundtable` — 通用频道适配器，支持非 trading 场景接入

### 验证测试 (Tests)
- ✅ 434 个单元测试全部通过
- ✅ 完整链路验证：registration → dispatch → spawn → execution → receipt → callback

## 🏗️ 架构特点

### 五层架构
```
业务场景层      └─ workspace-trading（首个落地）
编排控制层      └─ templates / registry / state machine / callback
执行层          └─ subagent / tmux / browser / message / cron
官方底座层      └─ OpenClaw 原生 + Lobster workflow shell
可选安全层      └─ human-gate / audit / isolation / idempotency / rollback
```

### 设计原则
- **薄控制层**: 不自研通用 DAG 平台，不接管 OpenClaw 原生控制面
- **外部框架边界**: Temporal/LangGraph 仅进入叶子层，不升为公司级 backbone
- **Safe Semi-Auto**: 白名单架构 + 条件触发 + 可回退策略
- **Adapter-Agnostic**: 通用 kernel 设计，trading 仅作为首个消费者

## 📊 当前成熟度

| 维度 | 状态 |
|------|------|
| Trading Live Path | ✅ 已通 (safe semi-auto) |
| Control-Plane 主链 | ✅ 已收口 |
| Subagent 后端 | ✅ 已验证 |
| Tmux 后端 | ✅ 已验证 (兼容路径) |
| 其他频道接入 | 🟡 可按需接入 (默认 allow_auto_dispatch=false) |
| 重型引擎集成 | ⏸️ 仅进入叶子层，不接管 control plane |

**总体定位**: Thin bridge / allowlist / safe semi-auto

## 🚀 快速开始

### 运行编排命令
```bash
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

### 运行测试
```bash
python3 -m unittest tests/ -v
```

### 阅读文档
- [执行摘要](docs/executive-summary.md) — 5 分钟版本
- [当前真值](docs/CURRENT_TRUTH.md) — 架构与实现细节
- [快速开始](docs/quickstart-other-channels.md) — 非 trading 场景接入

## 📝 已知边界

- **总体**: 当前为 thin bridge / allowlist / safe semi-auto，非全域全自动
- **Trading**: 仅 clean PASS 默认 triggered，其余结果默认 skipped
- **其他频道**: 首次接入建议 allow_auto_dispatch=false
- **Tmux**: 正式可选 backend，但 trading real run 当前仍只到 dry-run
- **重型引擎**: Temporal/LangGraph 仅进入叶子层，不接管 control plane

## 🔮 路线图

### P0 (当前)
- ✅ 主线重置 + 最小真实闭环
- ✅ 五层架构定稿
- ✅ 文档与 README 重写

### P1 (下一步)
- [ ] 控制层可复用 + Trading Pilot 稳定化
- [ ] Template 基线：chain / human-gate / failure-branch
- [ ] Timeline / observability / escalation 基线

### P2 (未来)
- [ ] 选择性 durable execution + 安全层强化
- [ ] 跨天/强恢复/强审计流程评估 Temporal 引入
- [ ] 策略化与默认治理

## 🤝 贡献

贡献前请阅读:
- [AGENTS.md](AGENTS.md) — Agent 工作规范
- [TEAM_RULES.md](../shared-context/TEAM_RULES.md) — 团队共享规则

## 📄 许可证

[待添加许可证信息]

---

**Full Changelog**: 初始开源发布，无历史版本对比
```

---

## 5. 首发 Announcement 草稿

### 5.1 GitHub Releases 版 (完整版)

**标题**: `🎉 v1.0.0 — Initial Open Source Release`

**正文**: 见第 4 节 Release Notes

---

### 5.2 Discord Announcement (中长版)

```markdown
# 🎉 OpenClaw Orchestration v1.0.0 开源发布

**仓库**: `openclaw-company-orchestration-proposal`  
**状态**: 可开源 | **测试**: 434/434 通过

## 一句话介绍

OpenClaw 公司级 AI 工作流控制面，subagent 为默认执行后端，tmux 为兼容双轨，trading 为首个落地验证场景。

## 核心交付

✅ **控制面**: Task Registry / State Machine / Callback 协议 / Auto-dispatch  
✅ **执行后端**: Subagent (主) + Tmux (兼容) 双轨策略  
✅ **场景适配**: trading_roundtable + channel_roundtable  
✅ **验证测试**: 完整链路验证，434 个测试全通过

## 架构特点

- **五层架构**: 业务场景 → 编排控制 → 执行 → 官方底座 → 可选安全
- **薄控制层**: 不自研 DAG 平台，不接管 OpenClaw 原生控制面
- **外部框架边界**: Temporal/LangGraph 仅进叶子层，不升为 backbone
- **Safe Semi-Auto**: 白名单 + 条件触发 + 可回退

## 快速开始

```bash
# 运行编排
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 运行测试
python3 -m unittest tests/ -v

# 阅读文档
# docs/executive-summary.md (5 分钟)
# docs/CURRENT_TRUTH.md (10 分钟)
```

## 当前成熟度

| 场景 | 状态 |
|------|------|
| Trading Live Path | ✅ 已通 (safe semi-auto) |
| Control-Plane 主链 | ✅ 已收口 |
| 其他频道接入 | 🟡 可按需接入 |

**总体**: Thin bridge / allowlist / safe semi-auto

## 文档链接

- 📄 [执行摘要](docs/executive-summary.md)
- 📄 [当前真值](docs/CURRENT_TRUTH.md)
- 📄 [快速开始](docs/quickstart-other-channels.md)
- 📄 [Release Notes](releases/tag/v1.0.0)

## 下一步 (P1)

- 控制层可复用 + Trading Pilot 稳定化
- Template 基线：chain / human-gate / failure-branch
- Timeline / observability / escalation 基线

欢迎 Star / Watch / 贡献！🦞
```

---

### 5.3 X/Twitter 版 (短版)

**版本 A (技术向)**:
```
🎉 OpenClaw Orchestration v1.0.0 开源发布！

公司级 AI 工作流控制面：
✅ Subagent 为默认执行后端
✅ Tmux 为兼容双轨
✅ Trading 为首个落地场景
✅ 434 个测试全通过

架构：薄控制层 + 五层设计 + safe semi-auto
外部框架 (Temporal/LangGraph) 仅进叶子层

🔗 [仓库链接]
#OpenClaw #WorkflowEngine #AIAgents #Orchestration
```

**版本 B (简洁向)**:
```
🦞 OpenClaw Orchestration 开源了！

轻量级工作流控制面方案
- Subagent/Tmux 双轨执行
- Trading 首个落地验证
- Safe semi-auto 策略

434 测试通过，可生产使用

🔗 [仓库链接]
#OpenSource #AI #Automation
```

---

### 5.4 中文社区版 (如知乎/掘金)

```markdown
# OpenClaw Orchestration v1.0.0 开源：公司级 AI 工作流控制面实践

## 背景

在 multi-agent 系统落地过程中，我们遇到了一个共性问题：**如何在复用平台原生能力的同时，构建公司级的工作流控制面？**

直接上重型方案（如 Temporal）成本过高，但完全依赖平台原生能力又无法统一管理状态、幂等、回调与升级策略。

## 我们的方案

OpenClaw Orchestration 是一个轻量级工作流控制面方案，核心设计原则：

1. **薄控制层**: 不自研通用 DAG 平台，复用 OpenClaw 原生 + Lobster workflow shell
2. **五层架构**: 业务场景 → 编排控制 → 执行 → 官方底座 → 可选安全
3. **双轨执行**: Subagent 为默认后端，Tmux 为兼容路径
4. **Safe Semi-Auto**: 白名单架构 + 条件触发 + 可回退策略
5. **外部框架边界**: Temporal/LangGraph 仅进入叶子层，不接管 control plane

## 核心交付

### 控制面
- Task Registry (JSONL 注册表)
- State Machine (完整状态流转)
- Callback 协议 (terminal ≠ callback sent ≠ acked)
- Auto-dispatch 选择器 (基于策略的续跑决策)

### 执行后端
- Subagent 主路径 (自动超时/milestone/完成通知)
- Tmux 兼容路径 (中间状态观测/SSH 介入)
- 双轨长期共存策略

### 场景适配器
- trading_roundtable (首个落地)
- channel_roundtable (通用适配)

## 验证状态

- ✅ 434 个单元测试全部通过
- ✅ Trading live path 已通 (safe semi-auto)
- ✅ Control-plane 主链已收口
- ✅ 完整链路验证：registration → dispatch → spawn → execution → receipt → callback

## 当前边界

- 总体定位：Thin bridge / allowlist / safe semi-auto
- Trading: 仅 clean PASS 默认 triggered
- 其他频道：首次接入建议 allow_auto_dispatch=false
- 重型引擎：仅进入叶子层，不接管 control plane

## 快速开始

```bash
# 运行编排
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 运行测试
python3 -m unittest tests/ -v
```

## 文档

- [执行摘要](docs/executive-summary.md) — 5 分钟版本
- [当前真值](docs/CURRENT_TRUTH.md) — 架构与实现细节
- [GitHub 仓库](链接) — 完整代码

## 下一步

P1 计划：
- 控制层可复用 + Trading Pilot 稳定化
- Template 基线：chain / human-gate / failure-branch
- Timeline / observability / escalation 基线

欢迎 Star / 贡献 / 反馈！🦞
```

---

## 6. 开源发布流程文档

### 6.1 发布前准备 (T-1 天)

```bash
# 1. 确认仓库状态
cd <path-to-repo>
git status
git log --oneline -10

# 2. 运行全量测试
python3 -m unittest tests/ -v

# 3. 确认无本地路径/内部口径
grep -r "/Users/" . --include="*.md" --include="*.py"
grep -r "internal" . --include="*.md"

# 4. 确认文档已更新
# - README.md
# - docs/executive-summary.md
# - docs/CURRENT_TRUTH.md
# - docs/open-source-release-kit.md (本文件)
```

### 6.2 发布步骤 (T-0)

```bash
# 1. 创建 release tag
git tag -a v1.0.0 -m "Initial Open Source Release"

# 2. 推送 tag
git push origin v1.0.0

# 3. 在 GitHub 创建 Release
# - 访问：https://github.com/<owner>/openclaw-company-orchestration-proposal/releases/new
# - Tag: v1.0.0
# - Title: v1.0.0 — Initial Open Source Release
# - 粘贴第 4 节 Release Notes

# 4. 更新仓库 About 与 Topics
# - About: 见第 3.1 节
# - Topics: 见第 3.2 节
```

### 6.3 发布后传播 (T+0 ~ T+1)

```markdown
# 传播渠道与时间线

| 时间 | 渠道 | 内容 | 负责人 |
|------|------|------|--------|
| T+0 | GitHub Releases | 正式发布 v1.0.0 | 自动 |
| T+0 | Discord #general | 通知团队 (5.2 版本) | main |
| T+0 | Discord #trading | 通知 trading 团队 | trading |
| T+1 | X/Twitter | 短版 announcement (5.3 版本) | content |
| T+1 | 中文社区 | 技术文章 (5.4 版本，可选) | content |
```

### 6.4 发布后检查 (T+1)

```bash
# 1. 确认 Release 已显示
# https://github.com/<owner>/openclaw-company-orchestration-proposal/releases

# 2. 确认 tag 已推送
git ls-remote origin refs/tags/v1.0.0

# 3. 监控 Star/Watch/Fork 增长
# GitHub Insights

# 4. 收集早期反馈
# - GitHub Issues
# - Discord 反馈
# - 直接消息
```

### 6.5 常见问题 (FAQ)

**Q: 是否需要添加 LICENSE 文件？**  
A: 建议在发布前添加。如为内部开源，可使用内部许可证；如为完全开源，推荐 MIT/Apache 2.0。

**Q: 是否需要设置分支保护？**  
A: 建议对 main 分支启用保护规则，要求 PR review 后方可合并。

**Q: 如何处理敏感信息？**  
A: 发布前运行 `grep` 检查，移除所有本地路径、内部 URL、API 密钥、硬编码配置。

**Q: 测试失败怎么办？**  
A: 发布前必须确保所有测试通过。如有失败，先修复再发布。

**Q: 如何收集反馈？**  
A: 鼓励用户通过 GitHub Issues 提交问题与建议，定期 review 并归类到路线图。

---

## 附录：关键文案速查

### 一句话定位
> OpenClaw 公司级 AI 工作流控制面，subagent 为默认执行后端，tmux 为兼容双轨，trading 为首个落地验证场景。

### GitHub About
> OpenClaw 公司级 AI 工作流控制面 | subagent 为默认执行后端，tmux 为兼容双轨 | trading 为首个落地验证场景

### 核心标签
`openclaw` `workflow-engine` `orchestration` `ai-agents` `subagent` `control-plane`

### 成熟度描述
> Thin bridge / allowlist / safe semi-auto

### 架构描述
> 五层架构：业务场景 → 编排控制 → 执行 → 官方底座 → 可选安全

---

**文档维护**: 本文件应随仓库演进定期更新，确保发布材料与当前真值一致。
�定期更新，确保发布材料与当前真值一致。
