# P0.5-3 human-gate 真实通道契约

## 0. 范围冻结

- 目标：把当前 `HumanDecisionAdapterStub` 的 `--decision approve|reject`，替换成**真实 message/browser 输入**。
- P0.5 只做 **一份统一 decision payload**；`message` 和 `browser` 都先归一化到这份 payload，再驱动后续状态机。
- **不改** `minimal task registry` 顶层 6 字段：`task_id / owner / runtime / state / evidence / callback_status`。
- `reject / timeout / withdraw` 的细分语义，**只写进 `evidence`**；P0 不新增顶层 `timeout/cancelled` 状态。

---

## 1. 当前代码最小改动点

| 文件 | 当前 stub | 最小接线改动 |
|---|---|---|
| `poc/lobster_minimal_validation/adapters.py` | `HumanDecisionAdapterStub.resolve(decision: str)` | 改成接收统一 `decision payload`，不再只吃 CLI 字符串 |
| `poc/lobster_minimal_validation/poc_runner.py` | `run_human_gate(payload, decision: str)` | 改成 `run_human_gate(payload, decision_payload)`；把 `evidence.decision` 升级为 `evidence.human_gate.request/decision` |
| `poc/lobster_minimal_validation/run_poc.py` | `--decision approve|reject` | 改成 `--decision-file examples/human-gate-decision.json`，或由真实 message/browser adapter 回填 |

**冻结口径**：`task_id` 仍然是唯一 join key；不再新造第二套 approval registry。

补充代码归属：`human-gate-message` 插件源码放在本 repo 的 `plugins/human-gate-message/`；runtime repo 只做加载与 verdict glue。

---

## 2. message 路径怎么接

### 2.1 发起审批

- [ ] Lobster / human-gate 节点产出 `approval_request + resume_token`
- [ ] 先回写 registry：
  - `runtime=human`
  - `state=waiting_human`
  - `callback_status=pending`
  - `evidence.human_gate.request = {transport, resume_token, timeout_ms, prompt, source_ref}`
- [ ] 用 OpenClaw `message` 通道发一条审批消息（按钮或明确回复词均可）
  - 必选动作：`approve` / `reject`
  - 可选动作：`withdraw`
- [ ] 保存消息引用到 `evidence.human_gate.request.source_ref`

### 2.2 收到人工动作

- [ ] 把消息点击 / 回复事件归一化成统一 `decision payload`
- [ ] 校验 `task_id + resume_token` 是否匹配当前 `waiting_human` 任务
- [ ] 先写 `evidence.human_gate.decision = <payload>`
- [ ] 再按 `verdict` 执行：
  - `approve` → 调 Lobster resume；registry 切回 `runtime=lobster`、`state=running`
  - `reject` → 不 resume，直接收敛终态
  - `withdraw` → 关闭当前审批请求，直接收敛终态

### 2.3 message 路径最小验收

- [ ] 真发出 1 条审批消息
- [ ] 真收到 1 次人工按钮/回复
- [ ] `evidence.human_gate.request.source_ref` 有真实消息引用
- [ ] `evidence.human_gate.decision.verdict` 不再来自 CLI 参数

---

## 3. browser 路径怎么接

### 3.1 发起审批页

- [ ] 复用同一份 `approval_request + resume_token`
- [ ] 渲染一个最薄审批页/表单，只保留：
  - `task_id`
  - `resume_token`
  - `approve / reject / withdraw` 按钮
  - 可选 `reason`
- [ ] 把审批页 URL 或页面引用写入 `evidence.human_gate.request.source_ref`

### 3.2 回填决定

- [ ] 浏览器按钮提交后，后端只产出统一 `decision payload`
- [ ] **browser 不直接改 registry**；仍由同一个 human-gate adapter 统一写 registry / resume Lobster
- [ ] browser 路径和 message 路径共用同一套 verdict 映射，不再分叉状态机

### 3.3 browser 路径最小验收

- [ ] 能打开真实审批页
- [ ] 人工点击后能生成同结构 `decision payload`
- [ ] `approve` 与 `reject` 至少验证 1 条真实链路

---

## 4. decision payload 最小结构

样例：`examples/human-gate-decision.json`

```json
{
  "decision_id": "dec_20260319_0001",
  "task_id": "tsk_p0_human_001",
  "resume_token": "lobster_resume_abc123",
  "verdict": "approve",
  "source": {
    "transport": "message",
    "ref": "discord:channel:1483883339701158102:message:1483900000000000000"
  },
  "actor": {
    "id": "user_boss",
    "name": "老板"
  },
  "decided_at": "2026-03-19T08:31:12Z",
  "reason": "批准演示环境发布"
}
```

