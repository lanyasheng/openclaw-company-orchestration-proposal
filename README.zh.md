# OpenClaw Orchestration Control Plane

> **OpenClaw 多 Agent 工作流编排的统一控制面。**
>
> **默认后端：** subagent | **兼容后端：** tmux | **首个验证场景：** trading continuation
>
> **当前成熟度：** safe semi-auto / thin bridge / 单场景生产验证

---

## 快速开始（30 秒）

**统一入口命令：**

```bash
python3 ~/.openclaw/scripts/orch_command.py
```

**常见场景：**

```bash
# 默认：使用当前频道上下文
python3 ~/.openclaw/scripts/orch_command.py

# 指定频道/主题
python3 ~/.openclaw/scripts/orch_command.py \
  --channel-id "discord:channel:YOUR_ID" \
  --channel-name "your-channel" \
  --topic "讨论主题"

# Trading 场景
python3 ~/.openclaw/scripts/orch_command.py --context trading_roundtable

# 首次接入：先验证稳定再开启自动执行
python3 ~/.openclaw/scripts/orch_command.py --auto-execute false
```

**默认行为：**
- ✅ coding lane → Claude Code（via subagent）
- ✅ non-coding lane → subagent
- ✅ auto_execute=true（自动注册/派发/回调/续推）
- ✅ gate_policy=stop_on_gate（命中 gate 正常停住）

**文档入口：**
- **Skill 入口：** [`runtime/skills/orchestration-entry/SKILL.md`](runtime/skills/orchestration-entry/SKILL.md)
- **其他频道：** [`docs/quickstart/quickstart-other-channels.md`](docs/quickstart/quickstart-other-channels.md)
- **当前真值：** [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md)

---

## 这个仓库解决什么问题

**核心问题：** 当一个任务完成后，系统如何知道下一步该做什么——并且安全地继续推进？

真实的多 Agent 系统很少因为"模型无法回答"而失败。它们失败是因为：
- 一个任务结束了，但没人知道谁拥有下一步
- 多个子任务都回来了，但没有 clean fan-in 点
- 系统能生成计划，却不能安全地自动派发下一步
- callback 发出去了，但没有正确回到父会话或用户可见频道
- 业务归属和执行归属混在一起

**这个仓库通过以下机制让这些过渡变得显式：**
- Continuation contract
- Handoff schema
- Registration / readiness 追踪
- Dispatch plan
- Bridge consumption
- Execution request / receipt
- Callback/ack 分离

---

## 为什么存在（以及为什么不直接用 Temporal/LangGraph）

很多团队要么过早跳进 Temporal 式的复杂性，要么困在脚本意大利面。这个仓库探索**中间路径**：
- 足够结构化以可靠
- 不过度复杂以保持迭代速度

**为什么不选 Temporal 当 backbone？**
- Temporal 是重型 durable workflow 基础设施——worker 管理、确定性保证、版本控制负担重
- 我们当前需求：Agent 交接的薄控制面，不是企业级 workflow 引擎
- 决策：用 OpenClaw 做 runtime foundation，控制面保持薄且显式

**为什么不选 LangGraph 当 backbone？**
- LangGraph 擅长 Agent 内部的 reasoning graph
- 我们需求：跨多个 Agent 和场景的公司级编排
- 决策：控制面保留在 OpenClaw；LangGraph 仅用于局部 analysis graph（如需要）

**设计原则：** 外部框架只进入叶子执行层，不替代控制面。

---

## 架构总览

```text
┌─────────────────────────────────────────────────────┐
│ 业务场景层                                           │
│ trading / channel / 未来其他领域适配器                │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 控制面（本仓库）                                      │
│ contract / planning / registration / readiness      │
│ callback / receipt / dispatch / continuation        │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ 执行层                                               │
│ subagent（默认）/ Claude Code / tmux（兼容）         │
└─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────┐
│ OpenClaw Runtime 基础层                              │
│ sessions / tools / hooks / channels / messaging     │
└─────────────────────────────────────────────────────┘
```

**关键边界：** 控制面决定**下一步怎么走**；执行层**真正去跑**；OpenClaw 提供原始能力。

### 主流程

```
Request → Planning → Registration → Readiness Check → Dispatch
       → Execution → Receipt → Callback → Next-Step Decision
       → (repeat or closeout)
```

**核心原则：** 一个任务不是在执行停下时结束，而是在**"下一步状态被明确表达"之后才真正收口**。

### Owner 与 Executor 合同

```text
owner    = 业务归属 / 判断 / 验收
executor = 真正执行的人或执行器

例子：
- owner=trading, executor=claude_code
- owner=main, executor=subagent
- owner=content, executor=tmux
```

这个解耦让 coding lane 可以默认走 Claude Code，而不要求业务角色 agent 自己扛执行。

**详细架构：** [`docs/architecture/overview.md`](docs/architecture/overview.md)

---

## 边界（不是什么）

- ❌ 不是通用 DAG 平台
- ❌ 不是 OpenClaw 替代品
- ❌ 不是 LangGraph/Temporal/DeepAgents 的 wrapper
- ❌ 不是单纯的 trading bot repo
- ❌ 不是"全自动无人续跑"

