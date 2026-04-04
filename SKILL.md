---
name: openclaw-orchestration
description: "OpenClaw 编排控制面。防止 agent 任务静默结束/死循环/卡死。Continuation Contract 强制交接 + Waiting Anomaly 内置检测 + 先验证再自动化。触发词：编排、workflow、任务派发、subagent、批次执行、fan-in。"
metadata: {
  "clawdis": {
    "emoji": "🎯",
    "requires": {
      "bins": ["python3"],
      "env": []
    }
  }
}
---

# openclaw-orchestration

OpenClaw 编排控制面。多 agent 任务的显式交接、fan-in 评审、卡死检测。

## WARNING: 废弃目录

**不要直接看 `orchestration_runtime/` 目录，它已废弃。** 所有代码在 `runtime/orchestrator/`。

## Quick Start

```bash
# 1. 写配置（或用 quickstart.py 自动生成）
python3 quickstart.py "分析这个代码库的安全问题"

# 2. 或手动三步走
python3 runtime/orchestrator/cli.py plan "修复所有 lint 告警" config.json
python3 runtime/orchestrator/cli.py run workflow_state_wf_*.json --workspace .
python3 runtime/orchestrator/cli.py show workflow_state_wf_*.json
```

可选依赖（推荐）：`pip install langgraph langgraph-checkpoint-sqlite`
无依赖时自动降级为轮询引擎，功能不变。

## 核心概念（只有 3 个）

### 1. Task — 注册

一个 JSON 配置定义所有任务和依赖关系。每个任务属于一个批次（batch）。

```json
[
  {
    "batch_id": "scan",
    "label": "安全扫描",
    "tasks": [
      {"task_id": "t1", "label": "依赖检查", "max_retries": 2},
      {"task_id": "t2", "label": "代码审计"}
    ],
    "depends_on": [],
    "fan_in_policy": "all_success"
  },
  {
    "batch_id": "fix",
    "label": "修复问题",
    "tasks": [{"task_id": "t3", "label": "自动修复"}],
    "depends_on": ["scan"]
  }
]
```

关键字段：
- `batch_id`: 批次唯一 ID
- `tasks[].task_id`: 任务唯一 ID
- `tasks[].max_retries`: 失败重试次数（默认 0）
- `depends_on`: 前置批次 ID 列表（Kahn 算法校验无环）
- `fan_in_policy`: `all_success` | `any_success` | `majority`

### 2. Dispatch — 派发执行

CLI `run` 命令按拓扑序执行批次。同一批次内的任务并行派发。

```bash
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace /project
```

执行器默认使用 `SubagentExecutor`（进程管理 + 自动清理）。可通过 `executor_interface.py` 的 `TaskExecutorBase` 接入自定义后端。

状态流转：`pending → running → completed / failed / timeout`

### 3. Contract — 完成交接

每个批次完成后，`BatchReviewer` 根据 fan-in 策略做出 `ContinuationDecision`：

```
{
  "stopped_because": "batch scan completed: 2/2 success",
  "decision": "proceed",        // proceed | gate | stop
  "next_batch": "fix"
}
```

- `proceed`: 自动进入下一批次
- `gate`: 暂停等人工审查，之后 `resume` 继续
- `stop`: 终止工作流

这是防止任务静默结束的核心机制 — 每个批次结束时必须产生显式契约。

## 使用示例

### 示例 1: Review MR

```json
[
  {
    "batch_id": "review",
    "label": "代码审查",
    "tasks": [
      {"task_id": "lint", "label": "Lint 检查"},
      {"task_id": "security", "label": "安全扫描"},
      {"task_id": "logic", "label": "逻辑审查"}
    ],
    "depends_on": [],
    "fan_in_policy": "all_success"
  },
  {
    "batch_id": "report",
    "label": "生成报告",
    "tasks": [{"task_id": "summary", "label": "汇总审查结果"}],
    "depends_on": ["review"]
  }
]
```

