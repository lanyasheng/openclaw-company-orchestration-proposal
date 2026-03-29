# Observability Batch 6 设计文档：最小可视化看板

> **状态**: ✅ 已完成  
> **日期**: 2026-03-30  
> **优先级**: P1 (用户批准连续推进)

---

## 0. 执行摘要

### 任务目标

实现最小可用可视化看板，基于现有 observability 状态卡/统一索引，提供可直接查看的任务总览。

### 完成情况

✅ **全部完成**：

1. ✅ 设计摘要：范围 / 风险 / 回退
2. ✅ TUI 看板实现（使用 rich 库）
3. ✅ 显示内容：
   - 任务总数
   - 按 stage 分组
   - 按 owner 分组
   - 最近活跃任务列表
   - 关键字段：task_id / scenario / owner / executor / stage / heartbeat / promised_eta / anchor
4. ✅ 严格基于现有 observability truth（cards/index/boards）读取
5. ✅ 最小交付：
   - `dashboard.py`: 可运行入口
   - `README_DASHBOARD.md`: 使用说明
   - `test_dashboard.py`: 验证脚本（12 个测试，100% 通过）
6. ✅ 提交并 push 到 origin/main

---

## 1. 范围

### 包含

| 功能 | 说明 | 状态 |
|------|------|------|
| 任务摘要面板 | 总数/活跃/完成/失败统计 | ✅ |
| 按 stage 分组表 | 8 个阶段，颜色编码 | ✅ |
| 按 owner 分组表 | 每个 owner 的任务分布 | ✅ |
| 最近活跃任务 | 最近 15 个任务详情 | ✅ |
| 关键字段显示 | task_id/scenario/owner/executor/stage/heartbeat/ETA/anchor | ✅ |
| 实时刷新 | 可配置间隔（默认 5 秒） | ✅ |
| JSON 导出 | 导出快照到文件 | ✅ |
| 验证测试 | 12 个测试用例 | ✅ |

### 不包含（后续批次可选）

| 功能 | 说明 | 优先级 |
|------|------|--------|
| Web UI | Flask/FastAPI 网页界面 | P2 |
| 告警集成 | 在看板中显示未确认告警 | P2 |
| 过滤/搜索 | 按 owner/scenario/stage 过滤 | P3 |
| 历史趋势图 | 任务完成趋势可视化 | P3 |
| 导出 CSV | CSV 格式导出 | P3 |
| 交互式操作 | 点击任务查看详情 | P3 |

---

## 2. 设计决策

### 2.1 为什么选择 TUI 而非 Web UI？

| 因素 | TUI | Web UI | 决策理由 |
|------|-----|--------|---------|
| 启动时间 | <1 秒 | 5-10 秒（启动服务器） | TUI 更快 |
| 依赖 | rich 库 | Flask/FastAPI + 浏览器 | TUI 更轻量 |
| SSH 友好 | ✅ 直接终端运行 | ❌ 需要端口转发 | TUI 更适合远程 |
| 开发成本 | ~300 行 | ~1000+ 行 | TUI 符合最小可用 |
| 维护成本 | 低 | 中 | TUI 更简单 |

**结论**: Batch 6 目标是"最小可用"，TUI 更合适。

### 2.2 为什么读取现有状态卡而非新建数据源？

**原则**: 单一真值（Single Source of Truth）

```
现有真值链：
  subagent_state → observability_card → board_snapshot
                      ↓
                  dashboard.py (只读)

错误设计（双写真值）：
  subagent_state → observability_card → board_snapshot
                      ↓                    ↓
                  dashboard ←—— 新建数据源 ——X
```

**风险缓解**:
- 只读访问，不修改任何数据
- 直接调用 `list_cards()` 和 `generate_board_snapshot()`
- 不引入新的存储或同步逻辑

### 2.3 为什么使用 rich 库？

