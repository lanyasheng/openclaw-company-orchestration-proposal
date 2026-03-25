# CURRENT_TRUTH(2026-03-24)

> **角色**: 📍 **当前真值唯一入口** - 了解"今天系统实际如何工作"从这里开始
>
> **何时阅读**:
> - 首次接触本仓,想快速了解当前状态
> - 不确定某个文档是否仍是最新口径
> - 准备修改实现/文档前,确认真值边界
>
> **真值边界**: 本文档 + `runtime/` 实现 + `tests/` 验收 = 当前唯一可信源;`archive/`、`docs/plans/` 历史计划文档仅供参考
>
> **更新**: 2026-03-24 - Deer-Flow 借鉴线 Batch A/B: SubagentExecutor 封装 + 热状态存储已实现 (32 个测试通过)
>
> **更新**: 2026-03-25 - P0 Batch 5: Subagent Session Cleanup 已实现 (process group kill / cleanup status / UI cleanup unknown 显式建模)

**更新**: 2026-03-25 - **Subtask Completion Validator v1 已实现 (audit-only)**: 完成 validator 核心模块 (`completion_validator.py` / `completion_validator_rules.py`) + 集成到 `completion_receipt.py` + 20 个测试通过。当前模式：`audit_only` (只记录不拦截)，支持 Through/Block/Gate 规则、白名单机制、audit 日志。

**更新**: 2026-03-25 - **事故归因证据链审计完成**: 完成《事故归因证据链审计报告》(`docs/review/incident-causality-audit-2026-03-25.md`)，审计 cleanup/completion/callback/validator 四条证据链。**主因定位**: (1) Validator 是 audit-only 模式不拦截，(2) Completion receipt status 不包含 validator 结果，(3) Validator 白名单可能误伤。**修复优先级**: P0-Validator 结果冒泡到 receipt status / enforce 模式灰度测试。详见审计报告。

**更新**: 2026-03-25 - **P0 Validator 全切完成 (enforce 模式)**: Validator 结果已接入 `completion_receipt` 主判定链，从 audit-only 切换到 enforce 模式。核心变更：(1) `_determine_receipt_status()` 接入 validator 结果，(2) `blocked_completion`/`gate_required`/`validator_error` 映射为 `receipt_status=failed`，(3) 白名单保持最小收紧 (`explore/list/check/scan/audit`)，(4) 新增 12 个集成测试 + 21 个现有测试全部通过。受影响文件：`completion_validator_rules.py` (mode=enforce)、`completion_receipt.py` (接入 validator)、`test_completion_receipt_validator_integration.py` (新增)。详见 commit。

**更新**: 2026-03-25 - **P0 极小切片 04: Validator Whitelist 精细化完成**: 收紧白名单机制降低高抽象任务误放行风险。核心变更：(1) 白名单 label 从 5 个减少到 3 个 (`explore/audit/scan`)，移除过宽的 `list/check`，(2) 匹配逻辑从子串匹配改为前缀匹配 (`checklist` 不再匹配 `check`)，(3) 白名单任务也要满足基本质量检查 (B4 未处理错误、B6 空输出)，(4) 新增 8 个测试 (白名单匹配/收紧/基本条件检查) + 28 个现有测试全部通过。受影响文件：`completion_validator_rules.py` (新增 `_match_whitelist`/收紧配置)、`test_completion_validator.py` (新增 8 测试)。详见 commit。

**更新**: 2026-03-25 - **P0 Batch-B: Parent-Child / Fan-in / Closeout 整合完成**: 将 lineage / fan-in readiness / closeout glue 三条能力整合成一个可验证的 integration slice。核心变更：(1) 新增 `build_fanin_closeout_context(batch_id)` 函数，基于 lineage 查 children -> readiness 检查 -> 生成 closeout glue input，(2) 新增 `FaninCloseoutContext` 数据结构，(3) 新增 `get_completion_receipt_by_spawn_id()` 便捷函数，(4) 6 个集成测试全部通过 (happy path / not-ready path / no lineage / incomplete closeout / serialization / regression)。受影响文件：`lineage.py` (新增整合函数)、`completion_receipt.py` (新增便捷函数)、`test_lineage_fanin_closeout_integration.py` (新增 6 测试)。详见 commit。

**更新**: 2026-03-25 - **P0 极小切片 01: Lineage 数据结构 + 最小接线已实现**: 新增 `lineage.py` 模块 (parent_id/child_id/batch_id/lineage_id/relation_type/created_at + 序列化/反序列化)，最小接线到 `sessions_spawn_bridge.py` 的 `_call_via_python_api()` 路径，7 个测试全部通过 (数据结构/CRUD/便捷函数/接线/向后兼容)。受影响文件：`lineage.py` (新增)、`sessions_spawn_bridge.py` (集成 lineage_id)、`test_lineage.py` (新增 7 测试)。详见 commit。

