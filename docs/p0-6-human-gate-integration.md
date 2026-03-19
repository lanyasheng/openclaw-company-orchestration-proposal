# P0.6-2 human-gate 最小真实集成（repo-local）

## 1. 目标

在 `poc/lobster_minimal_validation/` 内，把 human-gate 从“直接吃 CLI `--decision approve|reject`”推进到**统一 decision payload 驱动**的最小真实闭环。

这一步仍然是 **repo-local harness**：

- 不接真实 `message` provider
- 不接真实 `browser` provider
- 只用 JSON 文件模拟“外部人工决定已被归一化”这件事

但 P0.6 已做到：

1. `run_poc.py` 真正从 `--decision-file` 读取 payload
2. `poc_runner.py` 真正校验 `task_id + resume_token`
3. `approve / reject / timeout / withdraw` 四种 verdict 都走统一 resolver
4. `minimal task registry` 顶层 6 字段不变，细节全部写进 `evidence.human_gate`

---

## 2. 与 P0.5 契约的关系

P0.5 文档定义的是**真实 provider 目标契约**：未来 `message` / `browser` 都应产出同一份 decision payload。

P0.6 这次做的是中间层接线：

- 先不证明 provider 能发出 payload
- 先证明**只要 provider 给了 payload**，registry / runtime / callback / verdict 分支就能正确收敛

所以这里新增一个 repo-local 约束：

- `source.transport` 在 POC 中允许写 `file`
- `source.ref` 指向 decision payload 文件路径

等真实 provider 接入时，只需要把：

- `transport=file` 替换成 `message` 或 `browser`
- `ref=<file path>` 替换成真实消息引用或页面引用

状态机和 registry 写法**不用再改第二遍**。

---

## 3. 当前实现口径

### 3.1 输入

`human-gate` workflow 现在需要两份输入：

1. 任务输入：`inputs/human-gate-basic.json`
2. 决策输入：`inputs/human-gate-decision-*.json`

运行方式：

```bash
python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-approve.json
```

### 3.2 request 侧落点

进入 `waiting_human` 前，runner 会生成并落库：

```json
{
  "human_gate": {
    "request": {
      "transport": "file",
      "resume_token": "lobster_resume_tsk_p0_human_001",
      "timeout_ms": 1800000,
      "prompt": "是否批准 deploy-demo?",
      "source_ref": "local://human-gate/request/tsk_p0_human_001",
      "driver": "decision-payload-file",
      "native": false,
      "requested_at": "2026-03-19T08:31:00Z"
    }
  }
}
```

### 3.3 decision 侧落点

adapter 读取 `--decision-file` 后，归一化到：

```json
{
  "adapter": "human-decision-payload-file",
  "native": false,
  "decision_id": "dec_20260319_approve_0001",
  "task_id": "tsk_p0_human_001",
  "resume_token": "lobster_resume_tsk_p0_human_001",
  "verdict": "approve",
  "source": {
    "transport": "file",
    "ref": "poc/lobster_minimal_validation/inputs/human-gate-decision-approve.json"
  },
  "actor": {
    "id": "user_boss",
    "name": "老板"
  },
  "decided_at": "2026-03-19T08:31:12Z",
  "reason": "批准演示环境发布"
}
```

### 3.4 resolution 侧落点

四条 verdict 统一写到 `evidence.human_gate.resolution`：

| verdict | registry 终态 | resolution.status | callback.result |
|---|---|---|---|
| `approve` | `completed(runtime=lobster)` | `resumed` | `completed` |
| `reject` | `degraded(runtime=human)` | `rejected` | `degraded` |
| `timeout` | `failed(runtime=human)` | `timed_out` | `failed` |
| `withdraw` | `degraded(runtime=human)` | `withdrawn` | `degraded` |

---

## 4. 与 minimal task registry 的对齐

### 4.1 顶层字段保持冻结

仍然只有：

- `task_id`
- `owner`
- `runtime`
- `state`
- `evidence`
- `callback_status`

### 4.2 human-gate 细节全部下沉到 evidence

推荐最小结构：

```json
{
  "input": {...},
  "precheck": {...},
  "human_gate": {
    "request": {...},
    "decision": {...},
    "resolution": {...}
  }
}
```

这样可以同时满足：

- registry 顶层不扩容
- `waiting_human` 有证据可查
- 终态能看出是 `reject / timeout / withdraw` 哪一类，而不是只剩一个笼统 state

---

## 5. 最小验证点

本轮代码层面的最小验收：

- [x] `run_poc.py` 改成 `--decision-file`
- [x] adapter 从 payload 读取 verdict，而不是直接吃 CLI 字符串
- [x] 支持 `approve / reject / timeout / withdraw`
- [x] 校验 `task_id + resume_token`
- [x] `evidence.human_gate.request/decision/resolution` 三段齐全
- [x] 最小测试覆盖 4 条 verdict 分支和 decision-file 读取

---

## 6. 下一步怎么接真实 provider

当后续进入 P0.7 / P1 时，真实接线只需要做两件事：

1. **message/browser 负责产出统一 payload**
   - 填好 `decision_id / task_id / resume_token / verdict / source / actor / decided_at`
2. **继续复用当前 runner + adapter 的状态机**
   - 不再回退成 `if --decision == approve`
   - 不再另造第二套 approval registry

换句话说，P0.6 解决的是：

> human-gate 下游已经不再依赖“CLI 字符串”，而是依赖稳定的 decision payload 契约。

这就是从“纯 stub”跨到“最小真实闭环”的关键边界。
