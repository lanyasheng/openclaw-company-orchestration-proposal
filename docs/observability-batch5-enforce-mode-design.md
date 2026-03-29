# Observability Batch 5 设计摘要：Hook Enforce Mode

> **批次**: Batch 5 - 行为约束钩子可配置 enforce 模式  
> **日期**: 2026-03-29  
> **状态**: 设计中 → 实现中  
> **优先级**: P0 (用户已批准直接执行)

---

## 0. 执行摘要

### 问题陈述

当前 Batch 1-4 已完成：
- ✅ Batch 1: 状态卡 CRUD 系统
- ✅ Batch 2: 行为约束钩子（audit-only 模式）
- ✅ Batch 3: tmux 统一状态索引
- ✅ Batch 4: 主动告警 + 人话回报闭环

**最大缺口**：Batch 2 的行为约束钩子只处于 **audit-only** 模式，只记录不拦截，不阻断主流程。

具体问题：
1. 主 agent 宣称"进行中"但无执行锚点 → 只记录审计，不阻止回复
2. 子任务完成后无翻译汇报 → 只记录审计，不阻止流转
3. 无统一配置入口，无法动态调整 enforce 级别

### 设计目标

将行为约束钩子从 audit-only 升级为 **可配置的 enforce 模式**：
1. **三档可配**：audit / warn / enforce
2. **集中配置**：单一配置模块 + 环境变量覆盖
3. **可回退**：enforce 不是硬编码，可随时降级回 audit
4. **最小侵入**：不破坏现有 truth plane，拦截点在合适层级

---

## 1. 范围

### 1.1 包含的功能

| 功能 | 说明 | 优先级 |
|------|------|--------|
| **三档 enforce mode** | audit / warn / enforce | P0 |
| **集中配置模块** | `hook_config.py` 统一管理 | P0 |
| **环境变量覆盖** | `OPENCLAW_HOOK_ENFORCE_MODE` | P0 |
| **两个关键钩子升级** | promise_anchor / completion_translation | P0 |
| **单元测试** | 覆盖三档模式行为 | P0 |
| **集成测试** | 验证拦截点有效 | P1 |

### 1.2 不包含的功能（后续批次）

| 功能 | 说明 | 后续批次 |
|------|------|---------|
| 每钩子独立配置 | 当前是全局配置，后续支持 per-hook 配置 | Batch 6 |
| 动态热加载 | 当前需重启生效，后续支持运行时切换 | Batch 6 |
| 告警升级策略 | 当前 enforce 直接阻断，后续支持渐进升级 | Batch 6 |

---

## 2. 架构设计

### 2.1 配置层级

```
环境变量 (最高优先级)
    ↓
集中配置模块 (hook_config.py)
    ↓
钩子默认值 (audit-only)
```

### 2.2 Enforce Mode 定义

| 模式 | 行为 | 使用场景 |
|------|------|---------|
| **audit** | 只记录审计日志，不拦截 | 开发/测试/观察期 |
| **warn** | 记录 + 显式告警，不阻断 | 过渡期/低风险环境 |
| **enforce** | 记录 + 告警 + 阻断主流程 | 生产环境/高风险操作 |

### 2.3 拦截点设计

#### Promise Anchor Hook (post_promise_verify_hook.py)

```python
# 集成点：orchestrator.py - 会话回复前
from hooks.hook_config import get_hook_enforce_mode
from hooks.post_promise_verify_hook import verify_promise_has_anchor

mode = get_hook_enforce_mode("post_promise_verify")

if mode == "enforce":
    # 阻断模式：无锚点则阻止回复
    if not result.has_anchor:
        raise HookViolationError(f"承诺必须有执行锚点：{result.missing_reason}")
elif mode == "warn":
    # 告警模式：记录并告警，但不阻止
    if not result.has_anchor:
        log_warning(f"⚠️ 空承诺检测：{result.missing_reason}")
# mode == "audit": 只记录审计日志（现有行为）
```

#### Completion Translation Hook (post_completion_translate_hook.py)

