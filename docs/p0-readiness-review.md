# P0 / P0.5 / P0.6 readiness 收口审查

## 结论先行

**结论：暂不通过。**

当前仓库已经完成 **repo-local proof**，足以证明 P0/P0.5 的核心假设不是空图；但 **还不具备直接进入真实 OpenClaw 集成** 的条件。原因有两条：

1. **关键真实接线仍是 stub**：human-gate、failure-branch、subagent terminal、final callback delivery 都还没变成真实 OpenClaw 通道。
2. **当前 HEAD 不是绿色**：`HumanDecisionAdapterStub` 已切到 P0.6 的 `decision payload` 口径，但 `poc_runner.py` / `run_poc.py` / `tests` / 示例文档仍停留在旧的 `--decision approve|reject` 口径，导致 human-gate 用例报错。

> 可进入下一步，但下一步只能是“补齐最薄真实接线”，不能再继续扩范围。

---

## 1）现在已经验证了什么

### 已验证（有代码/测试/样例产物）

- **chain 最小闭环成立**
  - 顺序执行、evidence 落盘、final callback 只发一次的本地 harness 已有。
  - 证据：`poc/lobster_minimal_validation/`、`tests/test_lobster_minimal_validation.py`
- **failure-branch 至少能以显式 stub 收敛**
  - 主链失败后可进入 fallback，并以 `degraded` 结束，不会假装成 Lobster 原生能力。
  - 证据：`FailureBranchAdapterStub` + 对应用例/expected 输出
- **callback_status 真值语义已冻结**
  - 已证明：`state` 与 `callback_status` 必须解耦；terminal 不等于 callback 已发。
  - 证据：`docs/p0-5-callback-status.md`、`examples/callback-status-transitions.json`、`tests/test_callback_status_semantics.py`
- **subagent bridge 的 repo-local 最小闭环成立**
  - 已证明：`child_session_key -> task_id` 反查、`await_terminal` 真解阻、terminal evidence 回写 registry、且 terminal 后 `callback_status` 仍保持 `pending`。
  - 证据：`docs/p0-5-bridge-simulator.md`、`poc/subagent_bridge_sim/`、`tests/test_subagent_bridge_sim.py`
- **human-gate 的统一 decision payload 契约已经写清楚**
  - `resume_token / source.ref / actor.id / decided_at` 的最小结构已经定稿。
  - 证据：`docs/p0-5-human-gate-contract.md`、`examples/human-gate-decision.json`

### 当前实测结果

- 通过：
  - `python3 -m unittest tests.test_callback_status_semantics tests.test_subagent_bridge_sim`
  - `python3 -m unittest tests.test_lobster_minimal_validation.LobsterMinimalValidationTest.test_chain_completes_and_callback_only_once tests.test_lobster_minimal_validation.LobsterMinimalValidationTest.test_failure_branch_degrades_with_stub`
- 未通过：
  - `python3 -m unittest tests.test_lobster_minimal_validation tests.test_callback_status_semantics tests.test_subagent_bridge_sim`
  - 失败点：human-gate 2 个用例报 `TypeError`（adapter 新旧口径未接齐）

---

## 2）哪些仍是 stub

- **human-gate 真实输入通道**：还没接真实 `message` / `browser`；当前只是 repo-local payload / 旧 CLI 参数混用。
- **failure-branch 原生语义**：仍是 `FailureBranchAdapterStub`，尚未证明 Lobster 原生 error branch/fallback。
- **subagent 真桥接**：当前只是 sample JSON 模拟 `sessions_spawn` 与 terminal ingest，不是真实 gateway / `subagent_ended`。
- **final callback 真发送/确认**：当前只有本地 `callback.json` 与语义样例，未接真实 send/ack plane。
- **parallel / 真 join**：仍不在已验证范围内。

---

## 3）是否具备进入真实 OpenClaw 集成（非 repo-local prototype）的条件

**结论：还不具备。**

准确说法是：

- **具备“进入最薄真实接线阶段”的前提材料**；
- **不具备“现在就开始真实集成并宣称 ready”的条件**。

卡点不是方向错误，而是 **最后 1 层接线还没打通，且当前 HEAD 还有断点**。在 human-gate 口径重新打绿之前，不应进入更大范围集成。

---

## 4）若继续推进，下一步只应做哪 2 件事

### 只做这 2 件事

1. **打通一条真实 human-gate/message 链**
   - 统一 `adapters.py`、`poc_runner.py`、`run_poc.py`、tests、examples 到同一份 `decision payload` 口径；
   - 先只接 `message`，不要同时开 browser；
   - 验收标准：不再依赖 `--decision approve|reject`，并且 human-gate 测试重新全绿。

2. **把 subagent bridge 从 sample JSON 升级为一条真实 OpenClaw 薄接线**
   - 真调 `sessions_spawn(runtime="subagent")`；
   - 真吃 terminal/completion 回写 registry；
   - 继续遵守 P0.5 语义：**terminal 成立后仍是 `callback_status=pending`，只有真实 final callback send/ack 才推进状态。**

---

## 收口口径

**P0/P0.5 已证明“方向对”；P0.6 当前只证明“契约开始落地”，还没证明“真实接线完成”。**

所以这轮收口结论不是“可以上真实集成”，而是：

> **允许进入下一轮最薄真实接线；不允许扩 scope。**
