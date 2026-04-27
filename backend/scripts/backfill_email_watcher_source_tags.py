"""
回溯补标脚本：把历史 activity_log 中 email_watcher 触发的 RJ 号
（action=fetch_check 或 action=circle_index_triggered）补写到 circle_works.source_tags。

用法：
  预览（不写入）：py -3 backend/scripts/backfill_email_watcher_source_tags.py
  写入：         py -3 backend/scripts/backfill_email_watcher_source_tags.py --apply
"""

import sys
import os
import json

# 把项目根目录和 backend 加到 path，以便直接导入 ORM
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APPLY = '--apply' in sys.argv


def main():
    from app.models.database import SessionLocal, ActivityLog, CircleWork, init_db
    init_db()
    db = SessionLocal()
    try:
        # 收集所有 email_watcher 触发过的 rjcode
        rjcodes_to_tag = set()

        # 从 fetch_check 日志的 detail.rjcodes 提取
        fetch_logs = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.category == 'email_watcher',
                ActivityLog.action == 'fetch_check',
            )
            .all()
        )
        for log in fetch_logs:
            detail = log.detail or {}
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except Exception:
                    detail = {}
            codes = detail.get('rjcodes') or []
            for code in codes:
                rjcodes_to_tag.add(str(code).strip().upper())

        # 从 circle_index_triggered 日志的 rjcode 字段提取
        trigger_logs = (
            db.query(ActivityLog)
            .filter(
                ActivityLog.category == 'email_watcher',
                ActivityLog.action == 'circle_index_triggered',
                ActivityLog.status == 'success',
            )
            .all()
        )
        for log in trigger_logs:
            if log.rjcode:
                rjcodes_to_tag.add(log.rjcode.strip().upper())

        print(f"从 activity_log 找到历史 email_watcher RJ 号共 {len(rjcodes_to_tag)} 个:")
        for code in sorted(rjcodes_to_tag):
            print(f"  {code}")

        if not rjcodes_to_tag:
            print("没有需要补标的 RJ 号，退出。")
            return

        # 查找对应的 circle_works
        updated = []
        skipped = []
        not_found = []

        for rjcode in sorted(rjcodes_to_tag):
            work = (
                db.query(CircleWork)
                .filter(
                    (CircleWork.canonical_rjcode == rjcode) |
                    (CircleWork.display_rjcode == rjcode)
                )
                .first()
            )
            if not work:
                not_found.append(rjcode)
                continue
            tags = list(work.source_tags or [])
            if 'email_watcher' in tags:
                skipped.append(rjcode)
                continue
            tags.append('email_watcher')
            if APPLY:
                work.source_tags = tags
            updated.append(rjcode)

        print(f"\n需要补标: {len(updated)} 个 — {updated}")
        print(f"已有标签跳过: {len(skipped)} 个 — {skipped}")
        print(f"未在 circle_works 找到: {len(not_found)} 个 — {not_found}")

        if APPLY:
            db.commit()
            print(f"\n✓ 已写入 {len(updated)} 个作品的 source_tags = email_watcher")
        else:
            print("\n（预览模式，加 --apply 参数才会真正写入）")
    finally:
        db.close()


if __name__ == '__main__':
    os.chdir(ROOT)
    main()