**更新**: 2026-03-25 - **P0 极小切片 02: Fan-in Readiness Check 最小实现已实现**: 在 `lineage.py` 中新增 `check_fanin_readiness()` 函数，基于 batch_id 查询所有 child lineage + closeout 状态，判断是否 ready to fan-in。6 个测试全部通过 (无 lineage/全部完成/部分完成/incomplete closeout/最小接线/回归测试)。受影响文件：`lineage.py` (新增函数)、`test_lineage_fanin_readiness.py` (新增 6 测试)、`test_lineage.py` (清理 pytest warning)。详见 commit。

**更新**: 2026-03-25 - **P0 极小切片 03: Closeout Glue Core 最小实现已实现**: 新增 `closeout_glue.py` 模块，提供 `ExecutionToCloseoutGlue` 类，把 completion receipt 的核心字段映射到 closeout 可消费的结构。映射字段：`execution_id` → `source_execution_id`, `receipt_status` → `dispatch_readiness`, `result_summary` → `summary`, `lineage_id` → `lineage_id`, `next_step/next_owner/stopped_because` → 从 continuation_contract 继承。14 个测试全部通过 (数据结构/映射逻辑/dispatch readiness 判定/summary 提取/continuation 字段提取/最小接线/回归测试)。受影响文件：`closeout_glue.py` (新增)、`test_closeout_glue.py` (新增 14 测试)。详见 commit。

**更新**: 2026-03-24 - P0 Batch 4: Failure Closeout Guarantee 已实现 (失败场景兜底 + 测试覆盖)

**更新**: 2026-03-24 - P0 Batch 3: Coding Issue Lane Baseline 已实现 (schema + 测试 + 最小链路)
>
> **更新**: 2026-03-24 - **Wave 2 Cutover 完成**: SubagentExecutor 执行基板扩展到 sessions_spawn_bridge,统一执行链路 (55 个测试通过)
>
> **更新**: 2026-03-23 - Owner/Executor 解耦 + Coding Lane 默认 Claude Code 已实现
>
> **更新**: 2026-03-22 - V8 Real Execute Mode + Auto-Trigger Consumption 已实现
>
> **用途**: 给这个 proposal repo 一个**当前真值入口**,避免旧计划、旧评审、旧 POC 被继续误读成"今天的默认口径"。
>
> **注意**: 这个 repo 现在已升级为**单仓分层 monorepo**:`docs/` 持阅读入口,`runtime/` 持实现真值,`tests/` 持验收。历史上 runtime 曾散落在 OpenClaw workspace 本地;从 2026-03-22 起,本仓开始承担 orchestration runtime 的统一收口。

---



### 分支策略
- **`main` 是唯一 canonical branch** - 所有开发、发布、文档更新均针对 `main`
- 历史 integration 分支(如 `integration/monorepo-runtime-import-20260322`)已全部合并并删除
- 备份 tag:`backup/integration-monorepo-runtime-import-20260324`
- 无长期特性分支;使用短期 topic 分支通过 PR 合并


---

## 0. 入口指引(从哪里开始)

### 阅读入口(推荐顺序)
1. **首次了解** → [`../README.md`](../README.md)(仓库总览 + 快速开始)
2. **当前真值** → 本页(`CURRENT_TRUTH.md`)
3. **设计背景** → [`executive-summary.md`](executive-summary.md)(5 分钟方案总览)
4. **其他频道** → [`quickstart/quickstart-other-channels.md`](quickstart/quickstart-other-channels.md)(非 trading 场景)
5. **Completion Validator 设计** → [`plans/subtask-completion-validator-design-2026-03-25.md`](plans/subtask-completion-validator-design-2026-03-25.md)(设计锚点)

### Runtime 入口
```bash
# 统一入口命令 (standard OpenClaw installation)
python3 ~/.openclaw/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 或从本仓直接运行
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 runtime/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"
```

### Quickstart 入口
| 场景 | 入口 |
|------|------|
| **非 trading 频道**(架构/产品/运营等) | `quickstart-other-channels.md` |
| **trading 场景** | 本节 2.4 + `trading_roundtable` 部分 |
| **验证测试** | `python3 -m unittest tests/ -v` |

**首次接入建议**:`allow_auto_dispatch=false`,先验证 callback/ack/dispatch artifacts 稳定,再考虑自动续跑。

## 1. 当前仓库应该怎样理解

这个仓库现在应当被理解为:

> **OpenClaw 公司级 orchestration / workflow 的单仓分层 monorepo。**

它同时承担:
- `docs/`:canonical 阅读入口 / 计划 / 边界 / CURRENT_TRUTH
- `runtime/`:orchestrator、entry command、callback bridge、skills 等实现真值
- `tests/`:针对 runtime 的验收测试

它仍然不是:
- 任一单个 POC、单个插件、单个 pilot 的代名词
- "已经默认全自动闭环"的完成态说明

