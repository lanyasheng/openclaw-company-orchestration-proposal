# workspace-trading 首条 Pilot Workflow 冻结稿

## 结论先行
**首条 pilot 就定为：`固定候选验收闭环（Acceptance Harness Dry-Run v1）`。**

这是当前最适合先跑通的一条 `workspace-trading` workflow，原因只有三个：
1. **今天就能执行**：`workspace-trading` 已有 `research/run_acceptance_harness.py`、`research/v2_portfolio/acceptance_harness.py`、样例输入与已生成 artifact。
2. **天然离线、可回退、零真实交易副作用**：输入是 repo 内 JSON，执行是本地 Python 验收脚本，输出只有 JSON/Markdown，不触发网关、不下单、不改盘中逻辑。
3. **正好覆盖 P1 主线最需要验证的链路**：`workflow model -> dispatch -> subagent -> terminal/state -> callback`，同时不把问题扩成“通用 DAG 平台”。

---

## 1. Pilot 名称
- **中文名**：固定候选验收闭环（Acceptance Harness Dry-Run v1）
- **workflow_id**：`workspace-trading.acceptance-harness-dry-run.v1`
- **目标**：对 `workspace-trading` 中已经冻结的固定候选验收输入，跑一次 repo-native acceptance harness，产出结构化 artifact / report，并把终态按 `completed / degraded / failed / timeout` 收敛到控制面。

---

## 2. 为什么选它，而不是别的 trading use case

### 2.1 选它的依据（基于当前真值）
`workspace-trading` 里已经有以下可直接复用资产：
- CLI：`research/run_acceptance_harness.py`
- 核心模块：`research/v2_portfolio/acceptance_harness.py`
- 固定样例输入：`research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json`
- 已生成的结构化样例产物：`artifacts/acceptance/2026-03-19/acceptance_harness_sample_20260319.json`
- 说明文档：`docs/module_delivery/final_issue_closure/2026-03-19-acceptance-harness-and-tradability-gate-v1.md`

### 2.2 不选其它候选的原因
1. **盘前 preflight / 盘中风控守门**：虽然业务价值高，但天然更接近在线依赖，容易把 pilot 早期验证拖进“行情时效 / 外部 provider / 盘中 SOP”复杂度。
2. **真实回测驱动 acceptance runner**：方向正确，但 `workspace-trading` 当前真值仍是 **sample-metrics -> acceptance harness** 已落地，`真实回测输入路径` 还属于下一步（见 `docs/next-batch-subagent-tasks.md` 的 Task 2）。
3. **盘后汇总 / 多 agent 分析链**：容易变成内容生产和多 repo 协调问题，不能最小化验证 workflow control plane 主链。

**因此，P1 Task 1 不再摇摆：先打穿 acceptance harness dry-run。**

---

## 3. 风险边界与非目标

### 3.1 明确边界
本 workflow **只允许**：
- 读取 `workspace-trading` repo 内固定输入 JSON
- 在 `workspace-trading` 内运行 acceptance harness CLI
- 落盘 JSON artifact / Markdown report
- 回写 workflow registry / callback / timeline 摘要

### 3.2 明确禁止
本 workflow **明确不做**：
- 不接真实下单
- 不调用 live trading gateway
- 不改盘中执行配置
- 不做任意策略扫参
- 不做通用 DAG / 动态 fan-out / 多策略并发编排
- 不把 acceptance verdict 误表述成“已可实盘放行”

### 3.3 回退方式
- **控制面回退**：停掉该 workflow 的 trigger，恢复为人工手动执行 `research/run_acceptance_harness.py`
- **业务面回退**：删除本次生成的 artifact/report，不影响 `workspace-trading` 既有主回测链
- **方案面回退**：撤回本 workflow definition，不影响后续改选其它 pilot

---

## 4. Trigger（冻结为单一触发方式）

### 4.1 首版 trigger
**只支持人工触发（manual dispatch）**，不做 cron、不做自动 webhook。

### 4.2 触发输入
最小输入如下：
- `task_id`：控制面生成的稳定任务 ID
- `run_label`：本次运行标签，例如 `pilot_20260319_01`
- `input_config_path`：固定为 `research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json`
- `workspace_repo`：`workspace-trading`
- `artifacts_dir`：`artifacts/acceptance/<YYYY-MM-DD>`
- `reports_dir`：`reports/acceptance/<YYYY-MM-DD>`
- `git_commit`：可选；若不显式给，由 `workspace-trading` 当前 HEAD 记录到 manifest

### 4.3 触发前置校验
触发前必须全部满足：
1. `workspace_repo == workspace-trading`
2. `input_config_path` 命中 allowlist（首版只允许 sample config）
3. 命令中不包含任何 live trading / gateway / order / broker 操作
4. `task_id` 未被重复 dispatch

