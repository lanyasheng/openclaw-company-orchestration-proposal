# Observability 配置与使用指南

> **版本**: v1.0  
> **日期**: 2026-03-28  
> **目标读者**: 所有需要使用 observability 能力的 agent 和开发者

---

## 0. 快速开始（5 分钟上手）

### 如果你是第一次用

```bash
# 1. 查看所有任务
python3 scripts/sync-tmux-observability.py list

# 2. 生成任务看板
python3 -c "
from observability_card import generate_board_snapshot
import json
print(json.dumps(generate_board_snapshot()['summary'], indent=2))
"

# 3. 查询特定任务
python3 -c "
from observability_card import get_card
import json
card = get_card('task_xxx')
print(json.dumps(card.to_dict(), indent=2))
"
```

### 如果你要接入 tmux

看这个文档：**`tmux-integration-guide.md`**

---

## 1. 配置说明

### 1.1 目录结构

```
~/.openclaw/shared-context/observability/
├── cards/                    # 状态卡目录（每张卡一个 JSON 文件）
│   ├── task_001.json
│   ├── task_002.json
│   └── ...
├── index/                    # 统一索引（按 owner 分片）
│   ├── main.jsonl
│   ├── trading.jsonl
│   ├── ainews.jsonl
│   └── ...
└── boards/                   # 任务看板快照（按日期）
    ├── board-2026-03-28.json
    └── ...
```

### 1.2 环境变量（可选）

默认配置即可用，无需额外配置。如需自定义：

```bash
# 自定义 observability 目录（默认：~/.openclaw/shared-context/observability）
export OPENCLAW_OBSERVABILITY_DIR="/custom/path/observability"
```

### 1.3 依赖检查

```bash
# 检查模块是否可用
python3 -c "
from observability_card import create_card, get_card
print('✅ observability_card 模块可用')

from tmux_status_sync import TmuxStatusSync
print('✅ tmux_status_sync 模块可用')

from backend_selector import recommend_backend
print('✅ backend_selector 模块可用')
"
```

---

## 2. 核心能力

### 2.1 状态卡系统

**用途**: 追踪每个任务的实时状态

**字段**:
```json
{
  "card_version": "observability_card_v1",
  "task_id": "task_001",
  "scenario": "coding_issue",
  "owner": "main",
  "executor": "tmux",
  "stage": "running",
  "heartbeat": "2026-03-28T16:00:00+08:00",
  "recent_output": "最近 100 字符输出摘要",
  "attach_info": {
    "session_id": "cc-feature-xxx",
    "tmux_socket": "/tmp/clawdbot-tmux-sockets/clawdbot.sock"
  },
  "promise_anchor": {
    "promised_eta": "2026-03-28T18:00:00+08:00",
    "anchor_type": "tmux_session",
    "anchor_value": "cc-feature-xxx"
  },
  "metrics": {
    "created_at": "2026-03-28T14:00:00",
    "started_at": "2026-03-28T14:05:00",
    "completed_at": null,
    "duration_seconds": 0
  }
}
```

**API**:
```python
from observability_card import create_card, update_card, get_card, list_cards

# 创建
card = create_card(
    task_id="my_task",
    scenario="coding_issue",
    owner="main",
    executor="tmux",
    stage="dispatch",
    promised_eta="2026-03-28T18:00:00+08:00",
    anchor_type="tmux_session",
    anchor_value="cc-my-task",
)

# 更新
update_card(
    task_id="my_task",
    stage="running",
    heartbeat="2026-03-28T16:00:00+08:00",
    recent_output="Working on...",
)

# 查询
card = get_card("my_task")

# 列表（支持过滤）
cards = list_cards(owner="main", stage="running", limit=100)
```

### 2.2 任务看板

**用途**: 概览所有任务状态

**API**:
```python
from observability_card import generate_board_snapshot

snapshot = generate_board_snapshot()
print(snapshot['summary'])
# {
#   "total_cards": 10,
#   "by_stage": {"dispatch": 3, "running": 5, "completed": 2},
#   "by_owner": {"main": 6, "trading": 4}
# }
```

### 2.3 tmux 集成

**用途**: tmux session 自动注册到 observability 索引

**CLI**:
```bash
# 注册新任务
python3 scripts/sync-tmux-observability.py register \
  --task-id "my_task" \
  --label "my-feature" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"

# 同步状态
python3 scripts/sync-tmux-observability.py sync \
  --task-id "my_task" \
  --label "my-feature" \
  --owner "main" \
  --scenario "coding_issue" \
  --promised-eta "2026-03-28T18:00:00+08:00"

# 查看所有 tmux 任务
python3 scripts/sync-tmux-observability.py list
```

### 2.4 后端自动选择

**用途**: 根据任务特征自动推荐 tmux/subagent

**API**:
```python
from backend_selector import recommend_backend

rec = recommend_backend(
    task_description="重构认证模块，预计 1 小时，需要看过程",
    estimated_duration_minutes=60,
    requires_monitoring=True,
)
print(f"推荐：{rec.backend}")  # tmux
print(f"理由：{rec.reason}")
print(f"置信度：{rec.confidence:.2f}")
```

**CLI**:
```bash
python3 runtime/orchestrator/backend_selector.py
```

---

## 3. 其他 Agent 如何使用

### 场景 1: main agent 要追踪任务