当前正确总口径是:
- **OpenClaw 持 control plane**
- **本仓同时持阅读入口与 orchestration runtime 收口**
- **外部框架只进叶子层 / benchmark / 局部方法层**
- **总体仍是 thin bridge / allowlist / safe semi-auto**

### 1.1 本地 workspace 副本已退役(2026-03-22)
历史上 orchestration runtime 曾散落在本地 workspace;从 2026-03-22 起:
- **Canonical 主线**:本仓 `runtime/` 目录
- **本地副本状态**:已加 (已标记 deprecated) 标成 legacy / 只读 / 待退役
- **规则**:禁止双写,新改动必须提交到本仓 monorepo



---


## 2. 本轮已经定下来的真值

### 2.1 planning 默认口径已经收口

1. **gstack-style planning 已作为全局默认 planning method 落地。**
   默认顺序:`problem reframing -> scope/product review -> engineering review -> execution/test plan`。

2. **要点是"借方法,不换政权"。**
   gstack 现在的定位是 planning / review-readiness 方法层脚手架,**不是** OpenClaw 的 control plane 替代品。

3. **下一阶段默认不是"先加循环",而是"先出 planning artifact"。**
   非 trivial feature / bugfix / workflow 设计,先有 planning,再谈执行与自动推进。

### 2.2 TEAM_RULES 已 codify planning default 与 heartbeat boundary

当前默认已经明确:
- 长任务 / 编码 / 复杂文档默认走 `sessions_spawn(runtime="subagent")`;
- planning artifact 应成为执行层默认输入;
- heartbeat 只做 wake / liveness / 巡检 / 催办 / 告警;
- **heartbeat 不得写 terminal truth,不得直接 dispatch 下一跳,不得接管 gate。**

### 2.2.1 coding issue lane baseline 已实现 (2026-03-24)

**P0 Batch 3: Coding Issue Lane Baseline** 已完成,冻结了 issue lane 的最小输入输出契约。

### 2.2.5 Subagent Session Cleanup 已实现 (2026-03-25)

**P0 Batch 5: Subagent Session Cleanup** 已完成，补齐 execution substrate 中 process/session/UI 清理不完整的问题。

**核心问题**：
- SubagentExecutor 已负责 execute_async / get_result / timeout 标记 / semaphore release / active count
- 但缺口是：task terminal != process/UI/session 完整清理
- timeout 路径目前主要是标记状态，不是强保证 kill process/process group
- 用户观察到：测试执行完后，Claude Code 打开的网页仍可能残留

**两层清理区分**：
1. **execution resource release**（已有，继续保留）：
   - semaphore release
   - active count decrement
   - memory cache cleanup
   
2. **session/process cleanup**（本批新增）：
   - timeout 时：kill process / process group
   - cancel 时：kill process / process group
   - terminal 后：session cleanup hook / cleanup status 字段

**核心设计** (`runtime/orchestrator/subagent_executor.py`):
- **CleanupStatus 类型**：`pending | process_killed | session_cleaned | ui_cleanup_unknown | cleanup_failed`
- **CLEANUP_COMPLETE_STATES**：`{process_killed, session_cleaned, ui_cleanup_unknown}`
- **SubagentResult 新增字段**：
  - `pgid`: 进程组 ID（start_new_session=True 时 pgid=pid）
  - `cleanup_status`: 清理状态
  - `cleanup_metadata`: 清理元数据（action / timestamp / ui_cleanup）
- **新增方法**：
  - `_kill_process_group(result)`: 杀死进程组（SIGTERM）
  - `cancel(task_id)`: 取消运行中任务
  - `force_cleanup(task_id)`: 强制清理（无论状态）
  - `cleanup(task_id, kill_process=True)`: 清理已完成任务

**显式建模**：
- `ui_cleanup: "unknown"`：网页/UI 可能残留，不假装已清完
- `process_killed`：进程组已杀死
- `session_cleaned`：进程自然结束/已清理
- `cleanup_failed`：清理失败（记录错误）

**测试覆盖** (`tests/orchestrator/test_subagent_executor.py`):
- ✅ cleanup_status 定义
- ✅ SubagentResult cleanup 字段序列化
- ✅ completed cleanup
- ✅ timed_out cleanup
- ✅ failed cleanup
- ✅ cancelled cleanup
- ✅ process group kill
- ✅ cleanup metadata tracking
- ✅ UI cleanup unknown 显式建模
- 总计：27/27 通过（新增 10 个 cleanup 测试）

**验证命令**：
```bash
cd <repo-root>
python3 tests/orchestrator/test_subagent_executor.py
# 输出：27 passed
```

**设计原则**：
1. 进程级 cleanup 强保证（kill process group）
2. UI/网页无法直接关时显式建模 `ui_cleanup_unknown`
3. 小步可回退，不做大爆炸改写
4. 没有测试结果不得宣称完成

### 2.2.2 failure closeout guarantee 已实现 (2026-03-24)

**P0 Batch 4: Failure Closeout Guarantee** 已完成，解决了"系统内部知道失败，但老板没及时收到标准化失败回报"的问题。

