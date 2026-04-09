# Trading Roundtable Operator Runbook v1.0 ⚠️ DEPRECATED

> **状态**: ⚠️ **DEPRECATED** — 本文档已过时，仅供参考。请以当前 canonical 文档为准。
> 
> **迁移指引**: 
> - 当前 canonical runbook: `docs/runbooks/trading_roundtable_operator_runbook.md` (待更新)
> - 当前协议：`docs/protocols/trading_roundtable_auto_execution_protocol_v1.md`
> - 本文档保留作为历史参考，但不再维护。新 operator 请阅读最新文档。

> **Operator-facing checklist for trading roundtable batch execution**  
> **版本**: 1.0.0 (deprecated)  
> **原生效日期**: 2026-03-24  
> **关联协议**: `../docs/protocols/trading_roundtable_auto_execution_protocol_v1.md`

---

## TL;DR

每批 trading roundtable 完成后，**必须**执行以下默认动作才能启动下一批：

```
验收 (Acceptance) → Closeout (Runtime) → Git 收口 → Push → 下一批
```

**红线**: 任何一步失败都不得启动下一批。

---

## 1. 每批完成后的默认动作（P0 强制）

### 1.1 标准流程

| 步骤 | 动作 | 负责人 | 产出物 | 验证方式 |
|------|------|--------|--------|---------|
| 1. 验收 | 检查 callback envelope 完整性 | Runtime/Operator | `acceptance_result.json` | `dispatch_readiness=true` |
| 2. Closeout | 写入 closeout artifact | Runtime | `closeout_artifact.json` | `closeout_status=complete\|pending_push` |
| 3. Git 收口 | 更新 manifest + commit | Operator | Git commit | `git_closeout_commit` 非空 |
| 4. Push | 推送到远端 | Operator | Push 成功 | `push_status=pushed` |
| 5. 下一批 | 启动下一批 | Runtime | `dispatch_plan.json` | `status=triggered` |

### 1.2 详细步骤

#### Step 1: 验收 (Acceptance)

**自动执行**，由 `trading_roundtable.py` 在 callback 被消费后自动评估。

**检查清单**:
- [ ] P0 强制字段完整（`candidate_id`, `signal_type`, `tradability_score`）
- [ ] `tradability_score >= 0.7`（可配置）
- [ ] `artifact_paths` 非空且包含 `terminal.json`
- [ ] `terminal_status != failed`

**产出**: `acceptance_result` 包含在 `dispatch_plan.safety_gates` 中

**验证命令**:
```bash
python3 -c "
import json
from pathlib import Path
dispatch = json.loads(Path('PATH_TO_DISPATCH.json').read_text())
print('dispatch_readiness:', dispatch.get('safety_gates', {}).get('default_auto_dispatch_status'))
print('blockers:', dispatch.get('safety_gates', {}).get('default_auto_dispatch_blockers'))
"
```

---

#### Step 2: Closeout (Runtime)

**自动执行**，由 `closeout_tracker.py` 在 trading roundtable callback 处理后自动创建。

**产出物**: `~/.openclaw/shared-context/orchestrator/closeouts/closeout-{batch_id}.json`

**关键字段**:
```json
{
  "closeout_status": "complete|pending_push|incomplete|blocked",
  "push_status": "pending|pushed|not_required|blocked",
  "push_required": true,
  "continuation_contract": {
    "stopped_because": "...",
    "next_step": "...",
    "next_owner": "..."
  }
}
```

**验证命令**:
```bash
python3 -c "
import json
from pathlib import Path
closeout = json.loads(Path('~/.openclaw/shared-context/orchestrator/closeouts/closeout-BATCH_ID.json').expanduser().read_text())
print('closeout_status:', closeout['closeout_status'])
print('push_status:', closeout['push_status'])
print('push_required:', closeout['push_required'])
print('next_step:', closeout['continuation_contract']['next_step'])
"
```

---

#### Step 3: Git 收口

**手动执行**，由 Operator 负责。

**命令**:
```bash
cd <REPO_ROOT>  # 替换为实际 repo 路径，例如 ~/repos/openclaw-company-orchestration-proposal

# 更新 manifest（如果脚本已实现）
python3 runtime/scripts/update_manifest.py \
  --batch-id BATCH_ID \
  --closeout-status accepted \
  --tradability-score 0.85

# 或手动更新 manifest.json
# (添加 batch closeout 记录)

# 提交
git add docs/batch-summaries/BATCH_ID_closeout.md manifest.json
git commit -m "Closeout BATCH_ID: accepted, tradability=0.85"
```

**产出物**: Git commit hash

**验证**:
```bash
git log -1 --oneline
# 输出应包含 "Closeout BATCH_ID"
```

---

#### Step 4: Push

**手动执行**，由 Operator 负责。

**命令**:
```bash
git push origin main
```

