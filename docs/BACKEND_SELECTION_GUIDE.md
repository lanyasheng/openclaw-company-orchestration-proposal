# Backend Selection Guide

**Version:** P0-3 Batch 7 (2026-03-30)  
**Status:** Production ready

## Overview

OpenClaw Orchestration 支持两种执行后端 (backend)：
- **subagent**: 默认后端，适用于自动化、CI/CD、非交互式执行
- **tmux**: 一等公民后端，适用于交互式调试、实时监控、人工观测

系统会根据任务特征自动推荐最佳后端，同时支持显式指定覆盖自动推荐。

## Backend 选择决策树

```
收到任务
├── 用户显式指定 backend_preference？
│   ├── 是 → 使用用户指定（最高优先级，不可覆盖）
│   └── 否 → 进入自动推荐
│
└── 自动推荐逻辑（backend_selector）
    ├── 预计时长 > 30 分钟？ → 倾向 tmux (+0.5 分)
    ├── 预计时长 ≤ 30 分钟？ → 倾向 subagent (+0.3 分)
    ├── 需要监控中间过程？ → 倾向 tmux (+0.4 分)
    ├── 包含监控关键词？ → 倾向 tmux (+0.3 分)
    ├── 包含编码关键词？ → 倾向 tmux (+0.2 分)
    ├── 包含文档关键词？ → 倾向 subagent (+0.3 分)
    └── 最终得分高者胜出
```

## 评分规则

### 基础分
- `subagent`: 0.3 分（默认）
- `tmux`: 0.0 分（默认）

### 加分项
| 因素 | 条件 | 加分 |
|------|------|------|
| 长任务 | estimated_duration > 30min | tmux +0.5 |
| 短任务 | estimated_duration ≤ 30min | subagent +0.3 |
| 需要监控 | requires_monitoring = true | tmux +0.4 |
| 监控关键词 | 包含"监控/观察/debug"等 | tmux +0.3 |
| 编码任务 | 包含"编码/实现/重构"等 | tmux +0.2 |
| 文档任务 | 包含"文档/README/注释"等 | subagent +0.3 |

### 决策阈值
- `score_tmux > score_subagent` → 推荐 tmux
- `score_subagent ≥ score_tmux` → 推荐 subagent

## 使用示例

### 示例 1: 长编码任务（自动推荐 tmux）

```python
decision = {
    "action": "proceed",
    "reason": "重构认证模块",
    "metadata": {
        "estimated_duration_minutes": 60,  # 长任务
    },
}

continuation = {
    "task_preview": "重构认证模块，预计 1 小时完成",
}

# 系统自动推荐 tmux
# backend_selection metadata:
# {
#   "auto_recommended": True,
#   "recommended_backend": "tmux",
#   "reason": "推荐 tmux：长任务 (>30min), 编码任务",
#   "confidence": 1.0,
# }
```

### 示例 2: 短文档任务（自动推荐 subagent）

```python
decision = {
    "action": "proceed",
    "reason": "写 README",
    "metadata": {
        "estimated_duration_minutes": 15,  # 短任务
    },
}

continuation = {
    "task_preview": "编写 API 文档",
}

# 系统自动推荐 subagent
```

### 示例 3: 显式指定覆盖自动推荐

```python
decision = {
    "action": "proceed",
    "reason": "长任务但用户指定 subagent",
    "metadata": {
        "orchestration_contract": {
            "backend_preference": "subagent",  # 显式指定
        },
        "estimated_duration_minutes": 60,
    },
}

# 即使用户指定 subagent 但任务是长任务
# 系统仍使用 subagent（显式偏好优先）
# backend_selection metadata:
# {
#   "explicit_override": True,
#   "explicit_preference": "subagent",
#   "auto_recommended": False,
# }
```

### 示例 4: 需要监控的调试任务

```python
continuation = {
    "task_preview": "调试偶发 bug，需要监控中间过程",
}

# 系统检测到监控关键词，推荐 tmux
```

## Tmux Backend 定位

### 是一等公民，不是兼容层

