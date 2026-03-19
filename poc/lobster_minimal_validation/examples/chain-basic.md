# chain-basic

## 结论先行

这是三条样例里最接近 Lobster 原生能力的一条：**顺序 chain 已有本地可跑实现，且不依赖 stub。**

## 输入

文件：`poc/lobster_minimal_validation/inputs/chain-basic.json`

```json
{
  "task_id": "tsk_p0_chain_001",
  "topic": "hello",
  "target": "internal-demo"
}
```

## 运行命令

```bash
python3 -m poc.lobster_minimal_validation.run_poc chain \
  --input poc/lobster_minimal_validation/inputs/chain-basic.json
```

## 步骤

1. 创建 registry，初始为 `queued`
2. 进入 `running`
3. 顺序执行 `step_a`
4. 顺序执行 `step_b`
5. 发送一次 `final_callback`
6. 收敛到 `completed`

## 预期输出

- 输出目录：`poc/lobster_minimal_validation/runs/chain/`
- `registry.json` 中可见状态轨迹：`queued -> running -> completed`
- `evidence` 至少包含：`input / step_a / step_b`
- `callback.json.result = completed`
- `callback_status = acked`

参考样例目录：`poc/lobster_minimal_validation/expected/chain-basic/`
