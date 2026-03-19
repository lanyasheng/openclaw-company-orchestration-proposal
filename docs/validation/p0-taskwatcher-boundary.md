# P0-3《taskwatcher 边界收口审计》

## 结论先行

**基于当前 workspace 真值，taskwatcher 不是 backbone。**

当前真正承担 **内部 subagent 主链** 的，是 OpenClaw core 里的：
- `src/agents/subagent-registry.ts`
- `src/agents/subagent-registry-queries.ts`
- `src/agents/subagent-announce.ts`
- `src/agents/subagent-spawn.ts`

而 workspace 里的所谓 `taskwatcher`，实际落在：
- `skills/task_callback_bus/`

它现在已经长成一个 **外部状态观察 + callback/delivery + 若干派生桥接能力** 的大包，但**不应再被表述为 state-of-truth / durable backbone / 默认内部执行主链**。

---

## 1）taskwatcher 现在还承担什么（按当前 workspace 真值）

### 1.1 代码层真实职责

| 现在承担的事 | 证据文件 | 结论 |
|---|---|---|
| 轮询 active task，找 adapter，判断状态变化，决定 notify/close/escalate | `skills/task_callback_bus/bus.py` | **这是 watcher 本体** |
| 存 `CallbackTask` 记录、tasks.jsonl 读写 | `skills/task_callback_bus/models.py` `stores.py` | 是 watcher 自己的任务存储，但不该再升格成 backbone registry |
| 监控多类 source-of-truth：XHS、GitHub PR、cron、ACP session、coding agent run、generic-exec/status_file | `skills/task_callback_bus/adapters.py` | 是 external observer / compatibility adapter 层 |
| 推送 callback 到 discord / telegram / session / direct | `skills/task_callback_bus/notifiers.py` | 是 delivery 层，应该保留 |
| 终态自动产出 follow-up / dispatch 文件 | `skills/task_callback_bus/terminal_bridge.py` | 是 terminal fan-out，不是 backbone |
| 触发 Discord panel 更新 | `skills/task_callback_bus/discord_panel_bridge.py` | 是 UI/看板 fan-out，不是 backbone |
| ACP session 状态镜像到 `agent-sessions/` / `agent-runs/` | `skills/task_callback_bus/acp_state_bridge.py` | 是 bridge / compatibility，不是主链执行 |
| 对“状态错了但产物已出”的遗留任务做 reconcile | `skills/task_callback_bus/content_aware_completer.py` | 是 repair/reconcile，不是 state owner |
| 内部通信 guardrail、request lifecycle、completion bus | `skills/task_callback_bus/agent_comm_guardrail.py` `agent_request_store.py` `completion_bus.py` | **明显 scope creep**；不该继续算进 watcher 边界 |

### 1.2 数据面真实使用情况

当前共享任务库：
- `~/.openclaw/shared-context/monitor-tasks/tasks.jsonl` 存在，当前 52 行记录
- adapter 分布：`generic-exec` 43、`cron-job-completion` 3、`xiaohongshu-note-review` 4、`acp-session-completion` 1
- task_type 分布：`sessions_spawn` 39、`exec_command` 3、`file_state` 1、`status_monitor` 5、`agent_run` 1、`test` 3
- target_system 分布：`local_exec` 23、`acp` 21、`xiaohongshu` 5、`test` 3

**结论**：历史上 taskwatcher 实际被拿来当过“通用异步回执层”，尤其包了大量 `sessions_spawn` / `acp` / `status_file` 场景。

但这只是**历史承载**，不等于未来 backbone 口径应该继续这么写。

### 1.3 与 core 真相的冲突点

在 OpenClaw core 里：
- `subagent-registry.ts` 已负责 run 注册、requester/controller 绑定、cleanup、archive
- `subagent-registry-queries.ts` 已负责 descendant 统计、requester 解析
- `subagent-announce.ts` 已负责 completion announce、pending descendants settle、wake continuation、重复 announce 抑制
- `subagent-spawn.ts` 已把 spawn 接受语义、thread/session 模式、completion note 固化

另外，`/Users/study/openclawbugfix/openclaw/src` / `docs` 下**没有** `taskwatcher` runtime 实现（代码搜索无命中）。

**所以现在的 runtime 真相是：内部主链已经在 core；taskwatcher 只是 workspace 侧 watcher/bus。**

---

## 2）哪些职责必须保留

### 必须保留的边界表