P0-3 Batch 7 (2026-03-30) 起，tmux backend 正式成为**一等公民**，与 subagent 并列：

| 特性 | subagent | tmux |
|------|----------|------|
| 定位 | 默认后端（自动化） | 一等后端（交互式） |
| 适用场景 | CI/CD、批处理、简单任务 | 调试、监控、复杂任务 |
| 中间状态可观测 | 否（通过 runner artifacts） | 是（实时 tmux pane） |
| 自动超时 | 是 | 是（watchdog） |
| 回调机制 | canonical callback | canonical callback |
| 生命周期管理 | runner + subagent_ended | tmux session + callback bridge |

### 桥脚本说明

`orchestrator_dispatch_bridge.py` 是 tmux backend 的专用桥接脚本，提供：
- `prepare`: 准备 dispatch plan 参考文档
- `start`: 启动 tmux session
- `status`: 查询 tmux 状态
- `receipt`: 构建 terminal receipt
- `complete`: 完成 dispatch 并桥接到 callback（关键路径）
- `capture/attach`: 可选工具（详细观测/交互调试）

**注意**: 桥脚本的存在是为了提供 tmux-specific 命令接口，**不表示 tmux 是兼容层**。

## Backend Selection Metadata

所有 dispatch plan 都会在 `orchestration_contract.backend_selection` 中记录选择依据：

```json
{
  "orchestration_contract": {
    "backend_selection": {
      "auto_recommended": true,
      "recommended_backend": "tmux",
      "applied_backend": "tmux",
      "confidence": 1.0,
      "reason": "推荐 tmux：长任务 (>30min), 编码任务",
      "factors": {
        "estimated_duration": 60,
        "duration_factor": "long_task",
        "coding_keywords": 1
      },
      "explicit_override": false
    }
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `auto_recommended` | bool | 是否经过自动推荐 |
| `recommended_backend` | string | 推荐的后端 |
| `applied_backend` | string | 实际应用的后端 |
| `confidence` | float | 推荐置信度 (0.0-1.0) |
| `reason` | string | 推荐理由（人类可读） |
| `factors` | dict | 决策因素（机器可读） |
| `explicit_override` | bool | 是否被显式偏好覆盖 |

## 配置建议

### 何时显式指定 backend_preference

**推荐显式指定 subagent:**
- 批处理任务
- CI/CD 流水线
- 已验证的简单重复任务

**推荐显式指定 tmux:**
- 需要人工实时观测的任务
- 容易卡住需要调试的任务
- 复杂编码任务（需要看中间过程）

**不推荐显式指定:**
- 普通任务（让系统自动推荐）
- 不确定时（先让系统推荐，再根据结果调整）

## 测试覆盖

以下测试用例已覆盖：
- ✅ 显式 backend_preference 不被自动推荐覆盖
- ✅ 未指定时调用 backend_selector 并得出可解释结果
- ✅ 长任务 (>30min) 倾向 tmux
- ✅ 短任务 (<30min) 倾向 subagent
- ✅ 需要监控的任务倾向 tmux
- ✅ 文档任务倾向 subagent
- ✅ backend_selection metadata 正确记录

运行测试：
```bash
python3 tests/orchestrator/test_backend_selector_integration.py
```

## 回退方案

### 环境变量强制指定

```bash
# 强制所有任务使用 subagent
export FORCE_BACKEND=subagent

# 强制所有任务使用 tmux
export FORCE_BACKEND=tmux
```

### 代码回退

```bash
# Git revert 本次提交
git revert <commit-hash>
```

## 相关文档

- [Design Document](docs/design/backend_selector_integration_design.md)
- [CURRENT_TRUTH](docs/CURRENT_TRUTH.md)
- [Continuation Backends](runtime/orchestrator/continuation_backends.py)
- [Backend Selector](runtime/orchestrator/backend_selector.py)
- [Dispatch Planner](runtime/orchestrator/core/dispatch_planner.py)

---

**Last Updated:** 2026-03-30  
**Maintainer:** Zoe (CTO & Chief Orchestrator)