```python
# 在派发任务前创建状态卡
from observability_card import create_card

card = create_card(
    task_id="task_001",
    scenario="coding_issue",
    owner="trading",
    executor="subagent",
    stage="dispatch",
    promised_eta="2026-03-28T18:00:00+08:00",
    anchor_type="session_id",
    anchor_value="cc-feature-xxx",
)

# 任务完成后更新状态
from observability_card import update_card

update_card(
    task_id="task_001",
    stage="completed",
    heartbeat=datetime.now().astimezone().isoformat(),
    recent_output="Task completed successfully",
)
```

### 场景 2: trading agent 要查看自己的任务

```python
from observability_card import list_cards

# 查询 trading 的所有任务
trading_tasks = list_cards(owner="trading", limit=100)

# 查询 trading 正在运行的任务
running_tasks = list_cards(owner="trading", stage="running", limit=100)
```

### 场景 3: 定期检查超时任务

```python
from observability_card import list_cards
from datetime import datetime, timedelta

# 找出超时的任务
now = datetime.now().astimezone()
timeout_threshold = timedelta(minutes=30)

all_tasks = list_cards(stage="running", limit=1000)
for card in all_tasks:
    if card.promise_anchor.get("promised_eta"):
        promised_eta = datetime.fromisoformat(card.promise_anchor["promised_eta"])
        if now > promised_eta + timeout_threshold:
            print(f"⚠️ 超时任务：{card.task_id} (owner={card.owner})")
```

### 场景 4: 在 dispatch 时自动推荐 backend

```python
from backend_selector import recommend_backend

# 根据任务描述推荐 backend
rec = recommend_backend(
    task_description="调试一个偶发的 bug，可能需要监控",
    requires_monitoring=True,
)

# 使用推荐的 backend
if rec.backend == "tmux":
    # 启动 tmux 会话
    pass
else:
    # 使用 subagent
    pass
```

---

## 4. 行为约束钩子（Batch 2）

### 4.1 子任务完成后强制翻译人话

**钩子**: `post_completion_translate_hook.py`

**作用**: 防止"做完了不汇报"

**触发时机**: 子任务完成后，主 agent 回复前

**检查逻辑**:
1. 扫描 ACP 完成报告时间戳
2. 扫描主 agent 后续消息，查找是否有人话总结
3. 超时未翻译则标记为"空转"并告警

### 4.2 宣称"进行中"必须有执行锚点

**钩子**: `post_promise_verify_hook.py`

**作用**: 防止"空承诺"

**触发时机**: 主 agent 宣称"进行中/processing/running"时

**检查逻辑**:
1. 扫描会话消息，查找"进行中"等关键词
2. 检查是否有对应的 dispatch artifact / session_id / tmux_session
3. 无锚点则标记为"空承诺"

---

## 5. 最佳实践

### 5.1 任务命名

- `task_id`: 使用有意义的命名，如 `coding_auth_001`
- `label`: 简短描述，如 `refactor-auth`
- `promised_eta`: 留足 buffer，不要过于乐观

### 5.2 状态同步频率

- **短任务**: 每 5-10 分钟同步一次
- **长任务**: 每 2-5 分钟同步一次
- **关键任务**: 可配置实时同步

### 5.3 监控策略

- 使用看板快照定期审查
- 关注 `stuck` / `failed` 状态
- 超时任务自动告警（Batch 2 钩子）

### 5.4 清理旧任务

```python
from observability_card import list_cards, delete_card
from datetime import datetime, timedelta

# 删除 30 天前已完成的任务
cutoff = datetime.now().astimezone() - timedelta(days=30)
old_tasks = list_cards(stage="completed", limit=1000)
for card in old_tasks:
    if card.metrics.completed_at:
        completed_at = datetime.fromisoformat(card.metrics.completed_at)
        if completed_at < cutoff:
            delete_card(card.task_id)
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

### 问题 4: backend 推荐不准确

```python
# 调试推荐逻辑
from backend_selector import BackendSelector

selector = BackendSelector()
rec = selector.recommend(
    task_description="调试一个偶发的 bug",
    requires_monitoring=True,
)
print(f"推荐：{rec.backend}")
print(f"因素：{rec.factors}")
print(f"分数详情：tmux={rec.factors.get('score_tmux')}, subagent={rec.factors.get('score_subagent')}")
```

---

## 7. 相关文档

| 文档 | 说明 |
|------|------|
| `observability-transparency-design-2026-03-28.md` | 完整设计方案 |
| `tmux-integration-guide.md` | tmux 接入指南 |
| `observability-batch1-completion-report.md` | Batch 1 完成报告 |
| `observability-batch2-completion-report.md` | Batch 2 完成报告 |
| `observability-batch3-completion-report.md` | Batch 3 完成报告 |
| `README.md` (主仓库) | 快速开始章节 |

---

## 8. 附录：命令速查

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

# backend 推荐
python3 -c "from backend_selector import recommend_backend; rec = recommend_backend('任务描述'); print(f'推荐：{rec.backend}, 理由：{rec.reason}')"
```

---

## 9. 给未来自己的提醒

如果你（未来的 Zoe）忘记了这套系统怎么用：

1. **看这个文档的第 0 节**（快速开始）
2. **运行命令速查里的命令**
3. **查看 `docs/observability-transparency-design-2026-03-28.md`** 了解设计初衷

**核心原则**:
- observability 层只读，不写 truth plane
- 状态卡从 truth plane 同步，不双写
- 轻量级 JSON/JSONL 存储，无重型依赖

**不要做的事**:
- ❌ 不要用 tmux 替代 canonical truth
- ❌ 不要为了可视化破坏 callback/gate 真值
- ❌ 不要双写状态（truth + observability）

---

**最后更新**: 2026-03-28  
**维护者**: Zoe (CTO & Chief Orchestrator)
