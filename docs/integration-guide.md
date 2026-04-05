# OpenClaw 编排层 — 项目接入指南

> 让 orchestrator-cli 管理任意项目的任务执行。面向开发者和 AI agent。
> v1.0 | 2026-04-04

## 术语

| 术语 | 含义 |
|------|------|
| orchestrator-cli | 编排器唯一入口 (`runtime/orchestrator/cli.py`) |
| batch | 一组并行执行的任务 |
| DAG | batch 间的有向无环依赖图 |
| fan-in | batch 内所有任务完成后汇总评审，决定是否推进 |
| workflow_state | `workflow_state_wf_*.json`，工作流唯一真值 |
| progress 文件 | `~/.openclaw/shared-context/progress/<session>.json`，阶段信号 |

## 前置条件

```bash
tmux -V                          # tmux 可用
claude --version                 # Claude Code CLI 可用
jq --version                     # hooks 依赖
ls ~/.openclaw/shared-context/   # OpenClaw gateway 目录存在
ls /tmp/oc-orch/runtime/orchestrator/cli.py  # 编排层代码可达
```

## Step 1: 项目 Hooks 配置（一次性）

在项目 `.claude/settings.json` 中添加：

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

**Stop hook**: CC 完成一轮回答时触发。写 `phase=idle-waiting-input` 到 progress 文件，编排层 poll 机制据此判定该轮完成。仅处理 `nc-*` 前缀的 session。

**SessionEnd hook**: CC 进程退出时触发。用 `tmux capture-pane` 保存最终输出；检测退出原因；调用 `notify-callback.sh` 通知编排层；写 continuation contract 到 task-registry。

**环境变量**: hooks 依赖 `NC_SESSION`（tmux session 名）和 `NC_PROJECT_DIR`（项目路径），由 `dispatch.sh` 自动注入。手动启动时需自行 export。

## Step 2: 创建任务配置

config.json 是一个 JSON 数组，每个元素定义一个 batch：

```json
[
  {
    "batch_id": "b0",
    "label": "批次描述",
    "depends_on": [],
    "tasks": [
      {"task_id": "t1", "label": "任务描述", "prompt": "CC 执行的具体指令"}
    ]
  }
]
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `batch_id` | 是 | 全局唯一标识 |
| `label` | 是 | 人类可读描述 |
| `depends_on` | 是 | 依赖的 batch_id 数组，`[]` = 无依赖 |
| `tasks[].task_id` | 是 | 任务唯一标识 |
| `tasks[].label` | 是 | 任务描述 |
| `tasks[].prompt` | 否 | CC prompt，缺省用 label |

DAG 规则: `depends_on` 列出的 batch 全部完成后当前 batch 才启动。Kahn 算法拓扑排序，自动检测环。

fan-in 决策: `proceed`(全部成功，推进) / `gate_blocked`(需人工审批) / `retry`(部分失败重试) / `abort`(终止)。

### 示例: 多 batch 代码重构

```json
[
  {
    "batch_id": "analysis",
    "label": "代码分析",
    "depends_on": [],
    "tasks": [
      {"task_id": "scan_deps", "label": "扫描依赖关系",
       "prompt": "分析 src/ 下所有模块的依赖关系，输出到 /tmp/deps.md"},
      {"task_id": "find_dead", "label": "查找死代码",
       "prompt": "静态分析找出未引用的函数和类，列出到 /tmp/dead-code.md"}
    ]
  },
  {
    "batch_id": "refactor",
    "label": "执行重构",
    "depends_on": ["analysis"],
    "tasks": [
      {"task_id": "extract_if", "label": "提取接口",
       "prompt": "根据 /tmp/deps.md，将耦合度高的模块提取公共接口"},
      {"task_id": "rm_dead", "label": "删除死代码",
       "prompt": "根据 /tmp/dead-code.md，安全删除无引用代码"}
    ]
  },
  {
    "batch_id": "verify",
    "label": "验证",
    "depends_on": ["refactor"],
    "tasks": [
      {"task_id": "run_tests", "label": "运行测试",
       "prompt": "运行全量测试，确保重构未破坏功能"}
    ]
  }
]
```

依赖图: `analysis`(2并行) --> `refactor`(2并行) --> `verify`(1)

## Step 3: 运行

```bash
OC=/tmp/oc-orch
PY="PYTHONPATH=$OC/runtime/orchestrator python3 $OC/runtime/orchestrator/cli.py"