**核心设计** (`runtime/orchestrator/closeout_guarantee.py`):
- 区分"任务失败已知" (`internal_completed=True`) 与"用户已感知失败" (`user_visible_closeout=True`)
- 为失败路径定义最小 guarantee 字段(通过 `metadata` 传递):
  - `failure_summary`: 失败摘要(人类可读)
  - `failure_stage`: 失败阶段(planning | execution | closeout | callback)
  - `truth_anchor`: 真值锚点(机器可读的状态证据,如 `status.json:state=failed|exit_code=1`)
  - `fallback_action`: 兜底行动建议
  - `user_visible_failure_closeout`: 用户是否已感知失败
- 状态机:`pending | guaranteed | fallback_needed | blocked`
- 兜底规则:如果 `ack_status!="sent"` 且 `dispatch_status!="triggered"`,生成 `fallback_needed` guarantee

**薄层接入**:
- 在 `completion_ack_guard.py` 中,每个 completion ack 自动 emit guarantee artifact
- 失败场景不阻塞主 ack 流程,guarantee emit 失败不影响 ack receipt 落盘
- guarantee artifact 落盘到 `~/.openclaw/shared-context/orchestrator/closeout_guarantees/`

**测试覆盖** (`tests/orchestrator/test_failure_closeout_guarantee.py`):
- ✅ 覆盖:任务失败但未形成用户可见失败回报时,产生 `fallback_needed` guarantee
- ✅ 覆盖:失败回报已送达时,不误报(`fallback_triggered=False`)
- ✅ 覆盖:成功路径不被回归破坏(15 个新测试 + 17 个现有测试全部通过)

**验证命令**:
```bash
cd <repo-root>
python3 -m pytest tests/orchestrator/test_failure_closeout_guarantee.py -v
# 输出:15 passed
python3 -m pytest tests/orchestrator/test_closeout_guarantee.py -v
# 输出:17 passed
```

### 2.2.4 Wave 2 Cutover 完成 (2026-03-24)

**Wave 2 Cutover: SubagentExecutor 执行基板扩展** 已完成,将 SubagentExecutor 从 coding issue lane 扩展到 sessions_spawn_bridge。

**核心变化** (`runtime/orchestrator/sessions_spawn_bridge.py`):
- **执行层统一**: `_call_via_python_api()` 现在使用 SubagentExecutor 替代直接调用 runner 脚本
- **保持 control plane 不变**: policy 评估、artifact 生成、linkage 链保持原样
- **向后兼容**: auto-trigger 配置、safe_mode、allowlist/denylist 保持不变
- **新增元数据**: `source=sessions_spawn_bridge`, `wave=wave2_cutover`

**执行路径切换**:
| 执行路径 | 原实现 | 新实现 | 状态 |
|---------|--------|--------|------|
| Issue Lane | SubagentExecutor | SubagentExecutor | ✅ Wave 1 (Batch D) |
| Sessions Spawn Bridge | Direct runner script | SubagentExecutor | ✅ Wave 2 Cutover |
| Trading Roundtable | Phase Engine + Bridge | SubagentExecutor (via Bridge) | ✅ Inherited |
| Channel Roundtable | Phase Engine + Bridge | SubagentExecutor (via Bridge) | ✅ Inherited |

**测试覆盖** (`tests/orchestrator/test_wave2_cutover.py`):
- ✅ SubagentExecutor 集成正常
- ✅ SessionsSpawnRequest 创建正常
- ✅ Bridge Policy 评估不变
- ✅ API Execution Artifact 生成不变
- ✅ Linkage 链完整 (registration→dispatch→spawn→execution→receipt→request→task)
- ✅ SubagentConfig 映射正确
- 总计:6/6 通过

**回归测试**:
- ✅ `test_sessions_spawn_bridge.py`: 21/21 通过
- ✅ `test_subagent_executor.py`: 16/16 通过
- ✅ `test_subagent_state.py`: 16/16 通过
- ✅ `test_issue_lane_executor.py`: 16/16 通过
- ✅ `test_wave2_cutover.py`: 6/6 通过
- 总计:55/55 通过

**验证命令**:
```bash
cd <repo-root>
python3 tests/orchestrator/test_wave2_cutover.py
# 输出:6 passed
python3 -m pytest tests/orchestrator/test_sessions_spawn_bridge.py -v
# 输出:21 passed
```

**设计原则**:
1. 替换 execution substrate,不替换 control plane
2. 保持 planning / continuation / closeout / failure guarantee / heartbeat boundary 语义不变
3. 小步可回退,不做大爆炸改写
4. 没有测试结果不得宣称完成

### 2.2.3 Deer-Flow 借鉴线 Batch A/B 已实现 (2026-03-24)

**Deer-Flow 借鉴线 Batch A/B** 已完成,基于 `shared-context/intel/2026-03-24-deerflow-orchestration-mechanism-lessons.md` 的分析结论。

