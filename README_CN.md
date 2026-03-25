# OpenClaw 公司级编排 — 多 Agent 工作流控制面

> **单一 CLI**、**单一 JSON 状态文件**、**按批并行**、**扇入评审**、**自动推进或可暂停门禁**。有 LangGraph 走图引擎；没有则降级为轮询主循环。

[English README](README.md) · [操作指南](docs/OPERATIONS.md) · [当前真值](docs/CURRENT_TRUTH.md)

---

## 这套东西解决什么问题

面向 OpenClaw 体系的多 Agent 编排 **控制面**（不是再造一个通用 Agent 框架）：

1. **规划** — 校验批次 DAG（`depends_on`）、拓扑排序、落盘 `workflow_state_*.json`。
2. **执行** — 每个批次内并行下发任务，经 `SubagentExecutor` 起子进程 / 跑 runner。
3. **评审** — 按 `fan_in_policy`（全成功 / 任一成功 / 过半）聚合，并可触发 **门禁**。
4. **推进** — `proceed` 进下一批、`gate` 等人、`stop` 判失败。

OpenClaw 继续握 **策略、频道、sessions_spawn 语义**；本运行时负责 **批次 DAG、持久化、续跑语义** 这一层。

---

## 上手命令

```bash
python3 runtime/orchestrator/cli.py plan "目标描述" config.json
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace /你的/workspace
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

- **`run`**：能 `import langgraph` 时走 **`workflow_graph.py`（LangGraph）**；否则走 **`workflow_loop.py`（轮询）**。状态文件与语义一致。

---

## 1. 架构总览

```mermaid
graph TD
  subgraph Entry["CLI"]
    CLI[cli.py]
  end
  subgraph Plan["创建"]
    TP[TaskPlanner]
    WS[workflow_state.py]
  end
  subgraph Engines["运行 / 恢复"]
    LG[workflow_graph<br/>LangGraph]
    WL[workflow_loop<br/>轮询降级]
  end
  subgraph Runtime["批次内运行时"]
    BE[BatchExecutor]
    SE[SubagentExecutor]
    BR[BatchReviewer]
  end
  subgraph Truth["持久化"]
    JSON[(workflow_state.json)]
  end

  CLI -->|plan| TP
  TP --> WS
  WS --> JSON
  CLI -->|run / resume| LG
  CLI -->|无 LangGraph 依赖| WL
  LG --> BE
  LG --> BR
  WL --> BE
  WL --> BR
  BE --> SE
  LG --> WS
  WL --> WS
  WS --> JSON
```

---

## 2. 工作流生命周期

```mermaid
flowchart TD
  subgraph Boot["启动"]
    A[编写批次配置] --> B[TaskPlanner：DAG 校验 + 拓扑序]
    B --> C[写入 workflow_state.json]
  end
  subgraph Loop["批次循环"]
    D[check_batch]
    E[dispatch 下发]
    F[monitor 等终态]
    G[review 扇入 + 门禁]
    H[advance 决策]
    D --> E --> F --> G --> H
  end
  subgraph Out["结果分支"]
    H -->|proceed| D
    H -->|gate| I[gate_blocked 暂停]
    H -->|stop| J[failed]
    H -->|无下一批| K[completed]
  end
  C --> D
```

---

## 3. 工作流级状态机

对应 `workflow_state.py` 中的 `WorkflowState.status`：

```mermaid
stateDiagram-v2
  [*] --> pending
  pending --> running
  running --> completed
  running --> failed
  running --> gate_blocked
  gate_blocked --> running: resume
  completed --> [*]
  failed --> [*]
```

---

## 4. `workflow_state.json` 数据流

```mermaid
graph LR
  subgraph Root["WorkflowState"]
    WID[workflow_id]
    ST[status]
    PLN[plan]
    BAT[batches]
    SUM[context_summary]
    ART[artifact_chain]
  end
  subgraph Batch["BatchEntry"]
    BID[batch_id]
    DEP[depends_on]
    FAN[fan_in_policy]
    TSK[tasks]
    CON[continuation]
  end
  subgraph Task["TaskEntry"]
    TID[task_id]
    LBL[label]
    EXE[executor]
    TST[status]
    RS[result_summary]
  end
  BAT --> Batch
  TSK --> Task
