# 编排系统透明度/可视化设计方案

> **版本**: v1.0  
> **日期**: 2026-03-28  
> **状态**: 设计稿 + Batch 1 实现中  
> **作者**: Zoe (CTO & Chief Orchestrator)

---

## 0. 执行摘要

### 问题陈述

当前 OpenClaw 编排系统相比 oh-my-claude-code 等 tmux-first 框架缺乏**过程透明度**：
- 用户无法直观看到任务执行进度
- 主 agent 承诺后缺乏可见的执行锚点
- subagent/tmux 执行状态分散，无统一索引
- 缺少"状态卡/任务看板"式的概览视图

### 设计目标

在不推翻当前 canonical artifact / callback / dispatch / receipt / closeout **真值链**的前提下，补充透明度层：
1. **保持真值链不变**：所有 canonical truth 仍由现有 artifact 系统承载
2. **新增观察面**：独立于真值链的 observability plane，用于可视化和进度追踪
3. **行为约束系统化**：将"承诺即执行"转化为可验证的钩子和防呆机制

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Observability Plane                       │
│  (新增) 状态卡 / 任务看板 / tmux 监控 / 进度可视化              │
│  - 只读，不写 truth                                          │
│  - 从 truth plane 同步状态                                    │
│  - 提供人类可读的进度视图                                     │
└─────────────────────────────────────────────────────────────┘
                              ↑ 读取
┌─────────────────────────────────────────────────────────────┐
│                      Truth Plane                             │
│  (现有) dispatch / callback / receipt / closeout artifacts   │
│  - 唯一真值来源                                              │
│  - 状态机 / task registry / state files                      │
│  - 不可绕过，不可双写                                         │
└─────────────────────────────────────────────────────────────┘
                              ↑ 调度
┌─────────────────────────────────────────────────────────────┐
│                    Execution Plane                           │
│  (现有) subagent / tmux / browser / message / cron           │
│  - 真正执行任务的 runtime                                     │
│  - subagent 是默认主链                                        │
│  - tmux 是可选 backend（用于需要中间观测的场景）                 │
└─────────────────────────────────────────────────────────────┘
```

### 关键决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| tmux 位置 | observability backend | tmux 不替代 canonical truth，仅提供可观测性 |
| 状态卡存储 | 独立 JSON 文件 | 与 truth plane 分离，避免污染真值 |
| 统一索引 | 轻量级 JSONL | 支持快速查询，不引入重型数据库 |
| 行为约束 | 钩子 + 校验脚本 | 在 dispatch/closeout 关键点插入检查 |

---

## 1. tmux 在未来架构中的位置

### 1.1 定位：Observability Backend（非 Primary Backend）

```
执行后端选择：
├── subagent (默认主链)
│   - 适用于：大多数编码/文档/长任务
│   - 特点：--print 模式，runner 管理，subagent_ended 自动通知
│   - 透明度：通过 completion receipt + state file 提供终态
│
└── tmux (可选，用于需要中间观测的场景)
    - 适用于：>30min 长任务、需要监控进度、易卡住的任务
    - 特点：交互模式，零 token 状态查询，SSH 可 attach
    - 透明度：通过 tmux snapshot + status script 提供中间状态