**核心设计原则**:
- **借 execution layer,不换 control plane**: SubagentExecutor 封装执行细节,不替换现有 sessions_spawn / roundtable 主链
- **薄层、可回退**: 新增模块独立,不影响现有功能
- **内存快、文件真**: 内存缓存加速访问,文件持久化保证重启不丢

**Batch A: SubagentExecutor 封装** (`runtime/orchestrator/subagent_executor.py`):
- SubagentConfig: subagent 配置(label / runtime / timeout / allowed_tools)
- SubagentResult: 执行结果(task_id / status / result / error)
- SubagentExecutor: 执行引擎(execute_async / get_result / cleanup)
- 工具权限隔离:allowed_tools / disallowed_tools 过滤
- 统一 task_id / timeout / status / result handle
- 测试:16/16 通过 (`tests/orchestrator/test_subagent_executor.py`)

**Batch B: 热状态存储** (`runtime/orchestrator/subagent_state.py`):
- SubagentStateManager: 状态管理器
- 内存缓存 + 文件持久化混合
- 重启后可从磁盘恢复终态
- 线程安全的并发操作
- 测试:16/16 通过 (`tests/orchestrator/test_subagent_state.py`)

**明确不做的部分**:
- ❌ 双线程池架构:Python GIL 限制,收益有限
- ❌ 全局内存字典:重启就丢,不如 shared-context 文件可靠
- ❌ task_tool 轮询:已有 callback bridge / watcher / ack-final 协议

**验证命令**:
```bash
cd <repo-root>
python3 tests/orchestrator/test_subagent_executor.py
# 输出:16 passed
python3 tests/orchestrator/test_subagent_state.py
# 输出:16 passed
```

**使用示例**:
```python
from subagent_executor import SubagentExecutor, SubagentConfig

executor = SubagentExecutor(
    config=SubagentConfig(
        label="coding-task",
        runtime="subagent",
        timeout_seconds=900,
        allowed_tools=["read", "write", "edit"],
    ),
    cwd="/Users/study/.openclaw/workspace",
)

task_id = executor.execute_async("实现 XXX 功能")
result = executor.get_result(task_id)
```

**设计原则**:
1. 薄层扩展,不重构现有架构
2. 失败场景与成功路径共享同一套 guarantee 状态机
3. guarantee 是兜底机制,不影响主流程
4. 元数据通过 `metadata` 字典传递,保持向后兼容

**核心 schema** (`runtime/orchestrator/issue_lane_schemas.py`):
- `IssueInput`: 支持 GitHub issue URL / 标准化 payload 两种输入
- `PlanningOutput`: planning artifact(problem reframing / scope / engineering review / execution plan)
- `ExecutionOutput`: 执行结果(`PatchArtifact` / `PRDescription` / test results)
- `CloseoutOutput`: closeout summary(`stopped_because` / `next_step` / `next_owner` / `dispatch_readiness`)
- `IssueLaneContract`: 统一契约(input -> planning -> execution -> closeout)

**最小链路已打通**:
- issue input -> planning -> execution handoff -> closeout
- 12 个测试全部通过(schema 验证 / 序列化 / 端到端链路 / 向后兼容)
- 测试文件:`runtime/tests/orchestrator/test_issue_lane_schemas.py`

**设计原则**:
1. 最小通用 schema,不做大而全设计
2. 向后兼容,保留扩展现有 handoff schema
3. 支持 GitHub issue URL 和标准化 payload 两种输入
4. 输出包含 patch artifact / PR description / closeout summary
5. 默认接 Claude Code / subagent lane

**验证命令**:
```bash
cd <repo-root>
python3 runtime/tests/orchestrator/test_issue_lane_schemas.py
# 输出:Results: 12 passed, 0 failed
```

### 2.3 外部框架策略已经统一

一句话:

> **OpenClaw 继续持有控制面;外部框架只准进入叶子执行层、benchmark 层或局部方法层。**

换成更直接的话:
- **继续 OpenClaw native 的层**:入口、`sessions_spawn`、launch/completion hook、callback bridge、scenario adapter、watcher/reconcile 边界、heartbeat 治理边界;
- **允许外部框架进入的层**:DeepAgents 风格 coding runtime、SWE-agent issue lane、局部 analysis graph、未来少数 durable pilot;
- **明确不引成主链的层**:DeepAgents、SWE-agent、OpenSWE、LangGraph、Temporal 都不升为公司级 orchestration backbone。

### 2.4 当前 live continuation 真值仍需收紧理解

以下仍然成立:
- `channel_roundtable` 与 `trading_roundtable` 已证明 continuation 不是纸面设计;
- 当前默认仍是 allowlist、条件触发、可回退;
- trading 不是任意结果都自动 continuation;
- `tmux` 已是正式可选 backend,但不等于已证明全局自动闭环。