| 职责 | 是否必须保留 | 原因 | 归属建议 |
|---|---|---|---|
| 外部状态观察（polling / file status / external adapter check） | **保留** | 这些 source-of-truth 不在 core runtime 内，仍需要 watcher 去看 | `taskwatcher` |
| callback/delivery（discord/telegram/session/direct） | **保留** | 外部通知、补发、失败重试、本来就是 watcher 擅长的事 | `taskwatcher` |
| delivery audit / retry / DLQ / resend 语义 | **保留** | 这是 callback 面的核心可靠性，不应丢 | `taskwatcher` 或 delivery-outbox 子模块 |
| terminal reconcile / repair（只补账，不主导状态） | **保留** | 老任务、漏桥接、状态错写仍需要兜底 | `taskwatcher` |
| external-only ACP/session file bridge（过渡期） | **保留但降级为兼容层** | 历史 ACP wrapper/status_file 还在，需要兼容读 | `taskwatcher` compatibility adapter |
| terminal fan-out（follow-up / dispatch / panel） | **保留，但改成订阅者** | 这些是终态后的副作用，不应控制主状态机 | 从 watcher 触发或从 registry event 触发均可 |

### 保留口径（建议写死）

> `taskwatcher` 只负责 **消费外部状态 / 做 callback delivery / 做 reconcile**。  
> 它可以是 external async observer，但不是 state-of-truth，不是默认执行主链，不是 durable orchestration backbone。

---

## 3）哪些职责必须从 backbone 口径里移除

### 必须移除的边界表

| 应移除的口径 | workspace 证据 | 为什么必须移除 | 新 owner |
|---|---|---|---|
| `taskwatcher = 默认内部长任务主链` | `tasks.jsonl` 里大量 `sessions_spawn/generic-exec` 历史记录；但 core 已有 `subagent-registry + subagent-announce` | 历史承载 ≠ 正确架构；继续这么写会跟 core 真值冲突 | `subagent core` |
| `taskwatcher = state-of-truth / registry owner` | `stores.py` 只是 watcher 自己的 JSONL store；core 另有 run registry | watcher 存储是 observer 侧台账，不应做统一真值 | `minimal task registry` |
| `taskwatcher = live agent coordination 通道` | `agent_comm_guardrail.py` 明确禁止；知识库也写明 watcher 不负责 live coordination | 这会把 callback 面和 control 面混掉 | `sessions_send` / main control plane |
| `taskwatcher = durable execution / replay / wake / descendant orchestration` | 这些能力已在 core `subagent-registry*` / `subagent-announce.ts` | watcher 不具备 deterministic replay，强扛只会重复造轮子 | `subagent core` |
| `taskwatcher = human gate / task planning / routing backbone` | 当前 watcher 包里没有可靠的人审/编排内核，只有 bridge/notify/guardrail 碎片 | 这不是 watcher 模型擅长的职责 | `control plane + registry + templates` |
| `taskwatcher = 统一公司级 request lifecycle owner` | `agent_request_store.py` / `completion_bus.py` 已经开始长成另一套控制面 | 这部分应从 watcher 包里拆出去，归 control plane / registry | `minimal task registry` / request-control 模块 |

### 明确要删掉的旧口径

1. **删掉**“taskwatcher 是 backbone 候选”  
   改成：**taskwatcher 是 external watcher / callback plane**

2. **删掉**“内部 `sessions_spawn` 默认走 taskwatcher”  
   改成：**内部默认走 subagent core registry + announce**

3. **删掉**“taskwatcher 负责 live 协调/agent-to-agent”  
   改成：**live 协调走 `sessions_send`**

4. **删掉**“taskwatcher 持有统一 task 真值”  
   改成：**task registry 持有统一 task 真值，watcher 只是 observer/delivery**

5. **删掉**“terminal bridge / panel bridge / completion bus = watcher backbone”  
   改成：**它们只是 watcher 下游 fan-out 或需拆出的控制面模块**

---

## 4）如何与 subagent 主链、最小 task registry 配合

## 4.1 推荐分工

| 层 | 负责什么 | 不负责什么 |
|---|---|---|
| **subagent core** | 内部长任务执行、run 生命周期、requester/controller 绑定、descendant settle、completion announce | 外部平台轮询、跨渠道 delivery retry |
| **minimal task registry** | 统一 task 真值、状态机、idempotency key、delivery state、evidence 索引 | 直接轮询外部系统、直接发通知 |
| **taskwatcher** | 观察外部 source-of-truth、回填状态、发 callback、做 reconcile | 持有主状态、做内部执行编排 |
| **fan-out subscribers** | follow-up、dispatch、panel、看板 | 改 registry 主状态 |