**验证**:
```bash
git status
# 应显示 "Your branch is up to date with 'origin/main'."
```

---

#### Step 5: 下一批

**自动/手动执行**，取决于 `allow_auto_dispatch` 配置。

**条件**:
- ✅ 前 4 步全部完成
- ✅ `closeout_status != blocked`
- ✅ `push_status = pushed`
- ✅ `dispatch_readiness = ready`

**验证命令**:
```bash
python3 -c "
import json
from pathlib import Path
# 检查最新 dispatch plan
dispatch_files = sorted(Path('~/.openclaw/shared-context/orchestrator/dispatches/').expanduser().glob('disp_*.json'))
if dispatch_files:
    dispatch = json.loads(dispatch_files[-1].read_text())
    print('dispatch_id:', dispatch['dispatch_id'])
    print('status:', dispatch['status'])
    print('allow_auto_dispatch:', dispatch['safety_gates']['allow_auto_dispatch'])
"
```

---

## 2. Callback 输出要求（P0 强制）

### 2.1 子任务必须输出 canonical callback payload

**每个 trading 子任务完成后，必须**:

1. **写出 business callback payload** 到固定路径：
   ```
   ~/.openclaw/shared-context/orchestrator/tmux_receipts/<dispatch_id>.business-callback.json
   ```

2. **或通过 completion report 内嵌 payload**：
   ```json
   {
     "business_callback_payload": { ... },
     "trading_roundtable": {
       "packet": { ... },
       "roundtable": { ... }
     }
   }
   ```

3. **或至少生成 blocked fallback payload**（如果无法产出真实业务结论）：
   ```json
   {
     "summary": "Task completed but insufficient for clean business closeout",
     "verdict": "FAIL",
     "trading_roundtable": {
       "packet": {
         "packet_version": "trading_phase1_packet_v1",
         "phase_id": "trading_phase1",
         "owner": "trading",
         "generated_at": "2026-03-24T00:00:00+08:00"
       },
       "roundtable": {
         "conclusion": "FAIL",
         "blocker": "insufficient_evidence",
         "owner": "trading",
         "next_step": "Re-run with proper artifact generation",
         "completion_criteria": "..."
       }
     }
   }
   ```

### 2.2 最小 callback payload 结构

```json
{
  "summary": "简短总结",
  "verdict": "PASS|FAIL|DEGRADED",
  "trading_roundtable": {
    "packet": {
      "packet_version": "trading_phase1_packet_v1",
      "phase_id": "trading_phase1",
      "candidate_id": "xxx",
      "signal_type": "long|short",
      "tradability_score": 0.85,
      "tradability_reason": "...",
      "artifact_paths": ["/path/to/terminal.json", ...],
      "owner": "trading",
      "generated_at": "2026-03-24T00:00:00+08:00"
    },
    "roundtable": {
      "conclusion": "PASS|CONDITIONAL|FAIL",
      "blocker": "none|<blocker>",
      "owner": "trading",
      "next_step": "下一步动作",
      "completion_criteria": "完成标准"
    },
    "summary": "可选：scenario 专属总结"
  }
}
```

### 2.3 验证命令

```bash
# 检查 business callback payload 是否存在
ls -la ~/.openclaw/shared-context/orchestrator/tmux_receipts/*.business-callback.json

# 检查内容
python3 -c "
import json
from pathlib import Path
files = Path('~/.openclaw/shared-context/orchestrator/tmux_receipts/').expanduser().glob('*.business-callback.json')
for f in sorted(files)[-3:]:
    payload = json.loads(f.read_text())
    print(f'{f.name}: verdict={payload.get(\"verdict\")}, has_trading_roundtable={\"trading_roundtable\" in payload}')
"
```

---

## 3. Dispatch Reference 中的 Callback 要求

### 3.1 Dispatch Plan 中的 `canonical_callback` 字段

每个 dispatch plan 都包含 `canonical_callback` 字段，明确 callback 要求：

```json
{
  "canonical_callback": {
    "required": true,
    "business_terminal_source": "scripts/orchestrator_callback_bridge.py complete",
    "callback_payload_schema": "trading_roundtable.v1.callback",
    "callback_envelope_schema": "canonical_callback_envelope.v1",
    "backend_terminal_role": "diagnostic_only",
    "report_role": "evidence_only_until_callback"
  }
}
```

### 3.2 Dispatch Reference 中的说明

Dispatch reference（由 `orchestrator_dispatch_bridge.py prepare` 生成）包含：

