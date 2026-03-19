# P0.5-2《callback_status 真值语义固化》

## 0. 目标

这份文档只固化一件事：**`callback_status` 表示 final callback 的真实发送/确认状态，不表示任务执行状态。**

必须分清两层真值：

- **任务是否已经收敛**：看 `state`
- **final callback 是否真的发出/被确认**：看 `callback_status`

P0.5 的硬约束：

> `callback_status` 只能在 **final callback 真发出后**，才从 `pending` 变成 `sent / acked / failed`。
>
> **禁止**把“任务完成”“subagent 终态到了”“报告已写出”误写成“callback 已完成”。

---

## 1. 先定死语义边界

### 1.1 `state` 回答什么问题

`state` 只回答：**任务执行链本身是否收敛**。

例如：

- `queued`
- `running`
- `waiting_human`
- `completed`
- `failed`
- `degraded`

其中：

- `completed / failed / degraded` = 任务终态

### 1.2 `callback_status` 回答什么问题

`callback_status` 只回答：**上游/调用方的 final callback 到底发没发、是否确认、是否发送失败。**

固定枚举：

- `pending`：还没发 final callback，或尚未进入 callback 发送动作
- `sent`：final callback 已真实发出，但还没有 receipt / ack
- `acked`：上游已确认收到 final callback
- `failed`：已经尝试发送 final callback，但发送失败

### 1.3 两者必须解耦

以下情况都允许存在，而且是**正确状态**：

- `state = completed` + `callback_status = pending`
- `state = failed` + `callback_status = pending`
- `state = degraded` + `callback_status = pending`

这表示：

> **任务已经收敛，但 final callback 还没真正发出去。**

这不是 bug；相反，把这种状态提前写成 `sent/acked` 才是 bug。

---

## 2. 真值规则（P0.5 冻结版）

## 2.1 核心规则

1. 创建任务时，默认：`callback_status = pending`
2. 任务运行中，保持：`callback_status = pending`
3. child/subagent 到 terminal 时，仍然保持：`callback_status = pending`
4. 只有执行了 **final callback 发送动作**，才允许把 `pending` 改成：
   - `sent`：发送成功但未确认
   - `failed`：发送动作执行了，但发送失败
5. 只有拿到上游 receipt / ack，才允许：`sent -> acked`
6. **不允许**出现：
   - `pending -> acked`（跳过真实发送）
   - 在 `child terminal ingest` 阶段把 `pending -> sent`
   - 因为 `state=completed` 就把 `callback_status` 改成 `sent/acked`
   - 因为报告文件存在，就把 `callback_status` 改成 `sent/acked`

## 2.2 一句话判断法

如果你问的是：

- “任务做完了吗？” → 看 `state`
- “调用方收到最终回执了吗？” → 看 `callback_status`

**不要混用。**

---

## 3. 状态流转表

| 阶段/事件 | `state` | `callback_status` | 是否允许改变 `callback_status` | 说明 |
|---|---|---|---|---|
| task created | `queued` | `pending` | 否 | 初始态，尚未发生 callback |
| task running | `running` | `pending` | 否 | 仍在执行，不谈 callback 完成 |
| waiting human | `waiting_human` | `pending` | 否 | 人工闸门不等于 callback |
| child/subagent terminal ingested | `completed` / `failed` / `degraded` | `pending` | 否 | 只代表任务终态已成立，不代表 callback 已发 |
| report/evidence written | terminal | `pending` | 否 | 产物存在 ≠ callback 已发 |
| final callback send succeeded | terminal | `sent` | 是 | 这是 `pending -> sent` 的唯一合法时机 |
| callback receipt confirmed | terminal | `acked` | 是 | 只允许 `sent -> acked` |
| final callback send failed | terminal | `failed` | 是 | 这是 `pending -> failed` 的合法时机 |

---

## 4. 允许的最小流转

## 4.1 正常成功链路

```text
queued/pending
-> running/pending
-> completed/pending
-> completed/sent
-> completed/acked
```

含义：

1. 任务完成
2. 但 callback 还没发，所以仍是 `pending`
3. final callback 真发出后，才变 `sent`
4. 上游确认后，才变 `acked`

## 4.2 终态已成立，但 callback 还没发

```text
queued/pending
-> running/pending
-> failed/pending
```

这条链路本身**完全合法**。它只表示：

- 任务已经失败收敛
- 但 failure final callback 还没有真正发送

## 4.3 callback 发送失败

```text
queued/pending
-> running/pending
-> degraded/pending
-> degraded/failed
```

含义：

