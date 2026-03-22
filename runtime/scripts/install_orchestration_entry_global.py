#!/usr/bin/env python3
"""Install the canonical orchestration-entry skill/command into ~/.openclaw."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = WORKSPACE_ROOT / "skills" / "orchestration-entry" / "SKILL.md"
SOURCE_REFERENCES_DIR = WORKSPACE_ROOT / "skills" / "orchestration-entry" / "references"
SOURCE_COMMAND = WORKSPACE_ROOT / "scripts" / "orch_command.py"
SOURCE_HELPERS = {
    "entry_defaults.py": WORKSPACE_ROOT / "orchestrator" / "entry_defaults.py",
    "continuation_backends.py": WORKSPACE_ROOT / "orchestrator" / "continuation_backends.py",
}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_text_file(source: Path, target: Path) -> None:
    _write_text(target, source.read_text(encoding="utf-8"))


def _copy_text_tree(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.exists():
        return
    for source in source_dir.rglob("*"):
        relative = source.relative_to(source_dir)
        target = target_dir / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        _copy_text_file(source, target)


def install(global_root: Path) -> Dict[str, str]:
    scripts_dir = global_root / "scripts"
    runtime_dir = scripts_dir / "orchestration_entry_runtime"
    skill_dir = global_root / "skills" / "orchestration-entry"

    references_dir = skill_dir / "references"

    installed = {
        "skill": str(skill_dir / "SKILL.md"),
        "references_dir": str(references_dir),
        "command": str(scripts_dir / "orch_command.py"),
        "runtime_dir": str(runtime_dir),
    }

    _copy_text_file(SOURCE_SKILL, skill_dir / "SKILL.md")
    _copy_text_tree(SOURCE_REFERENCES_DIR, references_dir)
    _copy_text_file(SOURCE_COMMAND, scripts_dir / "orch_command.py")
    _write_text(runtime_dir / "__init__.py", '"""Runtime helpers for the globally installed orch_command."""\n')

    for name, source in SOURCE_HELPERS.items():
        _copy_text_file(source, runtime_dir / name)

    command_path = scripts_dir / "orch_command.py"
    command_path.chmod(command_path.stat().st_mode | 0o111)
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install the orchestration-entry skill and self-contained orch_command runtime into ~/.openclaw.",
    )
    parser.add_argument(
        "--global-root",
        default=str(Path("~/.openclaw").expanduser()),
        help="target OpenClaw home directory; default=~/.openclaw",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    global_root = Path(args.global_root).expanduser().resolve()
    installed = install(global_root)
    json.dump(
        {
            "global_root": str(global_root),
            "workspace_root": str(WORKSPACE_ROOT),
            "installed": installed,
            "self_contained_runtime": True,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