```

### 1.2 tmux 与 subagent 并存策略

| 维度 | subagent | tmux |
|------|----------|------|
| **默认选择** | ✅ 默认 | ⚠️ 仅特殊场景 |
| **中间状态可见** | ❌ 仅终态 | ✅ 实时 |
| **自动超时** | ✅ runner 管理 | ❌ 需定期检查 |
| **SSH attach** | ❌ | ✅ |
| **Token 效率** | ✅ 高 | ⚠️ 需轮询 |
| **适用场景** | <30min / 不需要看中间过程 | >30min / 需要监控 / 易卡住 |

### 1.3 tmux 状态映射

```python
# tmux 原生状态 → 统一状态语言
TMUX_STATUS_MAP = {
    "running": "running",      # Claude 正在执行
    "idle": "idle",            # Claude 空闲，等待输入
    "likely_done": "completed", # 检测到完成信号
    "done_session_ended": "completed", # session 退出，report 已生成
    "stuck": "stuck",          # 检测到错误信号
    "dead": "failed",          # session 已退出，无 report
}
```

---

## 2. 状态卡/任务看板最小字段

### 2.1 状态卡 Schema (v1)

```json
{
  "card_version": "observability_card_v1",
  "task_id": "task_xxx",
  "batch_id": "batch_yyy",
  "scenario": "trading_roundtable | channel_roundtable | coding_issue | custom",
  "owner": "main | trading | ainews | macro | content | butler",
  "executor": "subagent | tmux | browser | message | cron",
  "stage": "planning | dispatch | running | callback_received | closeout | completed | failed",
  "heartbeat": "2026-03-28T15:00:00",
  "recent_output": "最近 100 字符输出摘要",
  "attach_info": {
    "session_id": "cc-feature-xxx",
    "tmux_socket": "/tmp/clawdbot-tmux-sockets/clawdbot.sock",
    "report_path": "/tmp/cc-feature-xxx-completion-report.md",
    "log_path": "/Users/study/.openclaw/workspace/repos/.../run/claude.stdout.log"
  },
  "gate_state": {
    "gate_type": "human | auto | validator",
    "gate_status": "pending | passed | failed | conditional",
    "gate_reason": "等待用户确认 | validator blocked | clean PASS"
  },
  "promise_anchor": {
    "promised_at": "2026-03-28T14:00:00",
    "promised_eta": "2026-03-28T15:00:00",
    "anchor_type": "dispatch_id | session_id | tmux_session",
    "anchor_value": "dispatch_abc123 | cc-feature-xxx"
  },
  "metrics": {
    "created_at": "2026-03-28T14:00:00",
    "started_at": "2026-03-28T14:05:00",
    "completed_at": null,
    "duration_seconds": 3600,
    "retry_count": 0
  }
}
```

### 2.2 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `task_id` | ✅ | 任务唯一 ID |
| `batch_id` | ⚠️ | 批次 ID（批量任务时） |
| `scenario` | ✅ | 场景类型 |
| `owner` | ✅ | 负责 agent |
| `executor` | ✅ | 执行后端类型 |
| `stage` | ✅ | 当前阶段 |
| `heartbeat` | ✅ | 最后心跳时间 |
| `recent_output` | ⚠️ | 最近输出摘要（用于快速诊断） |
| `attach_info` | ⚠️ | 附加信息（session/report/log 路径） |
| `gate_state` | ⚠️ | Gate 状态（如有） |
| `promise_anchor` | ✅ | 承诺锚点（承诺时间 + 执行锚点） |
| `metrics` | ✅ | 时间指标 |

### 2.3 存储结构

```
~/.openclaw/shared-context/observability/
├── cards/                    # 状态卡目录
│   ├── task_xxx.json
│   ├── task_yyy.json
│   └── ...
├── index/                    # 统一索引（按 owner/scenario 分片）
│   ├── main.jsonl
│   ├── trading.jsonl
│   ├── ainews.jsonl
│   └── ...
├── boards/                   # 任务看板快照
│   ├── board-2026-03-28.json
│   └── ...
└── hooks/                    # 行为约束钩子
    ├── pre-dispatch-check.py
    ├── post-promise-verify.py
    └── ...
