#!/usr/bin/env python3
"""
test_hook_config.py — Hook Enforce Mode 配置测试

测试范围：
1. 默认配置加载
2. 环境变量覆盖
3. Per-hook 独立配置
4. 便捷函数

运行方式：
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python runtime/tests/orchestrator/hooks/test_hook_config.py
```
"""

import json
import os
import sys
from pathlib import Path

# 添加 runtime/orchestrator 到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

from hooks.hook_config import (
    HookConfig,
    EnforceMode,
    get_hook_enforce_mode,
    set_global_enforce_mode,
    set_hook_enforce_mode,
    ENV_ENFORCE_MODE,
    ENV_PER_HOOK_MODES,
    _reset_global_config,
    _get_global_config,
)


def test_default_config():
    """测试：默认配置加载"""
    # 确保没有环境变量干扰
    if ENV_ENFORCE_MODE in os.environ:
        del os.environ[ENV_ENFORCE_MODE]
    if ENV_PER_HOOK_MODES in os.environ:
        del os.environ[ENV_PER_HOOK_MODES]
    
    _reset_global_config()
    config = _get_global_config()
    
    assert config.get_enforce_mode() == "audit", f"Expected default mode 'audit', got {config.get_enforce_mode()}"
    assert config.get_enforce_mode("post_promise_verify") == "audit"
    assert config.get_enforce_mode("post_completion_translate") == "audit"
    
    print("✅ test_default_config PASSED")


def test_global_env_override():
    """测试：全局环境变量覆盖"""
    old_env = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        # 设置环境变量
        os.environ[ENV_ENFORCE_MODE] = "enforce"
        
        _reset_global_config()
        config = _get_global_config()
        
        assert config.get_enforce_mode() == "enforce"
        assert config.get_enforce_mode("post_promise_verify") == "enforce"
        assert config.get_enforce_mode("post_completion_translate") == "enforce"
        
        print("✅ test_global_env_override PASSED")
    finally:
        # 清理
        if old_env is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env
        elif ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        elif ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()


def test_per_hook_env_override():
    """测试：Per-hook 环境变量覆盖"""
    old_env = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        # 设置环境变量
        os.environ[ENV_ENFORCE_MODE] = "audit"  # 全局 audit
        os.environ[ENV_PER_HOOK_MODES] = json.dumps({
            "post_promise_verify": "enforce",
            "post_completion_translate": "warn",
        })
        
        _reset_global_config()
        config = _get_global_config()
        
        # 全局模式
        assert config.get_enforce_mode() == "audit"
        
        # Per-hook 模式优先
        assert config.get_enforce_mode("post_promise_verify") == "enforce"
        assert config.get_enforce_mode("post_completion_translate") == "warn"
        assert config.get_enforce_mode("unknown_hook") == "audit"  # 回退到全局
        
        print("✅ test_per_hook_env_override PASSED")
    finally:
        # 清理
        if old_env is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env
        elif ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        elif ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()


def test_set_global_mode_programmatically():
    """测试：编程方式设置全局模式"""
    _reset_global_config()
    
    # 设置全局模式
    set_global_enforce_mode("warn")
    assert get_hook_enforce_mode() == "warn"
    
    set_global_enforce_mode("enforce")
    assert get_hook_enforce_mode() == "enforce"
    
    set_global_enforce_mode("audit")
    assert get_hook_enforce_mode() == "audit"
    
    _reset_global_config()
    print("✅ test_set_global_mode_programmatically PASSED")


def test_set_hook_mode_programmatically():
    """测试：编程方式设置 per-hook 模式"""
    _reset_global_config()
    
    # 设置 per-hook 模式
    set_hook_enforce_mode("post_promise_verify", "enforce")
    set_hook_enforce_mode("post_completion_translate", "warn")
    
    assert get_hook_enforce_mode("post_promise_verify") == "enforce"
    assert get_hook_enforce_mode("post_completion_translate") == "warn"
    assert get_hook_enforce_mode() == "audit"  # 全局默认
    
    _reset_global_config()
    print("✅ test_set_hook_mode_programmatically PASSED")


def test_invalid_env_value_ignored():
    """测试：无效的环境变量值被忽略"""
    old_env = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        # 设置无效值
        os.environ[ENV_ENFORCE_MODE] = "invalid_mode"
        
        _reset_global_config()
        config = _get_global_config()
        
        # 应该回退到默认值
        assert config.get_enforce_mode() == "audit", f"Expected audit, got {config.get_enforce_mode()}"
        
        print("✅ test_invalid_env_value_ignored PASSED")
    finally:
        # 清理
        if old_env is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env
        elif ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        elif ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()


