# 状态真值锚点策略（orchestration / continuation / follow-up）

> 目的：避免把“准备做 / 待注册”说成“已经在推进”。
> 分层：TEAM_RULES 只保留核心原则；本文件承载当前架构主线的详细规则。

---

## 1. 适用范围
仅适用于以下场景：
- orchestration follow-up
- roundtable continuation
- partial continuation
- post-completion replan
- next-task registration / auto-dispatch

不要求所有普通聊天都套这里的详细字段。

---

## 2. 核心原则
**没有真值锚点，不得把计划表述成执行中。**

允许的锚点至少一项：
- `task_id`
- `batch_id`
- `runId`
- `branch`
- `commit hash`
- `push 结果`
- 明确产物路径
- 已落盘 registration / dispatch artifact

---

## 3. 允许的状态措辞

### 3.1 pending_registration / 待启动
用于：
- 只是下一步打算
- follow-up 还未注册成新任务
- 还没有 run / task / commit / artifact anchor

允许表述：
- 待启动
- pending_registration
- 下一步准备做 X
- 计划发起 X

禁止表述：
- 正在推进
- 我已经在推
- 已开始处理
- 已推进这条线

### 3.2 in_progress / 已启动
必须满足：
- 已有真值锚点
- 最好同时有活跃任务或已落盘产物

推荐表述模板：
- 已启动，锚点：`task_id=...`
- 已推进，锚点：`branch=...` / `commit=...`
- 已发起，锚点：`runId=...`

---

## 4. orchestration 主线特殊规则

### 4.1 原 dispatch plan 内的 continuation
如果属于同一 flow/batch 已注册的下一跳：
- 可以表述为 `in_progress`
- 但仍应附锚点（如 `batch_id` / `runId` / dispatch artifact）

### 4.2 原 dispatch plan 外的新 follow-up
如果是新的 docs 工作、remediation、operator-facing 交付等：
- 在注册前只能是 `pending_registration`
- 注册后才可升级为 `in_progress`

### 4.3 partial continuation v2/v3
当前阶段真实链路是：
`proposal -> registration -> auto-dispatch intent / limited execution`

因此：
- 只有 proposal：仍是 `pending_registration`
- 已 registration：可说“已注册下一批任务”，但不等于“已执行”
- 已 dispatch artifact / run：才可说“已启动下一轮”

---

## 5. 推荐回复模板

### 模板 A：待启动
> 当前后续工作仍是 `pending_registration`，还没有新的 task/run 锚点；我下一步会先完成注册，再汇报启动状态。

### 模板 B：已注册但未执行
> 下一批任务已注册，锚点：`task_id=...` / `registration_id=...`；当前还未进入执行态。

### 模板 C：已启动
> 已启动下一轮，锚点：`runId=...` / `task_id=...` / `dispatch artifact=...`。

---

## 6. 为什么下沉到这里
- TEAM_RULES 是 Core 文档，必须短
- orchestration 状态语义有场景细节，不适合塞进全局规则正文
- 这类规则应跟着 monorepo 主线演进，而不是把全局规则越堆越长

---

## 7. 当前 canonical 关联文档
- `CURRENT_TRUTH.md`
- `partial-continuation-kernel-v1.md`
- `partial-continuation-kernel-v2.md`
- runtime 下相关模块：
  - `post_completion_replan.py`
  - `partial_continuation.py`
  - `task_registration.py`
