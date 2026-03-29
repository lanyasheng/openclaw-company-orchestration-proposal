#!/usr/bin/env python3
"""cleanup-observability-demo-cards.py

安全清理 observability 层里的旧 demo/test 卡。

策略：
- 仅匹配明确 demo/test marker（task_id / anchor / session_id 等）
- 默认支持 dry-run 预览
- 仅清理最近活动时间超过 TTL 的卡
- 只动 observability cards/index，不碰 canonical truth
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "runtime" / "orchestrator"))

from dashboard import CARD_DIR, cleanup_demo_cards  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="安全清理 observability demo/test 卡")
    parser.add_argument(
        "--card-dir",
        type=Path,
        default=CARD_DIR,
        help="卡片目录（默认：~/.openclaw/shared-context/observability/cards）",
    )
    parser.add_argument(
        "--ttl-hours",
        type=float,
        default=24.0,
        help="仅清理最近活动时间超过该阈值的 demo/test 卡（小时）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览，不删除",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON",
    )
    args = parser.parse_args()

    report = cleanup_demo_cards(
        Path(args.card_dir),
        older_than_hours=args.ttl_hours,
        dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    mode = "DRY-RUN" if args.dry_run else "DELETE"
    print(f"Observability demo cleanup [{mode}]")
    print(f"- scanned: {report['scanned']}")
    print(f"- matched: {report['matched']}")
    print(f"- deleted: {report['deleted_count']}")
    print(f"- ttl_hours: {report['older_than_hours']}")
    if report["candidates"]:
        print("- candidates:")
        for item in report["candidates"]:
            print(
                "  - "
                f"{item['task_id']} | stage={item['stage']} | age={item['age_hours']}h | "
                f"reason={item['reason']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
