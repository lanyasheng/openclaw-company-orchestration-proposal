#!/usr/bin/env python3
"""
Smoke test for skill/entry path consolidation.

验证点:
1. runtime/skills/orchestration-entry/SKILL.md 存在
2. runtime/scripts/orch_command.py 存在
3. install 脚本使用正确的 repo 内路径
4. 无硬编码的 workspace 绝对路径
"""

import json
import subprocess
import sys
from pathlib import Path


def test_skill_entry_exists():
    """测试 skill 入口文件存在"""
    print("=" * 60)
    print("Test 1: Skill entry files exist in repo")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    
    skill_path = REPO_ROOT / "runtime" / "skills" / "orchestration-entry" / "SKILL.md"
    command_path = REPO_ROOT / "runtime" / "scripts" / "orch_command.py"
    install_path = REPO_ROOT / "runtime" / "scripts" / "install_orchestration_entry_global.py"
    
    assert skill_path.exists(), f"Skill SKILL.md not found at {skill_path}"
    assert command_path.exists(), f"orch_command.py not found at {command_path}"
    assert install_path.exists(), f"install script not found at {install_path}"
    
    print(f"✅ All skill entry files exist in repo")
    print(f"   - SKILL.md: {skill_path}")
    print(f"   - orch_command.py: {command_path}")
    print(f"   - install script: {install_path}")
    print()


def test_install_script_paths():
    """测试 install 脚本使用正确的 repo 内路径"""
    print("=" * 60)
    print("Test 2: Install script uses correct repo paths")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    install_path = REPO_ROOT / "runtime" / "scripts" / "install_orchestration_entry_global.py"
    
    content = install_path.read_text()
    
    # Check for correct path references
    assert "REPO_ROOT = Path(__file__).resolve().parents[2]" in content, \
        "Install script should use REPO_ROOT (2 levels up)"
    assert 'REPO_ROOT / "runtime" / "skills"' in content, \
        "Install script should reference runtime/skills"
    assert 'REPO_ROOT / "runtime" / "scripts"' in content, \
        "Install script should reference runtime/scripts"
    assert 'REPO_ROOT / "runtime" / "orchestrator"' in content, \
        "Install script should reference runtime/orchestrator"
    
    # Check for absence of wrong paths
    assert "WORKSPACE_ROOT" not in content, \
        "Install script should not use WORKSPACE_ROOT"
    assert 'Path(__file__).resolve().parents[1]' not in content or \
           "WORKSPACE_ROOT" in content, \
        "Install script should not use parents[1] without REPO_ROOT"
    
    print("✅ Install script uses correct repo-internal paths")
    print("   - Uses REPO_ROOT (2 levels up)")
    print("   - References runtime/skills, runtime/scripts, runtime/orchestrator")
    print("   - No WORKSPACE_ROOT references")
    print()


def test_no_hardcoded_workspace_paths():
    """测试无硬编码的 workspace 绝对路径"""
    print("=" * 60)
    print("Test 3: No hardcoded workspace absolute paths")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    
    # Files to check
    files_to_check = [
        REPO_ROOT / "runtime" / "skills" / "orchestration-entry" / "SKILL.md",
        REPO_ROOT / "runtime" / "scripts" / "orch_command.py",
        REPO_ROOT / "runtime" / "scripts" / "install_orchestration_entry_global.py",
    ]
    
    workspace_path_patterns = [
        "/Users/study/.openclaw/workspace",
        "~/.openclaw/workspace",
        "WORKSPACE_ROOT",
    ]
    
    issues = []
    for file_path in files_to_check:
        if not file_path.exists():
            continue
        content = file_path.read_text()
        for pattern in workspace_path_patterns:
            if pattern in content and pattern != "~/.openclaw/workspace":
                # ~/.openclaw/workspace is OK for global install target
                issues.append(f"{file_path}: contains '{pattern}'")
    
    # Special check: SKILL.md should not have hardcoded paths
    skill_content = (REPO_ROOT / "runtime" / "skills" / "orchestration-entry" / "SKILL.md").read_text()
    if "/Users/study/.openclaw/workspace" in skill_content:
        issues.append("SKILL.md contains hardcoded /Users/study/.openclaw/workspace path")
    
    assert len(issues) == 0, f"Found hardcoded workspace paths:\n" + "\n".join(issues)
    
    print("✅ No hardcoded workspace absolute paths found")
    print("   - SKILL.md uses relative paths")
    print("   - orch_command.py uses relative paths")
    print("   - install script uses REPO_ROOT")
    print()


def test_install_script_syntax():
    """测试 install 脚本语法正确"""
    print("=" * 60)
    print("Test 4: Install script syntax validation")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    install_path = REPO_ROOT / "runtime" / "scripts" / "install_orchestration_entry_global.py"
    
    result = subprocess.run(
        ["python3", "-m", "py_compile", str(install_path)],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Install script has syntax errors: {result.stderr}"
    
    print("✅ Install script has valid Python syntax")
    print()


def test_skill_documentation_paths():
    """测试 skill 文档中的路径是正确的"""
    print("=" * 60)
    print("Test 5: Skill documentation uses correct paths")
    print("=" * 60)
    
    REPO_ROOT = Path(__file__).resolve().parents[2]
    skill_path = REPO_ROOT / "runtime" / "skills" / "orchestration-entry" / "SKILL.md"
    
    content = skill_path.read_text()
    
    # Check for correct path references in examples
    assert "runtime/orchestrator/cli.py" in content or "runtime/scripts/orch_command.py" in content, \
        "SKILL.md should reference runtime paths in examples"
    
    # Check for absence of wrong paths
    assert "workspace/orchestrator/" not in content, \
        "SKILL.md should not reference workspace/orchestrator/"
    
    print("✅ Skill documentation uses correct paths")
    print("   - References runtime/orchestrator/cli.py")
    print("   - No workspace/orchestrator/ references")
    print()


def main():
    """运行所有 smoke tests"""
    print("\n" + "=" * 60)
    print("Skill/Entry Path Consolidation Smoke Tests")
    print("=" * 60 + "\n")
    
    all_passed = True
    tests = [
        ("Skill entry files exist", test_skill_entry_exists),
        ("Install script paths", test_install_script_paths),
        ("No hardcoded workspace paths", test_no_hardcoded_workspace_paths),
        ("Install script syntax", test_install_script_syntax),
        ("Skill documentation paths", test_skill_documentation_paths),
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
        print("✅ ALL SKILL/ENTRY SMOKE TESTS PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ SOME SKILL/ENTRY SMOKE TESTS FAILED")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