---

## 5. 固定节点列表（不是通用 DAG）

> 这条 pilot workflow 固定为 **6 个节点**，不支持动态增删节点。

| 顺序 | 节点 ID | 执行位置 | 作用 | 成功输出 |
|---|---|---|---|---|
| 1 | `init_registry` | 控制面 | 创建 task registry 记录，写入 `state=queued`、`callback_status=pending` | `task_id`、初始 evidence |
| 2 | `validate_request` | 控制面 | 校验 repo 边界、输入 config allowlist、无 live-trading side effect | 可 dispatch 的执行参数 |
| 3 | `dispatch_acceptance_subagent` | `workspace-trading` subagent | 执行 acceptance harness CLI，生成 repo-native artifact/report | `child_session_key`、terminal 输出 |
| 4 | `await_terminal` | 控制面 / subagent bridge | 等待子任务终态，收敛 `completed/failed/timeout` terminal 证据 | terminal envelope |
| 5 | `collect_and_classify` | 控制面 | 读取 artifact JSON，验证 manifest/checklist，按 verdict 映射 workflow state | 业务终态 + artifact 索引 |
| 6 | `final_callback` | callback plane | 发送一次最终回执；终态与 callback_status 分离 | `callback_status=sent/acked/failed` |

### 5.1 节点 3 的固定执行命令
在 `workspace-trading` 中执行以下命令：

```bash
python3 research/run_acceptance_harness.py \
  --input research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json \
  --artifacts-dir artifacts/acceptance/<YYYY-MM-DD> \
  --reports-dir reports/acceptance/<YYYY-MM-DD> \
  --test-command "python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py -q" \
  --test-command "python3 -m pytest tests/v2_portfolio/test_acceptance_harness.py tests/v2_portfolio/test_validation_harness.py tests/v2_portfolio/test_cli.py -q"
```

> 首版不允许把这一步扩成真实回测生成 scenario；那是下一条 backlog（`acceptance runner`），不是本 pilot 的 scope。

---

## 6. Fan-out / Join 规则（固定，不泛化）

### 6.1 控制面 fan-out
**没有控制面 fan-out。**

P1 Task 1 的目标不是验证多子任务并行，而是先把单条主链跑通：
`manual dispatch -> single subagent -> terminal -> classify -> callback`

### 6.2 业务内 fan-out
允许的唯一 fan-out 发生在 **acceptance harness 业务语义内部**，固定为 4 个 scenario 维度：
- `etf_basket`
- `stock_basket`
- `oos`
- `regime`

这 4 个维度不是控制面动态展开出来的子 workflow，而是 `workspace-trading` acceptance artifact 中**必须同时出现**的固定检查项。

### 6.3 Join 规则
`collect_and_classify` 节点在读取 JSON artifact 时，必须同时满足：
1. `summary.scenario_count == 4`
2. `summary.dimensions_covered` 恰好覆盖：`etf_basket / stock_basket / oos / regime`
3. `acceptance_manifest` 存在
4. `acceptance_checklist` 存在
5. `generated_artifact_path` 已记录
6. `report_path` 已记录

任一缺失，**不进入 degraded，而直接记为 failed**。

---

## 7. 成功 / 降级 / 失败 / 超时语义

这里明确区分两件事：
1. **workflow 执行有没有跑通**
2. **业务 verdict 好不好**

### 7.1 `completed`
同时满足：
- subagent 命令退出码为 0
- JSON artifact 成功写出
- manifest/checklist 完整
- 四个固定维度齐全
- `acceptance_manifest.verdict_summary.overall_verdict == PASS`

含义：**workflow 跑通，且本次固定候选验收结论为 PASS。**

### 7.2 `degraded`
同时满足：
- subagent 命令退出码为 0
- JSON artifact 成功写出
- manifest/checklist 完整
- 四个固定维度齐全
- `acceptance_manifest.verdict_summary.overall_verdict` 为 `CONDITIONAL` 或 `FAIL`

含义：**workflow 运行成功，但业务结论不够好。**

为什么不是 `failed`：
- 这条 pilot 的目标是“把验收闭环跑出来”，不是“保证策略一定 PASS”
- 候选策略被判 `FAIL`，属于业务结果，不属于编排故障

### 7.3 `failed`
任一命中即 `failed`：
- subagent 命令非 0 退出
- 输入 config 不合法 / 不在 allowlist
- artifact JSON 未生成
- `acceptance_manifest` 或 `acceptance_checklist` 缺失
- 四个固定维度缺失、重复或统计不一致
- terminal 已到达，但 artifact 解析失败

含义：**编排链路或产物契约没跑通。**

