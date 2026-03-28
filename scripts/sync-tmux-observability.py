#!/usr/bin/env python3
"""
sync-tmux-observability.py — tmux 状态同步到 observability 索引

用于从 shell 脚本调用，将 tmux session 状态同步到 observability cards。

使用方式：
```bash
# 注册新任务
python sync-tmux-observability.py register \
  --task-id task_001 \
  --label feature-xxx \
  --owner main \
  --scenario custom \
  --promised-eta 2026-03-28T18:00:00

# 更新状态
python sync-tmux-observability.py update \
  --task-id task_001 \
  --session cc-feature-xxx

# 查询状态
python sync-tmux-observability.py status \
  --session cc-feature-xxx

# 列出活跃 session
python sync-tmux-observability.py list --owner main
```
"""

import argparse
import json
import sys
from pathlib import Path

# 添加 orchestrator 目录到路径
SCRIPT_DIR = Path(__file__).parent
ORCHESTRATOR_DIR = SCRIPT_DIR.parent / "runtime" / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_DIR))

from tmux_status_sync import (
    TmuxStatusSync,
    get_tmux_status,
    list_tmux_cards,
    register_tmux_card,
    sync_tmux_session,
    update_tmux_card,
)


def cmd_register(args):
    """注册新任务"""
    try:
        card = register_tmux_card(
            task_id=args.task_id,
            label=args.label,
            owner=args.owner,
            scenario=args.scenario,
            promised_eta=args.promised_eta,
            socket=Path(args.socket) if args.socket else None,
            target=args.target,
            ssh_host=args.ssh_host,
        )
        
        result = {
            "success": True,
            "action": "register",
            "card": card.to_dict(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        result = {
            "success": False,
            "action": "register",
            "error": str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_update(args):
    """更新状态"""
    try:
        card = update_tmux_card(
            task_id=args.task_id,
            session=args.session,
            socket=Path(args.socket) if args.socket else None,
            target=args.target,
            ssh_host=args.ssh_host,
        )
        
        if card is None:
            result = {
                "success": False,
                "action": "update",
                "error": "Card not found",
            }
            print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        
        result = {
            "success": True,
            "action": "update",
            "card": card.to_dict(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        result = {
            "success": False,
            "action": "update",
            "error": str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_status(args):
    """查询状态"""
    try:
        state = get_tmux_status(
            session=args.session,
            socket=Path(args.socket) if args.socket else None,
            target=args.target,
            ssh_host=args.ssh_host,
        )
        
        result = {
            "success": True,
            "action": "status",
            "state": state.to_dict(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        result = {
            "success": False,
            "action": "status",
            "error": str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_list(args):
    """列出活跃 session"""
    try:
        sessions = list_tmux_cards(
            owner=args.owner if args.owner else None,
            limit=args.limit,
        )
        
        result = {
            "success": True,
            "action": "list",
            "count": len(sessions),
            "sessions": sessions,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        result = {
            "success": False,
            "action": "list",
            "error": str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def cmd_sync(args):
    """同步单个 session（register + update）"""
    try:
        # 先尝试更新
        card = sync_tmux_session(
            task_id=args.task_id,
            session=args.session,
            socket=Path(args.socket) if args.socket else None,
            target=args.target,
            ssh_host=args.ssh_host,
            force=args.force,
        )
        
        if card is None:
            result = {
                "success": False,
                "action": "sync",
                "error": "Card not found (use --force to create)",
            }
            print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
            return 1
        
        result = {
            "success": True,
            "action": "sync",
            "card": card.to_dict(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        result = {
            "success": False,
            "action": "sync",
            "error": str(e),
        }
        print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Sync tmux session status to observability index"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # register 命令
    register_parser = subparsers.add_parser("register", help="Register new tmux task")
    register_parser.add_argument("--task-id", required=True, help="Task ID")
    register_parser.add_argument("--label", required=True, help="Task label")
    register_parser.add_argument(
        "--owner", required=True,
        choices=["main", "trading", "ainews", "macro", "content", "butler", "custom"],
        help="Owner agent"
    )
    register_parser.add_argument(
        "--scenario", required=True,
        choices=["trading_roundtable", "channel_roundtable", "coding_issue", "custom"],
        help="Scenario type"
    )
    register_parser.add_argument("--promised-eta", required=True, help="Promised ETA (ISO-8601)")
    register_parser.add_argument("--socket", help="Tmux socket path")
    register_parser.add_argument(
        "--target", choices=["local", "ssh"], default="local",
        help="Target type"
    )
    register_parser.add_argument("--ssh-host", help="SSH host alias")
    register_parser.set_defaults(func=cmd_register)
    
    # update 命令
    update_parser = subparsers.add_parser("update", help="Update tmux task status")
    update_parser.add_argument("--task-id", required=True, help="Task ID")
    update_parser.add_argument("--session", required=True, help="Session name")
    update_parser.add_argument("--socket", help="Tmux socket path")
    update_parser.add_argument(
        "--target", choices=["local", "ssh"], default="local",
        help="Target type"
    )
    update_parser.add_argument("--ssh-host", help="SSH host alias")
    update_parser.set_defaults(func=cmd_update)
    
    # status 命令
    status_parser = subparsers.add_parser("status", help="Get tmux session status")
    status_parser.add_argument("--session", required=True, help="Session name")
    status_parser.add_argument("--socket", help="Tmux socket path")
    status_parser.add_argument(
        "--target", choices=["local", "ssh"], default="local",
        help="Target type"
    )
    status_parser.add_argument("--ssh-host", help="SSH host alias")
    status_parser.set_defaults(func=cmd_status)
    
    # list 命令
    list_parser = subparsers.add_parser("list", help="List active tmux sessions")
    list_parser.add_argument(
        "--owner",
        choices=["main", "trading", "ainews", "macro", "content", "butler", "custom"],
        help="Filter by owner"
    )
    list_parser.add_argument("--limit", type=int, default=100, help="Max results")
    list_parser.set_defaults(func=cmd_list)
    
    # sync 命令
    sync_parser = subparsers.add_parser("sync", help="Sync tmux session (update or create)")
    sync_parser.add_argument("--task-id", required=True, help="Task ID")
    sync_parser.add_argument("--session", required=True, help="Session name")
    sync_parser.add_argument("--socket", help="Tmux socket path")
    sync_parser.add_argument(
        "--target", choices=["local", "ssh"], default="local",
        help="Target type"
    )
    sync_parser.add_argument("--ssh-host", help="SSH host alias")
    sync_parser.add_argument("--force", action="store_true", help="Create if not exists")
    sync_parser.set_defaults(func=cmd_sync)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
