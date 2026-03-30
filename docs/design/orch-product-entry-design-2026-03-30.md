# P0-3 Batch 9: Onboard + Run + Status 产品入口设计摘要

**日期:** 2026-03-30  
**作者:** Zoe (subagent)  
**状态:** 执行中

---

## 范围 (Scope)

### 目标
把当前统一执行入口进一步封装成真正面向频道/agent 的**产品化三件套**：
1. **onboard** — 给频道生成/解释接入方案（adapter/scenario/owner/backend/gate）
2. **run** — 触发一次当前频道/指定频道的执行（尽量隐藏内部 contract 细节）
3. **status** — 查看当前频道/批次/任务的状态总览

### 设计原则
- **复用现有 control plane**：不得另起真值链
  - onboard 复用 `entry_defaults.build_default_entry_contract()` 的 contract 推导能力
  - run 复用 `unified_execution_runtime.UnifiedExecutionRuntime` 
  - status 复用 `observability_card` 的 card/board snapshot 能力
- **零心智负担**：其他 agent 一句话就会用，文档里给出最短用法示例
- **向后兼容**：保留现有 `orch_command.py contract` 入口，不破坏已有契约

### 不在范围 (Out of Scope)
- 不修改现有 backend_selector 决策逻辑
- 不修改 existing adapters (trading_roundtable / channel_roundtable)
- 不修改 observability card schema
- 不修改 completion_receipt / callback_bridge 核心链路

---

## 架构设计 (Architecture)

### 新增命令层
```
runtime/scripts/orch_product.py  (新)
├── onboard 命令
├── run 命令
└── status 命令
```

### 依赖关系
```
orch_product.py (新入口)
│
├─ entry_defaults.build_default_entry_contract()   # onboard 复用
├─ unified_execution_runtime.UnifiedExecutionRuntime  # run 复用
└─ observability_card.*  # status 复用
```

### 命令设计

#### 1. `onboard` 命令
```bash
# 最小用法 — 当前频道自动推导
python3 runtime/scripts/orch_product.py onboard

# 指定频道
python3 runtime/scripts/orch_product.py onboard \
  --channel-id "discord:channel:123456" \
  --channel-name "general" \
  --topic "架构讨论"

# 输出：频道接入建议卡（含 adapter/scenario/owner/backend/gate 推荐）
```

**输出结构:**
```json
{
  "version": "orch_product_onboard_v1",
  "channel": { "channel_id": "...", "channel_name": "...", "topic": "..." },
  "recommendation": {
    "adapter": "channel_roundtable",
    "scenario": "generic_roundtable",
    "owner": "main",
    "backend": "subagent",
    "gate_policy": "stop_on_gate"
  },
  "bootstrap_capability_card": { ... },
  "operator_kit": { ... },
  "next_steps": [
    "1. 确认推荐配置",
    "2. 运行 'orch_product.py run' 触发执行",
    "3. 运行 'orch_product.py status' 查看状态"
  ],
  "example_commands": {
    "run": "python3 runtime/scripts/orch_product.py run --channel-id ...",
    "status": "python3 runtime/scripts/orch_product.py status --channel-id ..."
  }
}
```

#### 2. `run` 命令
```bash
# 最小用法 — 使用当前频道默认配置
python3 runtime/scripts/orch_product.py run --task "任务描述"

# 指定频道
python3 runtime/scripts/orch_product.py run \
  --channel-id "discord:channel:123456" \
  --task "任务描述"

# 显式 backend
python3 runtime/scripts/orch_product.py run \
  --task "..." --backend tmux --workdir /path/to/workdir

# 输出：执行结果（task_id, dispatch_id, backend, session_id, callback_path, wake_command）
```

**内部流程:**
1. 调用 `entry_defaults.build_default_entry_contract()` 生成 contract
2. 调用 `UnifiedExecutionRuntime.run_task()` 执行任务
3. 自动注册 observability card
4. 返回执行结果

#### 3. `status` 命令
```bash
# 当前频道状态
python3 runtime/scripts/orch_product.py status

# 指定频道
python3 runtime/scripts/orch_product.py status \
  --channel-id "discord:channel:123456"

# 指定批次
python3 runtime/scripts/orch_product.py status --batch-key "batch_xxx"

# 输出：状态总览（active_tasks, completed_tasks, blockers, next_steps）
```

