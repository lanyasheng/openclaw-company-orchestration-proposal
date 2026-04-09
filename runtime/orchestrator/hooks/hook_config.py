#!/usr/bin/env python3
"""
hook_config.py — 行为约束钩子配置管理

核心功能：
- 统一配置入口
- 环境变量覆盖
- 三档 enforce mode 管理 (audit / warn / enforce)

使用示例：
```python
from hooks.hook_config import get_hook_enforce_mode, set_global_enforce_mode

# 获取全局 enforce mode
mode = get_hook_enforce_mode()  # "audit" / "warn" / "enforce"

# 获取指定钩子的 enforce mode
mode = get_hook_enforce_mode("post_promise_verify")

# 设置全局模式
set_global_enforce_mode("enforce")
```

环境变量：
- OPENCLAW_HOOK_ENFORCE_MODE: 全局 enforce mode (audit/warn/enforce)
- OPENCLAW_HOOK_PER_HOOK_MODES: JSON 格式的 per-hook 配置
"""

from __future__ import annotations

import copy
import json
import os
from typing import Dict, Literal, Optional

__all__ = [
    "EnforceMode",
    "HookConfig",
    "get_hook_enforce_mode",
    "set_global_enforce_mode",
    "set_hook_enforce_mode",
    "ENV_ENFORCE_MODE",
    "ENV_PER_HOOK_MODES",
]

# 类型定义
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
    """
    钩子配置管理器
    
    核心功能：
    - 加载默认配置
    - 从环境变量覆盖配置
    - 获取/设置 enforce mode
    - 支持 per-hook 独立配置（后续扩展）
    
    配置优先级：
    1. 环境变量 (最高优先级)
    2. 集中配置模块
    3. 钩子默认值 (audit-only)
    """
    
    def __init__(self):
        self._config: Dict = copy.deepcopy(DEFAULT_CONFIG)
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
            try:
                per_hook_modes = json.loads(per_hook_json)
                if isinstance(per_hook_modes, dict):
                    # 验证 mode 值
                    validated_modes = {}
                    for hook_name, mode in per_hook_modes.items():
                        if mode in ["audit", "warn", "enforce"]:
                            validated_modes[hook_name] = mode
                    self._config["per_hook_modes"] = validated_modes
            except json.JSONDecodeError:
                pass  # 忽略无效 JSON
    
    def get_enforce_mode(self, hook_name: Optional[str] = None) -> EnforceMode:
        """
        获取指定钩子的 enforce mode
        
        Args:
            hook_name: 钩子名称（可选）。如果提供，优先使用 per-hook 配置。
        
        Returns:
            EnforceMode: "audit" / "warn" / "enforce"
        
        优先级：
        1. per-hook 配置（如果 hook_name 提供且在配置中）
        2. 全局配置
        """
        # 优先使用 per-hook 配置
        if hook_name and hook_name in self._config["per_hook_modes"]:
            mode = self._config["per_hook_modes"][hook_name]
            if mode in ["audit", "warn", "enforce"]:
                return mode
        
        # 回退到全局配置
        return self._config["global_enforce_mode"]
    
    def set_global_mode(self, mode: EnforceMode):
        """
        设置全局 enforce mode
        
        Args:
            mode: "audit" / "warn" / "enforce"
        """
        if mode in ["audit", "warn", "enforce"]:
            self._config["global_enforce_mode"] = mode
    
    def set_hook_mode(self, hook_name: str, mode: EnforceMode):
        """
        设置指定钩子的 enforce mode
        
        Args:
            hook_name: 钩子名称
            mode: "audit" / "warn" / "enforce"
        """
        if mode in ["audit", "warn", "enforce"]:
            self._config["per_hook_modes"][hook_name] = mode
    
    def get_config(self) -> Dict:
        """获取完整配置（用于调试/测试）"""
        return self._config.copy()
    
    def reset(self):
        """重置为默认配置（用于测试）"""
        self._config = copy.deepcopy(DEFAULT_CONFIG)
        self._load_from_env()


# 全局单例
_global_config = HookConfig()


def get_hook_enforce_mode(hook_name: Optional[str] = None) -> EnforceMode:
    """
    获取指定钩子的 enforce mode（便捷函数）
    
    Args:
        hook_name: 钩子名称（可选）
    
    Returns:
        EnforceMode: "audit" / "warn" / "enforce"
    
    使用示例：
    ```python
    # 获取全局模式
    mode = get_hook_enforce_mode()
    
    # 获取指定钩子模式
    mode = get_hook_enforce_mode("post_promise_verify")
    ```
    """
    return _global_config.get_enforce_mode(hook_name)


def set_global_enforce_mode(mode: EnforceMode):
    """
    设置全局 enforce mode（便捷函数）
    
    Args:
        mode: "audit" / "warn" / "enforce"
    
    使用示例：
    ```python
    set_global_enforce_mode("enforce")
    ```
    """
    _global_config.set_global_mode(mode)


def set_hook_enforce_mode(hook_name: str, mode: EnforceMode):
    """
    设置指定钩子的 enforce mode（便捷函数）
    
    Args:
        hook_name: 钩子名称
        mode: "audit" / "warn" / "enforce"
    
    使用示例：
    ```python
    set_hook_enforce_mode("post_promise_verify", "enforce")
    set_hook_enforce_mode("post_completion_translate", "warn")
    ```
    """
    _global_config.set_hook_mode(hook_name, mode)


def _reset_global_config():
    """重置全局配置（仅用于测试）"""
    global _global_config
    _global_config = HookConfig()


def _get_global_config() -> HookConfig:
    """获取全局配置对象（仅用于测试）"""
    return _global_config
