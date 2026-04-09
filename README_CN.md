# OpenClaw 编排控制面

> Agent 完成任务后，下一步该怎么走？
> 这个仓库让答案变得显式、可追溯、安全。

[English](README.md) · [运维指南](docs/OPERATIONS.md)

---

## 解决什么问题

多 Agent 系统的失败不在能力，在于**协调**：

| 缺口 | 后果 |
|------|------|
| 没有显式交接 | Agent A 做完了，没人通知 Agent B，任务静默停滞 |
| 没有扇入汇总 | 5 个并行任务结果不一，继续还是停止？按什么规则？ |
| 没有状态持续性 | 进程崩溃，做到哪了？做了什么？怎么恢复？ |
| 没有安全门禁 | 无限制自动派发 → 失控 Agent，浪费算力 |

---

## 核心能力

批量 DAG 工作流引擎，通过 tmux + Claude Code CLI 编排多 Agent 任务执行。

| 能力 | 实现 | 状态 |
|------|------|------|
| **批量 DAG 规划** | `depends_on` 定义依赖，Kahn 算法校验 DAG，拓扑排序确定执行顺序 | ✅ 生产验证 |
| **并行派发 + 重试** | `BatchExecutor` 通过可插拔 Executor 派发任务，监控完成，自动重试 | ✅ 生产验证 |
| **扇入审查** | `BatchReviewer` 支持 `all_success` / `any_success` / `majority` 策略 | ✅ 生产验证 |
| **安全门禁** | 可配置的门禁条件，暂停等待人工审查，resume 继续 | ✅ 生产验证 |
| **单 JSON 状态** | 每个工作流一个 `workflow_state_*.json`，唯一事实源 | ✅ 生产验证 |
| **LangGraph 集成** | 可选 LangGraph StateGraph 引擎，零依赖轮询降级 | ✅ 生产验证 |
| **可插拔 Executor** | `TaskExecutorBase` 抽象接口，可替换任意执行后端 | ✅ 接口已定义 |

---

## 快速开始

```bash
pip install langgraph langgraph-checkpoint-sqlite  # 可选

python3 runtime/orchestrator/cli.py plan "分析代码库" config.json
python3 runtime/orchestrator/cli.py run workflow_state_wf_xxx.json --workspace .
python3 runtime/orchestrator/cli.py show workflow_state_wf_xxx.json
python3 runtime/orchestrator/cli.py resume workflow_state_wf_xxx.json
```

---

## 仓库结构

```
runtime/orchestrator/           # 核心模块 (18 个文件)
├── cli.py                      # CLI 入口: plan/run/show/resume
├── workflow_state.py           # 单 JSON 状态模型
├── task_planner.py             # DAG 校验 + 拓扑排序
├── batch_executor.py           # 并行派发 + 重试
├── batch_reviewer.py           # 扇入策略 + 门禁
├── orchestrator.py             # 规则链决策引擎
├── executor_interface.py       # 可插拔 Executor 抽象接口
├── subagent_executor.py        # 进程管理 + fork 防护
├── tmux_executor.py            # Tmux 会话 Executor
└── utils/                      # 原子写入、UTC 时间戳

scripts/                        # Shell 派发引擎
├── start-tmux-task.sh          # 通用 tmux 任务启动器
└── monitor/status scripts

tests/orchestrator/             # 测试套件 (89 个单元测试)
```

---

## 测试

```bash
PYTHONPATH=runtime/orchestrator python3 -m pytest tests/ -v -k "not e2e"
```

---

## 协议

MIT
