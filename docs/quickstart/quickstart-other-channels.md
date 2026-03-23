# 其他频道 Quickstart（非 trading 场景）

> 适用场景：除 `trading_roundtable` 外的所有频道（如架构讨论、产品评审、运营协调等）
> 
> 成熟度：**thin bridge / allowlist / safe semi-auto**，不是默认全自动

---

## 1. 默认入口

**非 trading 场景默认走 `channel_roundtable`，不需要新 adapter。**

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --context channel_roundtable \
  --channel-id "<你的频道 ID>" \
  --channel-name "<你的频道名称>" \
  --topic "<讨论主题>"
```

---

## 2. 首次接入建议

**首次建议 `allow_auto_dispatch=false`**，先验证 callback / ack / dispatch artifacts 稳定，再决定是否放开默认自动续跑。

```bash
python3 ~/.openclaw/scripts/orch_command.py \
  --context channel_roundtable \
  --channel-id "<你的频道 ID>" \
  --channel-name "<你的频道名称>" \
  --topic "<讨论主题>" \
  --auto-execute false
```

---

## 3. 最小可运行命令

基于 monorepo 内 runtime 路径的最小命令：

```bash
# 从 runtime 目录直接运行
cd <path-to-repo>/openclaw-company-orchestration-proposal
python3 runtime/scripts/orch_command.py \
  --context channel_roundtable \
  --channel-id "<channel-id>" \
  --channel-name "<channel-name>" \
  --topic "<topic>"
```

输出为 JSON contract，可重定向到文件：

```bash
python3 runtime/scripts/orch_command.py \
  --context channel_roundtable \
  --channel-id "-1002381931352" \
  --channel-name "general" \
  --topic "示例讨论" \
  --output /tmp/orch-contract.json
```

---

## 4. 何时仍需显式策略/allowlist

以下情况需要显式配置策略或 allowlist：

| 场景 | 建议配置 |
|------|----------|
| 首次接入新频道 | `allow_auto_dispatch=false` |
| 需要 human-gate 审批 | 显式声明 `approval_required=true` |
| 涉及敏感操作（生产变更、资金相关） | 显式 allowlist + human-gate |
| 需要跨天/强恢复/强审计 | 考虑 Temporal 或额外 watcher |
| 需要自动续跑下一轮 | 先验证 3-5 轮手动 callback 稳定，再改 `auto_execute=true` |

---

## 5. 验证步骤

1. **生成 contract**
   ```bash
   python3 runtime/scripts/orch_command.py --context channel_roundtable --channel-id "xxx" --topic "测试" --output /tmp/test-contract.json
   ```

2. **检查 contract 结构**
   ```bash
   cat /tmp/test-contract.json | python3 -m json.tool | head -50
   ```

3. **确认关键字段**
   - `orchestration.context` = `channel_roundtable`
   - `orchestration.entrypoint.auto_execute` = `true` 或 `false`
   - `orchestration.evidence.channel` 包含正确的 channel_id/channel_name

4. **运行轻量测试**（可选）
   ```bash
   cd <path-to-repo>/openclaw-company-orchestration-proposal
   python3 -m unittest tests.test_orchestration_entry -v
   ```

---

## 6. 下一步

- 阅读完整 contract：`runtime/orchestrator/entry_defaults.py`
- 查看示例：`examples/` 目录
- 了解 callback 机制：`docs/continuation-contract-v1.md`
- 了解调度器：`docs/scheduler-dispatch-contract.md`

---

## 红线

- ❌ 不要把当前成熟度理解成"默认全自动"
- ❌ 不要在生产环境直接 `auto_execute=true`  without 验证
- ❌ 不要跳过 callback / ack 验证直接上自动续跑
- ✅ 首次接入一律 `allow_auto_dispatch=false`
- ✅ 先跑通 3-5 轮手动 callback，再考虑自动
- ✅ 涉及敏感操作必须 human-gate