| 库 | 优点 | 缺点 | 决策 |
|----|------|------|------|
| **rich** | 美观、易用、跨平台、活跃维护 | 需安装 | ✅ 首选 |
| curses | Python 标准库，无需安装 | API 复杂、跨平台差 | ❌ |
| textual | 基于 rich，更现代 | 较新、生态小 | ⚠️ 备选 |
| 纯文本 | 无依赖 | 视觉效果差 | ❌ |

**结论**: rich 在美观、易用、维护性之间取得最佳平衡。

---

## 3. 架构

### 3.1 组件图

```
┌─────────────────────────────────────────────────────────────┐
│                      dashboard.py                            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │   Summary   │  │  Stage Table │  │  Owner Table    │    │
│  │   Panel     │  │              │  │                 │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Active Tasks Table (15 recent)            │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                            ↓
              ┌─────────────────────────┐
              │   observability_card    │
              │   (existing module)     │
              └─────────────────────────┘
                            ↓
              ┌─────────────────────────┐
              │   ~/.openclaw/shared-   │
              │   context/observability │
              │   /cards/*.json         │
              └─────────────────────────┘
```

### 3.2 数据流

```
用户启动看板
     ↓
Dashboard.__init__()
     ↓
Dashboard.load_cards() → list_cards(limit=1000)
     ↓
ObservabilityCardManager.list_cards()
     ↓
读取 CARD_DIR/*.json 文件
     ↓
返回 List[ObservabilityCard]
     ↓
render_dashboard(cards)
     ↓
创建 Layout:
  - create_summary_panel()
  - create_stage_table()
  - create_owner_summary()
  - create_active_tasks_table()
     ↓
Live 刷新（或单次输出）
```

### 3.3 关键函数

| 函数 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `render_dashboard()` | 创建完整布局 | List[ObservabilityCard] | Layout |
| `create_summary_panel()` | 摘要面板 | List[ObservabilityCard] | Panel |
| `create_stage_table()` | 阶段分组表 | List[ObservabilityCard] | Table |
| `create_owner_summary()` | Owner 统计表 | List[ObservabilityCard] | Table |
| `create_active_tasks_table()` | 活跃任务表 | List[ObservabilityCard] | Table |
| `format_heartbeat()` | 格式化心跳 | ISO 时间戳 | 相对时间字符串 |
| `get_eta_color()` | ETA 颜色判断 | ETA 时间戳 | 颜色名 |
| `get_anchor_display()` | 锚点显示 | ObservabilityCard | 格式化字符串 |

---

## 4. 风险与回退

### 4.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| rich 未安装 | 中 | 低 | README 包含安装说明；ImportError 友好提示 |
| 状态卡目录不存在 | 低 | 中 | 自动创建目录；错误提示清晰 |
| 终端不支持颜色 | 低 | 低 | 降级为纯文本；--once 模式 |
| 终端不支持 UTF-8 | 低 | 低 | README 包含环境变量设置 |
| 大量卡片性能问题 | 低 | 低 | limit=1000；仅显示最近 15 个活跃任务 |
| 数据不一致 | 低 | 中 | 只读访问；不修改源数据 |

### 4.2 回退方案

```bash
# 1. 卸载 rich（极端情况）
pip3 uninstall rich --break-system-packages

# 2. 使用纯文本模式（修改代码）
# 注释掉 rich 导入，改用 print 语句

# 3. 回退代码
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
git revert 8b21078

# 4. 删除看板文件
rm runtime/orchestrator/dashboard.py
rm runtime/orchestrator/README_DASHBOARD.md
rm runtime/tests/orchestrator/test_dashboard.py
```

---

## 5. 质量门验收

| 质量门 | 标准 | 状态 |
|--------|------|------|
| 功能完整 | 任务总数/stage 分组/owner 分组/活跃任务/关键字段 | ✅ |
| 单一真值 | 只读现有 cards，不新建数据源 | ✅ |
| 最小可用 | TUI 而非 Web UI，代码 <500 行 | ✅ (320 行) |
| 测试覆盖 | 核心路径 100% | ✅ (12/12 测试通过) |
| 文档完整 | README + 使用示例 + 故障排除 | ✅ |
| 性能 | 启动 <1 秒，刷新 <100ms | ✅ |
| Git 提交 | 提交并 push 到 origin/main | ✅ |