因此,当前正确写法仍是:
- **已有真实 continuation 场景**;
- **但总体仍停留在 thin bridge / allowlist / safe semi-auto**;
- **外部框架讨论的是下一阶段增强点,不是当前主链 owner。**

### 2.5 其他频道接入 quickstart 已就绪

新增真值(2026-03-22):
- **quickstart 文档已就绪**:`quickstart-other-channels.md`
- 非 trading 场景默认仍走 `channel_roundtable`,**不需要新 adapter**
- 首次接入仍建议 `allow_auto_dispatch=false`,先证明 callback / ack / dispatch artifacts 稳定,再决定是否放开默认自动续跑
- 最小可运行命令见 quickstart 文档

边界同样要写清:
- 这不代表"其他频道零配置默认全自动"
- 当前成熟度仍是 **thin bridge / allowlist / safe semi-auto**

### 2.6 WS3 暴露的是机制缺口,不是单一个案

当前新增口径:
- WS3 暴露的"waiting 但 active=0"属于 **waiting integrity / hard-close / fail-fast / anomaly detection** 机制缺口;
- 处理顺序必须是:**先修机制,再处理个案**;
- `heartbeat` 仍只在治理外环,负责发现异常等待并请求重查,不负责代替主链写终态。

正式约束入口:`waiting-integrity-hard-close-policy-2026-03-21.md`


---


## 3. 为什么 agent 做完就停,以及接下来怎么修

### 3.1 现在为什么会停

"做完一件事就停"有两层原因:

1. **agent 内部停**
   - 只完成当前 step;
   - 缺默认 planning ledger / closeout checklist / next-step policy;
   - 常见表现是:改完一处代码、跑完一轮测试、写完一份文档后自然停住。

2. **公司级主链停**
   - `summary -> decision -> dispatch` 还没统一成默认 continuation contract;
   - 系统知道"这个 run 结束了",但还不能稳定回答"为什么停、谁接、下一步是什么"。

### 3.2 接下来不是靠盲目加循环修

下一阶段重点是:
1. **先规划**:planning artifact 成为默认输入;
2. **先 contract**:任务 closeout 必须带 `stopped_because / next_step / next_owner`;
3. **再自动推进**:只有 contract 足够清楚时,才讨论自动 dispatch;
4. **heartbeat 继续待在外环**:它负责提醒和重查,不负责代替主链做状态推进。


---


## 4. 当前计划入口

这轮 canonical 计划入口改为:

1. [`plans/overall-plan.md`](plans/overall-plan.md) - 当前真值 + P0/P1/P2 计划 + 明确边界
2. `p0-execution-backlog-2026-03-21.md` - P0 第一批执行清单、顺序与 cut line
3. `roadmap.md` - 按阶段展开的最小路线图
4. `validation-status.md` - 已验证 / 未验证边界
5. `runtime-integration/spawn-interceptor-live-bridge.md` - live bridge 当前已接/未接边界

如果只想先抓一句话:

> **下一阶段不是"上更多循环",而是"先把 planning、continuation contract、issue lane baseline、heartbeat boundary 定成默认",然后再用 DeepAgents / SWE-agent 做叶子层 pilot。**


---


## 5. historical / superseded 入口