### 示例 2: Fix Bug

```json
[
  {
    "batch_id": "diagnose",
    "label": "定位问题",
    "tasks": [{"task_id": "locate", "label": "定位 bug 根因"}],
    "depends_on": []
  },
  {
    "batch_id": "fix",
    "label": "修复",
    "tasks": [{"task_id": "patch", "label": "编写修复补丁"}],
    "depends_on": ["diagnose"]
  },
  {
    "batch_id": "verify",
    "label": "验证",
    "tasks": [{"task_id": "test", "label": "运行测试验证修复"}],
    "depends_on": ["fix"]
  }
]
```

### 示例 3: 批量操作（并行 + fan-in）

```json
[
  {
    "batch_id": "migrate",
    "label": "批量迁移 10 个服务",
    "tasks": [
      {"task_id": "svc1", "label": "服务 A", "max_retries": 1},
      {"task_id": "svc2", "label": "服务 B", "max_retries": 1},
      {"task_id": "svc3", "label": "服务 C", "max_retries": 1}
    ],
    "depends_on": [],
    "fan_in_policy": "majority"
  },
  {
    "batch_id": "validate",
    "label": "集成验证",
    "tasks": [{"task_id": "e2e", "label": "端到端测试"}],
    "depends_on": ["migrate"]
  }
]
```

## CLI 命令速查

```
# ── DAG 工作流 ──
plan   <description> <config.json>          创建工作流（DAG 验证 + 拓扑排序）
run    <state.json> [--workspace <dir>]     执行工作流
resume <state.json> [--workspace <dir>]     从门控/崩溃处恢复
show   <state.json>                         查看工作流状态

# ── 回调驱动 ──
status        <task_id>                     查询单任务状态
batch-summary <batch_id>                    查询批次汇总
decide        <batch_id>                    对批次做决策
list          [--state <state>]             列出任务（可按状态过滤）
stuck         [--timeout <minutes>]         检测卡住的批次（默认 60 分钟）
test                                        运行内置冒烟测试
```

入口文件：`runtime/orchestrator/cli.py`

## 关键文件（给 agent 看的导航）

| 文件 | 用途 |
|------|------|
| `runtime/orchestrator/cli.py` | 唯一 CLI 入口 |
| `runtime/orchestrator/workflow_state.py` | 单 JSON 真值模型（WorkflowState, BatchEntry, TaskEntry） |
| `runtime/orchestrator/task_planner.py` | DAG 验证 + Kahn 拓扑排序 |
| `runtime/orchestrator/batch_executor.py` | 并行派发 + 重试 |
| `runtime/orchestrator/batch_reviewer.py` | Fan-in 策略 + 门控条件 |
| `runtime/orchestrator/workflow_graph.py` | LangGraph 引擎（可选） |
| `runtime/orchestrator/workflow_loop.py` | 零依赖轮询降级引擎 |
| `runtime/orchestrator/subagent_executor.py` | 进程管理 + 清理 |
| `runtime/orchestrator/executor_interface.py` | 可插拔执行器抽象接口 |
| `runtime/orchestrator/watchdog.py` | 停滞检测 + 自动恢复 |
| `runtime/orchestrator/state_machine.py` | 回调驱动的任务状态机 |

**`orchestration_runtime/` 目录已废弃，不要使用。所有代码在 `runtime/orchestrator/`。**

## 工作流状态机

```
工作流: pending → running → completed / failed / gate_blocked
                                              ↓ resume
                                           running

批次:   pending → running → completed / failed

任务:   pending → running → completed / failed / timeout
```

## 接入自定义执行器

继承 `TaskExecutorBase`，实现 `execute(task_id, prompt, label)` 方法：

```python
from runtime.orchestrator.executor_interface import TaskExecutorBase

class MyExecutor(TaskExecutorBase):
    def execute(self, task_id: str, prompt: str, label: str):
        # 你的执行逻辑
        return {"status": "success", "result": "..."}
```