### 必填字段

| 字段 | 说明 |
|---|---|
| `decision_id` | 决定事件 id；用于幂等去重 |
| `task_id` | 必须直接对齐 minimal task registry 主键 |
| `resume_token` | 只对 `approve` 路径生效；用于恢复 Lobster |
| `verdict` | 固定枚举：`approve / reject / timeout / withdraw` |
| `source.transport` | `message` 或 `browser` |
| `source.ref` | 消息 id / 页面 URL / 表单提交 ref |
| `actor.id` | 谁做的决定；`timeout` 时可写 `system` |
| `decided_at` | 决定时间 |

### 可选字段

- `actor.name`
- `reason`

---

## 5. 超时 / 拒绝 / 撤回怎么表示

| verdict | 触发方式 | registry 终态 | evidence 必填 |
|---|---|---|---|
| `approve` | 人工批准 | `running(runtime=lobster)` → 后续 `completed` | `evidence.human_gate.decision.verdict=approve` |
| `reject` | 人工明确拒绝 | `degraded(runtime=human)` | `evidence.human_gate.decision.verdict=reject` |
| `timeout` | 到时无人处理 | `failed(runtime=human)` | `verdict=timeout` + `reason=approval_timeout` |
| `withdraw` | 请求方/系统撤回审批 | `degraded(runtime=human)` | `verdict=withdraw` + `reason=request_withdrawn` |

**P0 固定口径**：

- `reject`：按现有样例继续收敛到 `degraded`
- `timeout`：映射到 `failed`
- `withdraw`：P0 没有 `cancelled` 顶层状态，先折叠到 `degraded`
- 如果后续要区分真正的 `cancelled`，留到 P1 扩 schema

---

## 6. 与最小 task registry 如何对齐

### 6.1 顶层字段不扩容

仍然只写：

```json
{
  "task_id": "tsk_p0_human_001",
  "owner": "zoe",
  "runtime": "human",
  "state": "waiting_human",
  "evidence": {},
  "callback_status": "pending"
}
```

### 6.2 evidence 推荐结构

```json
{
  "input": {"task_id": "tsk_p0_human_001", "change": "deploy-demo"},
  "precheck": {"status": "ok"},
  "human_gate": {
    "request": {
      "transport": "message",
      "resume_token": "lobster_resume_abc123",
      "timeout_ms": 1800000,
      "prompt": "是否批准 deploy-demo?",
      "source_ref": "discord:channel:...:message:..."
    },
    "decision": {
      "decision_id": "dec_20260319_0001",
      "task_id": "tsk_p0_human_001",
      "resume_token": "lobster_resume_abc123",
      "verdict": "approve",
      "source": {"transport": "message", "ref": "discord:channel:...:message:..."},
      "actor": {"id": "user_boss", "name": "老板"},
      "decided_at": "2026-03-19T08:31:12Z"
    }
  }
}
```

### 6.3 状态机对齐

- `queued -> running(runtime=lobster) -> waiting_human(runtime=human)`
- `approve`：`waiting_human -> running(runtime=lobster) -> completed`
- `reject`：`waiting_human -> degraded(runtime=human)`
- `timeout`：`waiting_human -> failed(runtime=human)`
- `withdraw`：`waiting_human -> degraded(runtime=human)`

### 6.4 callback_status 对齐

- 进入 `waiting_human` 时：保持 `callback_status=pending`
- 只有进入终态（`completed/failed/degraded`）后，才允许 `pending -> sent -> acked`
- 不允许在 `waiting_human` 期间提前发 final callback

---

## 7. 最小落地顺序

1. [ ] 先把 `run_poc.py` 的 `--decision` 改成 `--decision-file`
2. [ ] 再把 `adapters.py` 改成接收统一 `decision payload`
3. [ ] 在 `poc_runner.py` 中把 `evidence.decision` 升级为 `evidence.human_gate.request/decision`
4. [ ] 先接一条真实 `message` 路径
5. [ ] 再接一条真实 `browser` 路径，但仍复用同一 payload / 同一 resolver

**验收标准**：不再出现 “decision 来自 CLI 字符串”；必须能看到真实 `source.transport + source.ref + actor.id + decided_at`。
