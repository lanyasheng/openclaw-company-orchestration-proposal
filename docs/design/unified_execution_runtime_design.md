# Unified Execution Runtime Design

**Version:** P0-3 Batch 8 (2026-03-30)  
**Status:** Implementation in progress  
**Author:** Zoe (CTO & Chief Orchestrator)

---

## 1. Overview

### 1.1 Problem Statement

当前 tmux / subagent 接入需要多步工程化流程：
- tmux: `start` → `register` → `sync` → `wake` / `callback`
- subagent: `sessions_spawn` → `runner` → `callback`

用户反馈：**太工程化**，需要收成单入口体验。

### 1.2 Goal

实现统一执行入口（Unified Execution Runtime），提供：
- **单接口**：`run_task(...)` Python API + 可选 CLI
- **自动 backend 选择**：显式 `backend_preference` 优先，否则调用 `backend_selector`
- **tmux 自动化**：自动完成 start + observability register + 初始 sync + callback/wake 接线
- **subagent 兼容**：保持现有 subagent 路径不受影响
- **向后兼容**：旧接口保留，统一入口作为推荐主入口

---

## 2. Scope

### 2.1 In Scope

1. **统一执行入口模块**：`runtime/orchestrator/unified_execution_runtime.py`
2. **CLI 入口**：`runtime/orchestrator/run_task.py`（最小可用）
3. **测试覆盖**：
   - 显式指定 subagent / tmux
   - 未指定时自动推荐
   - tmux 路径自动注册 observability
   - tmux 路径返回 callback/wake 接线信息
   - subagent 路径不受影响
4. **文档更新**：README / QUICKSTART 最小更新

### 2.2 Out of Scope

1. **删除旧路径**：现有 `auto_dispatch.py`、`subagent_executor.py`、`tmux_terminal_receipts.py` 保留
2. **重构现有 backend 逻辑**：`continuation_backends.py`、`backend_selector.py` 保持向后兼容
3. **Dashboard 变更**：Dashboard 继续支持现有 dispatch artifact 格式

---

## 3. Architecture

### 3.1 High-Level Design

```
┌─────────────────────────────────────────────────────────────┐
│                   Unified Execution Runtime                  │
│                  (unified_execution_runtime.py)              │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  run_task(task_context: Dict) → ExecutionResult              │
│    │                                                          │
│    ├─ 1. Read task context / orchestration contract          │
│    │                                                          │
│    ├─ 2. Decide backend:                                     │
│    │     ├─ if backend_preference explicit → use it          │
│    │     └─ else → backend_selector.recommend()              │
│    │                                                          │
│    ├─ 3. Execute based on backend:                           │
│    │     ├─ subagent:                                        │
│    │     │     └─ SubagentExecutor.execute_async()           │
│    │     │           → runner → callback                     │
│    │     │                                                   │
│    │     └─ tmux:                                            │
│    │           ├─ start-tmux-task.sh (auto start)            │
│    │           ├─ sync-tmux-observability.py (auto register) │
│    │           ├─ initial status sync                        │
│    │           └─ callback/wake wiring info                  │
│    │                                                          │
│    └─ 4. Return ExecutionResult with:                        │
│          - task_id / dispatch_id                             │
│          - backend / session_id / label                      │
│          - callback_path / wake_command                      │
│          - status / artifacts                                │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

```
Task Context
    │
    ▼
┌──────────────────────┐
│  UnifiedExecution    │
│     Runtime          │
└──────────────────────┘
    │
    ├─ backend_preference? ──► Use explicit
    │
    └─ No preference ──► backend_selector.recommend()
                              │
                              ▼
                       BackendRecommendation
                              │
                              ▼
    ┌─────────────────────────┴─────────────────────────┐
    │                                                   │
    ▼                                                   ▼
┌─────────────┐                                 ┌─────────────┐
│  Subagent   │                                 │    Tmux     │
│   Path      │                                 │    Path     │
└─────────────┘                                 └─────────────┘
    │                                                   │
    │ SubagentExecutor                                  │ start-tmux-task.sh
    │ sessions_spawn(runtime="subagent")                │ sync-tmux-observability.py
    │ runner → status.json                              │ tmux session (cc-{label})
    │ callback → canonical_callback                     │ completion report → callback
    │                                                   │
    ▼                                                   ▼
