# Operations Guide — 编排器操作指南

> 面向使用者的操作入口。回答：入口在哪？状态记在哪？怎么看？怎么恢复？

## 唯一入口

```bash
python3 runtime/orchestrator/cli.py <command>
```

所有操作都通过这个 CLI 入口执行。无论是创建工作流、运行、恢复还是查看状态。

## 两条编排路径

本框架提供两条共存的编排路径，共享同一个执行基板（`SubagentExecutor`）：

| 路径 | 适用场景 | CLI 命令 | 核心模块 |
|------|---------|---------|---------|
| **DAG 工作流** | 批量编排：计划好所有批次 → 一次性自动推进 | `plan` / `run` / `resume` / `show` | `workflow_state` + `batch_executor` + `batch_reviewer` |
| **回调驱动** | 事件驱动：消息 → callback → decision → 下一跳 | `status` / `batch-summary` / `decide` / `list` / `stuck` | `state_machine` + `orchestrator` + `batch_aggregator` |

两者不是"版本替代"关系——DAG 路径适合预规划的批量任务，回调路径适合实时响应的事件流。

## DAG 工作流命令

### 创建工作流

```bash
# 1. 准备批次配置文件 (JSON)
cat > my_workflow.json << 'EOF'
[
  {
    "batch_id": "b0",
    "label": "数据收集",
    "tasks": [
      {"task_id": "t1", "label": "收集 A 股数据"},
      {"task_id": "t2", "label": "收集港股数据"}
    ],
    "depends_on": []
  },
  {
    "batch_id": "b1",
    "label": "分析",
    "tasks": [
      {"task_id": "t3", "label": "趋势分析"}
    ],
    "depends_on": ["b0"]
  }
]
EOF

# 2. 创建工作流（DAG 校验 + 拓扑排序）
python3 runtime/orchestrator/cli.py plan "Trading analysis" my_workflow.json
```

### 运行工作流

```bash
# 优先使用 LangGraph (自动 checkpoint)，无 langgraph 时降级到 WorkflowLoop
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace .
```

### 查看状态

```bash
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
```

输出示例:
```
Workflow: wf_20260325_143012
Status: completed
Batches: 2 (current: 1)

  [ completed] b0: 数据收集 → proceed
      [ completed] t1: 收集 A 股数据 — done
      [ completed] t2: 收集港股数据 — done
→ [ completed] b1: 分析 (deps: b0) → proceed
      [ completed] t3: 趋势分析 — done

Context summary (292 chars):
  Goal: Trading analysis ...
```

### 从中断处恢复

```bash
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json --workspace .
```

## 回调驱动命令

```bash
python3 runtime/orchestrator/cli.py status <task_id>         # 查询任务状态
python3 runtime/orchestrator/cli.py batch-summary <batch_id>  # 查询批次汇总
python3 runtime/orchestrator/cli.py decide <batch_id>         # 对批次做决策
python3 runtime/orchestrator/cli.py list [--state <state>]    # 列出任务
python3 runtime/orchestrator/cli.py stuck [--timeout <min>]   # 检测卡住的批次
```

## 真值唯一 — 状态文件

**唯一真值**: `workflow_state_<id>.json`

```
workflow_state_wf_xxx.json    ← 唯一真值，所有状态都在这里
├── workflow_id, status       ← 全局状态
├── plan.current_batch_index  ← 当前执行到哪个批次
├── batches[]                 ← 每个批次的详细状态
│   ├── tasks[]               ← 每个任务的执行结果
│   └── continuation          ← 批次完成后的决策
└── context_summary           ← LLM 语义恢复
```

回调驱动路径的状态存储在 `~/.openclaw/shared-context/job-status/`（由 `state_machine.py` 管理），通过 `state_sync.py` 桥接到 `workflow_state.json`。

## Runner 脚本契约

`SubagentExecutor` 向子进程注入以下环境变量：

| 变量 | 说明 |
|------|------|
| `OPENCLAW_TASK_ID` | 任务唯一标识 |
| `OPENCLAW_SUBAGENT_STATE_DIR` | 状态文件写入目录 |
| `OPENCLAW_SPAWN_DEPTH` | 递归深度（防 fork 炸弹） |

**Runner 必须做的事**：在退出前写入 `$OPENCLAW_SUBAGENT_STATE_DIR/$OPENCLAW_TASK_ID.json`，包含 `status` 和 `result` 字段。退出码作为 fallback（0 = completed, 非 0 = failed）。

**无 runner 时**：设置 `OPENCLAW_TEST_MODE=1` 可跑测试模式。

## 执行引擎

| 引擎 | 文件 | 何时使用 |
|------|------|---------|
| **LangGraph** (推荐) | `workflow_graph.py` | 安装了 `langgraph` 时自动使用。提供 SQLite checkpoint、条件路由、interrupt/resume |
| **WorkflowLoop** (降级) | `workflow_loop.py` | 无 langgraph 时使用。轮询模式，功能等价 |

两者共享底层模块：`workflow_state.py` + `batch_executor.py` + `batch_reviewer.py`。

## 可插拔执行器

`BatchExecutor` 默认使用 `SubagentTaskExecutor`，也可以注入自定义执行器：

```python
from executor_interface import TaskExecutorBase, TaskResult
from batch_executor import BatchExecutor

class MyExecutor(TaskExecutorBase):
    def execute(self, task_id, label, context):
        return task_id  # 返回 handle

    def poll(self, handle):
        return TaskResult(status="completed", output="done")

executor = BatchExecutor(".", executor=MyExecutor())
```

## 架构关系

```
cli.py (唯一入口)
  │
  ├── DAG 工作流路径:
  │   ├── plan → task_planner.py → workflow_state.json (创建)
  │   ├── run  → workflow_graph.py (LangGraph) 或 workflow_loop.py (降级)
  │   │          ├── batch_executor.py → TaskExecutorBase → SubagentExecutor (执行)
  │   │          ├── batch_reviewer.py (fan-in 评审)
  │   │          └── workflow_state.py (状态读写)
  │   ├── show → workflow_state.py (读取 + 展示)
  │   └── resume → 从 gate/中断处恢复
  │
  └── 回调驱动路径:
      ├── status → state_machine.py (任务状态查询)
      ├── batch-summary → batch_aggregator.py (批次汇总)
      ├── decide → orchestrator.py (规则链决策)
      └── list / stuck → 任务列举 / 卡住检测
```

## 常见场景

### 场景 1: Agent 上下文压缩后恢复

```bash
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
# 看到 context_summary，了解之前做到哪了
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json --workspace .
```

### 场景 2: 遇到 gate 需要人工审批

```bash
# show → 看到 status=gate_blocked
# 人工确认后:
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json --workspace .
```

### 场景 3: 通过 Python API 使用

```python
from task_planner import TaskPlanner
from workflow_loop import WorkflowLoop
from workflow_state import save_workflow_state

planner = TaskPlanner()
state = planner.plan("My workflow", batches_config)
save_workflow_state(state, "state.json")

loop = WorkflowLoop(".", timeout_seconds=900)
result = loop.run("state.json")
print(f"Workflow finished: {result.status}")
```
