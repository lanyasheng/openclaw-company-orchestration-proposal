# Waiting Integrity / Hard-Close / Fail-Fast Policy（2026-03-21）

## 结论先行

WS3 暴露的问题不是“某次 roundtable 偶发卡住”，而是 **waiting 合法性没有被架构化约束**：

- 上层把“已经派发过”误当成“现在仍有人在跑”；
- waiting 没有强绑定到可验证的 leaf run；
- leaf 失败/超时/掉线后，没有强制 hard-close closeout；
- heartbeat 只看到外环现象，没有把“等待但 active=0”升级为主链异常。

因此，从现在开始收口的正式口径是：

1. **waiting 不是意图字段，而是活跃等待绑定（active wait binding）。**
2. **任何 waiting 都必须绑定可验证的 `task_id / run_handle / last_seen / expected_artifacts`。**
3. **失败、超时、掉线、终态缺 artifact 都必须触发 hard-close closeout，不允许无限挂着。**
4. **external dependency 必须在进入 workflow 前声明等级：`best-effort / degraded / fatal`。**
5. **heartbeat 仍不是主链 owner；它只负责发现异常、告警、请求重查，不负责写业务终态。**

> WS3 只是事故样本；本文重点是机制约束，不是事故复盘。

---

## 1. 真值

### 1.1 为什么会出现“等待但没人跑”

出现假 waiting 的根因，是系统把 **“曾经成功 dispatch”** 误写成了 **“当前仍存在合法等待”**。

具体表现为：

- parent step 进入 waiting，但没有持续绑定到一个仍可解析的 child run；
- child 已终止、掉线、超时或从 active set 消失；
- parent 没有在 failure/timeout 后做 hard-close；
- 外环 heartbeat 没有把 `waiting + active=0` 提升为非法状态。

所以“等待但没人跑”的本质不是展示问题，而是：

> **控制面缺少一条‘waiting 必须对应可验证活跃 waiter’的硬约束。**

### 1.2 从架构上，waiting 的真值是什么

从本 policy 起，waiting 只表示：

> **控制面当前有一个尚未 closeout 的等待绑定，并且这个绑定仍能被 source-of-truth 验证。**

如果做不到这件事，状态就不是合法 waiting，而是：

- dispatch 失败未收口；
- terminal 丢失未收口；
- timeout 未收口；
- 异常 dangling state。

### 1.3 Waiting 的最小合法绑定

任何 workflow / task / step 想暴露 waiting，必须同时持有最小 `wait_binding`：

```json
{
  "task_id": "tsk_xxx",
  "workflow_id": "workflow.v1",
  "step_id": "await_terminal",
  "wait_kind": "subagent_terminal|human|external",
  "run_handle": "child_session_key|job_id|request_id",
  "last_seen_at": "2026-03-21T16:00:00Z",
  "expected_artifacts": [
    "terminal.json",
    "final-summary.json"
  ],
  "timeout_at": "2026-03-21T16:30:00Z",
  "dependency_class": "best-effort|degraded|fatal",
  "source_of_truth": "subagent-core|human-gate|external-adapter"
}
```

其中以下字段为 **硬必填**：

- `task_id`
- `run_handle`
- `last_seen_at`
- `expected_artifacts`

没有这 4 个字段，不得宣称 waiting 合法成立。

### 1.4 合法 waiting 的判定条件

一个 waiting 只有同时满足以下条件才合法：

1. `wait_binding` 完整存在；
2. `run_handle` 仍能被 source-of-truth 解析；
3. `last_seen_at` 仍在 freshness window 内；
4. `expected_artifacts` 已声明，不是事后猜；
5. `timeout_at` 已定义；
6. 该等待对应的 closeout owner 明确存在；
7. 没有被 terminal / timeout / anomaly rule 判定为应强制收口。

任何一条不满足，都不是“继续等”，而是“必须收口”。

---

## 2. 规则

### 2.1 Waiting 合法性约束（硬规则）

**R1. 没有 `wait_binding`，就没有 waiting。**

- dispatch 成功回执本身不足以证明后续 waiting 合法；
- 历史上一次的 waiting marker 不得复用到新 run；
- 重新 dispatch 必须生成新的 `run_handle` 与新的 waiting 绑定。

**R2. waiting 必须绑定单一 waiter。**

- 一个 waiting slot 只能对应一个当前生效的 `run_handle`；
- 如果切换 child run，必须先 hard-close 旧 binding，再创建新 binding；
- 不允许多个 leaf run 共享一个模糊 waiting 说明。

**R3. waiting 必须能回答“在等谁、最近一次看到它是什么时候、在等什么产物”。**

至少必须可追问并得到：

- 在等哪个 `task_id/run_handle`
- 最近一次 `last_seen_at`
- 期待哪些 artifact / terminal signal
- 超时点 `timeout_at`

如果任何一个问题答不出来，waiting 即视为非法。

### 2.2 Hard-close 规则（硬规则）

**R4. 失败、超时、掉线、终态缺 artifact，必须 hard-close。**

hard-close 的最小动作固定为：

1. 清除当前 `wait_binding`；
2. 写入 terminal/degraded/failed closeout；
3. 落盘异常证据（terminal、timeout、missing artifact、lookup miss 等）；
4. 明确 `stopped_because / next_step / next_owner`；
5. 禁止继续以原 waiting 继续展示。

**R5. hard-close 必须 exactly-once 地结束当前 waiting slot。**

