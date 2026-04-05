# OpenClaw 系统架构全览

> 面向人类工程师和 Muse (大龙虾) 的完整架构文档。
> 最后更新: 2026-04-05

---

## 系统架构图

```
用户（钉钉 / 终端）
  |
  v
OpenClaw Gateway (~/.openclaw/)
  |
  +-- Muse（大龙虾）<-- AGENTS.md + TOOLS.md
  |     |
  |     +-- 多任务 --> @orchestrator-planner skill --> config.json --> orchestrator-cli
  |     +-- 单任务 --> dispatch.sh
  |
  +-- Cron 调度器
  |     +-- patrol (10:30 / 14:00 / 19:00) --> 巡检发现 MR / Bug
  |     +-- daily-reflection (23:30) --> 经验沉淀
  |
  +-- TMCP 钉钉桥 (maxCycles=0 无限重连)

编排层 (~/.openclaw/orchestrator/)
  orchestrator-cli:  plan --> run --> show --> resume
  WorkflowLoop (确定性 Python 循环)
    +-- BatchExecutor
    |     +-- SubagentExecutor --> dispatch.sh --> tmux + claude
    |     +-- monitor + timeout 2h + retry 3x + cleanup
    +-- BatchReviewer (fan-in: all_success / majority / any_success)
    +-- 自动推进 --> next batch --> repeat (24h max)

dispatch 层 (~/.openclaw/skills/nanocompose-dispatch/)
  dispatch.sh        --> 创建 tmux session + CC (headless / interactive)
  send.sh            --> 控制实例 (消息 / interrupt / kill / compact)
  status.sh --all    --> 查看所有实例状态
  session-monitor.sh --> 30s capture-pane --> progress JSON
  on-stop.sh         --> CC 完成一轮 --> phase=idle-waiting-input
  on-session-end.sh  --> CC 退出 --> 钉钉通知

系统 crontab (*/5)
  orchestrator-watchdog --> stuck 检测 + 恢复 + 数据清理
```

---

## 层次职责

| 层 | 位置 | 职责 |
|----|------|------|
| Gateway | `~/.openclaw/` | Muse 主会话、钉钉桥、Cron 调度 |
| 编排层 | `~/.openclaw/orchestrator/` | DAG 工作流管理、批次执行、fan-in 决策、崩溃恢复 |
| Dispatch 层 | `~/.openclaw/skills/nanocompose-dispatch/` | tmux session 生命周期、CC 实例创建/控制/监控 |
| 执行层 | tmux session 内的 Claude Code | 实际完成代码审查、bug 修复、功能开发等工作 |

---

## 任务执行流程（端到端）

以下描述从"用户说话"到"任务完成汇报"的完整链路。

### 1. 入口：用户发出请求

用户通过钉钉群或终端向 Muse 说："帮我做 X"。

### 2. Muse 路由判断

Muse 根据任务复杂度决定走哪条路径：

- **单任务**（一次 MR review、一个 bug 修复）--> 直接调用 `dispatch.sh`
- **多任务/复杂任务**（跨文件重构、批量审查、多阶段开发）--> 调用 `@orchestrator-planner` skill

### 3a. 单任务路径

```
Muse
  --> dispatch.sh --type review --id 12345 --prompt "..."
      --> 创建 tmux session: nc-review-12345
      --> 在 session 内启动 claude (headless 或 interactive)
      --> session-monitor 每 30s 写 progress JSON
      --> CC 完成 --> on-stop.sh 写 phase=idle-waiting-input
      --> CC 退出 --> on-session-end.sh
          --> 写结果 JSON 到 results/
          --> notify-callback.sh 回报 Muse
          --> 发 macOS 通知 + 钉钉通知
```

### 3b. 多任务路径

```
Muse
  --> @orchestrator-planner skill
      --> 分析任务，自动生成 config.json (batch 定义 + DAG 依赖)
      --> orchestrator-cli plan "描述" config.json
          --> task_planner.py: DAG 验证 + Kahn 拓扑排序
          --> 创建 workflow_state_wf_*.json (唯一真值)
      --> orchestrator-cli run workflow_state_wf_*.json --workspace <项目目录>
          --> WorkflowLoop / LangGraph 开始执行
              --> 取出当前 batch (无未完成依赖的)
              --> BatchExecutor 并行启动 batch 内所有 task
                  --> 每个 task: SubagentExecutor --> dispatch.sh --> tmux + claude
              --> 等待 batch 内所有 task 完成 (poll progress JSON)
                  --> 2h 单 task 超时，自动重试 (最多 3 次)
              --> BatchReviewer fan-in 评审
                  --> all_success: 全部成功才通过
                  --> majority: 多数成功即通过
                  --> any_success: 任一成功即通过
              --> 评审通过 --> 推进到下一个 batch
              --> 循环直到所有 batch 完成 (24h 全局超时)
          --> 完成后回报 Muse
```