### 7.4 `timeout`
- `dispatch_acceptance_subagent` 发出后，在 **300 秒** 内未收到 terminal
- 一旦超时，workflow state 记为 `timeout`
- 超时后可以单独补发 callback，但**不得把 state 改写成 completed/degraded**，除非人工明确 override 并留下 evidence

### 7.5 `callback_status` 语义（必须独立）
遵守 proposal 主线既有口径：
- `state` 与 `callback_status` 分离
- `terminal != callback sent != callback acked`

因此允许出现：
- `state=completed` 且 `callback_status=failed`
- `state=degraded` 且 `callback_status=pending`

不允许出现：
- 因 callback 发送失败，把 `completed/degraded` 回写成 `failed`

---

## 8. 产物落库路径

## 8.1 workspace-trading（业务产物，主真值）
- 输入配置：`research/v2_portfolio/basket_configs/acceptance_harness_v1_sample.json`
- 结构化 JSON：`artifacts/acceptance/<YYYY-MM-DD>/acceptance_harness_<run_label>.json`
- Markdown 报告：`reports/acceptance/<YYYY-MM-DD>/acceptance_harness_<run_label>.md`

## 8.2 workflow control plane（控制面证据）
首版规范固定如下：
- registry：`artifacts/workflow-runs/workspace-trading.acceptance-harness-dry-run.v1/<task_id>/registry.json`
- terminal envelope：`artifacts/workflow-runs/workspace-trading.acceptance-harness-dry-run.v1/<task_id>/terminal.json`
- final callback envelope：`artifacts/workflow-runs/workspace-trading.acceptance-harness-dry-run.v1/<task_id>/callback.json`
- workflow summary：`artifacts/workflow-runs/workspace-trading.acceptance-harness-dry-run.v1/<task_id>/summary.md`

> 这里的 control-plane 路径是为 E5-T2 / E6 后续实现冻结接口，不代表现在已经全部落代码。

### 8.3 方案仓文档资产
- 本文档：`docs/workflows/workspace-trading-pilot-workflow.md`
- machine-readable draft：`docs/workflows/workspace-trading-pilot-workflow.yaml`

---

## 9. 最小 callback 载荷

`final_callback` 至少携带：
- `task_id`
- `workflow_id`
- `run_label`
- `candidate_id`
- `workflow_state`
- `business_overall_verdict`
- `artifact_json_path`
- `report_path`
- `child_session_key`

其中：
- `workflow_state` 来自控制面（`completed / degraded / failed / timeout`）
- `business_overall_verdict` 来自 acceptance manifest（`PASS / CONDITIONAL / FAIL`）

---

## 10. 一条完整执行示例

### 10.1 触发
控制面收到人工指令：
- workflow：`workspace-trading.acceptance-harness-dry-run.v1`
- run_label：`pilot_20260319_01`

### 10.2 执行
1. 控制面创建 `task_id`
2. 校验输入 config = sample config
3. 派发 `workspace-trading` subagent 执行 acceptance harness CLI
4. 等待 terminal
5. 读取生成的 JSON artifact
6. 若 artifact 完整且 verdict = `PASS` -> `completed`
7. 若 artifact 完整但 verdict = `CONDITIONAL/FAIL` -> `degraded`
8. 发送 final callback

### 10.3 终态示例
- **示例 A**：CLI 成功、artifact 完整、verdict = `PASS`
  - `state=completed`
- **示例 B**：CLI 成功、artifact 完整、verdict = `FAIL`
  - `state=degraded`
- **示例 C**：CLI 抛异常，JSON 未生成
  - `state=failed`
- **示例 D**：300 秒无 terminal
  - `state=timeout`

---

## 11. 首条 pilot 的验收标准（冻结）

P1 Task 1 只以以下标准验收：
1. pilot 名称和 scope 不再摇摆
2. trigger 固定为 manual dispatch
3. 节点列表固定为 6 个，不扩成通用 DAG
4. 允许的 fan-out 仅限 acceptance artifact 内部固定 4 维场景
5. 成功 / 降级 / 失败 / 超时语义明确
6. workspace-trading 业务产物路径明确
7. control-plane 证据路径明确
8. 明确禁止 live trading side effect

---

## 12. 下一步与本任务边界

这份冻结稿完成后，下一步直接进入：
- **E5-T2**：把本文档对应的 workflow definition + adapter binding 落代码
- **E5-T3**：给这条 pilot 补 runbook 和可重放 dry-run 入口

但 **P1 Task 1 到此为止**，不继续扩成：
- 多策略并发
- 真实回测 scenario 自动生成
- 盘前 / 盘中在线 workflow
- 通用 workflow schema 平台化

**一句话收口：先把 `固定候选验收闭环` 跑通，再谈下一层抽象。**