```python
# 集成点：completion_receipt.py - receipt 创建后
from hooks.hook_config import get_hook_enforce_mode
from hooks.post_completion_translate_hook import check_completion_requires_translation

mode = get_hook_enforce_mode("post_completion_translate")

if mode == "enforce":
    # 阻断模式：无翻译则阻止 receipt 流转
    if requirement.requires_translation and not translation:
        raise HookViolationError("完成汇报必须包含翻译")
elif mode == "warn":
    # 告警模式：记录并告警，但不阻止
    if requirement.requires_translation and not translation:
        log_warning(f"⚠️ 缺少翻译汇报：{requirement.reason}")
# mode == "audit": 只记录审计日志（现有行为）
```

---

## 3. 核心设计

### 3.1 配置模块 (hook_config.py)

```python
#!/usr/bin/env python3
"""
hook_config.py — 行为约束钩子配置管理

核心功能：
- 统一配置入口
- 环境变量覆盖
- 三档 enforce mode 管理
"""

import os
from typing import Dict, Literal, Optional

EnforceMode = Literal["audit", "warn", "enforce"]

# 默认配置
DEFAULT_CONFIG = {
    "global_enforce_mode": "audit",  # 默认 audit-only（向后兼容）
    "per_hook_modes": {},  # 每钩子独立配置（后续扩展）
}

# 环境变量名
ENV_ENFORCE_MODE = "OPENCLAW_HOOK_ENFORCE_MODE"
ENV_PER_HOOK_MODES = "OPENCLAW_HOOK_PER_HOOK_MODES"


class HookConfig:
    """钩子配置管理器"""
    
    def __init__(self):
        self._config = DEFAULT_CONFIG.copy()
        self._load_from_env()
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        # 全局 enforce mode
        global_mode = os.environ.get(ENV_ENFORCE_MODE, "").strip().lower()
        if global_mode in ["audit", "warn", "enforce"]:
            self._config["global_enforce_mode"] = global_mode
        
        # 每钩子独立配置（JSON 格式）
        per_hook_json = os.environ.get(ENV_PER_HOOK_MODES, "")
        if per_hook_json:
            import json
            try:
                per_hook_modes = json.loads(per_hook_json)
                self._config["per_hook_modes"] = per_hook_modes
            except json.JSONDecodeError:
                pass  # 忽略无效 JSON
    
    def get_enforce_mode(self, hook_name: Optional[str] = None) -> EnforceMode:
        """
        获取指定钩子的 enforce mode
        
        Args:
            hook_name: 钩子名称（可选）
        
        Returns:
            EnforceMode: "audit" / "warn" / "enforce"
        """
        # 优先使用 per-hook 配置
        if hook_name and hook_name in self._config["per_hook_modes"]:
            mode = self._config["per_hook_modes"][hook_name]
            if mode in ["audit", "warn", "enforce"]:
                return mode
        
        # 回退到全局配置
        return self._config["global_enforce_mode"]
    
    def set_global_mode(self, mode: EnforceMode):
        """设置全局 enforce mode"""
        if mode in ["audit", "warn", "enforce"]:
            self._config["global_enforce_mode"] = mode
    
    def set_hook_mode(self, hook_name: str, mode: EnforceMode):
        """设置指定钩子的 enforce mode"""
        if mode in ["audit", "warn", "enforce"]:
            self._config["per_hook_modes"][hook_name] = mode


# 全局单例
_global_config = HookConfig()


def get_hook_enforce_mode(hook_name: Optional[str] = None) -> EnforceMode:
    """获取指定钩子的 enforce mode（便捷函数）"""
    return _global_config.get_enforce_mode(hook_name)


def set_global_enforce_mode(mode: EnforceMode):
    """设置全局 enforce mode（便捷函数）"""
    _global_config.set_global_mode(mode)


def set_hook_enforce_mode(hook_name: str, mode: EnforceMode):
    """设置指定钩子的 enforce mode（便捷函数）"""
    _global_config.set_hook_mode(hook_name, mode)
```

### 3.2 异常类 (hook_exceptions.py)