```

---

## 3. "承诺即执行"行为约束系统化

### 3.1 问题

当前主 agent 可能：
- 宣称"进行中"但无真实执行锚点
- 承诺时限但未到点汇报
- 超时后静默等待，无中间状态

### 3.2 解决方案：三层约束

#### Layer 1: Dispatch 时强制锚点

```python
# pre-dispatch-check.py
def validate_promise_anchor(dispatch_payload: dict) -> tuple[bool, str]:
    """
    验证 dispatch 是否包含有效执行锚点。
    
    规则：
    1. 必须有 executor 字段 (subagent/tmux/...)
    2. 必须有 anchor_type 和 anchor_value
    3. 必须有 promised_eta
    """
    required = ["executor", "anchor_type", "anchor_value", "promised_eta"]
    missing = [k for k in required if k not in dispatch_payload]
    if missing:
        return False, f"缺少必需字段：{missing}"
    
    # 验证 anchor_value 非空
    if not dispatch_payload["anchor_value"]:
        return False, "anchor_value 不能为空"
    
    return True, "验证通过"
```

#### Layer 2: 同回合无锚点不得宣称进行中

```python
# post-promise-verify.py
def verify_promise_has_anchor(session_context: dict) -> tuple[bool, str]:
    """
    验证当前会话中宣称"进行中"的任务是否有锚点。
    
    规则：
    1. 扫描会话消息，查找"进行中/processing/running"等关键词
    2. 检查是否有对应的 dispatch artifact / session_id / tmux_session
    3. 无锚点则标记为"空承诺"
    """
    # 实现逻辑...
    pass
```

#### Layer 3: 超时自动告警

```python
# timeout-alert.py
def check_promise_timeout(cards: list[dict], threshold_minutes: int = 30) -> list[dict]:
    """
    检查承诺超时的任务卡。
    
    规则：
    1. 当前时间 - promised_eta > threshold
    2. stage 仍为 running/dispatch
    3. 无 heartbeat 更新
    """
    # 实现逻辑...
    pass
```

### 3.3 钩子集成点

| 钩子 | 集成点 | 触发时机 |
|------|--------|----------|
| `pre-dispatch-check` | `auto_dispatch.py` | dispatch 前 |
| `post-promise-verify` | `orchestrator.py` | 会话回复前 |
| `timeout-alert` | `watchdog.py` | 定期巡检 |

---

## 4. 最小实现批次规划

### Batch 1: 状态卡 + 统一索引（本批次）

**目标**：实现最小可用的状态卡系统，支持查询和展示。

**交付物**：
1. `observability_card.py` - 状态卡 CRUD 模块
2. `observability_index.py` - 统一索引模块
3. `cli.py` 新增命令：`orch-observability card-*`
4. 测试：`tests/observability/test_card.py`
5. 验证脚本：`scripts/verify-observability-batch1.sh`

**验收标准**：
- ✅ 能创建/读取/更新状态卡
- ✅ 能按 owner/scenario 查询卡片
- ✅ 能生成任务看板快照
- ✅ 测试通过率 100%

### Batch 2: 行为约束钩子

**目标**：实现"承诺即执行"的校验钩子。

**交付物**：
1. `hooks/pre-dispatch-check.py` - dispatch 前校验
2. `hooks/post-promise-verify.py` - 承诺后验证
3. 集成到 `auto_dispatch.py` 和 `orchestrator.py`
4. 测试：`tests/observability/test_hooks.py`

**验收标准**：
- ✅ 无锚点 dispatch 被拦截
- ✅ 空承诺被检测并告警
- ✅ 测试通过率 100%

### Batch 3: tmux 统一状态索引

**目标**：将 tmux session 状态纳入统一索引。

**交付物**：
1. `tmux_status_sync.py` - tmux 状态同步模块
2. 集成到 `start-tmux-task.sh` 和 `status-tmux-task.sh`
3. 看板增强：显示 tmux session 实时状态
4. 测试：`tests/observability/test_tmux_sync.py`

**验收标准**：
- ✅ tmux session 自动注册到索引
- ✅ 状态变更自动同步
- ✅ 测试通过率 100%

### Batch 4: 可视化看板（可选）

**目标**：Web 看板或终端看板。

**交付物**：
1. `dashboard/` - 看板实现（Web 或 TUI）
2. 实时刷新状态
3. 过滤/排序/搜索功能

**验收标准**：
- ✅ 实时显示所有任务状态
- ✅ 支持按 owner/scenario/stage 过滤
- ✅ 支持搜索

---

## 5. 风险与边界

### 5.1 不能做的事

| 风险 | 边界 | 缓解措施 |
|------|------|----------|
| tmux 透明层替代 canonical truth | ❌ 禁止 | 明确文档 + 代码注释 + 测试验证 |
| 为了可视化破坏 callback/gate 真值 | ❌ 禁止 | observability plane 只读，不写 truth |
| 双写状态（truth + observability） | ❌ 禁止 | observability 从 truth 同步，不独立维护 |
| 重型依赖（数据库/外部服务） | ❌ 避免 | 使用轻量级 JSON/JSONL 文件 |

### 5.2 回退方案

如果 Batch 1 实现后发现问题：
1. **立即回退**：删除 `~/.openclaw/shared-context/observability/` 目录
2. **不影响真值链**：truth plane 不受影响，系统继续运行
3. **重新设计**：基于问题调整方案，进入 Batch 1.5

### 5.3 成功指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 状态卡创建延迟 | <100ms | 基准测试 |
| 索引查询延迟 | <50ms | 基准测试 |
| 空承诺检测率 | 100% | 测试覆盖 |
| 用户满意度 | 主观评价 | 用户反馈 |

---

## 6. 附录：与现有系统集成

### 6.1 与 subagent_state.py 集成

```python
# observability_card.py 从 subagent_state 同步
from subagent_state import SubagentStateManager