```markdown
## Canonical callback contract

- required: true
- business_terminal_source: scripts/orchestrator_callback_bridge.py complete
- callback_payload_schema: trading_roundtable.v1.callback
- callback_envelope_schema: canonical_callback_envelope.v1
- backend_terminal_role: diagnostic_only
- report_role: evidence_only_until_callback
- business_callback_output_path: PATH/TO/business-callback.json
- rule: tmux STATUS / completion report do not by themselves advance trading roundtable business state.
- rule: if the task can produce real trading_roundtable truth, write a structured business callback JSON to business_callback_output_path.
- rule: if truth is insufficient for a clean business closeout, still write a blocked/degraded callback payload with explicit blocker and missing evidence instead of a generic completion note.
- rule: the bridge will wrap the normalized payload into callback_envelope so future adapters can share the same terminal callback contract.
```

### 3.3 验证命令

```bash
# 查看最新 dispatch reference
ls -lt ~/.openclaw/shared-context/orchestrator/dispatches/*.json | head -1

# 检查 canonical_callback 字段
python3 -c "
import json
from pathlib import Path
dispatch_files = sorted(Path('~/.openclaw/shared-context/orchestrator/dispatches/').expanduser().glob('disp_*.json'))
if dispatch_files:
    dispatch = json.loads(dispatch_files[-1].read_text())
    print(json.dumps(dispatch.get('canonical_callback'), indent=2))
"
```

---

## 4. 异常处理

### 4.1 常见异常及处理

| 异常 | 症状 | 处理 |
|------|------|------|
| Callback 缺失 | `business-callback.json` 不存在 | 检查子任务 completion report，手动补 callback |
| Closeout 卡住 | `closeout_status=pending_push` 超过 5 分钟 | 检查 git commit/push 状态 |
| Git 冲突 | `git push` 失败 | 解决冲突后重新 commit/push |
| Push 成功但下一批未启动 | `push_status=pushed` 但无新 dispatch | 检查 `dispatch_readiness` 和 `allow_auto_dispatch` |

### 4.2 诊断命令

```bash
# 检查 closeout 状态
python3 -c "
import json
from pathlib import Path
closeout_files = sorted(Path('~/.openclaw/shared-context/orchestrator/closeouts/').expanduser().glob('closeout-*.json'))
if closeout_files:
    closeout = json.loads(closeout_files[-1].read_text())
    print('closeout_status:', closeout['closeout_status'])
    print('push_status:', closeout['push_status'])
    print('next_step:', closeout['continuation_contract']['next_step'])
"

# 检查 waiting anomalies
python3 ~/.openclaw/workspace/repos/openclaw-company-orchestration-proposal/runtime/orchestrator/waiting_guard.py reconcile BATCH_ID

# 检查 dispatch plan 状态
python3 -c "
import json
from pathlib import Path
dispatch_files = sorted(Path('~/.openclaw/shared-context/orchestrator/dispatches/').expanduser().glob('disp_*.json'))
for f in dispatch_files[-3:]:
    dispatch = json.loads(f.read_text())
    print(f'{f.name}: status={dispatch[\"status\"]}, allow_auto_dispatch={dispatch[\"safety_gates\"][\"allow_auto_dispatch\"]}')
"
```

---

## 5. 快速参考卡片

### 5.1 每批完成后检查清单

```
[ ] 1. 验收通过 (dispatch_readiness=ready)
[ ] 2. Closeout 已创建 (closeout_status=complete|pending_push)
[ ] 3. Git commit 已完成 (git_closeout_commit 非空)
[ ] 4. Push 成功 (push_status=pushed)
[ ] 5. 下一批已启动 (新 dispatch plan status=triggered)
```

### 5.2 关键文件路径

| 文件类型 | 路径 |
|---------|------|
| Dispatch Plan | `~/.openclaw/shared-context/orchestrator/dispatches/disp_*.json` |
| Closeout Artifact | `~/.openclaw/shared-context/orchestrator/closeouts/closeout-*.json` |
| Business Callback | `~/.openclaw/shared-context/orchestrator/tmux_receipts/*.business-callback.json` |
| Summary | `~/.openclaw/shared-context/orchestrator/summaries/batch-*-summary.md` |
| Decision | `~/.openclaw/shared-context/orchestrator/decisions/dec_*.json` |

### 5.3 关键命令

```bash
# 更新 manifest 并提交
python3 runtime/scripts/update_manifest.py --batch-id BATCH_ID --closeout-status accepted

# 推送到远端
git push origin main

# 检查状态
python3 -c "import json; from pathlib import Path; print(json.dumps(json.loads(Path('PATH').read_text()), indent=2))"
```

---

## 6. 与完整协议的映射

| 本 Runbook 章节 | 对应协议章节 |
|----------------|-------------|
| 1. 每批完成后的默认动作 | 协议 4.8, 7 |
| 2. Callback 输出要求 | 协议 4.5, 4.5.1 |
| 3. Dispatch Reference 中的 Callback 要求 | 协议 4.4, 4.5 |
| 4. 异常处理 | 协议 6.3, 7.3, 7.3.1 |

**完整协议**: `../docs/protocols/trading_roundtable_auto_execution_protocol_v1.md`

---

*End of Operator Runbook*