```python
#!/usr/bin/env python3
"""
hook_exceptions.py — 钩子违规异常

核心异常：
- HookViolationError: 钩子违规，enforce 模式下抛出
"""


class HookViolationError(Exception):
    """
    钩子违规异常
    
    在 enforce 模式下，当钩子检查失败时抛出此异常，阻断主流程。
    
    使用示例：
    ```python
    if mode == "enforce" and not check_passed:
        raise HookViolationError(f"违规原因：{reason}")
    ```
    """
    
    def __init__(self, message: str, hook_name: str = "", metadata: dict = None):
        super().__init__(message)
        self.hook_name = hook_name
        self.metadata = metadata or {}
        self.message = message
    
    def to_dict(self) -> dict:
        return {
            "error_type": "HookViolationError",
            "hook_name": self.hook_name,
            "message": self.message,
            "metadata": self.metadata,
        }
```

### 3.3 钩子升级模式

每个钩子需要：
1. 导入配置模块
2. 在关键检查点获取 enforce mode
3. 根据 mode 决定行为（audit/warn/enforce）

---

## 4. 数据结构

### 4.1 HookConfig

```json
{
  "global_enforce_mode": "audit",
  "per_hook_modes": {
    "post_promise_verify": "enforce",
    "post_completion_translate": "warn"
  }
}
```

### 4.2 HookViolationError

```json
{
  "error_type": "HookViolationError",
  "hook_name": "post_promise_verify",
  "message": "承诺必须有执行锚点：缺少 promise_anchor 字段",
  "metadata": {
    "task_id": "task_001",
    "enforce_mode": "enforce",
    "timestamp": "2026-03-29T15:00:00"
  }
}
```

---

## 5. 集成点

### 5.1 post_promise_verify_hook.py 升级

在 `verify_anchor()` 方法中：
```python
from hooks.hook_config import get_hook_enforce_mode
from hooks.hook_exceptions import HookViolationError

def verify_anchor(self, task_context, ...):
    # ... 现有检查逻辑 ...
    
    mode = get_hook_enforce_mode("post_promise_verify")
    
    if not result.has_anchor:
        if mode == "enforce":
            raise HookViolationError(
                f"承诺必须有执行锚点：{result.missing_reason}",
                hook_name="post_promise_verify",
                metadata={"task_id": task_context.get("task_id", "")}
            )
        elif mode == "warn":
            log_warning(f"⚠️ 空承诺检测：{result.missing_reason}")
        # mode == "audit": 只记录审计日志（现有行为）
    
    return result
```

### 5.2 post_completion_translate_hook.py 升级

在 `check()` 方法后：
```python
from hooks.hook_config import get_hook_enforce_mode
from hooks.hook_exceptions import HookViolationError

def enforce_translation(self, receipt, task_context):
    mode = get_hook_enforce_mode("post_completion_translate")
    
    requirement = self.check(receipt, task_context)
    
    if requirement.requires_translation:
        translation = self._generate_translation(receipt, task_context)
        
        if not translation:
            if mode == "enforce":
                raise HookViolationError(
                    "完成汇报必须包含翻译",
                    hook_name="post_completion_translate",
                    metadata={"receipt_id": receipt.get("receipt_id", "")}
                )
            elif mode == "warn":
                log_warning(f"⚠️ 缺少翻译汇报：{requirement.reason}")
        
        return translation
    
    return None
```

---

## 6. 风险与回退

### 6.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| enforce 模式阻断正常流程 | 任务无法推进 | 默认 audit，手动升级；快速回退脚本 |
| 配置错误导致钩子失效 | 无保护 | 配置验证 + 默认值保护 |
| 异常未捕获导致崩溃 | 主流程中断 | 顶层异常处理 + 降级策略 |

### 6.2 回退方案

```bash
# 1. 环境变量回退（立即生效）
export OPENCLAW_HOOK_ENFORCE_MODE=audit

# 2. 代码回退
git revert <commit_hash>

# 3. 删除配置模块（极端情况）
rm runtime/orchestrator/hooks/hook_config.py
rm runtime/orchestrator/hooks/hook_exceptions.py
```

### 6.3 边界条件

| 边界 | 处理方式 |
|------|---------|
| 配置模块导入失败 | 回退到 audit-only 模式 |
| 环境变量格式错误 | 忽略，使用默认值 |
| HookViolationError 未捕获 | 顶层异常处理，记录日志并降级 |

