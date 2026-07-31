from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.dlsite_metadata_repair_service import DLsiteMetadataRepairService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="修复 DLsite 翻译占位社团元数据和库存目录")
    parser.add_argument("--apply", action="store_true", help="执行元数据更新和库存 mutation")
    parser.add_argument("--rjcode", action="append", default=[], help="仅处理指定 RJ，可重复传入")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    service = DLsiteMetadataRepairService()
    plans = await service.build_plans(args.rjcode or None)
    results = []
    for plan in plans:
        if args.apply and plan.get("status") == "ready":
            results.append(await service.apply_plan(plan))
        else:
            results.append(plan)
    print(json.dumps({"apply": args.apply, "count": len(results), "items": results}, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") in {"ready", "skipped"} for item in results) else 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(asyncio.run(run()))
