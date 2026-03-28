# Observability Batch 3 完成报告

> **日期**: 2026-03-28  
> **批次**: Batch 3 - tmux 统一状态索引  
> **状态**: ✅ 完成  
> **提交**: `11192ad`

---

## 执行摘要

### 任务目标
实现 Observability Batch 3 - tmux 统一状态索引，将 tmux session 状态纳入 observability 统一索引。

### 完成内容

#### 阶段 A：核心模块实现 ✅
- **tmux_status_sync.py**: tmux 状态同步模块 (558 行)
  - `TmuxStatusSync` 类：状态同步器
  - `TmuxSessionState` 数据类：session 状态表示
  - `TMUX_STATUS_MAP`: tmux 状态到统一状态映射
  - 支持 local 和 ssh 远程 tmux session

#### 阶段 B：脚本集成 ✅
- **start-tmux-task.sh**: 启动时自动注册任务到 observability 索引
- **status-tmux-task.sh**: 支持 `--sync-status` 参数同步状态
- **sync-tmux-observability.py**: CLI 工具 (267 行)
  - `register`: 注册新任务
  - `update`: 更新状态
  - `status`: 查询状态
  - `list`: 列出活跃 session
  - `sync`: 同步 (register + update)

#### 阶段 C：测试验证 ✅
- **test_tmux_status_sync.py**: 33 个单元测试，100% 通过
  - `TestTmuxSessionState`: 2 个测试
  - `TestTmuxStatusMap`: 4 个测试
  - `TestTmuxStatusSync`: 13 个测试
  - `TestTmuxStatusSyncCardIntegration`: 4 个测试
  - `TestConvenienceFunctions`: 3 个测试
  - `TestTmuxStatusSyncSSH`: 3 个测试
  - `TestTmuxStatusSyncEdgeCases`: 4 个测试
  - `TestTmuxStatusSyncIntegration`: 1 个完整工作流测试

- **verify-observability-batch3.sh**: 18 项验证检查，100% 通过

---

## 交付物清单

### 1. 核心模块
| 文件 | 行数 | 说明 |
|------|------|------|
| `runtime/orchestrator/tmux_status_sync.py` | 558 | tmux 状态同步核心模块 |
| `runtime/tests/orchestrator/observability/test_tmux_status_sync.py` | 634 | 33 个单元测试 |

### 2. CLI 工具
| 文件 | 行数 | 说明 |
|------|------|------|
| `scripts/sync-tmux-observability.py` | 267 | Python CLI 工具 |
| `scripts/verify-observability-batch3.sh` | 230 | 验证脚本 |

### 3. 脚本集成修改
| 文件 | 修改内容 |
|------|---------|
| `skills/claude-code-orchestrator/scripts/start-tmux-task.sh` | +40 行：启动时自动注册 |
| `skills/claude-code-orchestrator/scripts/status-tmux-task.sh` | +35 行：支持状态同步 |

---

## 测试结果

### 单元测试 (pytest)
```
============================= test session starts ==============================
collected 33 items

runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxSessionState::test_create_state PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxSessionState::test_to_dict PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusMap::test_running_mapping PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusMap::test_completion_mapping PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusMap::test_failure_mapping PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusMap::test_stuck_mapping PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_init PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_session_dead_no_report PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_session_dead_with_report PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_report_exists PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_running PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_idle PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_get_status_stuck PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_classify_pane_status_completion PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_classify_pane_status_error PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_classify_pane_status_execution PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_classify_pane_status_idle PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSync::test_classify_pane_status_default PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncCardIntegration::test_register_tmux_card PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncCardIntegration::test_sync_to_card_existing PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncCardIntegration::test_sync_to_card_not_exists_no_force PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncCardIntegration::test_list_active_sessions PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestConvenienceFunctions::test_register_tmux_card_function PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestConvenienceFunctions::test_get_tmux_status_function PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestConvenienceFunctions::test_list_tmux_cards_function PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncSSH::test_get_status_ssh_target PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncSSH::test_check_session_alive_ssh PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncSSH::test_check_remote_files_exist PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncEdgeCases::test_session_name_with_cc_prefix PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncEdgeCases::test_session_name_without_cc_prefix PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncEdgeCases::test_timeout_handling PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncEdgeCases::test_capture_pane_output_timeout PASSED
runtime/tests/orchestrator/observability/test_tmux_status_sync.py::TestTmuxStatusSyncIntegration::test_full_workflow PASSED

============================== 33 passed in 0.08s ==============================
```