```

`plan` 含 `total_batches`、`current_batch_index`、`description`。`continuation` 为 `ContinuationDecision`：`proceed` / `gate` / `stop`、`stopped_because`、`next_batch`、`decided_at`。

---

## 5. 典型两批次执行（时序）

```mermaid
sequenceDiagram
  participant CLI as cli.py
  participant PL as TaskPlanner
  participant G as LangGraph / 循环
  participant BE as BatchExecutor
  participant SE as SubagentExecutor
  participant BR as BatchReviewer
  participant F as workflow_state.json

  CLI->>PL: plan(description, config)
  PL->>F: 原子写入

  CLI->>G: run(state_path)
  loop 批次一
    G->>G: check_batch
    G->>BE: execute_batch
    BE->>SE: 各任务 execute_async
    G->>BE: monitor_batch
    BE->>SE: get_result
    G->>BR: review
    BR-->>G: proceed
    G->>F: 保存 + context_summary
  end
  loop 批次二
    G->>BE: execute_batch
    G->>BE: monitor_batch
    G->>BR: review
    BR-->>G: proceed / gate / stop
    G->>F: 保存
  end
```

---

## 6. 与其他框架怎么比

| 框架 | 主战场 | 本仓库相对它的位置 |
|------|--------|-------------------|
| **LangGraph** | 通用有状态图、checkpoint、中断恢复 | **内嵌为引擎 A**；批次语义、扇入、门禁、**JSON 真值**由本层定义 |
| **CrewAI** | 角色化班组、高层编排模式 | **文件型控制面** + 子进程执行；不提供 Crew/角色 DSL |
| **AutoGen / AG2** | 对话式多 Agent 协议 | **批次 DAG + 策略** 驱动 **spawn**，不以消息拓扑为中心 |
| **Temporal** | 持久工作流、多 Worker、规模化重试 | **单机编排器 + JSON 断点**；不依赖 Temporal 集群 |
| **Dify** | 低代码应用、RAG、对话流 | **代码优先**、对接 OpenClaw；不是可视化应用工厂 |

一句话：**我们是薄而硬的控制面**（批次、扇入、门禁、一份状态），LangGraph 是 **可选的图执行后端**，没有时也能跑。

---

## 7. 新业务接入清单

1. **写 `config.json`** — 批次数组：每批 `batch_id`、`label`、`tasks`（`task_id`、`label`，可选 `executor`，默认 `subagent`）、`depends_on`（指向已有 `batch_id`，环会被拒绝）。
2. **配 `fan_in_policy`** — `all_success`（默认）、`any_success`、`majority`。
3. **自定义门禁（可选）** — 扩展 `BatchReviewer._check_gate_conditions`；默认逻辑：任意任务 `result_summary` 含 `NEEDS_REVIEW` 即 `gate`。
4. **提供 runner** — `SubagentExecutor` 在 `--workspace` 下查找 `scripts/run_subagent_claude_v1.sh`（参数：任务描述、label）。不存在时走 **模拟** 子进程，便于测试。

流程：`plan` 生成状态文件 → `run` 时把 `--workspace` 指到含 `scripts/` 的工程根。

---

## 8. 待完善能力（对照业界）

| 维度 | 现状 | 相对 LangGraph / CrewAI / Temporal 的常见缺口 |
|------|------|-----------------------------------------------|
| **Checkpoint** | LangGraph 默认 `MemorySaver` 进程内 | 缺分布式 / 数据库级图状态 |
| **重试与补偿** | 失败经评审多为 `stop` | 缺系统化重试策略、saga |
| **横向扩展** | 单编排进程 | 未接队列 / Worker 池 |
| **可观测性** | 日志 + JSON | 缺统一 Trace/指标大盘 |
| **Agent 抽象** | 任务主要是字符串 + executor | 未内置角色/工具编排 DSL |
| **人机协同** | gate + `resume` | 缺审批台、超时升级等产品化能力 |
| **版本治理** | 随仓库演进 | 缺工作流定义注册与迁移 |

多数是 **薄控制面** 的刻意取舍；要补齐需单独排期。

---

## 配置示例

```json
[
  {
    "batch_id": "b0",
    "label": "采集",
    "tasks": [
      {"task_id": "t1", "label": "数据源 A"},
      {"task_id": "t2", "label": "数据源 B"}
    ],
    "depends_on": []
  },
  {
    "batch_id": "b1",
    "label": "汇总",
    "tasks": [{"task_id": "t3", "label": "合并结论"}],
    "depends_on": ["b0"],
    "fan_in_policy": "all_success"
  }
]
```

---

## 源码索引

- **状态模型：** `runtime/orchestrator/workflow_state.py`
- **双引擎：** `workflow_graph.py`、`workflow_loop.py`
- **规划：** `task_planner.py`
- **执行 / 评审：** `batch_executor.py`、`batch_reviewer.py`、`subagent_executor.py`
- **入口：** `runtime/orchestrator/cli.py`

---

## 仓库说明

本仓为 **OpenClaw 公司级 orchestration** 分层 monorepo（`docs/` 阅读入口、`runtime/` 实现真值、`tests/` 验收）。主链边界以 **`docs/CURRENT_TRUTH.md` + 源码** 为准，历史方案见 `archive/` 等目录。
