#!/usr/bin/env python3
"""
tests/orchestrator/trading/conftest.py

测试配置。
"""

import sys
from pathlib import Path

# 添加运行时路径
RUNTIME_PATH = Path(__file__).parent.parent.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(RUNTIME_PATH))
