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

编排控制面提供两条共存的执行路径：

| 路径 | 适用场景 | 入口 |
|------|---------|------|
| **DAG 工作流** | 预规划批量编排：规划所有批次 → 自动推进 | `cli.py plan / run / resume / show` |
| **回调驱动** | 事件驱动：消息 → callback → 决策 → 下一跳 | `cli.py status / decide / stuck` |

两条路径共享同一个执行基板（`SubagentExecutor` + `TmuxTaskExecutor`）。

| 能力 | 实现 | 状态 |
|------|------|------|
| **批量 DAG 规划** | Kahn 算法校验 DAG，拓扑排序确定执行顺序 | ✅ 生产验证 |
| **并行派发 + 重试** | `BatchExecutor` 通过可插拔 Executor 派发任务 | ✅ 生产验证 |
| **扇入审查** | `all_success` / `any_success` / `majority` 策略 | ✅ 生产验证 |
| **安全门禁** | 可配置门禁条件，暂停等待人工审查 | ✅ 生产验证 |
| **Continuation Kernel** | 9 版本制品链：注册 → 派发 → 孵化 → 执行 → 回执 → 回调 → 自动续行 | ✅ 生产验证 |
| **Hooks 系统** | 三档行为约束（audit/warn/enforce）：承诺验证、完成翻译 | ✅ 生产验证 |
| **可观测性** | 任务状态卡、看板渲染、tmux 同步 | ✅ 生产验证 |
| **告警** | 规则引擎 + 审计追踪 + 告警路由 | ✅ 生产验证 |
| **断路器** | 连续 3 次 / 累计 20 次失败自动熔断 | ✅ 已实现 |
| **可插拔 Executor** | `TaskExecutorBase` 抽象接口 | ✅ 接口已定义 |

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

## 可靠性

| 机制 | 实现 |
|------|------|
| 原子写入 | `tempfile + os.fsync + os.replace`（`utils/io.py`） |
| 文件锁 | `SingleWriterGuard` + `fcntl.flock` |
| 断路器 | 连续/累计失败追踪，自动熔断 |
| 看门狗 | 停滞检测、死进程回收、孤儿任务恢复 |
| Fork 防护 | 三层守卫：孵化深度 + 进程计数 + 信号量 |
| UTC 时间 | 所有超时比较使用 `datetime.now(timezone.utc)` |
| 崩溃恢复 | `workflow_loop` 异常时持久化状态再退出 |

---

## 测试

```bash
PYTHONPATH=runtime/orchestrator python3 -m pytest tests/ -v -k "not e2e"
```

---

## 协议

MIT