### 验证脚本
```
==============================================
Verification Summary
==============================================
Tests Passed: 18
Tests Failed: 0

✅ Batch 3 Verification PASSED
```

---

## 核心功能验证

### 1. tmux 状态映射
```python
TMUX_STATUS_MAP = {
    "running": "running",
    "idle": "idle",
    "likely_done": "completed",
    "done_session_ended": "completed",
    "stuck": "running",  # stuck 仍视为 running 但需要告警
    "dead": "failed",
    "input_pending": "dispatch",
    "submitted_scrollback": "running",
    "input_cleared": "running",
    "report_ready": "completed",
}
```

### 2. 注册新任务
```bash
python scripts/sync-tmux-observability.py register \
  --task-id task_001 \
  --label feature-xxx \
  --owner main \
  --scenario custom \
  --promised-eta 2026-03-28T18:00:00

# 输出:
{
  "success": true,
  "action": "register",
  "card": {
    "task_id": "task_001",
    "executor": "tmux",
    "stage": "dispatch",
    "promise_anchor": {
      "anchor_type": "tmux_session",
      "anchor_value": "cc-feature-xxx"
    },
    ...
  }
}
```

### 3. 更新状态
```bash
python scripts/sync-tmux-observability.py update \
  --task-id task_001 \
  --session cc-feature-xxx

# 输出:
{
  "success": true,
  "action": "update",
  "card": {
    "task_id": "task_001",
    "stage": "running",
    "metadata": {
      "tmux_status": "running",
      "tmux_session_alive": true
    },
    ...
  }
}
```

### 4. 查询状态
```bash
python scripts/sync-tmux-observability.py status \
  --session cc-feature-xxx

# 输出:
{
  "success": true,
  "action": "status",
  "state": {
    "session": "cc-feature-xxx",
    "status": "running",
    "mapped_stage": "running",
    "report_exists": false,
    "session_alive": true,
    ...
  }
}
```

### 5. 列出活跃 session
```bash
python scripts/sync-tmux-observability.py list --owner main

# 输出:
{
  "success": true,
  "action": "list",
  "count": 3,
  "sessions": [
    {
      "task_id": "task_001",
      "session": "cc-feature-xxx",
      "state": {"status": "running", ...},
      "card_stage": "running"
    },
    ...
  ]
}
```

### 6. start-tmux-task.sh 自动注册
```bash
bash start-tmux-task.sh \
  --label feature-xxx \
  --workdir /path/to/repo \
  --prompt-file /tmp/task.md \
  --task "Implement feature XXX"

# 自动后台执行:
# 1. 生成 task_id: tmux_feature_xxx_<timestamp>
# 2. 注册到 observability 索引
# 3. 5 秒后更新状态为 running
# 4. 输出 TASK_ID 用于后续追踪
```

### 7. status-tmux-task.sh 状态同步
```bash
bash status-tmux-task.sh \
  --label feature-xxx \
  --sync-status

# 自动同步状态到 observability 索引
```

---

## 架构设计

### 1. 状态同步流程
```
start-tmux-task.sh
  ↓ (后台)
sync-tmux-observability.py register
  ↓
tmux_status_sync.py::register_task()
  ↓
observability_card.py::create_card()
  ↓
~/.openclaw/shared-context/observability/cards/{task_id}.json

# 5 秒后自动更新状态
sync-tmux-observability.py update
  ↓
tmux_status_sync.py::sync_to_card()
  ↓
observability_card.py::update_card()
```

### 2. 状态检测逻辑
```
get_status(session)
  ├─ _check_session_alive() → session_alive
  ├─ _check_remote_files_exist() → report_exists
  │
  ├─ if not session_alive:
  │   ├─ if report_exists: status = "done_session_ended"
  │   └─ else: status = "dead"
  │
  ├─ if report_exists: status = "likely_done"
  │
  └─ else:
      ├─ _capture_pane_output() → pane
      └─ _classify_pane_status(pane) → status
```

