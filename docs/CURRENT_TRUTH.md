# CURRENT_TRUTH(2026-03-21)

> 用途:给这个 proposal repo 一个**当前真值入口**,避免旧计划、旧评审、旧 POC 被继续误读成"今天的默认口径"。
>
> 注意:这个 repo 现在已升级为**单仓分层 monorepo**:`docs/` 持阅读入口,`runtime/` 持实现真值,`tests/` 持验收。历史上 runtime 曾散落在 OpenClaw workspace 本地;从 2026-03-22 起,本仓开始承担 orchestration runtime 的统一收口。
---

## 0. 入口指引(从哪里开始)

### 阅读入口
1. **首次了解** → `../README.md`(仓库总览 + 快速开始)
2. **5 分钟版本** → `executive-summary.md`
3. **当前真值** → 本页(`CURRENT_TRUTH.md`)
4. **其他频道 quickstart** → `quickstart-other-channels.md`(非 trading 场景)
5. **完整方案** → `openclaw-company-orchestration-proposal.md`

### Runtime 入口
```bash
# 统一入口命令
python3 ~/.openclaw/scripts/orch_command.py --context <场景> --channel-id "<频道 ID>" --topic "<主题>"

# 或从本仓直接运行
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
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

这个仓库现在应当被理解为：

> **OpenClaw 公司级 orchestration / workflow 的单仓分层 monorepo。**

它同时承担：
- `docs/`：canonical 阅读入口 / 计划 / 边界 / CURRENT_TRUTH
- `runtime/`：orchestrator、entry command、callback bridge、skills 等实现真值
- `tests/`：针对 runtime 的验收测试

它仍然不是：
- 任一单个 POC、单个插件、单个 pilot 的代名词
- "已经默认全自动闭环"的完成态说明

当前正确总口径是：
- **OpenClaw 持 control plane**
- **本仓同时持阅读入口与 orchestration runtime 收口**
- **外部框架只进叶子层 / benchmark / 局部方法层**
- **总体仍是 thin bridge / allowlist / safe semi-auto**

### 1.1 本地 workspace 副本已退役（2026-03-22）
历史上 orchestration runtime 曾散落在 `~/.openclaw/workspace` 本地；从 2026-03-22 起：
- **Canonical 主线**：本仓 `runtime/` 目录
- **本地副本状态**：已加 `LEGACY_COPY_NOTICE.md` 标成 legacy / 只读 / 待退役
- **规则**：禁止双写，新改动必须提交到本仓 monorepo

详细退役地图见：`~/.openclaw/workspace/ORCHESTRATION_LEGACY_MAP.md`

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

1. `overall-plan.md` - 当前真值 + P0/P1/P2 计划 + 明确边界
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
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `overall-plan.md` |

---

## 6. 一句话总口径

**proposal repo 现在的真值是:它是 OpenClaw 公司级 orchestration 方案仓与统一阅读入口;gstack-style planning 已成为默认方法,TEAM_RULES 已 codify planning default 与 heartbeat boundary;OpenClaw 继续持有 control plane,外部框架只进叶子层/benchmark/局部方法层;下一阶段重点是先规划、先 contract、再自动推进,而不是盲目加循环。**

---

## 7. Post-Completion Follow-Up Registration(2026-03-22 新增)

### 7.1 问题:为什么"做完就停"看起来像机制坏了

当前系统已支持:
- 同一 orchestrated flow/batch 内 `callback -> decision -> dispatch` 的 continuation
- allowlist / gate / clean PASS 等控制

**但存在一个缝隙**:
- 当前任务结束后,如果出现新的 follow-up / docs 工作流 / operator-facing 交付,系统没有统一把它显式区分为:
  1) **已注册 continuation**(有 task/batch/dispatch anchor)
  2) **待注册新任务**(planned but not started)

结果就是:聊天里容易把"准备做下一步"说成"已经在推进"。

### 7.2 修复:post-completion replan contract

从 2026-03-22 起,新增 `runtime/orchestrator/post_completion_replan.py`,定义最小 contract:

```python
# 核心结构
followup_mode = "existing_dispatch" | "pending_registration"
truth_anchor_type = "task_id" | "batch_id" | "branch" | "commit" | "push" | "none"
allowed_status_phrase = "in_progress" | "pending_registration"
```

**核心规则(强制)**:
1. **没 anchor 时,followup_mode 只能是 `pending_registration`**
2. **没 anchor 时,status_phrase 只能是 `pending_registration`**
3. **有 anchor 时,才允许标成 `in_progress`**

### 7.3 Operator-Facing 规则(必须遵守)

#### 原 dispatch plan 内的 continuation
- 可以自动续推(前提是 clean PASS + whitelist 命中)
- 状态可以写 `in_progress`
- 必须有明确的 anchor(task_id / batch_id / dispatch step)

#### 原 dispatch plan 外的新 follow-up
- **必须先注册为新任务/新 branch/新 commit anchor**
- 注册前状态只能写 `待启动` / `pending_registration`
- **禁止口头说"继续推进"但系统里没有新任务注册**

#### 状态短语使用规范

| 场景 | followup_mode | truth_anchor | 允许的状态短语 |
|------|---------------|--------------|----------------|
| 原 plan 内的下一跳 | existing_dispatch | task_id / batch_id | `in_progress` |
| 新 follow-up(已注册) | existing_dispatch | branch / commit / push | `in_progress` |
| 新 follow-up(未注册) | pending_registration | none | `pending_registration` |
| 有 anchor 但需人工确认 | pending_registration | 有 | `pending_registration` |

### 7.4 代码入口

```python
from runtime.orchestrator.post_completion_replan import (
    build_replan_contract,
    validate_followup_status,
    PostCompletionReplanContract,
)

