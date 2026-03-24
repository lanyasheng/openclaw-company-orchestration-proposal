# 待更新文档清单 (2026-03-24)

> 来源：架构健康度报告第 7 节
> 
> 按优先级排序

---

## 1. 高优先级 (P1)

### 1.1 CURRENT_TRUTH.md 更新

**文件**: `docs/CURRENT_TRUTH.md`

**更新内容**:

#### 第 7.3 节 "当前成熟度边界 (2026-03-23 V10 更新)"

**当前内容**:
```markdown
- ✅ **434 个测试全部通过**
- ✅ **P0-3 Batches 1-6**: Legacy cleanup completed (2026-03-23)
```

**建议更新**:
```markdown
- ✅ **468 个测试全部通过** (2026-03-24)
- ✅ **P0-3 Batches 1-8**: Legacy cleanup completed (2026-03-23)
- ✅ **架构健康度审查完成**: ARCHITECTURE_HEALTH_REPORT_2026-03-24.md (95/100 健康)
```

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具替换：
# "434 个测试" → "468 个测试"
# "Batches 1-6" → "Batches 1-8"
# 在章节末尾添加架构健康度报告引用
```

**影响范围**: 
- 真值入口更新
- 外部引用同步

---

### 1.2 Technical Debt 文档更新

**文件**: `docs/technical-debt/technical-debt-2026-03-22.md`

**更新内容**:

#### 第 1.1 节 "trading_roundtable.py 职责过大"

**当前优先级**: P0

**建议更新**: 在章节顶部添加审查确认标记

```markdown
### 1.1 `trading_roundtable.py` 职责过大

> **架构健康度审查确认 (2026-03-24)**: 此债务已确认为唯一 P0 级技术债务
> 
> **审查建议**: 优先处理 (4-6 小时工作量)

**问题**:
- 文件行数：~1500 行
...
```

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具在 1.1 节顶部添加审查确认标记
```

**影响范围**: 技术债务优先级确认

---

## 2. 中优先级 (P2)

### 2.1 runtime/orchestrator/README.md 更新

**文件**: `runtime/orchestrator/README.md`

**更新内容**:

#### 新增章节 "测试覆盖"

在 "Backend Policy" 章节后添加：

```markdown
---

## 测试覆盖 (2026-03-24)

**总测试数**: 468 tests  
**通过率**: 100%  
**执行时间**: ~47s

```bash
# 运行全部测试
python3 -m pytest tests/orchestrator/ -v --tb=short

# 运行特定模块测试
python3 -m pytest tests/orchestrator/test_bridge_consumer.py -v
python3 -m pytest tests/orchestrator/test_sessions_spawn_bridge.py -v
python3 -m pytest tests/orchestrator/test_continuation_backends_lifecycle.py -v
```

**核心模块覆盖**:
- `bridge_consumer.py`: 18 tests
- `sessions_spawn_bridge.py`: 24 tests
- `sessions_spawn_request.py`: 23 tests
- `callback_auto_close.py`: 26 tests
- `continuation_backends.py`: 29 tests (lifecycle kernel)
- `trading_roundtable.py`: 20 tests
- `channel_roundtable.py`: 集成测试覆盖

**详细报告**: [`../reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md`](../reports/ARCHITECTURE_HEALTH_REPORT_2026-03-24.md)
```

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具在 README.md 中添加测试覆盖章节
```

**影响范围**: README 文档增强

---

### 2.2 Batch Summaries 补充

**文件**: `docs/batch-summaries/`

**检查项目**:
- [ ] P0-3-Batch-7-Fix-Real-Execution-Path.md (已存在)
- [ ] P0-3-Batch-8-Auto-Trigger-Fix.md (已存在)
- [ ] 确认 Batches 7-8 详细内容与 CURRENT_TRUTH.md 一致

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 检查 Batches 7-8 内容
cat docs/batch-summaries/P0-3-Batch-7-Fix-Real-Execution-Path.md
cat docs/batch-summaries/P0-3-Batch-8-Auto-Trigger-Fix.md
# 确认与 CURRENT_TRUTH.md 第 7.3 节一致
```

**影响范围**: 文档完整性

---

## 3. 低优先级 (P3)

### 3.1 README.md 更新

**文件**: `README.md`

**更新内容**:

#### 在 "How it actually works" 章节后添加

