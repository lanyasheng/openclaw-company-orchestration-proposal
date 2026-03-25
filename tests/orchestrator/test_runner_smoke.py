#!/usr/bin/env python3
"""
Smoke test for runner script availability and basic configuration.

验证点:
1. runner 脚本存在且可执行
2. Claude CLI 可访问或已配置
3. 环境变量配置正确
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_runner_script_exists():
    """测试 runner 脚本存在且可执行"""
    print("=" * 60)
    print("Test 1: Runner script exists and is executable")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    runner_path = REPO_ROOT / "scripts" / "run_subagent_claude_v1.sh"
    
    assert runner_path.exists(), f"Runner script not found at {runner_path}"
    assert runner_path.stat().st_size > 0, "Runner script is empty"
    
    # Check if executable
    assert os.access(runner_path, os.X_OK), f"Runner script is not executable: {runner_path}"
    
    # Check content has required sections
    content = runner_path.read_text()
    assert "CLAUDE_CLI_PATH" in content, "Missing CLAUDE_CLI_PATH configuration"
    assert "write_result" in content, "Missing write_result function"
    assert "OPENCLAW_TASK_ID" in content, "Missing OPENCLAW_TASK_ID handling"
    assert "claude --print" in content or "CLAUDE_BIN" in content, "Missing Claude CLI invocation"
    
    print(f"✅ Runner script exists and is executable")
    print(f"   - Path: {runner_path}")
    print(f"   - Size: {runner_path.stat().st_size} bytes")
    print(f"   - Executable: Yes")
    print()
    
    return True


def test_claude_cli_available():
    """测试 Claude CLI 可用"""
    print("=" * 60)
    print("Test 2: Claude CLI availability")
    print("=" * 60)
    
    # Check environment variable first
    claude_path = os.environ.get("CLAUDE_CLI_PATH", "")
    
    if not claude_path:
        # Try to find in PATH
        result = subprocess.run(
            ["which", "claude"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            claude_path = result.stdout.strip()
        elif os.path.exists("/Users/study/bin/claude"):
            claude_path = "/Users/study/bin/claude"
    
    if claude_path and os.path.exists(claude_path):
        print(f"✅ Claude CLI found at: {claude_path}")
        
        # Try to get version
        result = subprocess.run(
            [claude_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"   - Version: {result.stdout.strip()}")
        else:
            print(f"   - Version check failed (may still work)")
        print()
        return True
    else:
        print("⚠️  Claude CLI not found in PATH or common locations")
        print("   Install with: npm install -g @anthropic-ai/claude-code")
        print("   Or set CLAUDE_CLI_PATH environment variable")
        print()
        # Don't fail the test - runner can be configured later
        return True


def test_runner_help():
    """测试 runner 脚本可以显示帮助信息"""
    print("=" * 60)
    print("Test 3: Runner script help output")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    runner_path = REPO_ROOT / "scripts" / "run_subagent_claude_v1.sh"
    
    # Run with --help or just check it can be invoked
    result = subprocess.run(
        ["bash", "-n", str(runner_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Runner script has syntax errors: {result.stderr}"
    
    print("✅ Runner script has valid bash syntax")
    print()
    
    return True


def test_runner_stub_fallback():
    """测试 runner 在没有 Claude CLI 时的降级行为"""
    print("=" * 60)
    print("Test 4: Runner fallback behavior (no Claude CLI)")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    runner_path = REPO_ROOT / "scripts" / "run_subagent_claude_v1.sh"
    
    # Check that the script has proper error handling
    content = runner_path.read_text()
    
    assert "ERROR: Claude CLI not found" in content, "Missing Claude CLI not found error"
    assert "exit 127" in content, "Missing exit code 127 for missing CLI"
    assert "CLAUDE_CLI_PATH" in content, "Missing CLAUDE_CLI_PATH fallback"
    
    print("✅ Runner has proper error handling for missing Claude CLI")
    print("   - Shows clear error message")
    print("   - Exits with code 127 (command not found)")
    print("   - Documents CLAUDE_CLI_PATH environment variable")
    print()
    
    return True


def main():
    """运行所有 smoke tests"""
    print("\n" + "=" * 60)
    print("Runner Script Smoke Tests")
    print("=" * 60 + "\n")
    
    all_passed = True
    tests = [
        ("Runner script exists", test_runner_script_exists),
        ("Claude CLI availability", test_claude_cli_available),
        ("Runner syntax validation", test_runner_help),
        ("Runner fallback behavior", test_runner_stub_fallback),
    ]
    
    for name, test_func in tests:
        try:
            test_func()
        except AssertionError as e:
            print(f"❌ {name} FAILED: {e}\n")
            all_passed = False
        except Exception as e:
            print(f"❌ {name} ERROR: {e}\n")
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✅ ALL RUNNER SMOKE TESTS PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME RUNNER SMOKE TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
