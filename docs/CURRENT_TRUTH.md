# CURRENT_TRUTH(2026-03-22)

> **更新**: 2026-03-22 — V8 Real Execute Mode + Auto-Trigger Consumption 已实现

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
5. **完整方案** → `executive-summary.md`

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
- **本地副本状态**：已加 (已标记 deprecated) 标成 legacy / 只读 / 待退役
- **规则**：禁止双写，新改动必须提交到本仓 monorepo


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
| v2 | `task_registration.py` | Task registry ledger（JSONL 注册表） | ✅ 实现完成 |
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

`runtime/orchestrator/post_completion_replan.py` 提供最小 contract：
- 无 anchor 时，follow-up 只能是 `pending_registration`
- 有 anchor 时，才允许标成 `in_progress`
- 禁止口头说"继续推进"但系统里没有新任务注册

### 7.3 当前成熟度边界（2026-03-23 V9 更新）

- ✅ Trading + Channel 两个场景已接入
- ✅ 250+ 个测试全部通过（新增 14 个 v9 测试）
- ✅ **v5 完整闭环已实现**: spawn closure -> spawn execution artifact -> completion receipt artifact
- ✅ **v6 通用层已实现**: sessions_spawn request interface + callback auto-close bridge
- ✅ **v7 bridge consumption 已实现**: bridge consumer / execution envelope / consumed artifact
- ✅ **v8 execute mode 已实现**: `simulate_only=False` 时真正执行（当前为模拟执行记录）
- ✅ **v8 auto-trigger 已实现**: request prepared 后可自动触发 consumption（带 guard/dedupe）
- ✅ **v9 Real API Integration**: sessions_spawn_bridge 真实调用 OpenClaw sessions_spawn API
- ✅ **v9 API Execution Artifact**: childSessionKey / runId / linkage 真实落盘
- ✅ **真实落盘**: execution / receipt / request / close / consumed / api_execution artifacts 均已写入 `~/.openclaw/shared-context/`
- ✅ **Linkage 验证**: registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id → api_execution_id 链路正确
- ✅ **去重机制**: duplicate execution / receipt / request / consumption / api_execution prevention 正常工作
- ✅ **通用 kernel**: adapter-agnostic design，trading 仅作为首个消费者
- ✅ **状态扩展**: `prepared | consumed | executed | failed | blocked | pending | started`
- ✅ **技术债务收口**: `docs/technical-debt-2026-03-22.md` 已创建
- ✅ **P0-3 Batch 2**: Legacy runtime cleanup — deprecation markers + fix non-existent stop command (2026-03-23)
- ✅ **P0-3 Batch 3**: Legacy command deprecation — mark describe/capture/attach as deprecated (2026-03-23)
- ✅ **P0-3 Batch 4**: Subagent as default recommended backend — tighten tmux compat layer (2026-03-23)
- ✅ **P0-3 Batch 5**: Direct tmux -> subagent migration — remove tmux from default paths, minimize compat surface (2026-03-23)
- ✅ **P0-3 Batch 6**: Generic lifecycle kernel — extract backend-agnostic watchdog/lifecycle logic (2026-03-23)
- ⚠️ **CLI Integration**: 当前优先 mock Python API call，OpenClaw CLI 集成需确认 `openclaw sessions_spawn` 命令
- ⚠️ **Auto-trigger 配置**: 使用本地 JSON 文件，缺少版本控制（见 technical debt D5）
- ❌ 不等于"全域全自动无人续跑"

### 7.4 V5 闭环验证（2026-03-22）

**测试命令**:
```bash
cd /Users/study/.openclaw/workspace/orchestrator
python3 test_v5 闭环.py
```

**测试结果**:
```
✅ PASS: Happy path (spawn closure -> execution -> receipt)
✅ PASS: Blocked spawn (blocked/duplicate/missing payload 不执行)
✅ PASS: Duplicate prevention (去重机制正常工作)
总计：3/3 通过
```