### 4. 结果收集与汇报

```
任务完成
  --> 结果 JSON 写入 ~/.openclaw/shared-context/results/nc-{type}-{id}.json
  --> openclaw agent --deliver 回报 Muse 主会话
  --> Muse 汇总结果，回复用户
```

---

## 新任务的自动接入流程

当 Muse 收到一个复杂任务时，完整的自动接入流程如下：

1. **Muse 识别复杂度** -- 判定需要编排层介入
2. **调用 @orchestrator-planner skill** -- Muse 把用户需求传给 planner
3. **Planner 自动分解任务** -- 根据需求生成 config.json，定义 batch 和 DAG 依赖
4. **orchestrator-cli plan** -- 校验 DAG 合法性，创建 workflow_state JSON
5. **orchestrator-cli run** -- 后台启动 WorkflowLoop，按拓扑顺序执行
6. **自动推进** -- batch 间串行、batch 内并行，自动 fan-in 决策
7. **结果汇报** -- 全部 batch 完成后通知 Muse，Muse 汇总回复用户

用户不需要手动写 config.json，不需要知道编排层细节。说一句"帮我做 X"，整个链条自动运转。

---

## 编排层两条路径

编排层内部有两条共存路径，共享同一个执行基板 (`SubagentExecutor`)：

| 路径 | 适用场景 | CLI 命令 | 核心模块 |
|------|---------|---------|---------|
| DAG 工作流 | 预规划批量任务，一次性自动推进 | `plan` / `run` / `resume` / `show` | `workflow_state` + `batch_executor` + `batch_reviewer` |
| 回调驱动 | 事件驱动，消息触发决策 | `status` / `batch-summary` / `decide` / `list` / `stuck` | `state_machine` + `orchestrator` + `batch_aggregator` |

DAG 路径适合 Muse 主动发起的批量任务。回调路径适合外部事件（钉钉消息、Cron 巡检结果）驱动的实时响应。

---

## 执行引擎

| 引擎 | 文件 | 使用条件 |
|------|------|---------|
| LangGraph (推荐) | `workflow_graph.py` | 安装了 `langgraph` 时自动使用，提供 SQLite checkpoint + 条件路由 |
| WorkflowLoop (降级) | `workflow_loop.py` | 无 langgraph 时使用，轮询模式，功能等价 |

---

## 数据生命周期

### 目录结构

```
~/.openclaw/shared-context/
  +-- progress/          # session-monitor 每 30s 写入的实时 JSON
  +-- results/           # 任务结果 JSON
  +-- job-status/        # 回调路径状态 (state_machine.py)

~/.openclaw/orchestrator/
  +-- workflow_state_wf_*.json   # DAG 工作流唯一真值

~/.openclaw/logs/
  +-- dispatch.log               # dispatch 操作日志
  +-- session-monitor.log        # monitor 日志
  +-- workflow-run.log           # 编排层运行日志
```

### 清理策略

| 数据 | 保留周期 | 清理方式 |
|------|---------|---------|
| `progress/*.json` | 实时覆写，session 结束后清理 | session-monitor 自动管理 |
| `results/*.json` | 7 天 | crontab watchdog 自动清理 |
| `workflow_state_*.json` | 30 天 | 手动归档或 watchdog 清理 |
| `logs/` | 按文件大小轮转 | 标准 logrotate |
| tmux session | 任务完成后自动销毁 | on-session-end.sh 清理 |

### 状态真值

- **DAG 工作流**: `workflow_state_wf_*.json` 是唯一真值。所有 batch 状态、task 结果、continuation 决策都记录在这个文件中。
- **回调路径**: `~/.openclaw/shared-context/job-status/` 是真值源，通过 `state_sync.py` 桥接到 workflow_state。
- **实例实时状态**: `progress/*.json` 由 session-monitor 每 30s 采集，包含 status (active/idle/waiting/stuck/exited)、当前工具、最后输出行。

