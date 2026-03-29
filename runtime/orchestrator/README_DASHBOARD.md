# 编排系统可视化看板 (Batch 6)

> **状态**: ✅ 已完成  
> **版本**: v1.0  
> **日期**: 2026-03-30

---

## 概述

最小可用可视化看板，基于现有 observability 状态卡/统一索引，提供可直接查看的任务总览。

**核心原则**:
- ✅ 严格基于现有 observability truth（cards/index/boards）读取
- ✅ 不引入新的真值链
- ✅ 轻量方案（TUI，无需浏览器）
- ✅ 最小交付：一个可运行入口 + README + 验证脚本

---

## 快速开始

### 前置条件

```bash
# 确保 rich 已安装
pip3 install rich --break-system-packages

# 或使用 pipx（推荐）
pipx install rich
```

### 启动看板

```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

# 方式 1: 实时刷新看板（默认 5 秒）
python runtime/orchestrator/dashboard.py

# 方式 2: 指定刷新间隔
python runtime/orchestrator/dashboard.py --refresh 10

# 方式 3: 单次快照（不刷新）
python runtime/orchestrator/dashboard.py --once

# 方式 4: 导出 JSON 快照
python runtime/orchestrator/dashboard.py --export /tmp/board-snapshot.json
```

### 命令行选项

```
usage: dashboard.py [-h] [--refresh REFRESH] [--once] [--export PATH] [--card-dir CARD_DIR]

编排系统可视化看板 - Batch 6

选项:
  -h, --help            显示帮助信息
  --refresh, -r REFRESH 刷新间隔（秒），默认 5.0
  --once, -o            单次快照模式（不刷新）
  --export, -e PATH     导出 JSON 快照到指定路径
  --card-dir, -d PATH   状态卡目录（默认：~/.openclaw/shared-context/observability/cards）

示例:
  python dashboard.py                    # 实时看板（5 秒刷新）
  python dashboard.py --refresh 10       # 10 秒刷新
  python dashboard.py --once             # 单次快照
  python dashboard.py --export out.json  # 导出 JSON
```

---

## 看板内容

### 1. 任务摘要面板

显示：
- 任务总数
- 活跃任务数（running + dispatch）
- 完成任务数
- 失败任务数
- 按 Owner 分组统计

### 2. 按阶段分组表

显示所有任务按 stage 分组：
- planning
- dispatch
- running
- callback_received
- closeout
- completed
- failed
- cancelled

每个 stage 显示：任务数、任务 ID、Owner、心跳时间

### 3. 按 Owner 分组表

显示每个 Owner 的任务统计：
- 总数
- Running 数量
- Dispatch 数量
- Completed 数量
- Failed 数量

### 4. 最近活跃任务列表

显示最近 15 个活跃任务的详细信息：
- Task ID
- Scenario（场景类型）
- Owner（负责 agent）
- Executor（执行后端）
- Stage（当前阶段）
- 心跳（相对时间）
- ETA（承诺完成时间）
- Anchor（锚点信息）

---

## 颜色说明

### 阶段颜色

| Stage | 颜色 | 说明 |
|-------|------|------|
| planning | gray50 | 规划中 |
| dispatch | blue | 已分派 |
| running | yellow | 运行中 |
| callback_received | cyan | 已收到回调 |
| closeout | magenta | 收尾中 |
| completed | green | 已完成 |
| failed | red | 已失败 |
| cancelled | dim | 已取消 |

### ETA 颜色

| 状态 | 颜色 | 说明 |
|------|------|------|
| 已过期 | red | 超过承诺时间 |
| 30 分钟内到期 | yellow | 即将到期 |
| 正常 | green | 时间充裕 |

---

## 数据源

看板直接读取以下目录的状态卡：

```
~/.openclaw/shared-context/observability/
├── cards/           # 状态卡 JSON 文件（真值）
├── index/           # 索引文件（按 owner 分片）
└── boards/          # 看板快照（历史）
```

**重要**: 看板只读，不修改任何数据。

---

## 集成方式

### Python API

```python
from observability_card import list_cards, generate_board_snapshot
from dashboard import render_dashboard, Dashboard

# 方式 1: 使用便捷函数
cards = list_cards(limit=1000)
snapshot = generate_board_snapshot()

# 方式 2: 使用 Dashboard 类
dashboard = Dashboard(refresh_interval=5.0)
cards = dashboard.load_cards()
dashboard.render_once()

# 方式 3: 导出快照
dashboard.export_snapshot("/tmp/board-snapshot.json")
```