# Plan — 创建工作流
eval $PY plan "代码重构" /path/to/config.json

# Run — 执行（后台）
eval nohup $PY run workflow_state_wf_XXXXXXXX.json \
  --workspace /path/to/your/project \
  --backend tmux \
  '>' ~/.openclaw/logs/workflow.log 2'>&'1 '&'

# Show — 查看状态
eval $PY show workflow_state_wf_XXXXXXXX.json

# Resume — 崩溃后恢复（跳过已完成 batch）
eval $PY resume workflow_state_wf_XXXXXXXX.json \
  --workspace /path/to/your/project
```

`--backend` 选项: `tmux`(长任务/需监控) / `subagent`(短任务) / `auto`(默认，优先 tmux)。
环境变量 `OPENCLAW_DEFAULT_BACKEND` 可覆盖默认值。

## Step 4: 监控

**watchdog.sh** — tmux 状态守护:
```bash
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/session-monitor.sh start  # 启动(30s轮询)
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/session-monitor.sh once   # 单次扫描
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/session-monitor.sh stop   # 停止
```
功能: 检测 stuck(>30min) -> 告警 | context<20% -> compact | exited -> 清理

**status.sh** — 实例概览:
```bash
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/status.sh       # 编排任务
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/status.sh --all # 所有 claude 实例
```

**send.sh** — 控制实例:
```bash
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/send.sh <session> interrupt
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/send.sh <session> kill
bash ~/.openclaw/skills/nanocompose-dispatch/scripts/send.sh <session> compact
```

**crontab stuck 检测** (推荐):
```bash
*/5 * * * * cd /tmp/oc-orch && PYTHONPATH=runtime/orchestrator python3 runtime/orchestrator/cli.py stuck --timeout 60 >> ~/.openclaw/logs/stuck-check.log 2>&1
```

## 常见问题

**Q1: CC 完成了但编排层没检测到**
检查: `cat ~/.openclaw/shared-context/progress/nc-<session>.json` 是否有 `idle-waiting-input`。根因通常是 `.claude/settings.json` 未配置 Stop hook 或 `NC_SESSION` 未注入。

**Q2: 幽灵任务告警**
清理旧文件: `rm ~/.openclaw/shared-context/progress/nc-<old>*.json` 和 `~/.openclaw/shared-context/job-status/` 下过期记录。

**Q3: tmux session 不消失**
CC 在等用户输入（prompt 不够明确 / 触发 permission 确认）。用 `tmux attach -t nc-<session>` 查看，或 `send.sh <session> interrupt` 中断。预防: prompt 写明确，避免交互。

**Q4: 工作流中途失败**
`show` 查看失败的 batch/task -> 修复问题 -> `resume` 恢复。已完成的 batch 不会重跑。

## 自定义项目注意事项

**项目路径**: `dispatch.sh --project-dir /path/to/your/project` 指定（默认 NanoCompose）。

**CC 自动加载**: 在你的项目目录启动时，CC 加载 `.claude/settings.json`、`.claude/skills/`、`.claude/agents/`、`.claude/rules/`、`CLAUDE.md`。确保 `CLAUDE.md` 写好项目上下文。

**自定义执行器**: 实现 `TaskExecutorBase` 的 `execute()`(启动) 和 `poll()`(轮询) 方法，注入 `BatchExecutor`:
```python
from executor_interface import TaskExecutorBase, TaskResult
from batch_executor import BatchExecutor

class MyExecutor(TaskExecutorBase):
    def execute(self, task_id, label, context): return "handle"
    def poll(self, handle): return TaskResult(status="completed", output="done")

executor = BatchExecutor("/workspace", executor=MyExecutor())
```

## 接入 Checklist

```
[ ] 前置条件满足（tmux, claude CLI, jq, shared-context）
[ ] .claude/settings.json 配置 Stop + SessionEnd hooks
[ ] CLAUDE.md 写好项目上下文
[ ] config.json 定义 batch DAG + tasks
[ ] plan 生成 workflow_state
[ ] run 启动执行
[ ] show 确认运行中
[ ] crontab + watchdog 配置（推荐）
```