┌─────────────────────────────────────────────────────────────┐
│                  ExecutionResult (unified schema)            │
├─────────────────────────────────────────────────────────────┤
│ - task_id: str                                              │
│ - dispatch_id: str                                          │
│ - backend: "subagent" | "tmux"                              │
│ - session_id: str                                           │
│ - label: str                                                │
│ - status: "pending" | "running" | "completed" | "failed"    │
│ - callback_path: Optional[Path]                             │
│ - wake_command: Optional[str]                               │
│ - artifacts: Dict[str, Path]                                │
│ - metadata: Dict[str, Any]                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. API Design

### 4.1 Python API

```python
from unified_execution_runtime import (
    UnifiedExecutionRuntime,
    ExecutionResult,
    TaskContext,
)

# 最小用法
runtime = UnifiedExecutionRuntime()
result = runtime.run_task(
    task_description="重构认证模块，预计 1 小时",
    workdir="/Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal",
)

# 显式指定 backend
result = runtime.run_task(
    task_description="写 README 文档",
    backend_preference="subagent",
    workdir="...",
)

# 完整用法
context = TaskContext(
    task_description="重构认证模块",
    estimated_duration_minutes=60,
    task_type="coding",
    requires_monitoring=True,
    backend_preference=None,  # None = auto recommend
    workdir=Path("..."),
    metadata={
        "scenario": "trading_roundtable_phase1",
        "owner": "trading",
    },
)
result = runtime.run_task(context)

# 访问结果
print(f"Task ID: {result.task_id}")
print(f"Backend: {result.backend}")
print(f"Session: {result.session_id}")
print(f"Status: {result.status}")
print(f"Callback: {result.callback_path}")
print(f"Wake: {result.wake_command}")
```

### 4.2 CLI Entry (Minimal)

```bash
# 自动推荐 backend
python3 runtime/orchestrator/run_task.py \
  --task "重构认证模块，预计 1 小时" \
  --workdir /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

# 显式指定 backend
python3 runtime/orchestrator/run_task.py \
  --task "写 README 文档" \
  --backend subagent \
  --workdir ...

# JSON 输出（便于脚本消费）
python3 runtime/orchestrator/run_task.py \
  --task "..." \
  --output json \
  --workdir ...
```

---

## 5. Implementation Details

### 5.1 Backend Decision Logic

```python
def decide_backend(
    task_description: str,
    backend_preference: Optional[str],
    estimated_duration_minutes: Optional[int],
    task_type: Optional[str],
    requires_monitoring: Optional[bool],
) -> Tuple[str, BackendRecommendation]:
    """
    Decide backend with explicit preference priority.
    
    Returns:
        (applied_backend, recommendation)
    """
    if backend_preference:
        # Explicit override
        rec = BackendRecommendation(
            backend=backend_preference,
            confidence=1.0,
            reason="用户明确指定",
            factors={"user_preference": backend_preference},
        )
        return backend_preference, rec
    
    # Auto recommend
    rec = recommend_backend(
        task_description=task_description,
        estimated_duration_minutes=estimated_duration_minutes,
        task_type=task_type,
        requires_monitoring=requires_monitoring,
    )
    return rec.backend, rec
```

### 5.2 Tmux Path Automation

```python
def execute_tmux_task(
    task_description: str,
    workdir: Path,
    label: str,
    dispatch_id: str,
) -> ExecutionResult:
    """
    Execute tmux task with full automation:
    1. start-tmux-task.sh
    2. sync-tmux-observability.py
    3. Initial status sync
    4. Return callback/wake wiring info
    """
    session = f"cc-{label}"
    
    # 1. Start tmux session
    start_cmd = [
        str(TMUX_START_SCRIPT),
        "--label", label,
        "--workdir", str(workdir),
        "--task", task_description,
        "--lint-cmd", "",
        "--build-cmd", "",
    ]
    subprocess.run(start_cmd, check=True)
    
    # 2. Register observability (sync-tmux-observability.py)
    sync_cmd = [
        "python3", str(SYNC_OBSERVABILITY_SCRIPT),
        "--label", label,
        "--dispatch-id", dispatch_id,
    ]
    subprocess.run(sync_cmd, check=True)
    
    # 3. Initial status sync
    status_cmd = [str(TMUX_STATUS_SCRIPT), "--label", label]
    status_output = subprocess.run(status_cmd, capture_output=True, text=True)
    
    # 4. Build result with callback/wake wiring
    callback_path = Path("/tmp") / f"{session}-completion-report.json"
    wake_command = f"bash ~/.openclaw/skills/claude-code-orchestrator/scripts/wake.sh --label {label}"
    
    return ExecutionResult(
        task_id=dispatch_id,
        backend="tmux",
        session_id=session,
        label=label,
        status="running",
        callback_path=callback_path,
        wake_command=wake_command,
        artifacts={
            "report_json": callback_path,
            "report_md": callback_path.with_suffix(".md"),
        },
        metadata={
            "tmux_status_script": str(TMUX_STATUS_SCRIPT),
            "tmux_monitor_script": str(TMUX_MONITOR_SCRIPT),
        },
    )
```