# 示例:无 anchor 的新 follow-up(只能 pending_registration)
contract = build_replan_contract(
    followup_description="编写用户文档",
    original_task_id="task_123",
    # 没有 anchor_type / anchor_value → 自动设为 pending_registration
)
assert contract.followup_mode == "pending_registration"
assert contract.status_phrase == "pending_registration"

# 示例:有 anchor 的 continuation(可以 in_progress)
contract = build_replan_contract(
    followup_description="Phase 2 实现",
    original_batch_id="batch_phase1",
    anchor_type="batch_id",
    anchor_value="batch_phase2_scheduled",
)
assert contract.followup_mode == "existing_dispatch"
assert contract.status_phrase == "in_progress"
```

### 7.5 与现有机制的关系

- **不是大重构**:只是补一个最小 contract,不改变现有 callback/dispatch/ack 逻辑
- **不是全自动**:仍然需要显式注册 anchor,不能靠聊天口头继续
- **与 waiting-integrity 配合**:waiting guard 负责发现"等但没活",replan contract 负责区分"已注册 vs 待注册"

### 7.6 验收测试

```bash
# 运行 post-completion replan 测试
python3 -m pytest tests/orchestrator/test_post_completion_replan.py -q
```

覆盖:
- 无 anchor 的 follow-up 不能被标成 `in_progress`
- 有 anchor(至少一种)时可被标成已启动/已注册
- validate_followup_status 强制修正非法状态

### 7.7 Partial Continuation Kernel v1 → v2 (2026-03-22 新增)

#### v1 (基础 kernel)

从 2026-03-22 起，新增 `runtime/orchestrator/partial_continuation.py`，提供**通用 partial closeout / auto-replan / next-task registration 能力**。

**核心能力:**
1. **Partial Closeout Contract** — 描述任务部分完成后的状态
2. **Auto-Replan Helper** — 基于 `remaining_scope` 自动生成 next task candidates
3. **Next-Task Registration Payload** — 结构化注册 payload（v1: proposal only）

详细文档：`docs/partial-continuation-kernel-v1.md`

#### v2 (Auto-Registration Layer) — 2026-03-22 新增

**v2 核心升级：把 registration payload 变成真实注册记录**

新增模块：`runtime/orchestrator/task_registration.py`

**核心能力:**
1. **Task Registry Ledger** — JSONL 格式的统一任务注册表
   - `~/.openclaw/shared-context/task-registry/registry.jsonl`
   - 单个记录：`~/.openclaw/shared-context/task-registry/{registration_id}.json`

2. **Registration Status** — `registered | skipped | blocked`
   - 明确标识注册状态，不再是"只是 proposal"

3. **Truth Anchor** — 稳定的 source linkage
   - `anchor_type`: task_id | batch_id | branch | commit | push
   - `anchor_value`: 稳定 ID
   - `metadata`: source_task_id, source_batch_id, adapter, scenario

4. **Ready for Auto-Dispatch** — v3 入口标志
   - `ready_for_auto_dispatch: bool`
   - 当前状态：`proposal -> registration -> dispatch-ready intent`

**代码入口 (v2 API):**
```python
from runtime.orchestrator.partial_continuation import (
    generate_registered_registrations_for_closeout,  # v2 API
    adapt_closeout_for_trading,
)
from runtime.orchestrator.task_registration import (
    get_registration,
    list_registrations,
    get_registrations_by_source,
)

