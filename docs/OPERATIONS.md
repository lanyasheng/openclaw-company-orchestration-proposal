# Operations Guide — 编排器操作指南

> 面向使用者的操作入口。回答：入口在哪？状态记在哪？怎么看？怎么恢复？

## 唯一入口

```bash
python3 runtime/orchestrator/cli.py <command>
```

所有操作都通过这个 CLI 入口执行。无论是创建工作流、运行、恢复还是查看状态。

## 核心命令

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

# 2. 创建工作流
python3 runtime/orchestrator/cli.py plan "Trading analysis" my_workflow.json
# 输出: workflow_state_wf_20260325_143012.json
```

### 运行工作流

```bash
# 优先使用 LangGraph (自动 checkpoint)，无 langgraph 时降级到 WorkflowLoop
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json

# 指定工作目录
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace /path/to/workspace
```

### 查看状态

```bash
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
```

输出示例:
```
Workflow: wf_20260325_143012
Status: running
Batches: 2 (current: 1)

→ [ completed] b0: 数据收集 → proceed
      [ completed] t1: 收集 A 股数据 — done
      [ completed] t2: 收集港股数据 — done
  [   pending] b1: 分析 (deps: b0)
      [   pending] t3: 趋势分析
```

### 从中断处恢复

```bash
# 上下文压缩 / gate 阻断后恢复
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

## 真值唯一 — 状态文件

### 全局状态

**唯一真值**: `workflow_state_<id>.json`

这个文件包含：
- 工作流元信息 (ID, 状态, 创建时间)
- 所有批次的状态 (pending / running / completed / failed)
- 每个任务的状态和结果
- 每个批次的续行决策 (proceed / stop / gate)
- `context_summary` — LLM 上下文恢复用的语义摘要

```
workflow_state_wf_xxx.json    ← 唯一真值，所有状态都在这里
├── workflow_id, status       ← 全局状态
├── plan.current_batch_index  ← 当前执行到哪个批次
├── batches[]                 ← 每个批次的详细状态
│   ├── tasks[]               ← 每个任务的执行结果
│   └── continuation          ← 批次完成后的决策
└── context_summary           ← LLM 语义恢复
```

### v1 兼容状态

v1 的任务状态仍存储在 `~/.openclaw/shared-context/job-status/`（由 `state_machine.py` 管理）。v2 不依赖这个目录。

## 执行引擎

| 引擎 | 文件 | 何时使用 |
|------|------|---------|
| **LangGraph** (推荐) | `workflow_graph.py` | 安装了 `langgraph` 时自动使用。提供 checkpoint、条件路由、interrupt/resume |
| **WorkflowLoop** (降级) | `workflow_loop.py` | 无 langgraph 时使用。轮询模式，功能等价 |

两者共享底层模块：`workflow_state.py` + `batch_executor.py` + `batch_reviewer.py`。

## 架构关系

```
cli.py (唯一入口)
  ├── plan → task_planner.py → workflow_state.py (创建)
  ├── run  → workflow_graph.py 或 workflow_loop.py
  │          ├── batch_executor.py → subagent_executor.py (执行)
  │          ├── batch_reviewer.py (评审)
  │          └── workflow_state.py (读写状态)
  ├── show → workflow_state.py (读取)
  └── resume → workflow_graph.py 或 workflow_loop.py (恢复)
```

### v1 文件说明 (仍保留，但不在主链路中)

| 文件 | 角色 | v2 中的对应 |
|------|------|-----------|
| `orchestrator.py` | v1 回调处理 | `batch_reviewer.py` |
| `auto_dispatch.py` | v1 自动派发 | `batch_executor.py` |
| `auto_continue_trigger.py` | v1 续行触发 | `workflow_graph.py` (advance 节点) |
| `sessions_spawn_request.py` | v1 会话创建 | `batch_executor.py` (dispatch 节点) |
| `state_machine.py` | v1 任务状态 | `workflow_state.py` |

## 常见场景

### 场景 1: Agent 上下文压缩后恢复

```bash
# 查看当前状态
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
# 看到 context_summary，了解之前做到哪了

# 继续执行
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

### 场景 2: 遇到 gate 需要人工审批

```
show → 看到 status=gate_blocked
# 人工确认后
resume → 从 gate 处继续
```

### 场景 3: 通过 Python API 使用

```python
from task_planner import TaskPlanner
from workflow_graph import run_workflow
from workflow_state import save_workflow_state, load_workflow_state

planner = TaskPlanner()
state = planner.plan("My workflow", batches_config)
save_workflow_state(state, "state.json")
result = run_workflow(state, "state.json", workspace_dir=".")
```
