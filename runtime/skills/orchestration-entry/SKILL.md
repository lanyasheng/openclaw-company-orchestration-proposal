---
name: orchestration-entry
description: OpenClaw 多任务编排接入指南。当需要将多个 subagent/agent 任务拆成批次并行执行、自动推进下一批、从中断恢复、或接入新业务场景时使用。覆盖 DAG 工作流（plan/run/resume）和回调驱动两条路径。
triggers:
  - 编排.*接入
  - 多任务.*批次
  - workflow.*plan
  - orchestrat
  - 自动.*推进
  - 批次.*执行
  - dag.*任务
---

# OpenClaw Orchestration — 接入指南

## 一句话

用一个 JSON 配置描述你的任务批次和依赖关系，CLI 自动完成 plan → dispatch → monitor → review → advance 全流程。

## 接入方式

### 快速路径（< 5 分钟）

```bash
# 1. 写一个批次配置
cat > my_scenario.json << 'EOF'
[
  {
    "batch_id": "b1",
    "label": "数据收集",
    "tasks": [
      {"task_id": "t1", "label": "收集 A 数据"},
      {"task_id": "t2", "label": "收集 B 数据"}
    ]
  },
  {
    "batch_id": "b2",
    "label": "分析汇总",
    "depends_on": ["b1"],
    "tasks": [
      {"task_id": "t3", "label": "趋势分析"}
    ]
  }
]
EOF

# 2. 创建工作流（DAG 校验 + 拓扑排序）
python3 runtime/orchestrator/cli.py plan "我的场景" my_scenario.json

# 3. 运行（自动选择 LangGraph 或 WorkflowLoop 引擎）
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace .

# 4. 查看状态
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json

# 5. 从中断/gate 恢复
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json --workspace .
```

### 配置参数

每个 batch 支持的字段：

| 字段 | 必须 | 说明 |
|------|------|------|
| `batch_id` | 是 | 批次唯一标识 |
| `label` | 是 | 批次描述 |
| `tasks` | 是 | 任务列表（每项需 `task_id` + `label`） |
| `depends_on` | 否 | 依赖的批次 ID 列表（DAG 依赖） |
| `fan_in_policy` | 否 | `all_success`（默认）/ `any_success` / `majority` |

每个 task 支持的字段：

| 字段 | 必须 | 说明 |
|------|------|------|
| `task_id` | 是 | 任务唯一标识 |
| `label` | 是 | 任务描述（会传给 runner 脚本） |
| `executor` | 否 | 执行器类型（默认 `subagent`） |
| `max_retries` | 否 | 最大重试次数（默认 0） |

### Runner 脚本契约

任务实际由 `scripts/run_subagent_claude_v1.sh` 执行。仓库已提供模板。

**环境变量**（由 SubagentExecutor 注入）：
- `OPENCLAW_TASK_ID` — 任务 ID
- `OPENCLAW_SUBAGENT_STATE_DIR` — 状态文件目录
- `OPENCLAW_SPAWN_DEPTH` — 递归深度

**Runner 必须做的事**：在退出前写入 `$OPENCLAW_SUBAGENT_STATE_DIR/$OPENCLAW_TASK_ID.json`，包含 `status` 和 `result` 字段。

**无 runner 时**：设置 `OPENCLAW_TEST_MODE=1` 可跑测试模式（自动写入 completed 状态）。

### Python API 接入

```python
from task_planner import TaskPlanner
from workflow_loop import WorkflowLoop
from workflow_state import save_workflow_state

planner = TaskPlanner()
state = planner.plan("描述", batches_config)
save_workflow_state(state, "state.json")
loop = WorkflowLoop(".", timeout_seconds=900)
result = loop.run("state.json")
```

### 自定义执行器

实现 `TaskExecutorBase` 接口即可替换默认的 SubagentExecutor：

```python
from executor_interface import TaskExecutorBase, TaskResult
from batch_executor import BatchExecutor

class MyExecutor(TaskExecutorBase):
    def execute(self, task_id, label, context):
        # 启动你的 agent/worker，返回 handle
        return task_id

    def poll(self, handle):
        # 检查是否完成
        return TaskResult(status="completed", output="done")

executor = BatchExecutor(".", executor=MyExecutor())
```

## 全流程自动化链路

```
cli plan → TaskPlanner(DAG 校验)
              ↓
         workflow_state.json（唯一真值）
              ↓
cli run  → WorkflowGraph(LangGraph) / WorkflowLoop(降级)
              ↓
         BatchExecutor.execute_batch → SubagentExecutor → 子进程
              ↓
         子进程写状态文件 → _monitor_process_and_release 检测终端态
              ↓
         BatchExecutor.monitor_batch → 检测所有任务完成
              ↓
         BatchReviewer.review → fan_in_policy 评审
              ↓
         advance → 下一批次 / completed / gate_blocked / failed
              ↓
         自动循环直到所有批次完成
```

## 状态文件（唯一真值）

所有状态记录在 `workflow_state_<id>.json`，包含：
- 工作流全局状态
- 每个批次的状态和续行决策
- 每个任务的执行结果
- `context_summary`（LLM 上下文恢复用）

## 回调驱动命令（v1 兼容）

```bash
python3 runtime/orchestrator/cli.py status <task_id>
python3 runtime/orchestrator/cli.py batch-summary <batch_id>
python3 runtime/orchestrator/cli.py decide <batch_id>
python3 runtime/orchestrator/cli.py list [--state <state>]
python3 runtime/orchestrator/cli.py stuck [--timeout <minutes>]
```

## 详细参考

- Runner 脚本契约和 hook guard → `references/hook-guard-capabilities.md`
- 操作指南 → `docs/OPERATIONS.md`
- 架构全景 → `docs/CURRENT_TRUTH.md`