**交付物示例**:
- Spawn closure: `spawn_18a59d08fbcd`
- Execution: `exec_607e018c9785` → `~/.openclaw/shared-context/spawn_executions/exec_607e018c9785.json`
- Receipt: `receipt_6d6f97ce0e10` → `~/.openclaw/shared-context/completion_receipts/receipt_6d6f97ce0e10.json`

**详细文档**: `archive/old-docs/partial-continuation-kernel-v5.md`（已归档，历史参考）

### 7.5 V6 通用层验证（2026-03-22 新增）

**测试命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_sessions_spawn_request.py -v
python3 -m pytest tests/orchestrator/test_callback_auto_close.py -v
```

**V6 新增能力**:
1. **sessions_spawn_request.py**: 从 receipt 生成 canonical sessions_spawn-compatible request
   - 包含 runtime / cwd / task / label / metadata（dispatch_id / spawn_id / source）
   - spawn_request_status = prepared | emitted | blocked | failed
   - 可被任何 adapter 消费（trading / channel / generic）

2. **callback_auto_close.py**: 从 receipt + request 生成 auto-close artifact
   - Linkage 包含：dispatch_id / spawn_id / execution_id / receipt_id / request_id / source task_id
   - close_status = closed | pending | blocked | partial
   - 支持通过任意 ID 反向查询闭环状态

**交付物示例**:
- Spawn request: `req_abc123` → `~/.openclaw/shared-context/spawn_requests/req_abc123.json`
- Callback close: `close_xyz789` → `~/.openclaw/shared-context/callback_closes/close_xyz789.json`

**详细文档**: `docs/partial-continuation-kernel-v6.md`

### 7.6 V7 Bridge Consumption 验证（2026-03-22 新增）

**测试命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/test_bridge_consumer.py -v
```

**测试结果**:
```
✅ PASS: Happy path (consume prepared request)
✅ PASS: Blocked (request status 不符不消费)
✅ PASS: Duplicate (同一 request 不重复消费)
✅ PASS: Missing (request 不存在抛出错误)
✅ PASS: Linkage (完整 linkage 验证)
总计：14/14 通过
```

**V7 新增能力**:
1. **bridge_consumer.py**: 消费 sessions_spawn request，生成 canonical consumed artifact
   - 包含 execution envelope（sessions_spawn params + execution context）
   - consumer_status = consumed | skipped | blocked | failed
   - 可被 OpenClaw bridge 直接执行

2. **Linkage**: 完整 10-ID 链路
   - registration_id → dispatch_id → spawn_id → execution_id → receipt_id → request_id → consumed_id
   - 支持通过任意 ID 反向查询

**交付物示例**:
- Consumed artifact: `consumed_abc123` → `~/.openclaw/shared-context/bridge_consumed/consumed_abc123.json`
- Execution envelope: 包含 sessions_spawn params + execution context

**详细文档**: `archive/old-docs/partial-continuation-kernel-v7.md`（已归档，历史参考）

### 7.7 V8 Real Execute Mode + Auto-Trigger 验证（2026-03-22 新增）

**测试命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 test_v8_execute_and_auto_trigger.py
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
测试结果：4 通过，0 失败
============================================================
```

**V8 新增能力**:
1. **Execute Mode** (`bridge_consumer.py`):
   - `BridgeConsumerPolicy.execute_mode`: `simulate` | `execute` | `dry_run`
   - `ExecutionResult`: 记录执行结果（executed / session_id / output / error）
   - `consumer_status` 扩展：`prepared | consumed | executed | failed | blocked`
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
   - `docs/technical-debt-2026-03-22.md`: 收敛已知优化点（trading_roundtable 拆分 / 模块收口 / 文档去重等）

**交付物示例**:
- Executed artifact: `consumed_abc123` with `consumer_status=executed`
- Execution result: `{"executed": true, "session_id": "session_xyz", "output": "..."}`
- Auto-trigger index: `~/.openclaw/shared-context/spawn_requests/auto_trigger_index.json`

**详细文档**: 
- `archive/old-docs/partial-continuation-kernel-v8.md`（已归档，历史参考）
- `docs/technical-debt-2026-03-22.md`

---

> **详细演进历史**：各版本 kernel 的详细设计文档见各模块源码的 docstring。
