# tmux 接入与使用指南

> **版本**: v1.0  
> **日期**: 2026-03-28  
> **状态**: ✅ 已实现 (Batch 3)

---

## 0. 执行摘要

### 什么时候用 tmux？

| 场景 | 推荐后端 | 理由 |
|------|----------|------|
| **<30min 的短任务** | `subagent` | Token 效率高，自动超时，无需监控 |
| **>30min 的长任务** | `tmux` | 可监控中间进度，SSH 可 attach |
| **需要看中间过程** | `tmux` | 实时看到 AI 在干什么 |
| **容易卡住的任务** | `tmux` | 可随时接管/调试 |
| **编码/重构任务** | `tmux` | 需要看文件修改过程 |
| **简单 callback/dispatch** | `subagent` | 不需要中间状态 |
| **文档生成任务** | `subagent` | 终态即可 |

### 一句话决策

> **默认用 subagent，只有需要监控中间过程/长任务/易卡住的任务才用 tmux。**

---

## 1. 快速开始

### 方式 A: 使用 CLI 工具（推荐）

```bash
# 1. 注册 tmux 任务（自动创建状态卡）
python3 scripts/sync-tmux-observability.py register \
  --task-id "my_task_001" \
  --label "my-feature" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"

# 2. 启动 tmux 会话（使用现有脚本）
bash ~/.openclaw/skills/claude-code-orchestrator/scripts/start-tmux-task.sh \
  --label "my-feature" \
  --workdir "/path/to/repo" \
  --task "实现 XXX 功能"

# 3. 查看状态
python3 scripts/sync-tmux-observability.py list

# 4. 同步状态（定期运行或手动触发）
python3 scripts/sync-tmux-observability.py sync \
  --task-id "my_task_001" \
  --label "my-feature" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"

# 5. 查看任务看板
python3 -c "
from observability_card import generate_board_snapshot
import json
print(json.dumps(generate_board_snapshot()['summary'], indent=2))
"
```

### 方式 B: 使用 Python API

```python
from observability_card import create_card, update_card, get_card, generate_board_snapshot
from datetime import datetime

# 1. 创建状态卡
card = create_card(
    task_id="my_task_001",
    scenario="coding_issue",
    owner="main",
    executor="tmux",
    stage="dispatch",
    promised_eta="2026-03-28T18:00:00+08:00",
    anchor_type="tmux_session",
    anchor_value="cc-my-feature",
)

# 2. 启动 tmux 会话后，更新状态
update_card(
    task_id="my_task_001",
    stage="running",
    heartbeat=datetime.now().astimezone().isoformat(),
    recent_output="Starting implementation...",
)

# 3. 查询状态
card = get_card("my_task_001")
print(card.to_dict())

# 4. 生成看板
snapshot = generate_board_snapshot()
print(snapshot['summary'])
```

---

## 2. 完整流程

### 阶段 1: 任务注册

```bash
# 注册任务
python3 scripts/sync-tmux-observability.py register \
  --task-id "task_001" \
  --label "feature-xxx" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"
```

**输出示例**:
```json
{
  "success": true,
  "action": "register",
  "card": {
    "task_id": "task_001",
    "scenario": "coding_issue",
    "owner": "main",
    "executor": "tmux",
    "stage": "dispatch",
    "promise_anchor": {
      "promised_eta": "2026-03-28T18:00:00+08:00",
      "anchor_type": "tmux_session",
      "anchor_value": "cc-feature-xxx"
    }
  }
}
```

### 阶段 2: 启动 tmux 会话

```bash
# 使用现有 tmux 启动脚本
bash ~/.openclaw/skills/claude-code-orchestrator/scripts/start-tmux-task.sh \
  --label "feature-xxx" \
  --workdir "/path/to/repo" \
  --task "实现 XXX 功能，要求 TDD"
```

**tmux session 命名规则**: `cc-{label}`

### 阶段 3: 状态同步

```bash
# 手动同步
python3 scripts/sync-tmux-observability.py sync \
  --task-id "task_001" \
  --label "feature-xxx" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"
```

**自动同步**: 可配置定期运行（如 cron 每 5 分钟）

### 阶段 4: 监控进度

```bash
# 查看所有任务
python3 scripts/sync-tmux-observability.py list

# 查看特定任务
python3 -c "
from observability_card import get_card
import json
card = get_card('task_001')
print(json.dumps(card.to_dict(), indent=2))
"

# 生成看板快照
python3 -c "
from observability_card import generate_board_snapshot
import json
snapshot = generate_board_snapshot()
print(json.dumps(snapshot['summary'], indent=2))
"
```

### 阶段 5: 任务完成

tmux 会话完成后，状态会自动同步为 `completed` 或 `failed`。

```bash
# 验证完成状态
python3 -c "
from observability_card import get_card
card = get_card('task_001')
print(f'Stage: {card.stage}')
print(f'Completed: {card.metrics.completed_at}')
"
```

---

## 3. 状态映射

### tmux 原生状态 → 统一状态语言