### 3. Pane 输出分类
```python
def _classify_pane_status(pane_output):
    # 完成信号
    if "REPORT_JSON=" or "Task Completed" in pane:
        return "likely_done"
    
    # 错误信号
    if "✗" or "Error:" or "FAILED" in pane:
        return "stuck"
    
    # 执行信号
    if "Thinking" or "Running" or "Bash(" in pane:
        return "running"
    
    # 空闲信号
    if "❯" in pane:
        return "idle"
    
    return "running"  # 默认
```

---

## 集成点说明

### start-tmux-task.sh 集成
```bash
# ========== Observability Batch 3: Auto-register tmux session to index ==========
TASK_ID="tmux_${LABEL}_$(date +%s)"
PROMISED_ETA="$(date -v+2H +%Y-%m-%dT%H:%M:%S)"
OBSERVABILITY_OWNER="${NAMESPACE:-main}"

# Register to observability index (non-blocking, audit-only)
if [[ -f "$SYNC_SCRIPT" ]]; then
  (python3 "$SYNC_SCRIPT" register \
    --task-id "$TASK_ID" \
    --label "$LABEL" \
    --owner "$OBSERVABILITY_OWNER" \
    --scenario "custom" \
    --promised-eta "$PROMISED_ETA" \
    --socket "$SOCKET" \
    --target "$TARGET" \
    ${SSH_HOST:+--ssh-host "$SSH_HOST"} \
    >/dev/null 2>&1 || true) &
fi

# Update status to running (non-blocking)
if [[ -f "$SYNC_SCRIPT" ]]; then
  (sleep 5 && python3 "$SYNC_SCRIPT" update \
    --task-id "$TASK_ID" \
    --session "$SESSION" \
    --socket "$SOCKET" \
    --target "$TARGET" \
    ${SSH_HOST:+--ssh-host "$SSH_HOST"} \
    >/dev/null 2>&1 || true) &
fi
# ========== End Batch 3 Integration ==========
```

### status-tmux-task.sh 集成
```bash
# ========== Observability Batch 3: Sync status if requested ==========
if [[ "$SYNC_STATUS" == true && -n "$TASK_ID" && -f "$SYNC_SCRIPT" ]]; then
  STATUS_VAR="$(echo "$STATUS" | sed 's/done_session_ended/completed/; s/likely_done/completed/')"
  
  # Update observability card (non-blocking)
  (python3 "$SYNC_SCRIPT" update \
    --task-id "$TASK_ID" \
    --session "$SESSION" \
    --socket "$SOCKET" \
    --target "$TARGET" \
    ${SSH_HOST:+--ssh-host "$SSH_HOST"} \
    >/dev/null 2>&1 || true) &
fi
# ========== End Batch 3 Status Sync ==========
```

---

## 质量门验收

| 质量门 | 验收结果 | 证据 |
|--------|---------|------|
| tmux session 自动注册到索引 | ✅ | 测试 `test_register_tmux_card` |
| 状态变更自动同步 | ✅ | 测试 `test_sync_to_card_existing`, `test_full_workflow` |
| 不破坏现有真值链 | ✅ | audit-only 模式，不写 truth plane |
| 单元测试覆盖率 | ✅ | 33 个测试，100% 通过 |
| 验证脚本检查 | ✅ | 18 项检查，100% 通过 |
| CLI 工具可用 | ✅ | 5 个命令 (register/update/status/list/sync) |
| SSH 远程支持 | ✅ | 测试 `test_check_session_alive_ssh` |
| 超时处理 | ✅ | 测试 `test_timeout_handling` |

---

## 风险与回退

### 风险缓解
| 风险 | 缓解措施 |
|------|---------|
| 同步脚本执行失败 | 后台执行 + `|| true`，不阻塞主流程 |
| tmux socket 不可用 | 超时处理 (5 秒)，返回安全默认值 |
| SSH 连接失败 | BatchMode=yes，快速失败 |
| 观测目录权限问题 | `_ensure_dirs()` 自动创建 |

