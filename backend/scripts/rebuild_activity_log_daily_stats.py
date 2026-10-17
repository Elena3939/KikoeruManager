"""核对日统计，默认只读；显式 --apply 后按事实替换，重复执行不会累加。"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.activity_log_daily_stats_service import rebuild_daily_stats
from app.models.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = rebuild_daily_stats(db, start_date=args.start, end_date=args.end, apply=args.apply)
        if args.apply:
            db.commit()
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
