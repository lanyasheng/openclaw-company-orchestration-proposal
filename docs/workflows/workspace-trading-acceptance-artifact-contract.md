# workspace-trading Acceptance Artifact 输入契约（v1）

## 结论先行
`control.collect_and_classify` 当前只认 **`workspace-trading` acceptance harness v1** 产物，主输入是 **artifact JSON**，manifest/checklist 可以内嵌，也可以额外提供 sidecar 路径；但 v1 真值链的 canonical 形态，仍然是：

1. `artifact_json_path` 指向 repo 内 acceptance JSON；
2. JSON 内必须带 `acceptance_manifest`；
3. JSON 内必须带 `acceptance_checklist`。

---

## 1. 请求 / terminal 输入字段

### 1.1 request 级字段
| 字段 | 必填 | 说明 |
|---|---|---|
| `workspace_repo` | 是 | 必须恒等于 `workspace-trading` |
| `workspace_repo_path` | 是 | business repo 根目录；相对路径按 scheduler 运行目录解析 |
| `artifact_json_path` | 否 | 兜底路径；若 terminal 未显式给出，则从 request 读取 |
| `report_path` | 否 | 兜底报告路径；若 terminal 未显式给出，则从 request 读取 |
| `acceptance_manifest_path` | 否 | sidecar manifest 路径；若提供，必须与 artifact 内嵌 manifest 一致 |
| `acceptance_checklist_path` | 否 | sidecar checklist 路径；若提供，必须与 artifact 内嵌 checklist 一致 |

### 1.2 `await_terminal` 输出字段
`collect_and_classify` 直接消费 `await_terminal` 的输出；当前要求：

```json
{
  "terminal_state": "completed|failed|timeout",
  "artifacts": {
    "artifact_json_path": "artifacts/acceptance/...json",
    "report_path": "reports/acceptance/...md",
    "acceptance_manifest_path": "optional-sidecar.json",
    "acceptance_checklist_path": "optional-sidecar.json"
  }
}
```

v1 只把 `terminal_state=completed` 继续往下判；`failed/timeout` 一律收敛为 workflow `failed`。

---

## 2. artifact JSON 最小结构

```json
{
  "manifest_version": "acceptance_harness.v1",
  "summary": {
    "scenario_count": 4,
    "dimensions_covered": ["etf_basket", "oos", "regime", "stock_basket"]
  },
  "acceptance_manifest": {
    "schema_version": "acceptance_manifest.v1",
    "generated_artifact_path": "artifacts/acceptance/...json",
    "report_path": "reports/acceptance/...md",
    "candidate_id": "...",
    "verdict_summary": {
      "overall_verdict": "PASS|CONDITIONAL|FAIL",
      "scenario_count": 4,
      "dimensions_covered": ["etf_basket", "oos", "regime", "stock_basket"]
    }
  },
  "acceptance_checklist": {
    "schema_version": "acceptance_checklist.v1",
    "overall_status": "PASS|WARN|FAIL",
    "items": [
      {"item_id": "run_label_recorded", "status": "PASS|WARN|FAIL", "detail": "..."}
    ]
  }
}
```

---

## 3. `collect_and_classify` 的 v1 校验规则

### 3.1 直接判 `failed`
任一命中：
- `workspace_repo != workspace-trading`
- `terminal_state != completed`
- `artifact_json_path` 缺失或文件不存在
- `manifest_version != acceptance_harness.v1`
- 缺 `acceptance_manifest` / `acceptance_checklist`
- `summary.scenario_count != 4`
- `summary.dimensions_covered` 不是固定四维：`etf_basket / stock_basket / oos / regime`
- manifest schema 不是 `acceptance_manifest.v1`
- checklist schema 不是 `acceptance_checklist.v1`
- manifest 内 `generated_artifact_path` 与实际 artifact 路径不一致
- manifest 内 `report_path` 与 terminal/request 给出的 report path 不一致
- checklist 任一 item 为 `FAIL`
- checklist `overall_status == FAIL`
- `overall_verdict` 不是 `PASS / CONDITIONAL / FAIL`
- 若提供 sidecar manifest/checklist，则 sidecar 与 artifact 内嵌内容不一致

### 3.2 判 `completed`
同时满足：
- 契约校验全通过
- `acceptance_manifest.verdict_summary.overall_verdict == PASS`

### 3.3 判 `degraded`
同时满足：
- 契约校验全通过
- `acceptance_manifest.verdict_summary.overall_verdict in [CONDITIONAL, FAIL]`

> 这里的 `FAIL` 是**业务 verdict FAIL**，不是编排失败；因此状态映射为 `degraded`，不是 `failed`。

---

## 4. v1 当前限制
- 还不把 `timeout` 暴露成 registry 顶层独立状态；当前 minimal scheduler 仍收敛到 `failed`
- 还不支持动态 scenario fan-out；固定只认 4 维 acceptance 产物
- 还不支持多 artifact 聚合；一次只收一个 candidate 的一份 acceptance bundle
