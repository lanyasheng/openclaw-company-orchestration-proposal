# 第二频道 Live E2E 验证设计摘要

**日期**: 2026-03-26  
**任务**: orch-second-channel-live-e2e-20260326  
**频道**: 1475854028855443607 (ainews_content_roundtable)

---

## 1. 范围

### 1.1 验证目标
对第二个非 trading 频道（ainews 内容频道）执行一次**真实 live E2E**，验证它是否也能像当前架构频道一样跑到 `dispatch -> request -> consumed -> execution`。

### 1.2 验证链路
```
callback (模拟) 
  → summary 
  → decision 
  → dispatch_plan (status=triggered)
  → auto_execute_intent (status)
  → auto_trigger_result (triggered)
  → request (created)
  → consumed (created)
  → execution (api_execution created)
```

### 1.3 验证范围
- ✅ 使用真实频道 ID: 1475854028855443607
- ✅ 使用真实 scenario: ainews_content_roundtable
- ✅ 使用真实 owner: ainews
- ✅ 生成真实 contract
- ✅ 跑真实 callback bridge（模拟 payload，但走真实代码路径）
- ✅ 验证 artifact 落盘路径
- ❌ 不实际调用 sessions_spawn 创建 subagent（避免产生真实执行成本）
- ❌ 不修改生产配置（除非验证发现配置缺口）

### 1.4 当前真值
- **Channel 1 (1483883339701158102)**: 已真实 live 验证到 execution
- **Channel 2 (1475854028855443607)**: 已完成模板/测试验证，待真实 live callback 复跑

---

## 2. 风险

### 2.1 低风险操作
| 风险点 | 等级 | 说明 |
|--------|------|------|
| 配置修改 | 🟢 低 | 只做最小 allowlist 新增，已有测试覆盖 |
| 代码改动 | 🟢 低 | 只修复断点，不改主链逻辑 |
| 数据污染 | 🟢 低 | artifact 带时间戳，易清理 |
| 生产影响 | 🟢 低 | 不实际创建 subagent，只做 callback 模拟 |

### 2.2 潜在问题
| 问题 | 概率 | 应对 |
|------|------|------|
| auto-trigger config 缺失 | 中 | 现场创建最小配置 |
| allowlist 检查失败 | 低 | 已有白名单配置 + 测试 |
| execution_handoff 缺失 | 中 | 检查 process_channel_roundtable_callback 返回值 |
| prepare_spawn_request 断点 | 低 | 已在 Channel 1 修复 |

---

## 3. 回退方案

### 3.1 配置回退
```bash
cd ~/repos/openclaw-company-orchestration-proposal
git checkout HEAD~1 -- runtime/orchestrator/channel_roundtable.py
git push origin main
```

### 3.2 Artifact 清理
```bash
# 清理本次验证产生的 artifacts（如需）
rm ~/.openclaw/shared-context/dispatches/dispatch_second_channel_*.json
rm ~/.openclaw/shared-context/spawn_requests/req_second_channel_*.json
rm ~/.openclaw/shared-context/bridge_consumed/consumed_second_channel_*.json
rm ~/.openclaw/shared-context/completion_receipts/receipt_second_channel_*.json
rm ~/.openclaw/shared-context/api_executions/exec_second_channel_*.json
```

### 3.3 代码回退
```bash
# 若本轮产生代码修复且需回退
git revert <commit-hash>
git push origin main
```

---

## 4. 执行步骤

### Step 1: 确认配置
- [ ] 检查 channel_roundtable.py 白名单是否包含 1475854028855443607
- [ ] 检查 auto-trigger config 是否存在
- [ ] 检查 artifact 目录是否存在

### Step 2: 创建测试 payload
- [ ] 构建 ainews 频道的 callback payload
- [ ] 包含 packet + roundtable 字段
- [ ] 设置 auto_execute=true

### Step 3: 执行 callback bridge
- [ ] 调用 orchestrator_callback_bridge.py complete
- [ ] 传入 --allow-auto-dispatch true（显式覆盖）
- [ ] 捕获输出，检查 dispatch_plan.status

### Step 4: 验证 artifacts
- [ ] 检查 dispatch_plan 文件
- [ ] 检查 spawn_request 文件
- [ ] 检查 consumed 文件
- [ ] 检查 completion_receipt 文件
- [ ] 检查 api_execution 文件

### Step 5: 验证关键字段
- [ ] dispatch_plan.status = triggered
- [ ] auto_execute_intent.status = completed/prepared
- [ ] auto_trigger_result.triggered = true/false
- [ ] request / consumed / execution 是否真实落盘

### Step 6: 断点分析（如有问题）
- [ ] 明确断点是在 dispatch / request / consumed / execution 哪一层
- [ ] 说明是代码还是配置问题
- [ ] 提出修复方案

### Step 7: 提交与汇报
- [ ] 若有代码/配置改动，提交并 push
- [ ] 输出结论 / 证据 / 动作
- [ ] 更新本文档为验证报告

---

## 5. 质量门

| 质量门 | 状态 |
|--------|------|
| 必须是 live E2E，不用测试冒充 | ⏳ 待验证 |
| 不把第二频道说成已验证，除非真跑出 artifact | ⏳ 待验证 |
| 不做无关大改 | ⏳ 待验证 |
| allowlist/config 最小新增 | ⏳ 待验证 |
| 输出格式：结论 / 证据 / 动作 | ⏳ 待验证 |

---

## 6. 成功标准

**全部满足才算验证通过**：
1. ✅ dispatch_plan.status = "triggered"
2. ✅ auto_execute_intent.status != "failed"
3. ✅ spawn_request 文件真实落盘
4. ✅ consumed 文件真实落盘
5. ✅ completion_receipt 文件真实落盘
6. ✅ (可选) api_execution 文件真实落盘
7. ✅ 关键字段可查询、可验证

---

*End of Design Summary*