```markdown
---

## 架构健康度

**最新审查**: 2026-03-24  
**健康度评分**: 95/100 (🟢 健康)  
**测试覆盖**: 468 tests (100% 通过率)

**详细报告**: [`ARCHITECTURE_HEALTH_REPORT_2026-03-24.md`](ARCHITECTURE_HEALTH_REPORT_2026-03-24.md)

**核心发现**:
- ✅ 双轨后端策略清晰且执行到位
- ✅ 文档与代码真值对齐
- ✅ 测试覆盖全面
- ⚠️ trading_roundtable.py 拆分是唯一 P0 级技术债务
```

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具在 README.md 中添加架构健康度章节
```

**影响范围**: 仓库首页增强

---

### 3.2 migration-retirement-plan.md 更新

**文件**: `docs/migration/migration-retirement-plan.md`

**更新内容**:

#### 第 5 节 "Success Metrics"

**当前内容**:
```markdown
### 5.2 Current Metrics (2026-03-23)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Total test coverage | >80% | ✅ 434 tests | ✅ Complete |
```

**建议更新**:
```markdown
### 5.2 Current Metrics (2026-03-24)

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Total test coverage | >80% | ✅ 468 tests | ✅ Complete |
| Architecture health score | >90 | ✅ 95/100 | ✅ Complete |
```

**执行方法**:
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
# 使用 edit 工具更新指标表格
```

**影响范围**: 双轨策略文档指标更新

---

## 4. 执行顺序

### 立即执行 (P1)
1. [ ] 更新 `docs/CURRENT_TRUTH.md` (测试数量 + Batches 7-8 状态)
2. [ ] 更新 `docs/technical-debt/technical-debt-2026-03-22.md` (D1 优先级确认)

### 后续执行 (P2)
3. [ ] 更新 `runtime/orchestrator/README.md` (添加测试覆盖章节)
4. [ ] 验证 Batches 7-8 详细内容

### 可选执行 (P3)
5. [ ] 更新 `README.md` (添加架构健康度章节)
6. [ ] 更新 `docs/migration/migration-retirement-plan.md` (指标更新)

---

## 5. 验证方法

执行更新后，运行以下命令验证：

```bash
# 1. 验证 CURRENT_TRUTH.md 更新
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
grep "468 个测试" docs/CURRENT_TRUTH.md
# 预期：找到更新后的测试数量

grep "Batches 1-8" docs/CURRENT_TRUTH.md
# 预期：找到更新后的批次状态

# 2. 验证技术债务文档更新
grep "架构健康度审查确认" docs/technical-debt/technical-debt-2026-03-22.md
# 预期：找到审查确认标记

# 3. 验证 README.md 更新
grep "架构健康度" README.md
# 预期：找到架构健康度章节 (如执行 P3 更新)

# 4. 验证 git 状态
git status
# 应仅显示文档修改
```

---

## 6. Commit 模板

### P1 更新 Commit
```
docs: 更新 CURRENT_TRUTH.md 和 technical-debt (架构审查后续)

- CURRENT_TRUTH.md:
  - 更新测试数量 434 → 468
  - 更新批次状态 Batches 1-6 → Batches 1-8
  - 添加架构健康度报告引用

- technical-debt-2026-03-22.md:
  - D1 (trading_roundtable 拆分) 添加审查确认标记
  - 明确为唯一 P0 级技术债务

来源：ARCHITECTURE_HEALTH_REPORT_2026-03-24.md
```

### P2 更新 Commit
```
docs: 更新 runtime/orchestrator/README.md 添加测试覆盖

- 新增"测试覆盖"章节
- 列出核心模块测试数量
- 添加详细报告引用

来源：ARCHITECTURE_HEALTH_REPORT_2026-03-24.md 第 7.2 节
```

### P3 更新 Commit
```
docs: 更新 README.md 和 migration-retirement-plan.md (架构健康度)

- README.md: 添加架构健康度章节
- migration-retirement-plan.md: 更新指标 (434→468 tests, 添加健康度评分)

来源：ARCHITECTURE_HEALTH_REPORT_2026-03-24.md 第 7.3 节
```

---

**清单生成时间**: 2026-03-24 01:15 GMT+8  
**来源**: ARCHITECTURE_HEALTH_REPORT_2026-03-24.md 第 7 节  
**维护者**: Zoe (CTO & Chief Orchestrator)
tor)
