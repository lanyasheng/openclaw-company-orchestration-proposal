# O1 / human-gate -> message 最薄真实接线交付说明

基线：`21d3556 docs: add p0 final readiness review`

## 1. 本轮目标

只做一件事：让 **message 侧** 能产出与 P0.6 已冻结契约一致的 **同一份 decision payload**，并证明 `poc/lobster_minimal_validation/` 这条下游消费链无需改 schema 就能继续消费。

## 2. 本轮做到的范围

### 2.1 message 侧真实最薄输出

在现有 `plugins/human-gate-message/` 上补了一层最薄 Lobster 对齐：

- 支持在拦截的 message args 里携带可选 `humanGate` 上下文：
  - `taskId`
  - `resumeToken`
  - `sourceRef`
  - `sourceTransport`
  - `prompt`
- 当 decision 进入终态（`approved/rejected/timeout/withdrawn`）后，插件会自动输出：

```text
<storageDir>/decision-payloads/<decisionId>.json
```

这份 JSON 的字段口径与现有 POC/adapter 契约对齐：

- `decision_id`
- `task_id`
- `resume_token`
- `verdict`
- `source.transport`
- `source.ref`
- `actor.id`
- `decided_at`
- `reason`（可选）

### 2.2 POC 下游零 schema 漂移消费

`poc/lobster_minimal_validation/` 的核心 runner / adapter 未扩 schema。

只补了 targeted tests，证明同一份 payload 在 `source.transport=message` 时仍可直接被消费：

- approve → `completed`
- reject → `degraded`

### 2.3 手动检查入口

插件 CLI 新增：

```bash
node plugins/human-gate-message/cli.js payload <decisionId>
```

用于直接查看归一化后的 decision payload。

## 3. 本轮明确没做的范围

以下都 **没有做**，故意留到后续：

1. **不扩 browser**
2. **不做 O2 subagent terminal + final callback send/ack 薄接线**
3. **不做完整 runtime glue**（按钮/UI/webhook/message 实发审批面）
4. **不改 minimal task registry 顶层 schema**
5. **不做第二套 approval registry / 不把 verdict 语义抬到顶层字段**
6. **不做 delivery retry / outbox / 并发审批面治理**

## 4. 关键设计取舍

### 4.1 为什么把接线放在插件侧

因为本仓里现成且最接近真实 message 接口路径的抽象，就是 `plugins/human-gate-message/`：

- 它已经代表真实 `message` 工具拦截点
- 它已经有 decision 持久化与 verdict 更新路径
- 在这里补统一 payload 导出，能最小复用现有资产

### 4.2 为什么仍然保留 `run_poc.py --decision-file`

这次目标不是重写 POC，而是证明：

> 只要 message 侧能产出同一份 payload，下游 runner / adapter 就不必再改第二遍。

因此选择最小策略：

- 上游：插件导出统一 payload 文件
- 下游：继续用现有 `--decision-file` 消费

## 5. 建议的下一步

### 优先级 1

把 runtime glue 补到能真正把 `humanGate` 上下文薄传入 message 调用，并让审批入口（按钮/CLI/webhook 任一）能回写插件 verdict。

### 优先级 2

进入 O2：

- 真接 `sessions_spawn(runtime="subagent")`
- 真吃 terminal/completion
- 真做 final callback send/ack
- 继续守住 `terminal != callback sent`

## 6. 回退方式

如果这条 O1 薄接线需要回退：

1. 回退 `plugins/human-gate-message/` 中的 unified payload 导出改动
2. 保留 P0.6 的 repo-local `--decision-file` 路径
3. 不影响既有 `file` transport 的 human-gate POC 语义

换言之，本轮改动是可逆的；回退后只会失去 message->payload 最薄真实接线，不会破坏已通过的 P0.6 基线。
