#!/usr/bin/env python3
"""
test_hook_exceptions.py — Hook 违规异常测试

测试范围：
1. HookViolationError 初始化
2. 序列化/反序列化
3. 字符串表示

运行方式：
```bash
cd /Users/study/.openclaw/workspace/repos/openclaw-company-orchestration-proposal
python runtime/tests/orchestrator/hooks/test_hook_exceptions.py
```
"""

import sys
from pathlib import Path

# 添加 runtime/orchestrator 到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "orchestrator"))

from hooks.hook_exceptions import HookViolationError


def test_hook_violation_error_basic():
    """测试：基本初始化"""
    error = HookViolationError(
        message="承诺必须有执行锚点",
        hook_name="post_promise_verify",
        metadata={"task_id": "task_001"}
    )
    
    assert error.message == "承诺必须有执行锚点"
    assert error.hook_name == "post_promise_verify"
    assert error.metadata == {"task_id": "task_001"}
    assert str(error) == "[post_promise_verify] 承诺必须有执行锚点"
    
    print("✅ test_hook_violation_error_basic PASSED")


def test_hook_violation_error_minimal():
    """测试：最小化初始化"""
    error = HookViolationError("简单错误消息")
    
    assert error.message == "简单错误消息"
    assert error.hook_name == ""
    assert error.metadata == {}
    assert str(error) == "简单错误消息"
    
    print("✅ test_hook_violation_error_minimal PASSED")


def test_hook_violation_error_str():
    """测试：字符串表示"""
    # 有 hook_name
    error1 = HookViolationError("错误", "hook_name")
    assert "[hook_name]" in str(error1)
    
    # 无 hook_name
    error2 = HookViolationError("错误")
    assert str(error2) == "错误"
    
    print("✅ test_hook_violation_error_str PASSED")


def test_hook_violation_error_repr():
    """测试：调试表示"""
    error = HookViolationError(
        message="测试错误",
        hook_name="test_hook",
        metadata={"key": "value"}
    )
    
    repr_str = repr(error)
    assert "HookViolationError" in repr_str
    assert "测试错误" in repr_str
    assert "test_hook" in repr_str
    
    print("✅ test_hook_violation_error_repr PASSED")


def test_hook_violation_error_to_dict():
    """测试：序列化为字典"""
    error = HookViolationError(
        message="承诺必须有执行锚点",
        hook_name="post_promise_verify",
        metadata={"task_id": "task_001", "anchor_type": "dispatch_id"}
    )
    
    error_dict = error.to_dict()
    
    assert error_dict["error_type"] == "HookViolationError"
    assert error_dict["hook_name"] == "post_promise_verify"
    assert error_dict["message"] == "承诺必须有执行锚点"
    assert error_dict["metadata"]["task_id"] == "task_001"
    assert error_dict["metadata"]["anchor_type"] == "dispatch_id"
    
    print("✅ test_hook_violation_error_to_dict PASSED")


def test_hook_violation_error_from_dict():
    """测试：从字典反序列化"""
    error_dict = {
        "error_type": "HookViolationError",
        "hook_name": "post_completion_translate",
        "message": "完成汇报必须包含翻译",
        "metadata": {"receipt_id": "receipt_123"}
    }
    
    error = HookViolationError.from_dict(error_dict)
    
    assert error.message == "完成汇报必须包含翻译"
    assert error.hook_name == "post_completion_translate"
    assert error.metadata == {"receipt_id": "receipt_123"}
    
    print("✅ test_hook_violation_error_from_dict PASSED")


def test_hook_violation_error_roundtrip():
    """测试：序列化/反序列化往返"""
    original_error = HookViolationError(
        message="测试错误",
        hook_name="test_hook",
        metadata={"key1": "value1", "key2": 123}
    )
    
    # 序列化
    error_dict = original_error.to_dict()
    
    # 反序列化
    restored_error = HookViolationError.from_dict(error_dict)
    
    assert restored_error.message == original_error.message
    assert restored_error.hook_name == original_error.hook_name
    assert restored_error.metadata == original_error.metadata
    
    print("✅ test_hook_violation_error_roundtrip PASSED")


def test_hook_violation_error_inheritance():
    """测试：继承自 Exception"""
    error = HookViolationError("测试")
    
    assert isinstance(error, Exception)
    assert isinstance(error, BaseException)
    
    # 可以被 try/except Exception 捕获
    try:
        raise HookViolationError("测试")
    except Exception as e:
        assert isinstance(e, HookViolationError)
    
    print("✅ test_hook_violation_error_inheritance PASSED")


def run_all_tests():
    """运行所有测试"""
    tests = [
        test_hook_violation_error_basic,
        test_hook_violation_error_minimal,
        test_hook_violation_error_str,
        test_hook_violation_error_repr,
        test_hook_violation_error_to_dict,
        test_hook_violation_error_from_dict,
        test_hook_violation_error_roundtrip,
        test_hook_violation_error_inheritance,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
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