### 回退方案
如需回退：
```bash
# 1. 删除核心模块
rm runtime/orchestrator/tmux_status_sync.py
rm runtime/tests/orchestrator/observability/test_tmux_status_sync.py
rm scripts/sync-tmux-observability.py
rm scripts/verify-observability-batch3.sh

# 2. 回滚脚本修改
git checkout skills/claude-code-orchestrator/scripts/start-tmux-task.sh
git checkout skills/claude-code-orchestrator/scripts/status-tmux-task.sh

# 3. 删除观测数据 (可选)
rm -rf ~/.openclaw/shared-context/observability/cards/
rm -rf ~/.openclaw/shared-context/observability/index/

# 4. Git 回滚
git revert 11192ad
```

---

## 使用指南

### 快速开始
```bash
# 1. 注册新任务
python scripts/sync-tmux-observability.py register \
  --task-id my_task \
  --label my-feature \
  --owner main \
  --scenario custom \
  --promised-eta 2026-03-28T18:00:00

# 2. 查询状态
python scripts/sync-tmux-observability.py status \
  --session cc-my-feature

# 3. 更新状态
python scripts/sync-tmux-observability.py update \
  --task-id my_task \
  --session cc-my-feature

# 4. 列出所有活跃 session
python scripts/sync-tmux-observability.py list --owner main
```

### 自动化集成
```bash
# 在 start-tmux-task.sh 中自动注册
bash start-tmux-task.sh \
  --label feature-xxx \
  --workdir /path/to/repo \
  --prompt-file /tmp/task.md \
  --task "Implement XXX"

# 输出包含 TASK_ID
# TASK_ID=tmux_feature_xxx_1711616400

# 后续可用 TASK_ID 追踪状态
bash status-tmux-task.sh \
  --label feature-xxx \
  --task-id tmux_feature_xxx_1711616400 \
  --sync-status
```

### Python API
```python
from tmux_status_sync import (
    TmuxStatusSync,
    get_tmux_status,
    register_tmux_card,
    sync_tmux_session,
    list_tmux_cards,
)

# 注册任务
card = register_tmux_card(
    task_id="task_001",
    label="feature-xxx",
    owner="main",
    scenario="custom",
    promised_eta="2026-03-28T18:00:00",
)

# 同步状态
updated = sync_tmux_session(
    task_id="task_001",
    session="cc-feature-xxx",
)

# 获取状态
state = get_tmux_status(session="cc-feature-xxx")
print(f"Status: {state.status} -> {state.mapped_stage}")

# 列出活跃 session
sessions = list_tmux_cards(owner="main", limit=10)
```

---

## 后续批次

### Batch 4: 可视化看板（可选）
- Web 看板或 TUI 看板
- 实时显示所有任务状态
- 支持过滤/排序/搜索

---

## 结论

**Batch 3 目标已达成**:
- ✅ 核心模块实现 (`tmux_status_sync.py`, 558 行)
- ✅ CLI 工具实现 (`sync-tmux-observability.py`, 267 行)
- ✅ 脚本集成完成 (start-tmux-task.sh, status-tmux-task.sh)
- ✅ 测试覆盖完成 (33 个单元测试，100% 通过)
- ✅ 验证脚本完成 (18 项检查，100% 通过)
- ✅ Git 提交完成 (`11192ad`, 已 push 到 origin/main)

**核心能力**:
1. tmux session 自动注册到 observability 索引
2. 状态变更自动同步 (running/idle/likely_done/stuck/dead)
3. 支持 local 和 ssh 远程 tmux session
4. 状态卡支持 `executor="tmux"` 类型
5. audit-only 模式，不破坏现有真值链

**下一步**:
- 实现 Batch 4 (可视化看板，可选)
- 根据使用情况优化状态检测逻辑
- 增加告警功能 (超时/卡住检测)

---

## 附录：文件清单

```
runtime/orchestrator/
  └── tmux_status_sync.py (558 行)
runtime/tests/orchestrator/observability/
  └── test_tmux_status_sync.py (634 行)
scripts/
  ├── sync-tmux-observability.py (267 行)
  └── verify-observability-batch3.sh (230 行)
skills/claude-code-orchestrator/scripts/
  ├── start-tmux-task.sh (+40 行修改)
  └── status-tmux-task.sh (+35 行修改)
```

**总计**: 6 个文件，1764 行新增代码/文档