def sync_from_subagent_state(task_id: str):
    """从 subagent state 同步到 observability card"""
    state_manager = SubagentStateManager()
    state = state_manager.get_state(task_id)
    
    card = create_card(
        task_id=task_id,
        stage=state["status"],  # pending/running/completed/failed
        heartbeat=state["updated_at"],
        metrics={
            "created_at": state["created_at"],
            "started_at": state["started_at"],
            "completed_at": state["completed_at"],
        }
    )
    return card
```

### 6.2 与 completion_receipt.py 集成

```python
# observability_card.py 从 completion receipt 同步
from completion_receipt import get_completion_receipt

def sync_from_receipt(receipt_id: str):
    """从 completion receipt 同步到 observability card"""
    receipt = get_completion_receipt(receipt_id)
    
    card = update_card(
        task_id=receipt["task_id"],
        stage="completed" if receipt["status"] == "completed" else "failed",
        recent_output=receipt.get("result_summary", ""),
        completed_at=receipt["created_at"],
    )
    return card
```

### 6.3 与 tmux_terminal_receipts.py 集成

```python
# tmux_status_sync.py 从 tmux receipt 同步
from tmux_terminal_receipts import get_tmux_receipt

def sync_from_tmux_receipt(dispatch_id: str):
    """从 tmux receipt 同步到 observability card"""
    receipt = get_tmux_receipt(dispatch_id)
    
    card = update_card(
        task_id=receipt["task_id"],
        executor="tmux",
        stage=map_tmux_status(receipt["status"]),
        attach_info={
            "session_id": receipt.get("session"),
            "report_path": receipt.get("report_path"),
        }
    )
    return card
```

---

## 7. 参考文档

- [CURRENT_TRUTH.md](CURRENT_TRUTH.md) - 当前系统真值
- [architecture-layering.md](architecture-layering.md) - 架构分层说明
- [executive-summary.md](executive-summary.md) - 执行摘要
- [subagent_state.py](../runtime/orchestrator/subagent_state.py) - Subagent 状态管理
- [completion_receipt.py](../runtime/orchestrator/completion_receipt.py) - Completion Receipt
- [tmux_terminal_receipts.py](../runtime/orchestrator/tmux_terminal_receipts.py) - Tmux Receipt

---

## 8. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-03-28 | 初始设计稿 + Batch 1 实现 |