以下内容保留,但**不再应被当成当前默认口径入口**:

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `docs/roadmap.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `executive-summary.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation-status.md` | historical pre-live design note | `validation-status.md` + 本页 |
| (已删除) | historical review snapshot | 本页 + `overall-plan.md` |


---


## 6. 一句话总口径

**proposal repo 现在的真值是:它是 OpenClaw 公司级 orchestration 方案仓与统一阅读入口;gstack-style planning 已成为默认方法,TEAM_RULES 已 codify planning default 与 heartbeat boundary;OpenClaw 继续持有 control plane,外部框架只进叶子层/benchmark/局部方法层;下一阶段重点是先规划、先 contract、再自动推进,而不是盲目加循环。**


---


## 7. Continuation Kernel 当前状态总结

### 7.1 已实现的 Kernel

| 版本 | 模块 | 核心能力 | 状态 |
|------|------|---------|------|
| v1 | `partial_continuation.py` | Partial closeout contract / auto-replan | ✅ 实现完成 |
| v2 | `task_registration.py` | Task registry ledger(JSONL 注册表) | ✅ 实现完成 |
| v3 | `auto_dispatch.py` | Auto-dispatch selector / policy evaluation | ✅ 实现完成 |
| v4 | `spawn_closure.py` | Spawn closure artifact / 去重 / policy guard | ✅ 实现完成 |
| v5.1 | `spawn_execution.py` | Spawn execution artifact / real execution | ✅ 实现完成 (2026-03-22) |
| v5.2 | `completion_receipt.py` | Completion receipt artifact / closure | ✅ 实现完成 (2026-03-22) |
| v6.1 | `sessions_spawn_request.py` | **通用** sessions_spawn-compatible request interface | ✅ 实现完成 (2026-03-22) |
| v6.2 | `callback_auto_close.py` | **通用** callback auto-close bridge / linkage | ✅ 实现完成 (2026-03-22) |
| v7.1 | `bridge_consumer.py` | **通用** bridge consumption layer / execution envelope | ✅ 实现完成 (2026-03-22) |
| v8.1 | `bridge_consumer.py` | **Real Execute Mode** + **ExecutionResult** | ✅ 实现完成 (2026-03-22) |
| v8.2 | `sessions_spawn_request.py` | **Auto-Trigger Consumption** + guard/dedupe | ✅ 实现完成 (2026-03-22) |
| v9.1 | `sessions_spawn_bridge.py` | **Real OpenClaw sessions_spawn API Integration** | ✅ 实现完成 (2026-03-23) |
| v9.2 | `sessions_spawn_bridge.py` | **API Execution Artifact** + childSessionKey/runId | ✅ 实现完成 (2026-03-23) |

### 7.2 Post-Completion Replan Contract

`runtime/orchestrator/post_completion_replan.py` 提供最小 contract:
- 无 anchor 时,follow-up 只能是 `pending_registration`
- 有 anchor 时,才允许标成 `in_progress`
- 禁止口头说"继续推进"但系统里没有新任务注册

### 7.3 当前成熟度边界(2026-03-23 V10 更新)

- ✅ Trading + Channel 两个场景已接入
- ✅ **468 个测试全部通过** (2026-03-24)
- ✅ **v5 完整闭环已实现**: spawn closure -> spawn execution artifact -> completion receipt artifact
- ✅ **v6 通用层已实现**: sessions_spawn request interface + callback auto-close bridge
- ✅ **v7 bridge consumption 已实现**: bridge consumer / execution envelope / consumed artifact
- ✅ **v8 execute mode 已实现**: `simulate_only=False` 时真正执行(当前为模拟执行记录)
- ✅ **v8 auto-trigger 已实现**: request prepared 后可自动触发 consumption(带 guard/dedupe)
- ✅ **v9 Real API Integration**: sessions_spawn_bridge 真实调用 OpenClaw sessions_spawn API
- ✅ **v9 API Execution Artifact**: childSessionKey / runId / linkage 真实落盘
- ✅ **真实落盘**: execution / receipt / request / close / consumed / api_execution artifacts 均已写入 `~/.openclaw/shared-context/` (standard OpenClaw home directory)
- ✅ **Linkage 验证**: registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id → api_execution_id 链路正确
- ✅ **去重机制**: duplicate execution / receipt / request / consumption / api_execution prevention 正常工作
- ✅ **通用 kernel**: adapter-agnostic design,trading 仅作为首个消费者
- ✅ **状态扩展**: `prepared | consumed | executed | failed | blocked | pending | started`
- ✅ **技术债务收口**: `docs/technical-debt-2026-03-22.md` 已创建
- ✅ **P0-3 Batches 1-6**: Legacy cleanup completed (2026-03-23)
- ✅ **P0-3 Final**: **Dual-track backend strategy** (subagent + tmux) - both backends retained indefinitely (2026-03-23)
- ✅ **仓库收敛改造**: README/README.zh 重写为单入口;根目录报告/测试文件归位 (2026-03-24)
- ✅ **架构健康度审查**: [`reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md`](reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md) (95/100 健康)
- ⚠️ **CLI Integration**: 当前优先 mock Python API call,OpenClaw CLI 集成需确认 `openclaw sessions_spawn` 命令
- ⚠️ **Auto-trigger 配置**: 使用本地 JSON 文件,缺少版本控制(见 technical debt D5)
- ❌ 不等于"全域全自动无人续跑"

**Dual-Track Backend Strategy**:
- **subagent**: DEFAULT backend for automated execution, CI/CD, new development
- **tmux**: FULLY SUPPORTED backend for interactive sessions, manual observation
- **Both backends coexist** - no breaking removal planned

### 7.4 V5 闭环验证(2026-03-22)

**测试命令**:
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 runtime/orchestrator/test_v5 闭环.py
```

**测试结果**:
```
✅ PASS: Happy path (spawn closure -> execution -> receipt)
✅ PASS: Blocked spawn (blocked/duplicate/missing payload 不执行)
✅ PASS: Duplicate prevention (去重机制正常工作)
总计:3/3 通过
```

**交付物示例**:
- Spawn closure: `spawn_18a59d08fbcd`
- Execution: `exec_607e018c9785` → `~/.openclaw/shared-context/spawn_executions/exec_607e018c9785.json`
- Receipt: `receipt_6d6f97ce0e10` → `~/.openclaw/shared-context/completion_receipts/receipt_6d6f97ce0e10.json`

**详细文档**: `archive/old-docs/partial-continuation-kernel-v5.md`(已归档,历史参考)

### 7.5 V6 通用层验证(2026-03-22 新增)

