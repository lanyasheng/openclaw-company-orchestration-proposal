# 回调驱动编排器 v1

> 轻量级任务编排引擎，实现 **批量派发 → 自动回调 → 自动汇总 → 自动决策 → 自动派发下一轮** 闭环

**Version**: 1.0.0  
**Created**: 2026-03-20  
**Owner**: main (Zoe)

---

## 快速开始

### 1. 运行测试
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal/runtime/orchestrator
python3 cli.py test
```

### 2. 查询任务状态
```bash
python3 cli.py status <task_id>
```

### 3. 查询批次汇总
```bash
python3 cli.py batch-summary <batch_id>
```

### 4. 对批次做出决策
```bash
python3 cli.py decide <batch_id>
```

### 5. 列出所有任务
```bash
python3 cli.py list [--state <state>]
```

### 6. 检测卡住的批次
```bash
python3 cli.py stuck [--timeout 60]
```

---

## Backend Policy (Dual-Track Strategy, 2026-03-23)

**Supported Backends**: `subagent` (DEFAULT) and `tmux` (FULLY SUPPORTED)

```python
# Default: subagent backend (recommended for automated execution)
from continuation_backends import normalize_dispatch_backend
backend = normalize_dispatch_backend("subagent")  # DEFAULT

# Also fully supported: tmux backend (for interactive/observable sessions)
backend = normalize_dispatch_backend("tmux")  # FULLY SUPPORTED
```

**P0-3 Batch 4 (2026-03-23)**: Documented backend policy.

**P0-3 Batch 5 (2026-03-23)**: Clarified default path while retaining tmux support.

**Dual-Track Strategy**: 
- **subagent**: Default for new development, automated execution, CI/CD
- **tmux**: Fully supported for interactive sessions, manual observation, debugging
- **Both backends retained indefinitely** - no breaking removal planned

---

## 核心模块

### state_machine.py — 任务状态机

统一跟踪任务生命周期：

```
pending → running → callback_received → next_task_dispatched → final_closed
                              ↓
                         timeout/failed → (retry or abort)
```

**关键函数**：
- `create_task(task_id, batch_id, timeout_seconds)`
- `update_state(task_id, new_state, result, next_task_ids)`
- `get_state(task_id)`
- `is_batch_complete(batch_id)`
- `get_batch_summary(batch_id)`

---

### batch_aggregator.py — Fan-in 汇总层

监听多个子任务的 completion 事件，按 batch_id 汇总：

**关键函数**：
- `analyze_batch_results(batch_id)` — 分析批次结果
- `generate_batch_summary_md(batch_id)` — 生成 Markdown 汇总报告
- `check_and_summarize_batch(batch_id)` — 检查并完成汇总
- `detect_stuck_batches(timeout_minutes)` — 检测卡住的批次

---

### trading_roundtable.py — Trading Roundtable 续线薄桥

把通用状态机/汇总/决策层接到 `trading_roundtable_phase1` 这个具体场景：

**关键函数**：
- `process_trading_roundtable_callback(...)` — 处理 callback，持久化 trading summary / decision / dispatch plan

**默认行为**：
- `trading_roundtable` 已 cut over 为 **default auto-continue within low-risk boundary**
- `orch_product onboard/run` 会写入 trading 默认自动推进配置：自动注册 / 自动派发 / 自动回流 / 自动续推
- dispatch plan 显式携带 `backend=subagent|tmux`，默认仍是 `subagent`
- clean PASS 且 low-risk continuation 默认 `triggered`；命中真实资金 / 不可逆线上动作 / gate review 时仍会停在人工 gate

---

### channel_roundtable.py — 其他频道/线程接入薄桥

把同样的 `summary -> decision -> dispatch plan` 链路，接到非 trading 的普通频道/线程场景：

**关键函数**：
- `process_channel_roundtable_callback(...)` — 处理 channel/thread roundtable callback，持久化 generic channel summary / decision / dispatch plan

**最小输入契约**：
- `result.channel_roundtable.packet`
  - `packet_version=channel_roundtable_v1`
  - `scenario`
  - `channel_id`
  - `topic`
  - `owner`
  - `generated_at`
- `result.channel_roundtable.roundtable`
  - `conclusion / blocker / owner / next_step / completion_criteria`

**默认行为**：
- 默认仍是 **safe semi-auto**
- dispatch plan 现在显式携带 `backend=subagent|tmux`
- 若调用方显式传入 `allow_auto_dispatch`，显式值优先
- 当前仅对白名单场景默认放开：`Temporal vs LangGraph｜OpenClaw 公司级编排架构`（频道 ID `1483883339701158102` / 对应精确 scenario+topic）
- 其他频道仍默认关闭；且即使白名单命中，也只会对 `proceed` / `retry` 这类明确可推进动作触发
- operator-facing 最小接入包入口：`orchestrator/examples/generic_channel_roundtable_onboarding_kit.md`

---

### orchestrator.py — 回调驱动编排器

根据汇总结果决定下一批派什么：

**关键类**：
- `Orchestrator` — 编排器主类
- `Decision` — 决策结果（现已带 `decision_id`，可被 dispatch plan 直接追踪）

**内置决策规则**：
- `rule_all_success` — 全部成功 → 推进
- `rule_has_common_blocker` — 有共同 blocker → 修复
- `rule_partial_failure` — 部分失败 → 重试
- `rule_major_failure` — 大部分失败 → 中止

---

## 使用示例

### Python API

```python
from orchestrator import (
    create_task,
    mark_callback_received,
    is_batch_complete,
    create_default_orchestrator,
)