**当前范围：** thin bridge / allowlist / safe semi-auto / trading continuation 已验证

---

## 当前成熟度

| 方面 | 状态 | 说明 |
|------|------|------|
| **后端策略** | ✅ 双轨兼容 | subagent（默认）+ tmux（兼容） |
| **Trading continuation** | ✅ 生产验证 | 真实执行路径已验证 |
| **控制面主链** | ✅ 已打通 | 注册 → 派发 → 执行 → receipt → callback |
| **测试** | ✅ 468 个通过 | 100% 通过率 |
| **自动续推** | ⚠️ safe semi-auto | 白名单、条件触发、可回退 |
| **Git push 自动续推** | ⚠️ 尚未完全自动 | 内部模拟闭环已通；真实 push 执行器待实现 |

**诚实总结：** 已不只是方案稿，但也还没重到可以叫"通用 workflow 平台"。

---

## 仓库结构

```text
openclaw-company-orchestration-proposal/
├── README.md / README.zh.md          # 单入口文档（本文件）
├── docs/
│   ├── CURRENT_TRUTH.md              # 当前真值入口
│   ├── executive-summary.md          # 5 分钟快速概览
│   ├── architecture/                 # 架构图与总览
│   ├── quickstart/                   # 频道专属 Quickstart
│   ├── configuration/                # Auto-trigger 配置与排查
│   ├── plans/                        # 当前计划与路线图
│   ├── reports/                      # 验证与健康报告
│   ├── review/                       # 架构评审
│   ├── technical-debt/               # 技术债务清单
│   └── ...                           # 其他文档
├── runtime/
│   ├── orchestrator/                 # 核心编排逻辑
│   ├── skills/                       # OpenClaw skill 集成
│   └── scripts/                      # 入口命令与工具
├── tests/
│   └── orchestrator/                 # 行为测试（真值来源）
├── archive/                          # 历史资料（仅供参考）
└── scripts/                          # 工具脚本
```

| 目录 | 用途 |
|------|------|
| `docs/` | 人类可读文档：当前真值、架构、迁移、发布材料 |
| `runtime/` | 实际编排运行时：contract、continuation、dispatch、bridge consumer |
| `tests/` | 行为真值——测试是真值来源，不只是打包卫生 |
| `archive/` | 历史资料保留参考，不是主路径 |

---

## 文档导航

| 目标 | 入口 |
|------|------|
| **首次了解** | [`docs/executive-summary.md`](docs/executive-summary.md) |
| **当前真值（最新）** | [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) |
| **架构详解** | [`docs/architecture/overview.md`](docs/architecture/overview.md) |
| **其他频道接入** | [`docs/quickstart/quickstart-other-channels.md`](docs/quickstart/quickstart-other-channels.md) |
| **Auto-trigger 配置** | [`docs/configuration/auto-trigger-config-guide.md`](docs/configuration/auto-trigger-config-guide.md) |
| **验证状态** | [`docs/validation-status.md`](docs/validation-status.md) |
| **当前计划** | [`docs/plans/overall-plan.md`](docs/plans/overall-plan.md) |
| **技术债务** | [`docs/technical-debt/technical-debt-2026-03-22.md`](docs/technical-debt/technical-debt-2026-03-22.md) |
| **近期报告** | [`docs/reports/`](docs/reports/) |
| **架构评审** | [`docs/review/`](docs/review/) |

### 文档角色说明

- **`docs/CURRENT_TRUTH.md`**：当前迭代状态的单一真值来源（v10，双轨后端策略）
- **`docs/executive-summary.md`**：历史 batch-1 计划；供上下文参考，以 README/CURRENT_TRUTH 为准
- **`docs/plans/overall-plan.md`**：当前真值计划，含 P0/P1/P2 优先级与边界
- **`docs/validation-status.md`**：已验证/未验证边界；为什么选择这个方向
- **`docs/technical-debt/technical-debt-2026-03-22.md`**：已知优化点与 backlog

---

## 测试

**运行全部测试：**

```bash
cd openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/ -v
```

**当前状态：** 468 个测试通过（100% 通过率）

**关键测试文件：**
- `test_execute_mode_and_auto_trigger.py` — Execute mode + auto-trigger 验证（原名 test_v8_execute_mode.py）
- `test_sessions_spawn_api_execution.py` — 真实 sessions_spawn API 集成（原名 test_v9_sessions_spawn_api.py）
- `test_mainline_auto_continue.py` — Trading 主线自动续推验证
- `test_sessions_spawn_bridge.py` — Sessions spawn bridge 验证
- `test_continuation_backends_lifecycle.py` — 通用 lifecycle kernel 测试

---

## 一句话记住它

> **这是一个构建在 OpenClaw 之上的工作流控制层：默认执行走 subagent，兼容保留 tmux，trading 是第一个真实验证场景，外部框架只进叶子层。**

---

## Owner 与维护

**Owner:** Zoe (CTO & Chief Orchestrator)

**最后更新：** 2026-03-24（仓库收敛改造）

**相关仓库：**
- OpenClaw core: `~/.openclaw/`
- Workspace: `~/.openclaw/workspace/`