| tmux 状态 | 统一状态 | 说明 |
|-----------|----------|------|
| `running` | `running` | Claude 正在执行 |
| `idle` | `idle` | Claude 空闲，等待输入 |
| `likely_done` | `completed` | 检测到完成信号 |
| `done_session_ended` | `completed` | session 退出，report 已生成 |
| `stuck` | `stuck` | 检测到错误信号，可能卡住 |
| `dead` | `failed` | session 已退出，无 report |

---

## 4. 状态卡字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `task_id` | ✅ | 任务唯一 ID |
| `batch_id` | ⚠️ | 批次 ID（批量任务时） |
| `scenario` | ✅ | 场景类型 |
| `owner` | ✅ | 负责 agent |
| `executor` | ✅ | 执行后端 (`subagent` / `tmux` / `browser` / `cron`) |
| `stage` | ✅ | 当前阶段 |
| `heartbeat` | ✅ | 最后心跳时间 |
| `recent_output` | ⚠️ | 最近输出摘要 |
| `attach_info` | ⚠️ | tmux session 信息 |
| `gate_state` | ⚠️ | Gate 状态（如有） |
| `promise_anchor` | ✅ | 承诺锚点 |
| `metrics` | ✅ | 时间指标 |

---

## 5. 常见场景

### 场景 1: 编码任务（需要监控）

```bash
# 适合用 tmux
python3 scripts/sync-tmux-observability.py register \
  --task-id "coding_001" \
  --label "refactor-auth" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T20:00:00+08:00"

# 启动 tmux
bash ~/.openclaw/skills/claude-code-orchestrator/scripts/start-tmux-task.sh \
  --label "refactor-auth" \
  --workdir "/path/to/repo" \
  --task "重构认证模块"
```

### 场景 2: 文档生成（不需要监控）

```bash
# 适合用 subagent（不需要 tmux）
# 直接使用 subagent，无需注册 tmux 状态卡
```

### 场景 3: 长时任务（>30min）

```bash
# 必须用 tmux
python3 scripts/sync-tmux-observability.py register \
  --task-id "long_001" \
  --label "full-refactor" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-29T12:00:00+08:00"
```

---

## 6. 故障排查

### 问题 1: 任务注册后找不到

```bash
# 检查索引文件
ls -la ~/.openclaw/shared-context/observability/cards/
cat ~/.openclaw/shared-context/observability/index/main.jsonl
```

### 问题 2: tmux 会话状态不同步

```bash
# 手动同步
python3 scripts/sync-tmux-observability.py sync \
  --task-id "task_001" \
  --label "feature-xxx" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"
```

### 问题 3: 状态卡字段缺失

```bash
# 检查状态卡
python3 -c "
from observability_card import get_card
import json
card = get_card('task_001')
print(json.dumps(card.to_dict(), indent=2))
"
```

---

## 7. 最佳实践

### 1. 任务命名

- `task_id`: 使用有意义的命名，如 `coding_auth_001`
- `label`: 简短描述，如 `refactor-auth`
- `promised_eta`: 留足 buffer，不要过于乐观

### 2. 状态同步频率

- **短任务**: 每 5-10 分钟同步一次
- **长任务**: 每 2-5 分钟同步一次
- **关键任务**: 可配置实时同步

### 3. 监控策略

- 使用看板快照定期审查
- 关注 `stuck` / `failed` 状态
- 超时任务自动告警（Batch 2 钩子）

---

## 8. 与 subagent 的对比

| 维度 | subagent | tmux |
|------|----------|------|
| **默认选择** | ✅ 默认 | ⚠️ 特殊场景 |
| **中间状态可见** | ❌ 仅终态 | ✅ 实时 |
| **自动超时** | ✅ runner 管理 | ❌ 需定期检查 |
| **SSH attach** | ❌ | ✅ |
| **Token 效率** | ✅ 高 | ⚠️ 需轮询 |
| **适用场景** | <30min / 不需要看中间过程 | >30min / 需要监控 / 易卡住 |

---

## 9. 附录：命令速查

```bash
# 注册
python3 scripts/sync-tmux-observability.py register --task-id xxx --label xxx --owner xxx --scenario xxx --promised-eta xxx

# 查看所有任务
python3 scripts/sync-tmux-observability.py list

# 同步状态
python3 scripts/sync-tmux-observability.py sync --task-id xxx --label xxx --owner xxx --scenario xxx --promised-eta xxx

# 查看特定任务
python3 -c "from observability_card import get_card; import json; print(json.dumps(get_card('task_xxx').to_dict(), indent=2))"

# 生成看板
python3 -c "from observability_card import generate_board_snapshot; import json; print(json.dumps(generate_board_snapshot()['summary'], indent=2))"
```

---

## 10. 相关文档

- `docs/observability-transparency-design-2026-03-28.md` - 完整设计方案
- `docs/observability-batch3-completion-report.md` - Batch 3 完成报告
- `runtime/orchestrator/tmux_status_sync.py` - tmux 状态同步模块
- `runtime/orchestrator/observability_card.py` - 状态卡模块
