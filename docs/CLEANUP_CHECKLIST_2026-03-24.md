# 待清理文件清单 (2026-03-24)

> 来源：架构健康度报告第 6 节
> 
> 优先级：P2-P3 (无高优先级清理项)

---

## 1. 建议重命名 (P2)

### 1.1 Batch Summary 命名规范化

| 当前路径 | 建议路径 | 理由 |
|----------|----------|------|
| `docs/batch-summaries/p0-2-batch-3-summary.md` | `docs/batch-summaries/P0-2-Batch-3-Summary.md` | 与其他 batch summary 命名规范一致 (P0-3 Batches 1-8 均为大写) |

**执行命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
git mv docs/batch-summaries/p0-2-batch-3-summary.md docs/batch-summaries/P0-2-Batch-3-Summary.md
git commit -m "docs: 规范化 batch summary 命名 (p0-2-batch-3 → P0-2-Batch-3)"
```

**影响范围**: 
- 无外部引用 (该文件为历史总结，未被其他文档引用)
- GitHub 链接自动重定向

---

## 2. 建议归档 (P3)

### 2.1 Continuation Kernel 历史文档

| 当前路径 | 建议路径 | 理由 |
|----------|----------|------|
| `archive/old-docs/partial-continuation-kernel-v5.md` | `docs/history/continuation-kernel-history/partial-continuation-kernel-v5.md` | CURRENT_TRUTH.md 仍引用为"历史参考"，但放在 `archive/` 下不易发现 |
| `archive/old-docs/partial-continuation-kernel-v6.md` | `docs/history/continuation-kernel-history/partial-continuation-kernel-v6.md` | 同上 |
| `archive/old-docs/partial-continuation-kernel-v7.md` | `docs/history/continuation-kernel-history/partial-continuation-kernel-v7.md` | 同上 |
| `archive/old-docs/partial-continuation-kernel-v8.md` | `docs/history/continuation-kernel-history/partial-continuation-kernel-v8.md` | 同上 |
| `archive/old-docs/partial-continuation-kernel-v9.md` | `docs/history/continuation-kernel-history/partial-continuation-kernel-v9.md` | 同上 |

**执行命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
mkdir -p docs/history/continuation-kernel-history
git mv archive/old-docs/partial-continuation-kernel-v*.md docs/history/continuation-kernel-history/
git commit -m "docs: 将 continuation kernel 历史文档移至 docs/history/ (更易发现)"
```

**影响范围**: 
- CURRENT_TRUTH.md 中的引用路径需要更新
- 外部链接可能失效 (但这些都是历史文档，外部引用可能性低)

**替代方案**: 保留在 `archive/old-docs/`，但在 CURRENT_TRUTH.md 中添加更明确的"已归档"标记

---

## 3. 建议清理的注释 (P3)

### 3.1 待提交标记清理

以下文件中包含"P0-3 Batch X (待提交)"或类似注释，但所有批次已提交：

| 文件 | 清理内容 | 建议操作 |
|------|----------|----------|
| `runtime/orchestrator/entry_defaults.py` | `# P0-3 Batch 5 (2026-03-23): 待提交` | 改为 `# P0-3 Batch 5 (2026-03-23): ✅ 已提交 (commit 62ed6ca)` |
| `runtime/orchestrator/continuation_backends.py` | `# P0-3 Batch 4 (待提交)` | 改为 `# P0-3 Batch 4 (2026-03-23): ✅ 已提交 (commit 7ef74cc)` |
| `runtime/orchestrator/tmux_terminal_receipts.py` | `# Batch 6 (待提交)` | 改为 `# Batch 6 (2026-03-23): ✅ 已提交 (commit 06dbe0b)` |

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具或手动替换
# 搜索模式："待提交" → 替换为 "✅ 已提交 (commit XXX)"
```

**影响范围**: 仅注释，无功能影响

---

## 4. 建议清理的代码 (P2)

### 4.1 测试警告修复

12 个测试函数返回布尔值而非使用 `assert`，导致 pytest 警告：

| 文件 | 测试函数 | 建议修复 |
|------|----------|----------|
| `tests/orchestrator/alerts/test_openclaw_adapter_smoke.py` | `test_openclaw_adapter_dry_run` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_openclaw_adapter_smoke.py` | `test_openclaw_adapter_binary_detection` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_openclaw_adapter_smoke.py` | `test_openclaw_adapter_real_send` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_openclaw_adapter_smoke.py` | `test_send_alert_convenience_function` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_dedup` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_throttle` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_state_file` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_log_file` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_payload_structure` | `return True` → `assert True` |
| `tests/orchestrator/alerts/test_trading_alert_sender.py` | `test_list_recent_alerts` | `return True` → `assert True` |

**执行命令**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具批量替换
# 或手动修复每个测试函数
```

**影响范围**: 仅测试代码，无生产代码影响

---

## 5. 执行优先级

### 立即执行 (P2)
- [ ] 重命名 `p0-2-batch-3-summary.md` → `P0-2-Batch-3-Summary.md`
- [ ] 修复测试警告 (12 个测试函数)

### 后续执行 (P3)
- [ ] 归档 continuation kernel 历史文档 (或保留但添加明确标记)
- [ ] 清理待提交注释

### 暂不执行
- [ ] 无 (所有清理项均为低风险)

---

## 6. 验证方法

执行清理后，运行以下命令验证：

```bash
# 1. 验证测试通过
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python3 -m pytest tests/orchestrator/ -v --tb=short

# 2. 验证无 pytest 警告
python3 -m pytest tests/orchestrator/alerts/ -v 2>&1 | grep -c "PytestReturnNotNoneWarning"
# 预期输出：0

# 3. 验证 git 状态
git status
# 应仅显示重命名和注释修改

# 4. 验证文档链接
grep -r "p0-2-batch-3" docs/
# 预期输出：无 (或仅历史引用)
```

---

**清单生成时间**: 2026-03-24 01:15 GMT+8  
**来源**: ARCHITECTURE_HEALTH_REPORT_2026-03-24.md 第 6 节  
**维护者**: Zoe (CTO & Chief Orchestrator)