- 任务终态 = `degraded`
- Lobster/控制层尝试发 final callback
- 但发送动作失败
- 所以 `callback_status = failed`

注意：这里的 `failed` 是 **callback delivery failed**，不是任务执行失败。

---

## 5. 错误案例（禁止）

## 5.1 错误：把任务完成误写成 callback 已发送

### 错误流转

```text
queued/pending
-> running/pending
-> completed/sent
```

如果这个 `sent` 发生在“subagent 终态 ingest”或“任务完成”那一刻，而不是发生在真正的 callback send step，语义就是错的。

### 为什么错

因为它表达成了：

> “调用方已经收到最终回执”

但事实只是：

> “任务已经完成，callback 还没发。”

---

## 5.2 错误：报告文件写出来就算 callback 已完成

### 错误流转

```text
running/pending
-> completed/pending
-> report_file exists
-> completed/acked
```

### 为什么错

`report_file` / `final-summary.json` / `artifact` 只证明：

- 执行有产物
- 终态可验收

它们**不能证明**：

- final callback 已发送
- 上游已确认收到

---

## 5.3 错误：`pending -> acked` 直跳

### 错误流转

```text
completed/pending
-> completed/acked
```

### 为什么错

除非系统能证明“发送与确认是同一原子动作，并且中间 send 成功已真实发生”，否则 P0.5 默认禁止跳过 `sent`。

P0.5 的推荐口径是：

```text
pending -> sent -> acked
```

如果没有 receipt，停在 `sent` 即可。

---

## 5.4 错误：把 subagent 结束当成 callback 完成

### 错误说法

- “subagent 回来了，所以 callback_status=acked”
- “child 终态到了，所以 callback_status=sent”

### 为什么错

subagent 结束只代表：

- child 工作结束
- terminal evidence 可回写

它**不代表**：

- Lobster/控制层已经执行 final callback
- 更不代表上游已经确认收到

---

## 6. 正确案例（推荐）

## 6.1 正确：先落终态，再发 final callback

```text
queued/pending
-> running/pending
-> completed/pending
-> completed/sent
-> completed/acked
```

对应动作顺序：

1. child 完成
2. registry 写 `state=completed`
3. evidence / report / summary 落盘
4. 执行 final callback send
5. send 成功后写 `callback_status=sent`
6. 如有 receipt，再写 `callback_status=acked`

## 6.2 正确：失败任务也要走 callback 真值

```text
queued/pending
-> running/pending
-> failed/pending
-> failed/sent
```

这表示：

- 任务失败结束
- 但失败结果已经真实回报给上游

这里 `sent` 不是“任务成功”，只是“final callback 已发出”。

## 6.3 正确：callback send 失败要诚实记 `failed`

```text
queued/pending
-> running/pending
-> degraded/pending
-> degraded/failed
```

这表示：

- 任务以 `degraded` 收敛
- 系统尝试发 final callback
- 但 callback send 自身失败

这是诚实状态，不是坏状态；坏状态是明明没发出去却写 `sent/acked`。

---

## 7. 最小实现守则

## 7.1 写代码时的 guardrail

可以直接按下面规则实现：

```text
if final callback send step 尚未执行:
    callback_status 必须保持 pending

if final callback send step 执行成功:
    callback_status = sent

if sent 之后拿到明确 receipt:
    callback_status = acked

if final callback send step 执行过但失败:
    callback_status = failed
```

## 7.2 禁止的 shortcut

禁止以下 shortcut：

- `if state in terminal: callback_status = sent`
- `if report_file exists: callback_status = acked`
- `if child_session ended: callback_status = sent`
- `if summary generated: callback_status = acked`

这些都是把“执行完成”偷换成“回执完成”。

---

## 8. 验收口径

对任何一条 P0/P0.5 链路，只问 3 个问题：

1. **任务终态是否成立？**
   - 看 `state`
2. **final callback 是否真的发出？**
   - 看 `callback_status in [sent, acked]`
3. **是否只是任务做完，但还没回报？**
   - 看 `state in [completed, failed, degraded] && callback_status = pending`

若出现以下情况，一律按语义 bug 处理：

- 没执行 callback send，却把 `callback_status` 改成 `sent/acked`
- 把 child terminal / report generated / task completed 当成 callback 已完成

---

## 9. 配套样例与最小校验

- 状态样例：`examples/callback-status-transitions.json`
- 最小校验测试：`tests/test_callback_status_semantics.py`

这两个文件的目的不是做平台级 engine，而是把 P0.5 的语义冻结成**可读样例 + 可跑校验**，防止后续再把“任务完成”误写成“callback 完成”。
