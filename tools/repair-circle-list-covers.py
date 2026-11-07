"""检查或补齐社团列表小图；在应用容器 /app 下运行。"""

import argparse
import json
import re
from app.core.circle_image_cache_service import CircleImageCacheService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    service = CircleImageCacheService()
    counts = {"cards": 0, "existing_list": 0, "repaired": 0, "failed": 0, "missing_list": 0}
    failed = []
    for source in sorted(service.cache_dir.iterdir()):
        if not re.fullmatch(r"[RVB]J\d{6,8}\.jpg", source.name):
            continue
        counts["cards"] += 1
        code = source.stem
        if service.has_local(code, "list"):
            counts["existing_list"] += 1
            continue
        counts["missing_list"] += 1
        if args.apply:
            if service.restore_list_from_card(code) is not None:
                counts["repaired"] += 1
            else:
                counts["failed"] += 1
                if len(failed) < 20:
                    failed.append(code)
        if counts["cards"] % 500 == 0:
            print(json.dumps(counts), flush=True)
    print(json.dumps({"final": counts, "failed_samples": failed}), flush=True)
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