def test_invalid_json_env_ignored():
    """测试：无效的 JSON 环境变量被忽略"""
    # 保存旧值
    old_env_mode = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        os.environ[ENV_ENFORCE_MODE] = "audit"
        os.environ[ENV_PER_HOOK_MODES] = "not valid json"
        
        _reset_global_config()
        config = _get_global_config()
        
        # 应该忽略无效的 JSON，使用空 per-hook 配置
        assert config.get_enforce_mode() == "audit", f"Expected audit, got {config.get_enforce_mode()}"
        assert config.get_enforce_mode("post_promise_verify") == "audit", f"Expected audit, got {config.get_enforce_mode('post_promise_verify')}"
        
        print("✅ test_invalid_json_env_ignored PASSED")
    finally:
        # 恢复旧值
        if old_env_mode is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env_mode
        elif ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        elif ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()


def test_invalid_per_hook_mode_value_ignored():
    """测试：无效的 per-hook mode 值被忽略"""
    old_env = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        os.environ[ENV_PER_HOOK_MODES] = json.dumps({
            "post_promise_verify": "enforce",
            "invalid_hook": "bad_mode",  # 无效值
        })
        
        _reset_global_config()
        config = _get_global_config()
        
        # 有效的 hook 配置应该生效
        assert config.get_enforce_mode("post_promise_verify") == "enforce"
        
        # 无效的 hook 配置应该被忽略
        assert "invalid_hook" not in config.get_config()["per_hook_modes"]
        
        print("✅ test_invalid_per_hook_mode_value_ignored PASSED")
    finally:
        # 清理
        if old_env is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env
        elif ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        elif ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()


def test_convenience_functions():
    """测试：便捷函数"""
    # 保存旧值
    old_env_mode = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        # 清除环境变量干扰
        if ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        if ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()
        
        # get_hook_enforce_mode
        mode = get_hook_enforce_mode()
        assert mode == "audit", f"Expected audit, got {mode}"
        
        mode = get_hook_enforce_mode("post_promise_verify")
        assert mode == "audit", f"Expected audit, got {mode}"
        
        # set_global_enforce_mode
        set_global_enforce_mode("warn")
        assert get_hook_enforce_mode() == "warn", f"Expected warn, got {get_hook_enforce_mode()}"
        
        # set_hook_enforce_mode
        set_hook_enforce_mode("post_promise_verify", "enforce")
        assert get_hook_enforce_mode("post_promise_verify") == "enforce", f"Expected enforce, got {get_hook_enforce_mode('post_promise_verify')}"
        assert get_hook_enforce_mode() == "warn", f"Expected warn (global), got {get_hook_enforce_mode()}"  # 全局不变
        
        print("✅ test_convenience_functions PASSED")
    finally:
        # 恢复旧值
        if old_env_mode is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env_mode
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        
        _reset_global_config()


def test_config_get_config():
    """测试：获取完整配置"""
    old_env = os.environ.get(ENV_ENFORCE_MODE)
    old_env_per_hook = os.environ.get(ENV_PER_HOOK_MODES)
    
    try:
        # 清除环境变量干扰
        if ENV_ENFORCE_MODE in os.environ:
            del os.environ[ENV_ENFORCE_MODE]
        if ENV_PER_HOOK_MODES in os.environ:
            del os.environ[ENV_PER_HOOK_MODES]
        
        _reset_global_config()
        
        set_global_enforce_mode("warn")
        set_hook_enforce_mode("post_promise_verify", "enforce")
        
        config_dict = _get_global_config().get_config()
        
        assert config_dict["global_enforce_mode"] == "warn"
        assert config_dict["per_hook_modes"]["post_promise_verify"] == "enforce"
        
        print("✅ test_config_get_config PASSED")
    finally:
        # 清理
        if old_env is not None:
            os.environ[ENV_ENFORCE_MODE] = old_env
        if old_env_per_hook is not None:
            os.environ[ENV_PER_HOOK_MODES] = old_env_per_hook
        
        _reset_global_config()


def _clear_env_vars():
    """清除环境变量"""
    if ENV_ENFORCE_MODE in os.environ:
        del os.environ[ENV_ENFORCE_MODE]
    if ENV_PER_HOOK_MODES in os.environ:
        del os.environ[ENV_PER_HOOK_MODES]


def run_all_tests():
    """运行所有测试"""
    tests = [
        test_default_config,
        test_global_env_override,
        test_per_hook_env_override,
        test_set_global_mode_programmatically,
        test_set_hook_mode_programmatically,
        test_invalid_env_value_ignored,
        test_invalid_json_env_ignored,
        test_invalid_per_hook_mode_value_ignored,
        test_convenience_functions,
        test_config_get_config,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            # 在每个测试之前清除环境变量，确保测试隔离
            _clear_env_vars()
            _reset_global_config()
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        finally:
            # 每个测试之后清除环境变量，确保测试隔离
            _clear_env_vars()
            _reset_global_config()
    
    # 最终清理
    _clear_env_vars()
    _reset_global_config()
    
    print(f"\n{'='*60}")
    print(f"Tests: {passed + failed} | Passed: {passed} | Failed: {failed}")
    print(f"{'='*60}")
    
    if failed == 0:
        print("✅ All tests PASSED!")
        return 0
    else:
        print(f"❌ {failed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
