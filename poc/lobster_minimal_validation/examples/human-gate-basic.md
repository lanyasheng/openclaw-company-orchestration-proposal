# human-gate-basic

## 结论先行

这条样例已演示 **waiting_human → 读取统一 decision payload → 恢复/收尾** 的最小真实闭环。当前仍是 repo-local，不接真实 message/browser provider；但 verdict、actor、source、resume_token 已统一到同一份 payload 契约。

## 输入

任务输入：`poc/lobster_minimal_validation/inputs/human-gate-basic.json`

```json
{
  "task_id": "tsk_p0_human_001",
  "change": "deploy-demo",
  "requires_approval": true,
  "resume_token": "lobster_resume_tsk_p0_human_001",
  "request_transport": "file",
  "request_source_ref": "local://human-gate/request/tsk_p0_human_001",
  "approval_prompt": "是否批准 deploy-demo?",
  "timeout_ms": 1800000
}
```

decision payload 样例：`poc/lobster_minimal_validation/inputs/human-gate-decision-approve.json`

```json
{
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

## 运行命令

批准路径：

```bash
python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-approve.json
```

拒绝路径：

```bash
python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-reject.json
```

超时路径：

```bash
python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-timeout.json
```

撤回路径：

```bash
python3 -m poc.lobster_minimal_validation.run_poc human-gate \
  --input poc/lobster_minimal_validation/inputs/human-gate-basic.json \
  --decision-file poc/lobster_minimal_validation/inputs/human-gate-decision-withdraw.json
```

## 步骤

1. 创建 registry，进入 `queued`
2. 运行 `precheck`
3. 生成 `evidence.human_gate.request`
4. 状态切到 `waiting_human`
5. 从 `--decision-file` 读取统一 decision payload
6. 校验 `task_id + resume_token`
7. 按 `verdict` 分支：
   - `approve` → `running(runtime=lobster)` → `completed`
   - `reject` → `degraded(runtime=human)`
   - `timeout` → `failed(runtime=human)`
   - `withdraw` → `degraded(runtime=human)`
8. 发送一次 `final_callback`

## 预期输出

- `registry.json` 中能看到 `waiting_human`
- `evidence.human_gate.request/decision/resolution` 三段齐全
- `evidence.human_gate.decision.verdict` 不再来自 CLI 字符串
- 批准路径：`callback.json.result = completed`
- 拒绝路径：`callback.json.result = degraded`
- 超时路径：`callback.json.result = failed`
- 撤回路径：`callback.json.result = degraded`

参考样例目录：
- `poc/lobster_minimal_validation/expected/human-gate-approve/`
- `poc/lobster_minimal_validation/expected/human-gate-reject/`
- `poc/lobster_minimal_validation/expected/human-gate-timeout/`
- `poc/lobster_minimal_validation/expected/human-gate-withdraw/`
