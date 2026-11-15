"""默认只读核对；--rebuild 续跑隔离代际，--publish 完整核对后切换读取。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.database import SessionLocal
from app.core.activity_operation_projection import projection_state, publish_revision
from app.core.activity_operation_rebuild import begin_rebuild, rebuild_chunk, differences, publish_rebuild, reconciliation
from app.core.activity_operation_normalizer import date_window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--start-date", help="只读对账起始日，北京时间 YYYY-MM-DD；不缩小重建范围")
    parser.add_argument("--end-date", help="只读对账结束日，北京时间 YYYY-MM-DD，包含当天")
    args = parser.parse_args()
    try:
        date_window(0, args.start_date, args.end_date)
    except (ValueError, TypeError) as error:
        parser.error(f"日期范围无效: {error}")
    with SessionLocal() as db:
        if args.rebuild:
            begin_rebuild(db)
            db.commit()
            while True:
                progress = rebuild_chunk(db, limit=args.chunk_size)
                db.commit()
                print(json.dumps(progress, ensure_ascii=False))
                if progress["done"]:
                    break
        state = projection_state(db)
        if not state:
            print(json.dumps({"ready": False, "reason": "尚未建立操作投影"}, ensure_ascii=False))
            return
        report = differences(db, state.building_generation or state.active_generation)
        report["reconciliation"] = reconciliation(
            db, state.building_generation or state.active_generation,
            baseline_generation=state.active_generation if state.building_generation is not None else None,
            start_date=args.start_date, end_date=args.end_date)
        print(json.dumps(report, ensure_ascii=False))
        if args.publish:
            publish_rebuild(db)
            db.commit()
            publish_revision()


if __name__ == "__main__":
    main()
