# OpenClaw 编排控制面

> 面向 OpenClaw 的多 Agent 工作流编排 — 一条主链、一个状态文件、自动批次推进。

[English](README.md)

## 它做什么

一个 Agent 任务完成后，下一步该做什么？这个框架用一个结构化的控制面来回答：

1. **分解** — 将目标拆分为有序的批次，每个批次内的任务并行执行
2. **执行** — 通过 SubagentExecutor 并行派发任务
3. **评审** — 用可配置的 fan-in 策略评估批次结果
4. **推进** — 自动推进到下一批次，或在 gate 处停下等待人工审批

```
TaskPlanner → BatchExecutor → BatchReviewer → advance → 下一批次 → ...
```

## 快速开始

```bash
# 1. 创建工作流
python3 runtime/orchestrator/cli.py plan "交易分析" config.json

# 2. 运行（自动检测 LangGraph，无则降级到轮询循环）
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json

# 3. 查看状态
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json

# 4. 中断或 gate 后恢复
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

### config.json 示例

```json
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
      {"task_id": "t3", "label": "跨市场趋势分析"}
    ],
    "depends_on": ["b0"],
    "fan_in_policy": "all_success"
  }
]
```

## 架构

```
cli.py                          ← 唯一入口
  │
  ├── task_planner.py           ← DAG 验证 + 拓扑排序
  │     └── workflow_state.py   ← 统一状态模型
  │
  ├── workflow_graph.py         ← LangGraph StateGraph（推荐）
  │   (或 workflow_loop.py)     ← 轮询降级（无需 langgraph 依赖）
  │     │
  │     ├── batch_executor.py   ← 并行 SubagentExecutor 派发
  │     │     └── subagent_executor.py
  │     │
  │     └── batch_reviewer.py   ← fan-in 评审 + 安全门控
  │
  └── workflow_state.py         ← 读取 / 保存 / 查询
```

### 唯一真值

所有状态存储在一个文件中：`workflow_state_<id>.json`

```
workflow_state.json
├── workflow_id, status         # 全局状态
├── plan.current_batch_index    # 当前执行到第几批
├── batches[]                   # 每个批次的完整状态
│   ├── tasks[]                 # 每个任务的结果和状态
│   └── continuation            # 评审决策（proceed/gate/stop）
└── context_summary             # LLM 上下文压缩后的语义恢复
```

### 执行引擎

| 引擎 | 文件 | 使用场景 |
|------|------|---------|
| **LangGraph** | `workflow_graph.py` | 安装了 `langgraph` — 自动 checkpoint、条件路由、interrupt/resume |
| **WorkflowLoop** | `workflow_loop.py` | 无 langgraph — 轮询方式，功能等价 |

两者共享相同的底层模块。CLI 自动检测使用哪个。

## 核心概念

### 续行合约 (Continuation Contract)

每个批次完成后产生一个显式决策：

```python
ContinuationDecision(
    stopped_because="所有任务已完成",
    decision="proceed",       # proceed | gate | stop
    next_batch="b1",
    decided_at="2026-03-25T10:05:00Z"
)
```

### Fan-in 策略

| 策略 | 规则 | 适用场景 |
|------|------|---------|
| `all_success` | 所有任务必须完成 | 关键工作流 |
| `any_success` | 至少一个任务成功 | 探索性调研 |
| `majority` | >50% 任务成功 | 投票/共识 |

### 安全门控 (Gate)

如果任何任务结果包含 `NEEDS_REVIEW`，该批次触发 gate — 工作流暂停，等待人工审批后运行 `resume`。

### DAG 依赖

批次可以声明依赖关系。Planner 通过 Kahn 算法验证 DAG（环检测）并按拓扑序排列批次。

### 上下文恢复

`context_summary` 在每次状态变更后自动生成。当 LLM Agent 的上下文窗口压缩时，可以读取这个字段来了解工作流当前进度，无需重放完整历史。

## Python API

```python
from task_planner import TaskPlanner
from workflow_graph import run_workflow
from workflow_state import save_workflow_state, load_workflow_state

# 规划
planner = TaskPlanner()
state = planner.plan("我的工作流", batches_config)
save_workflow_state(state, "state.json")

# 运行
result = run_workflow(state, "state.json", workspace_dir=".")

# 恢复
from workflow_graph import resume_workflow
result = resume_workflow("state.json")
```

## 测试

```bash
pip install pytest langgraph

# 运行所有测试
PYTHONPATH=runtime/orchestrator:runtime/scripts pytest tests/orchestrator/ -q

# 仅 v2 测试
PYTHONPATH=runtime/orchestrator:runtime/scripts pytest tests/orchestrator/test_workflow_v2.py -v
```

**781 个测试全部通过** — 34 个 v2 测试（状态、规划、评审、LangGraph 图）+ 747 个 v1 测试。

## 项目结构

```
runtime/orchestrator/
├── cli.py                  # CLI 入口
├── workflow_state.py       # 统一状态模型
├── workflow_graph.py       # LangGraph 引擎
├── workflow_loop.py        # 轮询引擎（降级）
├── task_planner.py         # DAG 规划
├── batch_executor.py       # 并行派发
├── batch_reviewer.py       # Fan-in + 门控
├── subagent_executor.py    # SubagentExecutor 封装
└── ...                     # v1 模块（保留兼容）

tests/orchestrator/
├── test_workflow_v2.py     # v2 测试套件
└── ...                     # v1 测试

docs/
├── CURRENT_TRUTH.md        # 当前系统状态
├── OPERATIONS.md           # 操作指南
└── ...                     # 设计文档
```

## 为什么做这个

大多数多 Agent 框架（LangGraph、CrewAI、AutoGen）关注 Agent 间通信或图执行。但它们不回答：

- **谁拥有任务？** — Owner/Executor 解耦，把业务判断和执行分开
- **完成后做什么？** — 续行合约让每次转移都显式化
- **上下文压缩后怎么恢复？** — `context_summary` 提供语义恢复
- **怎么安全地自动推进？** — Gate 条件 + fan-in 策略，而不只是"跑下一个节点"

这个框架是一个**控制面**，坐在执行层之上。它可以用 LangGraph 作为执行引擎，同时添加 LangGraph 原生不提供的编排语义。

## License

MIT