## 4.2 最小 task registry 应该只保留这些字段

| 字段 | 用途 |
|---|---|
| `task_id` | 全局稳定主键 |
| `runtime` | `subagent/browser/message/acp/external` |
| `adapter` | 外部观察器类型（如 `generic-exec` / `xhs-review`） |
| `requester_session_key` / `controller_session_key` | 谁发起、谁控制 |
| `runtime_ref` | `run_id` / `childSessionKey` / `status_file` / `session_file` / `target_object_id` |
| `current_state` / `terminal_state` / `state_version` | 统一状态机 |
| `needs_human_input` | 人审断点 |
| `delivery` | `callback_dispatched/delivered/attempts/idempotency_key/last_error` |
| `evidence` | `status_file/report_file/output_file/raw_ref` |
| `timestamps` | `created/started/ended/delivered` |

**不要**把 follow-up 配置、panel 配置、UI 展示字段、临时 bridge 状态都塞进 registry 主 schema。

## 4.3 配合方式（推荐时序）

### A. 内部 subagent 任务

1. control plane 创建 registry 记录
2. `sessions_spawn(runtime="subagent")`
3. core `subagent-registry` 更新 run 真值
4. core `subagent-announce` 负责 completion 回推
5. taskwatcher **不介入主状态推进**；最多只做 shadow observe / compatibility repair

**结论**：内部 subagent 主链不再注册到 watcher 作为 primary path。

### B. 外部异步任务 / 文件状态任务 / 外部平台审核

1. control plane 创建 registry 记录（state=`queued/running`）
2. registry 挂 `adapter + runtime_ref`
3. taskwatcher 轮询外部 source-of-truth
4. watcher 只把 `observed_state + evidence + delivery result` 回填 registry
5. terminal 事件再驱动 follow-up / panel / dispatch

**结论**：外部任务才是 taskwatcher 的标准场景。

### C. 历史兼容任务

1. 老任务仍可留在 `tasks.jsonl`
2. watcher 继续跑 compatibility adapter / content-aware reconcile
3. 新链路不再把 `tasks.jsonl` 当唯一真值
4. 待存量清空后，把 watcher store 降为 cache/compat 层

---

## 5）建议动作（P0 直接可执行）

### P0-1 文档口径立即收敛

- 所有 proposal / runbook 统一改成：
  - **subagent = 默认内部执行主链**
  - **taskwatcher = external watcher / callback plane**
  - **registry = state-of-truth**
- 删除任何“taskwatcher 是 backbone 候选/默认主链”的表述

### P0-2 新增一条硬规则

- **禁止新内部 `sessions_spawn(runtime="subagent")` 流程继续注册到 taskwatcher 作为 primary tracking path**
- 如果确实要接 watcher，只能是：
  - shadow observe
  - legacy compatibility
  - external async adapter

### P0-3 watcher 包内职责拆分

建议把 `skills/task_callback_bus/` 按边界拆成三类：

1. **watcher-core（保留）**
   - `bus.py`
   - `adapters.py`
   - `notifiers.py`
   - `dead_letter_queue.py`
   - `content_aware_completer.py`

2. **fan-out bridges（保留但降级）**
   - `terminal_bridge.py`
   - `discord_panel_bridge.py`

3. **control-plane pieces（迁出）**
   - `agent_request_store.py`
   - `agent_request_models.py`
   - `completion_bus.py`
   - `completion_consumer.py`
   - `agent_comm_guardrail.py`

### P0-4 建最小 registry，而不是继续扩 `CallbackTask`

- 不要再往 `CallbackTask` 里堆控制面字段
- `CallbackTask` 只保留 watcher 观察/通知所需最小字段
- 新的统一 schema 以 `orchestration_task` / `task_registry` 为准

### P0-5 generic-exec 明确降级为 compatibility adapter

当前 `GenericExecAdapter` 还在监控：
- `exec_command`
- `sessions_spawn`
- `file_state`

建议改口径：
- `exec_command` / `file_state`：**保留**（外部/文件型任务很好用）
- `sessions_spawn`：**不再作为新主链默认方案**，仅兼容历史 status_file/output_file 流程

---

## 最终一句话

**taskwatcher 该留下的是“看外部状态 + 发回执 + 做补账”；该拿掉的是“当内部主链、当统一真值、当实时协作控制面”。**