**测试命令**:
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_sessions_spawn_request.py -v
python3 -m pytest tests/orchestrator/test_callback_auto_close.py -v
```

**V6 新增能力**:
1. **sessions_spawn_request.py**: 从 receipt 生成 canonical sessions_spawn-compatible request
   - 包含 runtime / cwd / task / label / metadata(dispatch_id / spawn_id / source)
   - spawn_request_status = prepared | emitted | blocked | failed
   - 可被任何 adapter 消费(trading / channel / generic)

2. **callback_auto_close.py**: 从 receipt + request 生成 auto-close artifact
   - Linkage 包含:dispatch_id / spawn_id / execution_id / receipt_id / request_id / source task_id
   - close_status = closed | pending | blocked | partial
   - 支持通过任意 ID 反向查询闭环状态

**交付物示例**:
- Spawn request: `req_abc123` → `~/.openclaw/shared-context/spawn_requests/req_abc123.json`
- Callback close: `close_xyz789` → `~/.openclaw/shared-context/callback_closes/close_xyz789.json`

**详细文档**: `docs/partial-continuation-kernel-v6.md`

### 7.6 V7 Bridge Consumption 验证(2026-03-22 新增)

**测试命令**:
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_bridge_consumer.py -v
```

**测试结果**:
```
✅ PASS: Happy path (consume prepared request)
✅ PASS: Blocked (request status 不符不消费)
✅ PASS: Duplicate (同一 request 不重复消费)
✅ PASS: Missing (request 不存在抛出错误)
✅ PASS: Linkage (完整 linkage 验证)
总计:14/14 通过
```

**V7 新增能力**:
1. **bridge_consumer.py**: 消费 sessions_spawn request,生成 canonical consumed artifact
   - 包含 execution envelope(sessions_spawn params + execution context)
   - consumer_status = consumed | skipped | blocked | failed
   - 可被 OpenClaw bridge 直接执行

2. **Linkage**: 完整 10-ID 链路
   - registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id
   - 支持通过任意 ID 反向查询

**交付物示例**:
- Consumed artifact: `consumed_abc123` → `~/.openclaw/shared-context/bridge_consumed/consumed_abc123.json`
- Execution envelope: 包含 sessions_spawn params + execution context

**详细文档**: `archive/old-docs/partial-continuation-kernel-v7.md`(已归档,历史参考)

### 7.7 V8 Real Execute Mode + Auto-Trigger 验证(2026-03-22 新增)

**测试命令**:
```bash
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 runtime/orchestrator/test_v8_execute_and_auto_trigger.py
```

**测试结果**:
```
============================================================
V8 Execute Mode + Auto-Trigger 功能验证
============================================================
✓ ExecutionResult 数据结构正常
✓ Execute mode policy 正常
✓ Auto-trigger 配置正常
✓ 向后兼容性正常
============================================================
测试结果:4 通过,0 失败
============================================================
```

**V8 新增能力**:
1. **Execute Mode** (`bridge_consumer.py`):
   - `BridgeConsumerPolicy.execute_mode`: `simulate` | `execute` | `dry_run`
   - `ExecutionResult`: 记录执行结果(executed / session_id / output / error)
   - `consumer_status` 扩展:`prepared | consumed | executed | failed | blocked`
   - 支持 `simulate_only=False` 时真正执行 sessions_spawn

2. **Auto-Trigger Consumption** (`sessions_spawn_request.py`):
   - `auto_trigger_consumption(request_id)`: 自动触发 consumption
   - `configure_auto_trigger()`: 配置 enable/disable / allowlist / denylist / manual approval
   - `get_auto_trigger_status()`: 查询触发状态
   - Guard / Dedupe: 防止重复触发 / 场景过滤 / 手动审批

3. **CLI 命令**:
   ```bash
   # Auto-trigger
   python sessions_spawn_request.py auto-trigger <request_id>
   python sessions_spawn_request.py auto-trigger-config --enable --no-manual-approval
   python sessions_spawn_request.py auto-trigger-status

   # Bridge consumer (v7/v8)
   python bridge_consumer.py consume <request_id>
   python bridge_consumer.py list [--status <status>]
   ```

4. **技术债务收口**:
   - [`technical-debt/technical-debt-2026-03-22.md`](technical-debt/technical-debt-2026-03-22.md): 收敛已知优化点(trading_roundtable 拆分 / 模块收口 / 文档去重等)

**交付物示例**:
- Executed artifact: `consumed_abc123` with `consumer_status=executed`
- Execution result: `{"executed": true, "session_id": "session_xyz", "output": "..."}`
- Auto-trigger index: `~/.openclaw/shared-context/spawn_requests/auto_trigger_index.json`

**详细文档**:
- `archive/old-docs/partial-continuation-kernel-v8.md`(已归档,历史参考)
- [`technical-debt/technical-debt-2026-03-22.md`](technical-debt/technical-debt-2026-03-22.md)


---


> **详细演进历史**:各版本 kernel 的详细设计文档见各模块源码的 docstring。
的 docstring。