# v2: 生成 registrations with status 并自动注册到 task registry
registrations = generate_registered_registrations_for_closeout(
    closeout=adapted,
    adapter="trading_roundtable",
    auto_register=True,  # v2: 自动写入 task registry
    batch_id="batch_123",
)

# 检查结果
for reg in registrations:
    print(f"Status: {reg.registration_status}")
    print(f"Truth Anchor: {reg.truth_anchor}")
    print(f"Ready for Auto-Dispatch: {reg.ready_for_auto_dispatch}")
    
    # 如果 auto_register=True，可以获取 task registry record
    if "task_registry_record" in reg.metadata:
        task_id = reg.metadata["task_registry_record"]["task_id"]
```

**验收测试:**
```bash
# 运行 v2 task registration 测试
python3 -m pytest tests/orchestrator/test_task_registration.py -v
# 12 passed

# 运行 partial continuation 测试 (v1 + v2)
python3 -m pytest tests/orchestrator/test_partial_continuation.py -v
# 33 passed
```

**覆盖:**
- ✅ Task registry 基本操作（register, get, list, update）
- ✅ 注册会创建真实文件（JSONL ledger + 单个记录）
- ✅ 无 remaining scope 时不注册
- ✅ Blocked 时不注册
- ✅ Trading 场景能触发真实注册
- ✅ 已注册结果包含稳定 linkage（source task / source batch / new task id）
- ✅ `ready_for_auto_dispatch` flag 逻辑

**当前成熟度:**
- ✅ Generic kernel v1 实现完成
- ✅ Task registry ledger v2 实现完成
- ✅ `registration_status` / `truth_anchor` / `ready_for_auto_dispatch` v2 实现完成
- ✅ Trading 场景接入 v2（自动注册到 task registry）
- ⏳ Channel 场景可接入（未实施）
- ❌ 不等于"全域全自动无人续跑"（当前状态：`proposal -> registration -> dispatch-ready intent`）

详细文档：`docs/partial-continuation-kernel-v2.md`

### 7.8 Partial Continuation Kernel v3 — Auto-Dispatch Execution (2026-03-22 新增)

**v3 核心升级：把 registered tasks 推进到 auto-dispatch execution intent + 最小执行路径**

新增模块：`runtime/orchestrator/auto_dispatch.py`

**核心能力:**
1. **Auto-dispatch selector** — 从 task registry 读取 `registered + ready_for_auto_dispatch` 的任务
2. **Dispatch policy evaluation** — 评估是否可自动派发（scenario allowlist / missing anchor / blocked / duplicate）
3. **Dispatch artifact generation** — 生成真实 dispatch artifact（dispatch_status / dispatch_reason / dispatch_time / dispatch_target）
4. **最小真实执行路径** — trading 场景产生真实 dispatch artifact + execution intent（recommended_spawn）

**场景约束（必须）:**
- 只对白名单/低风险 scenario 自动 dispatch（默认：`trading_roundtable_phase1`）
- blocked / missing anchor / manual-only 必须停住
- 当前是 **registered -> auto-dispatch intent / limited execution**, 不是全域无人值守

**代码入口 (v3 API):**
```python
from runtime.orchestrator.auto_dispatch import (
    AutoDispatchSelector,
    DispatchExecutor,
    DispatchPolicy,
    select_ready_tasks,
    evaluate_dispatch_policy,
    execute_dispatch,
    list_dispatches,
    get_dispatch,
)
from runtime.orchestrator.task_registration import list_registrations

# 1. 选择 ready 的任务
ready_tasks = select_ready_tasks(limit=10)

# 2. 评估 policy
for record in ready_tasks:
    evaluation = evaluate_dispatch_policy(record)
    if evaluation["eligible"]:
        # 3. 执行 dispatch（写入 artifact + 更新任务状态）
        artifact = execute_dispatch(record)
        print(f"Dispatched: {artifact.dispatch_id}")
        print(f"Status: {artifact.dispatch_status}")
        print(f"Reason: {artifact.dispatch_reason}")
        
        # 4. 获取 execution intent
        if artifact.execution_intent:
            spawn = artifact.execution_intent["recommended_spawn"]
            print(f"Ready to spawn: {spawn['task_preview']}")
            print(f"Metadata: {spawn['metadata']}")