### 5.3 Subagent Path (Passthrough)

```python
def execute_subagent_task(
    task_description: str,
    workdir: Path,
    label: str,
    dispatch_id: str,
    timeout_seconds: int = 1800,
) -> ExecutionResult:
    """
    Execute subagent task via SubagentExecutor.
    Preserves existing subagent path.
    """
    from subagent_executor import SubagentExecutor, SubagentConfig
    
    config = SubagentConfig(
        label=label,
        runtime="subagent",
        timeout_seconds=timeout_seconds,
        cwd=str(workdir),
    )
    
    executor = SubagentExecutor(config=config, cwd=str(workdir))
    task_id = executor.execute_async(task_description)
    
    # Get initial status
    result = executor.get_status(task_id)
    
    callback_path = Path.home() / ".openclaw" / "shared-context" / "dispatches" / f"{dispatch_id}-callback.json"
    
    return ExecutionResult(
        task_id=task_id,
        dispatch_id=dispatch_id,
        backend="subagent",
        session_id=f"subagent-{label}",
        label=label,
        status=result.status,
        callback_path=callback_path,
        wake_command=None,  # subagent uses callback, not wake
        artifacts={
            "status_json": result.status_path,
            "final_summary": result.summary_path,
        },
        metadata={
            "pid": result.pid,
            "runner_label": label,
        },
    )
```

---

## 6. Risk Assessment

### 6.1 Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 破坏现有真值链 | High | Low | 保留旧路径，统一入口作为新层 |
| tmux observability 注册失败 | Medium | Medium | 详细日志 + 回退到手动注册 |
| callback/wake 接线错误 | High | Low | 测试覆盖 + 明确文档 |
| Backend 选择逻辑错误 | Medium | Low | 单元测试 + 显式 preference 优先 |

### 6.2 Rollback Plan

1. **Git revert**: `git revert <commit-hash>`
2. **Fallback to old path**: 旧接口保留，可手动调用
3. **Disable unified runtime**: 环境变量 `USE_UNIFIED_RUNTIME=0`

---

## 7. Testing Strategy

### 7.1 Unit Tests

- `test_unified_execution_runtime.py`:
  - ✅ 显式指定 subagent
  - ✅ 显式指定 tmux
  - ✅ 未指定时自动推荐
  - ✅ backend_selection metadata 正确记录

### 7.2 Integration Tests

- `test_tmux_observability_auto_register.py`:
  - ✅ tmux 路径自动注册 observability
  - ✅ observability card 正确生成
- `test_callback_wake_wiring.py`:
  - ✅ tmux 路径返回 callback/wake 接线信息
  - ✅ subagent 路径不受影响

### 7.3 E2E Tests

- `test_e2e_unified_runtime.py`:
  - ✅ 完整 run_task 流程（subagent）
  - ✅ 完整 run_task 流程（tmux，mock start）

---

## 8. Documentation Updates

### 8.1 README.md

添加章节：
```markdown
## Unified Execution Runtime

单入口执行任务：

```python
from unified_execution_runtime import UnifiedExecutionRuntime

runtime = UnifiedExecutionRuntime()
result = runtime.run_task(
    task_description="任务描述",
    workdir="/path/to/workdir",
)
```

### 8.2 QUICKSTART

添加快速开始示例。

---

## 9. Success Criteria

- ✅ 统一执行入口实现
- ✅ Python API + CLI 可用
- ✅ 测试覆盖所有要求场景
- ✅ 文档更新
- ✅ 提交并 push 到 origin/main
- ✅ 不破坏现有真值链
- ✅ 旧接口保留兼容

---

## 10. Timeline

- Design: 2026-03-30 14:53
- Implementation: 2026-03-30 15:00-17:00
- Testing: 2026-03-30 17:00-18:00
- Documentation: 2026-03-30 18:00-18:30
- Push to main: 2026-03-30 18:30

---

**Last Updated:** 2026-03-30 14:53  
**Maintainer:** Zoe (CTO & Chief Orchestrator)
