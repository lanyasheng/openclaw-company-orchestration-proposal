# failure-branch-basic

## 结论先行

这条样例证明了 **主链失败后仍能收敛到 fallback + final callback**；但因为 Lobster 当前未证实具备原生 failure branch，所以这里显式使用 `FailureBranchAdapterStub`，避免误报为原生能力。

## 输入

文件：`poc/lobster_minimal_validation/inputs/failure-branch-basic.json`

```json
{
  "task_id": "tsk_p0_fail_001",
  "mode": "force_fail_step_b",
  "target": "internal-demo"
}
```

## 运行命令

```bash
python3 -m poc.lobster_minimal_validation.run_poc failure-branch \
  --input poc/lobster_minimal_validation/inputs/failure-branch-basic.json
```

## 步骤

1. 创建 registry，进入 `queued`
2. 执行 `step_a` 成功
3. `step_b` 根据输入强制失败
4. 记录 `error=forced_failure_at_step_b`
5. 调用 `FailureBranchAdapterStub` 进入 fallback
6. 执行 `fallback_step`
7. 状态收敛到 `degraded`
8. 发送一次 `final_callback`

## 预期输出

- `registry.json.state = degraded`
- `evidence.step_b.status = failed`
- `evidence.failure_branch.adapter = failure-branch-stub`
- `evidence.failure_branch.native = false`
- `evidence.fallback_step.status = ok`
- `callback.json.result = degraded`

参考样例目录：`poc/lobster_minimal_validation/expected/failure-branch/`
