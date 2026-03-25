# runtime/

本目录是本仓的 **orchestration 实现真值层**。

## 包含内容
- `orchestrator/`：核心编排逻辑
- `scripts/`：入口命令与 callback / dispatch bridge
- `skills/`：runtime 侧技能入口（当前主要是 `orchestration-entry`）

## 边界
- `docs/` 负责阅读入口、CURRENT_TRUTH、计划与边界说明
- `runtime/` 负责真实实现
- `tests/` 负责针对 `runtime/` 的验收

## 运行时产物边界

**不应提交到 repo 的文件**：
- `runtime/*.db` / `runtime/*.sqlite` / `runtime/*.sqlite3` — 运行时数据库文件
- `*.pid` — 进程 ID 文件
- `*.lock` — 锁文件

**可以保留在 repo 的文件**：
- `docs/reports/*.md` — 测试报告、验证报告、健康报告等文档性产物

**规则**：运行时产生的临时状态文件不应入仓；有文档价值的报告/总结应保留在 `docs/reports/`。

## 当前口径
- 本目录已从 OpenClaw workspace 中最小导入 orchestration 相关实现子树
- 不包含人格/记忆/runtime 数据/无关 skills/trading 杂项
- 当前整体成熟度仍是 **thin bridge / allowlist / safe semi-auto**，不是默认全自动闭环

## Subagent Cleanup 语义（2026-03-25）

### 两层清理区分

**1. Execution Resource Release**（已有）：
- semaphore release
- active count decrement  
- memory cache cleanup

**2. Session/Process Cleanup**（本批新增）：
- timeout 时：kill process / process group（SIGTERM）
- cancel 时：kill process / process group
- terminal 后：session cleanup hook / cleanup status 字段

### CleanupStatus 状态机

```
pending → process_killed → (end)
        → session_cleaned → (end)
        → ui_cleanup_unknown → (end)
        → cleanup_failed → (end)
```

- `process_killed`: 进程组已杀死（主动 cleanup）
- `session_cleaned`: 进程自然结束/已清理
- `ui_cleanup_unknown`: **显式建模**：UI/网页可能残留，不假装已清完
- `cleanup_failed`: 清理失败（记录错误原因）

### 为什么 Claude Code 页面还会残留？

**原因**：
1. SubagentExecutor 只能控制进程级 cleanup（kill process group）
2. Claude Code 打开的网页是独立进程（浏览器），不在 subagent 进程组内
3. 当前显式建模为 `ui_cleanup_unknown`，不假装已清完

**已做到的**：
- ✅ 进程级 cleanup 强保证（kill process group）
- ✅ 状态建模清楚（`ui_cleanup: "unknown"`）
- ✅ 测试覆盖（completed / timed_out / failed / cancelled cleanup）

**未做到的**（需后续批次）：
- ❌ 自动关闭浏览器标签页（需要浏览器自动化集成）
- ❌ 清理 Claude Code 打开的所有 UI 资源

### 使用示例

```python
from subagent_executor import SubagentExecutor, SubagentConfig

executor = SubagentExecutor(
    config=SubagentConfig(
        label="coding-task",
        runtime="subagent",
        timeout_seconds=900,
    ),
    cwd="<REPO_ROOT>/../../..",  # Or use Path.home() / ".openclaw/workspace"
)

# 启动任务
task_id = executor.execute_async("实现 XXX 功能")

# 获取结果（自动检测超时 + cleanup）
result = executor.get_result(task_id)

# 手动取消（kill process group）
executor.cancel(task_id)

# 清理已完成任务
executor.cleanup(task_id, kill_process=True)

# 强制清理（无论状态）
result = executor.force_cleanup(task_id)
print(result["cleanup_status"])  # process_killed / session_cleaned / ui_cleanup_unknown
```