- 同一个 waiting 不能在 timeout 后继续保留为 waiting；
- 同一个 waiting 不能既保留 old binding，又创建 new binding；
- 没有新的 dispatch 证据，不得从 hard-closed waiting 重新变回 waiting。

**R6. “没有收到成功终态” 不等于 “可以继续等”。**

如果超时、lookup miss、active=0、artifact 缺失已经成立，默认动作是 hard-close，而不是延长等待。

### 2.3 Fail-fast / fallback / degraded 规则

外部依赖或 leaf dependency 在接入前，必须声明依赖等级：

| 等级 | 语义 | 失败/超时默认动作 | 是否允许继续等待 |
|---|---|---|---|
| `best-effort` | 可跳过，不影响主结论成立 | 记录 skip/fallback evidence；若 fallback 已定义则继续，否则收口为 `degraded` | **不允许**无限等待 |
| `degraded` | 失败后主链可降级继续，但结果必须带缺口说明 | bounded timeout 后 hard-close 为 `degraded` 或进入显式 fallback step | **不允许**无限等待 |
| `fatal` | 缺失即主链不成立 | launch reject / failure / timeout 立即 fail-fast，hard-close 为 `failed` | **不允许** |

补充约束：

**R7. fail-fast 是默认安全动作，不是异常选项。**

- 对 `fatal` 依赖，发不出去、看不到、等超时，都直接进入 failure closeout；
- 不允许把 fatal dependency 的缺失伪装成 waiting。

**R8. degraded/fallback 必须显式，不得口头化。**

- 如果声称“可降级”，必须有明确 fallback step 或 fallback artifact；
- 没有 fallback 证据时，不得用“degraded”掩盖实际无收口。

### 2.4 Anomaly waiting detection（硬规则）

以下任一情况成立，即判定为 **anomalous waiting**：

1. `waiting = true`，但 active task / active run = 0；
2. `run_handle` 无法解析或 source-of-truth lookup miss；
3. `now - last_seen_at > freshness_window`；
4. 已到 `timeout_at` 仍未 closeout；
5. terminal 已到，但 `expected_artifacts` 在 grace period 内仍缺失；
6. waiting 记录缺少 `task_id / run_handle / last_seen_at / expected_artifacts` 任一必填字段。

异常 waiting 的处理固定为：

1. 标记 anomaly evidence；
2. 发出 reconcile / closeout 请求；
3. 由主链 owner 执行 hard-close；
4. 后续若需重试，必须以新 dispatch / 新 binding 开新等待。

### 2.5 Heartbeat / outer governance 边界

**R9. heartbeat 不是 waiting 的 state owner。**

heartbeat 可以做：

- 发现 `waiting + active=0`
- 发现 no heartbeat / no artifact / timeout
- 发告警
- 发 reconcile 请求
- 催办 closeout owner

heartbeat 不可以做：

- 直接把 waiting 改写成 completed/degraded/failed；
- 直接 dispatch 下一跳；
- 代替主链决定 fallback；
- 覆盖 closeout owner。

一句话：

> **heartbeat 是治理外环，不是 continuation 主链。**

---

## 3. Rollout

### 3.1 文档冻结（立即）

1. 本文成为 waiting / hard-close / fail-fast / anomaly waiting 的正式口径；
2. CURRENT_TRUTH 只保留一句总口径：**先修机制，再处理个案**；
3. 后续 roundtable / trading / external adapter 文档，引用本文而不是各写一套 waiting 解释。

### 3.2 Runtime / schema 收口（下一批必须做）

1. 在 registry / scheduler evidence 中补齐显式 `wait_binding`；
2. 设置 waiting 前，强校验 `task_id / run_handle / last_seen_at / expected_artifacts`；
3. 为 `subagent_terminal / human / external` 统一 timeout 与 hard-close 入口；
4. external adapter 必须显式声明 `dependency_class`；
5. closeout 写入 continuation contract，不再允许 dangling waiting。

### 3.3 观测与治理（下一批必须做）

1. 增加 anomaly rule：
   - `waiting + active=0`
   - `waiting + no heartbeat`
   - `waiting + no artifact`
   - `waiting + timeout`
2. heartbeat 只负责告警与重查请求；
3. 主链 reconcile / closeout owner 负责最终 hard-close。

### 3.4 存量迁移（按 workflow 批次）

1. 先迁 `trading_roundtable` / `channel_roundtable` / subagent await_terminal；
2. 再迁 external-like adapter；
3. 不满足本文约束的 waiting，统一视为 historical debt，而不是合法设计。

---

## 4. 对 WS3 的正式解释

WS3 之所以会出现“上层在等，但 active task=0，leaf task 已掉线”，原因不是系统不会看 active task，而是：

1. waiting 没有被定义成 **活跃绑定**，只被当成“上次 dispatch 后的状态描述”；
2. leaf 消失后，没有 hard-close 把 waiting 收口；
3. external/outer governance 没有把 `waiting + active=0` 升级为异常等待。

以后从架构上禁止这类问题的方式也很直接：

- **没有绑定，不许 waiting；**
- **绑定失真，立即 anomaly；**
- **异常/超时/失败，强制 hard-close；**
- **heartbeat 只告警，不代替主链写状态。**

这就是“为什么会出现等待但没人跑”，以及“以后如何从架构上禁止”。

---

## 5. 一句话口径

**waiting 必须对应一个仍可验证的活跃 waiter；一旦 waiter 不可验证，就不是继续等，而是必须 hard-close。**