# 5. 列出 dispatches
all_dispatches = list_dispatches()
dispatched = list_dispatches(dispatch_status="dispatched")
by_registration = list_dispatches(registration_id="reg_123")
```

**Dispatch Artifact 结构:**
```json
{
  "dispatch_version": "auto_dispatch_v1",
  "dispatch_id": "dispatch_abc123",
  "registration_id": "reg_xyz789",
  "task_id": "task_def456",
  "dispatch_status": "dispatched",
  "dispatch_reason": "Policy evaluation passed",
  "dispatch_time": "2026-03-22T20:00:00",
  "dispatch_target": {
    "scenario": "trading_roundtable_phase1",
    "adapter": "trading_roundtable",
    "batch_id": "batch_123",
    "owner": "trading"
  },
  "execution_intent": {
    "recommended_spawn": {
      "runtime": "subagent",
      "task_preview": "Trading continuation",
      "task": "Continue trading roundtable phase 1...",
      "cwd": "/Users/study/.openclaw/workspace",
      "metadata": {
        "dispatch_id": "dispatch_abc123",
        "registration_id": "reg_xyz789",
        "task_id": "task_def456",
        "source": "auto_dispatch_v3",
        "trading_context": {
          "batch_id": "batch_123",
          "phase": "phase1_continuation",
          "adapter": "trading_roundtable"
        }
      }
    }
  },
  "policy_evaluation": {
    "eligible": true,
    "blocked_reasons": [],
    "checks": [...]
  }
}
```

**验收测试:**
```bash
# 运行 v3 auto_dispatch 测试
python3 -m pytest tests/orchestrator/test_auto_dispatch.py -v

# 运行所有 orchestrator 测试（dispatch / registration / partial）
python3 -m pytest tests/orchestrator -q -k "dispatch or registration or partial"
```

**覆盖:**
- ✅ 从 registry 选择 ready 的任务
- ✅ 过滤 not-ready / blocked status 的任务
- ✅ Policy evaluation: happy path (trading scenario)
- ✅ Policy evaluation: blocked (scenario not in allowlist)
- ✅ Policy evaluation: blocked (missing anchor)
- ✅ Policy evaluation: blocked (duplicate dispatch)
- ✅ Execute dispatch: 生成 artifact + 写入文件
- ✅ Execute dispatch: blocked path
- ✅ Trading 场景：execution_intent 包含 trading_context
- ✅ List / get dispatches
- ✅ Dispatch artifact 序列化 / 反序列化
- ✅ 自定义 policy

**当前成熟度:**
- ✅ Generic kernel v1 实现完成
- ✅ Task registry ledger v2 实现完成
- ✅ Auto-dispatch selector v3 实现完成
- ✅ Dispatch policy evaluation v3 实现完成
- ✅ Dispatch artifact generation v3 实现完成
- ✅ Execution intent v3 实现完成
- ✅ Trading 场景接入 v3（dispatch artifact + execution intent）
- ⏳ Channel 场景可接入（未实施）
- ❌ 不等于"全域全自动无人续跑"（当前状态：`proposal -> registration -> auto-dispatch intent / limited execution`）

**v3 新增真实能力:**
- ✅ 从"账本里有任务"推进到"系统能自动挑选并发起下一批"
- ✅ 真实 dispatch artifact 落盘（可被 downstream 消费）
- ✅ 最小执行路径：execution intent 包含 recommended_spawn
- ✅ 任务状态自动更新（pending → in_progress after dispatch）

**v3 未实现（下一阶段）:**
- ❌ 实际 subagent spawn（downstream execution）
- ❌ Callback-driven continuation（v4+ 目标）
- ❌ 全域无人续跑（仍是白名单/有限执行）

详细文档：`docs/partial-continuation-kernel-v3.md`

---

## 8. 历史入口与 Superseded 内容

保留但**不再应被当成当前默认口径入口**:

| 文档 | 当前状态 | 建议替代阅读 |
|------|----------|--------------|
| `../ROADMAP.md` | historical draft / superseded | `roadmap.md` + `overall-plan.md` |
| `official-lobster-integration-plan.md` | historical batch1 plan | `../README.md` + 本页 |
| `validation/p0-minimal-validation-plan.md` | historical pre-live design note | `validation-status.md` + 本页 |
| `reviews/independent-architecture-review-20260319.md` | historical review snapshot | 本页 + `overall-plan.md` |