---

## 监控与可观测

### session-monitor

`session-monitor.sh` 是 Claude 实例的实时监控进程，每 30 秒扫描所有 tmux session：

- 用 `tmux capture-pane` 获取当前输出
- 解析状态：active (正在执行工具)、idle (等待输入)、waiting (等待确认)、stuck、exited
- 检测正在使用的工具 (Read/Edit/Bash/Write/Grep/Glob 等)
- 写 JSON 到 `~/.openclaw/shared-context/progress/<session>.json`

```bash
# 启动 monitor
session-monitor.sh start [--interval 30]

# 停止 monitor
session-monitor.sh stop

# 查看 monitor 状态
session-monitor.sh status
```

### 状态查询

```bash
# 所有 Claude 实例 (含手动启动的)
status.sh --all

# 只看 dispatch 派发的 nc-* 任务
status.sh

# 实时进度 JSON
cat ~/.openclaw/shared-context/progress/*.json | python3 -c "
import json,sys
for line in sys.stdin:
  try:
    d=json.loads(line.strip())
    print(f\"  {d['session']:25s} {d['status']:10s} {d['phase']:10s} tool={d.get('last_tool','-')} | {d.get('last_line','-')[:60]}\")
  except: pass
"
```

### 系统 crontab

每 5 分钟运行 orchestrator-watchdog，职责：
- 检测 stuck 的 workflow（超时未推进）
- 自动恢复可恢复的 workflow
- 清理过期数据 (results 7 天、workflow_state 30 天)

---

## 容错机制

| 场景 | 处理方式 |
|------|---------|
| 单 task 执行超时 | 2h 硬超时，自动 kill + 重试 |
| 单 task 失败 | 自动重试，最多 3 次 |
| CC 进程崩溃 | on-session-end.sh 捕获，标记 failed，编排层决定是否重试 |
| 编排层崩溃 | `orchestrator-cli resume` 从 workflow_state JSON 恢复 |
| tmux session 丢失 | watchdog 检测 stuck，触发恢复 |
| 全局超时 | 24h 硬超时，整个 workflow 标记 timeout |
| fan-in 部分失败 | 根据策略 (all_success/majority/any_success) 决定是否推进 |

---

## 项目接入清单

接入编排层只需一步：在项目的 `.claude/settings.json` 中添加 hooks。

```json
{
  "hooks": {
    "Stop": [{
      "type": "command",
      "command": "bash ~/.openclaw/skills/nanocompose-dispatch/scripts/on-stop.sh",
      "timeout": 10000
    }],
    "SessionEnd": [{
      "type": "command",
      "command": "bash ~/.openclaw/skills/nanocompose-dispatch/scripts/on-session-end.sh",
      "timeout": 10000
    }]
  }
}
```

**Stop hook**: CC 完成一轮回答时触发，写 `phase=idle-waiting-input` 到 progress 文件，编排层据此判定该轮完成。

**SessionEnd hook**: CC 退出时触发，保存最终输出，通知编排层，写 continuation contract。

**环境变量**: hooks 依赖 `NC_SESSION`（tmux session 名）和 `NC_PROJECT_DIR`（项目路径），由 `dispatch.sh` 自动注入。手动启动时需自行 export。

完成 hooks 配置后，Muse 就可以通过 dispatch.sh 或 orchestrator-cli 向该项目派发任务了。

---

## 关键路径上的文件索引

| 文件 | 位置 | 作用 |
|------|------|------|
| `cli.py` | `orchestrator/runtime/orchestrator/` | 编排层唯一入口 |
| `workflow_loop.py` | 同上 | WorkflowLoop 确定性循环 |
| `workflow_graph.py` | 同上 | LangGraph 引擎 |
| `batch_executor.py` | 同上 | 批次执行器 |
| `batch_reviewer.py` | 同上 | fan-in 评审 |
| `workflow_state.py` | 同上 | 状态读写 |
| `dispatch.sh` | `skills/nanocompose-dispatch/scripts/` | tmux + CC 创建 |
| `send.sh` | 同上 | 实例控制 |
| `status.sh` | 同上 | 状态查询 |
| `session-monitor.sh` | 同上 | 实时监控 |
| `on-stop.sh` | 同上 | Stop hook |
| `on-session-end.sh` | 同上 | SessionEnd hook |