---

## 7. 测试策略

### 7.1 单元测试

| 测试模块 | 测试内容 | 目标覆盖率 |
|---------|---------|-----------|
| `test_hook_config.py` | 配置加载/优先级/便捷函数 | 100% |
| `test_hook_exceptions.py` | 异常类/序列化 | 100% |
| `test_hooks_enforce_mode.py` | 三档模式行为 | 100% |

### 7.2 测试场景

| 场景 | 验证内容 |
|------|---------|
| audit 模式 | 只记录审计，不抛异常 |
| warn 模式 | 记录 + 告警，不抛异常 |
| enforce 模式 | 抛 HookViolationError 阻断 |
| 环境变量覆盖 | 优先级正确 |
| 回退到 audit | 不破坏现有主链 |

---

## 8. 交付物清单

### 8.1 核心模块

| 文件 | 行数 (预估) | 说明 |
|------|-----------|------|
| `runtime/orchestrator/hooks/hook_config.py` | ~150 | 配置管理 |
| `runtime/orchestrator/hooks/hook_exceptions.py` | ~50 | 异常类 |
| `runtime/orchestrator/hooks/post_promise_verify_hook.py` | 升级 | 集成 enforce mode |
| `runtime/orchestrator/hooks/post_completion_translate_hook.py` | 升级 | 集成 enforce mode |
| `runtime/orchestrator/hooks/hook_integrations.py` | 升级 | 集成 enforce mode |

### 8.2 测试

| 文件 | 行数 (预估) | 说明 |
|------|-----------|------|
| `runtime/tests/orchestrator/hooks/test_hook_config.py` | ~150 | 配置测试 |
| `runtime/tests/orchestrator/hooks/test_hook_exceptions.py` | ~50 | 异常测试 |
| `runtime/tests/orchestrator/hooks/test_hooks_enforce_mode.py` | ~300 | 三档模式测试 |

### 8.3 文档

| 文件 | 说明 |
|------|------|
| `docs/observability-batch5-design.md` | 设计文档（本文件） |
| `docs/observability-batch5-completion-report.md` | 完成报告 |

---

## 9. 验收标准

| 验收项 | 标准 | 验证方式 |
|--------|------|---------|
| 三档 mode 可配 | audit/warn/enforce 行为正确 | 单元测试 |
| 集中配置入口 | hook_config.py 可导入 | 代码审查 |
| 环境变量覆盖 | OPENCLAW_HOOK_ENFORCE_MODE 生效 | 手动测试 |
| 两个关键钩子升级 | promise_anchor / completion_translation | 集成测试 |
| enforce 模式确实阻断 | 抛 HookViolationError | 单元测试 |
| 回退到 audit 不破坏主链 | 现有测试通过 | 回归测试 |
| Git 提交完成 | 已 push 到 origin/main | git log |

---

## 10. 质量门

| 质量门 | 标准 |
|--------|------|
| 代码质量 | 无 lint 错误，类型注解完整 |
| 测试覆盖 | 核心路径 100%，分支>80% |
| 文档完整 | 模块 docstring + 使用示例 |
| 集成兼容 | 不破坏现有 hooks / orchestrator |
| 性能 | 配置加载 <10ms |

---

## 11. 使用示例

### 11.1 开发环境（audit-only）

```bash
# 默认行为，只记录不拦截
# 无需设置环境变量
```

### 11.2 测试环境（warn 模式）

```bash
export OPENCLAW_HOOK_ENFORCE_MODE=warn
# 记录 + 告警，但不阻断
```

### 11.3 生产环境（enforce 模式）

```bash
export OPENCLAW_HOOK_ENFORCE_MODE=enforce
# 记录 + 告警 + 阻断
```

### 11.4 每钩子独立配置（后续扩展）

```bash
export OPENCLAW_HOOK_PER_HOOK_MODES='{"post_promise_verify":"enforce","post_completion_translate":"warn"}'
```

---

## 12. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-03-29 | 初始设计稿 |
| v1.0 | 2026-03-29 | 设计评审通过，开始实现 |