**输出结构:**
```json
{
  "version": "orch_product_status_v1",
  "channel": { "channel_id": "...", "channel_name": "..." },
  "snapshot_time": "2026-03-30T18:00:00+08:00",
  "active_tasks": [
    { "task_id": "...", "stage": "running", "backend": "tmux", "session_id": "..." }
  ],
  "completed_tasks": [
    { "task_id": "...", "stage": "completed", "verdict": "PASS" }
  ],
  "blockers": [],
  "next_steps": ["等待任务完成", "准备下一批次"],
  "board_snapshot_path": "/path/to/board-snapshot.json"
}
```

---

## 风险与缓解 (Risks & Mitigation)

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| **破坏现有 contract 兼容性** | 已有频道接入失效 | 保留 `orch_command.py` 不变；新入口仅作为上层封装 |
| **真值链分裂** | onboard/run/status 与现有 control plane 不一致 | 严格复用现有函数，不复制逻辑；所有真值仍来自 entry_defaults / unified_execution_runtime / observability_card |
| **状态卡缺失导致 status 失败** | status 命令返回空结果 | status 降级处理：无 card 时返回 "no observability cards found" + 引导用户先用 run 触发执行 |
| **backend 推荐与用户预期不符** | 用户期望 subagent 但推荐 tmux | run 命令支持 `--backend` 显式覆盖；onboard 输出中明确说明推荐理由 |

---

## 回退方案 (Rollback Plan)

如果新入口出现问题：

1. **立即回退**: 删除 `orch_product.py`，恢复使用 `orch_command.py`
2. **真值不受影响**: 新入口不修改现有 state 文件 / card 文件 / dispatch 文件
3. **已有任务继续运行**: tmux sessions / subagents 不受影响，继续通过原有 callback 机制完成

**回退命令:**
```bash
# 删除新入口
rm runtime/scripts/orch_product.py

# 恢复使用旧入口
python3 runtime/scripts/orch_command.py contract  # 保持不变
```

---

## 测试计划 (Test Plan)

### 单元测试
- `test_orch_product_onboard.py`: 验证 onboard 输出结构
- `test_orch_product_run.py`: 验证 run 触发执行
- `test_orch_product_status.py`: 验证 status 返回状态摘要

### 集成验证
1. **onboard 验证**: 
   - 无参数运行，确认输出当前频道接入建议
   - 指定频道参数，确认输出对应推荐配置
   
2. **run 验证**:
   - 触发 subagent 执行，确认返回 task_id / callback_path
   - 触发 tmux 执行，确认返回 session_id / wake_command
   
3. **status 验证**:
   - 无任务时返回空列表
   - 有 active 任务时返回正确状态
   - 有 completed 任务时返回正确结果

### 质量门
- [ ] onboard 输出频道接入建议 ✓
- [ ] run 能触发统一执行入口 ✓
- [ ] status 能返回当前状态摘要 ✓
- [ ] 不破坏现有 orch_command.py 兼容性 ✓
- [ ] 文档给出最短用法示例 ✓
- [ ] 提交并 push 到 origin/main ✓

---

## 交付物 (Deliverables)

1. **代码**: `runtime/scripts/orch_product.py` (新)
2. **测试**: `tests/orchestrator/test_orch_product.py` (新)
3. **文档**: `docs/orch_product_guide.md` (新)
4. **README 更新**: 在 README.md 中添加三件套快速入门

---

## 成功标准 (Success Criteria)

1. **可用性**: 其他 agent 能用一行命令完成接入 (`orch_product.py onboard`)
2. **简洁性**: 文档中三件套用法示例不超过 10 行
3. **兼容性**: 现有 `orch_command.py contract` 测试全部通过
4. **可观测性**: status 命令能正确返回 observability card 聚合结果

---

## 下一步行动 (Next Steps)

1. ✅ 完成设计摘要（本文件）
2. ⏳ 实现 `orch_product.py` 三件套命令
3. ⏳ 编写测试 `test_orch_product.py`
4. ⏳ 编写文档 `docs/orch_product_guide.md`
5. ⏳ 更新 README.md
6. ⏳ 运行测试验证
7. ⏳ 提交并 push 到 origin/main