### 与现有系统集成

看板与以下组件兼容：

1. **observability_card.py**: 直接读取状态卡
2. **tmux_status_sync.py**: 显示 tmux 会话状态
3. **completion_receipt.py**: 显示完成回执
4. **alert_dispatcher.py**: 可与告警系统集成（后续批次）

---

## 验证与测试

### 运行验证脚本

```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

# 运行测试
python runtime/tests/orchestrator/test_dashboard.py
```

### 手动验证

```bash
# 1. 检查状态卡目录
ls -la ~/.openclaw/shared-context/observability/cards/

# 2. 启动看板
python runtime/orchestrator/dashboard.py --once

# 3. 导出快照并检查
python runtime/orchestrator/dashboard.py --export /tmp/test-snapshot.json
cat /tmp/test-snapshot.json | python3 -m json.tool | head -50
```

---

## 故障排除

### 问题 1: rich 未安装

```
ModuleNotFoundError: No module named 'rich'
```

**解决**:
```bash
pip3 install rich --break-system-packages
```

### 问题 2: 状态卡目录不存在

```
FileNotFoundError: [Errno 2] No such file or directory: '~/.openclaw/shared-context/observability/cards'
```

**解决**:
```bash
mkdir -p ~/.openclaw/shared-context/observability/{cards,index,boards}
```

### 问题 3: 终端不支持颜色

**解决**: 使用 `--once` 模式或检查终端配置：
```bash
export TERM=xterm-256color
```

### 问题 4: 看板显示乱码

**解决**: 确保终端支持 UTF-8：
```bash
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
```

---

## 后续增强（可选）

以下功能可在后续批次中添加：

| 功能 | 说明 | 优先级 |
|------|------|--------|
| Web UI | 基于 Flask/FastAPI 的 Web 界面 | P2 |
| 自动刷新优化 | 仅在数据变化时刷新 | P2 |
| 告警集成 | 在看板中显示未确认告警 | P2 |
| 过滤/搜索 | 按 owner/scenario/stage 过滤 | P3 |
| 历史趋势 | 显示任务完成趋势图 | P3 |
| 导出 CSV | 支持导出为 CSV 格式 | P3 |

---

## 设计决策

### 为什么选择 TUI 而非 Web UI？

1. **轻量**: 无需额外服务器，直接终端运行
2. **快速**: 启动时间 <1 秒
3. **低依赖**: 仅需 rich 库
4. **SSH 友好**: 可直接在远程服务器使用
5. **符合 Batch 6 目标**: 最小可用，而非大而全

### 为什么读取现有状态卡而非新建数据源？

1. **单一真值**: 避免数据不一致
2. **向后兼容**: 不影响现有系统
3. **简单**: 无需额外同步逻辑

### 为什么使用 rich 库？

1. **美观**: 内置丰富的样式和布局
2. **易用**: API 简洁，学习成本低
3. **跨平台**: 支持 macOS/Linux/Windows
4. **活跃维护**: 社区活跃，文档完善

---

## Git 提交

```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal

git add runtime/orchestrator/dashboard.py
git add runtime/orchestrator/README_DASHBOARD.md
git add runtime/tests/orchestrator/test_dashboard.py

git commit -m "Observability Batch 6: Minimal Visualization Dashboard

- Add dashboard.py: TUI dashboard using rich library
- Add README_DASHBOARD.md: usage guide and documentation
- Add test_dashboard.py: verification script
- Features:
  - Task summary panel (total/active/completed/failed)
  - Grouped by stage with color coding
  - Grouped by owner statistics
  - Recent active tasks list (15 most recent)
  - Key fields: task_id/scenario/owner/executor/stage/heartbeat/ETA/anchor
  - Real-time refresh (configurable interval)
  - Export to JSON snapshot
- Quality gates:
  - Read-only: uses existing observability cards (no new truth chain)
  - Minimal: TUI instead of full web UI
  - Tested: verification script included
  - Documented: README with examples and troubleshooting

Usage:
  python runtime/orchestrator/dashboard.py           # Live dashboard
  python runtime/orchestrator/dashboard.py --once    # Single snapshot
  python runtime/orchestrator/dashboard.py --export out.json  # Export JSON"

git push origin main
```

---

## 结论

✅ **Batch 6 已完成**

- 最小可用 TUI 看板
- 基于现有 observability truth
- 无新真值链
- 包含验证脚本和文档
- 可立即使用