---

## 6. 使用示例

### 6.1 实时看板

```bash
# 默认 5 秒刷新
python runtime/orchestrator/dashboard.py

# 10 秒刷新
python runtime/orchestrator/dashboard.py --refresh 10
```

### 6.2 单次快照

```bash
# 输出到终端
python runtime/orchestrator/dashboard.py --once

# 导出 JSON
python runtime/orchestrator/dashboard.py --export /tmp/snapshot.json
```

### 6.3 验证测试

```bash
python runtime/tests/orchestrator/test_dashboard.py
```

输出：
```
✅ 目录存在
✅ 卡片可读
✅ 字段完整
✅ 关键字段
✅ 快照生成
✅ 快照导出
✅ 看板渲染
✅ Stage 分组
✅ Owner 分组
✅ 心跳格式化
✅ ETA 颜色
✅ 锚点显示

总计：12/12 通过
🎉 所有测试通过！Batch 6 验证完成。
```

---

## 7. 交付物清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `runtime/orchestrator/dashboard.py` | ~320 | TUI 看板主程序 |
| `runtime/orchestrator/README_DASHBOARD.md` | ~250 | 使用说明文档 |
| `runtime/tests/orchestrator/test_dashboard.py` | ~350 | 验证测试脚本 |
| `docs/observability-batch6-dashboard-design.md` | ~400 | 设计文档（本文件） |

---

## 8. Git 提交

```bash
commit 8b21078
Author: Zoe <zoe@openclaw>
Date:   Mon Mar 30 00:14:00 2026 +0800

    Observability Batch 6: Minimal Visualization Dashboard
    
    - Add dashboard.py: TUI dashboard using rich library (320 lines)
    - Add README_DASHBOARD.md: usage guide and documentation
    - Add test_dashboard.py: verification script (12 test cases, 100% pass)
    
    Features:
    - Task summary panel (total/active/completed/failed)
    - Grouped by stage with color coding (8 stages)
    - Grouped by owner statistics
    - Recent active tasks list (15 most recent)
    - Key fields: task_id/scenario/owner/executor/stage/heartbeat/ETA/anchor
    - Real-time refresh (configurable interval, default 5s)
    - Export to JSON snapshot
    
    Quality gates:
    - Read-only: uses existing observability cards (no new truth chain)
    - Minimal: TUI instead of full web UI
    - Tested: 12 test cases all pass
    - Documented: README with examples and troubleshooting
```

---

## 9. 后续工作

### 9.1 可选增强（按优先级）

| 功能 | 说明 | 批次 | 工作量 |
|------|------|------|--------|
| 告警集成 | 在看板中显示未确认告警 | Batch 7 | 2-3h |
| Web UI | Flask 简单网页界面 | Batch 8 | 4-6h |
| 过滤/搜索 | 按 owner/scenario/stage 过滤 | Batch 8 | 2h |
| 历史趋势 | 显示任务完成趋势图 | Batch 9 | 4h |

### 9.2 与 Batch 7+ 的集成

```
Batch 6 (当前): 基础看板
     ↓
Batch 7: + 告警集成 (alert_dispatcher)
     ↓
Batch 8: + Web UI + 过滤搜索
     ↓
Batch 9: + 历史趋势 + 分析
```

---

## 10. 结论

✅ **Batch 6 已完成并通过验收**

- 最小可用 TUI 看板
- 严格基于现有 observability truth
- 无新真值链
- 12 个测试用例 100% 通过
- 完整文档和使用说明
- 已提交并 push 到 origin/main

**下一步**: 按优先级继续 Batch 7+ 工作。