# 1. 创建任务
batch_id = "batch_001"
for i in range(3):
    task_id = f"tsk_{i:03d}"
    create_task(task_id, batch_id=batch_id)

# 2. 模拟回调
for i in range(3):
    task_id = f"tsk_{i:03d}"
    mark_callback_received(task_id, {"verdict": "PASS"})

# 3. 检查批次是否完成
if is_batch_complete(batch_id):
    # 4. 做出决策
    orch = create_default_orchestrator()
    decision = orch.decide(batch_id)
    
    print(f"Action: {decision.action}")
    print(f"Reason: {decision.reason}")
```

### CLI

```bash
# 查看任务状态
python3 cli.py status tsk_001

# 查看批次汇总
python3 cli.py batch-summary batch_001

# 做出决策
python3 cli.py decide batch_001

# 列出所有任务
python3 cli.py list

# 检测卡住的批次
python3 cli.py stuck --timeout 60
```

---

## 数据流

```
用户发起批量任务
       ↓
[任务状态机] 登记每个任务的状态
       ↓
子任务们执行 → 完成 → 回调
       ↓
[任务状态机] 更新状态
       ↓
[Fan-in 汇总层] 检测到 batch 完成 → 产出 summary
       ↓
[回调驱动编排器] 读取 summary → 决定下一批派什么
       ↓
[任务状态机] 更新状态 → 派发下一轮
       ↓
... 循环直到 final_closed
```

---

## 决策规则

| 规则 | 条件 | 动作 |
|------|------|------|
| `rule_all_success` | 成功率 = 100% | 推进到下一阶段 |
| `rule_has_common_blocker` | 有共同错误模式 | 修复 blocker |
| `rule_partial_failure` | 50% ≤ 成功率 < 100% | 重试失败任务 |
| `rule_major_failure` | 成功率 < 50% | 中止并报告 |

---

## 状态存储

- **任务状态**: `~/.openclaw/shared-context/job-status/{task_id}.json`
- **批次汇总**: `~/.openclaw/shared-context/job-status/batch-{batch_id}-summary.md`
- **决策记录**: `~/.openclaw/shared-context/orchestrator/decisions/{decision_id}.json`
- **派发记录**: `~/.openclaw/shared-context/orchestrator/dispatches/{dispatch_id}.json`

---

## 验收标准

### MVP（当前版本）
- [x] 能派发 2+ 个子任务
- [x] 所有子任务完成后自动汇总
- [x] 汇总后自动决策
- [x] 状态可在 CLI/文件中查询
- [x] Trading roundtable case 能产出可追踪的 `summary -> decision -> dispatch plan`

### 待实现（后续版本）
- [ ] 默认自动派发下一轮任务（需集成 sessions_spawn 的最终执行）
- [ ] 超时/失败自动处理
- [ ] 重试策略
- [ ] 条件分支（DAG）
- [ ] Web 看板

---

## 故障排除

### 任务状态不更新
检查 `~/.openclaw/shared-context/job-status/` 目录下是否有对应的 `.json` 文件。

### 批次汇总未生成
运行 `python3 cli.py batch-summary <batch_id>` 手动触发。

### 决策未做出
运行 `python3 cli.py decide <batch_id>` 查看哪个规则匹配。

### 检测到卡住的批次
运行 `python3 cli.py stuck --timeout 60` 查看卡住的任务。

---

## 与设计文档对应

本实现对应设计文档：
`docs/architecture/callback-driven-orchestration-v1-20260320.md` (in OpenClaw workspace)

---

## 下一步

1. **集成到 sessions_spawn 回调链路**
   - 在 subagent_ended hook 中自动调用 `process_batch_callback()`

2. **实现派发回调**
   - 将 `set_dispatch_callback()` 连接到 sessions_spawn

3. **添加 Web 看板**
   - 简单的 HTTP 服务器展示任务状态和批次汇总

4. **添加告警**
   - 检测超时/失败时发送 Discord 通知

---

*End of README*
