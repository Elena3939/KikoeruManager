"""本机合成索引基准；不连接生产、不扫描磁盘，不代表生产端到端延迟。"""

import argparse
import ast
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core import library_circle_aggregation_service as module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=int, default=69932)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--baseline", default="HEAD")
    args = parser.parse_args()
    source = subprocess.check_output([
        "git", "show", f"{args.baseline}:backend/app/core/library_circle_aggregation_service.py",
    ], cwd=ROOT).decode("utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LibraryCircleAggregationService")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_build_snapshot")
    namespace = dict(vars(module))
    exec(compile(ast.Module(body=[method], type_ignores=[]), "baseline_build_snapshot", "exec"), namespace)
    rows = []
    for index in range(args.positions):
        rjcode = f"RJ{10000000 + index % 60000}"
        name = f"[社团{index % 1314}][{rjcode}] 作品"
        rows.append(dict(rjcode=rjcode, relative_path=f"音声/{name}", name=name,
                         library_id=str(index % 3), library_name="基准库", library_type="local",
                         top_category="音声", size=1000, modified_time=100))

    def service():
        instance = module.LibraryCircleAggregationService()
        instance._load_index_work_rows = lambda: rows
        instance._load_active_library_summary_items = lambda: []
        instance._load_circle_identities = lambda codes: {}
        instance._load_index_views = lambda: ([], "benchmark")
        return instance

    baseline, optimized, hot = [], [], []
    expected = None
    for _ in range(args.samples):
        instance = service()
        started = time.perf_counter()
        old = namespace["_build_snapshot"](instance, now=time.monotonic(), index_views=[], view_token="benchmark")
        baseline.append((time.perf_counter() - started) * 1000)
        instance = service()
        started = time.perf_counter()
        result = instance._build_snapshot(now=time.monotonic(), index_views=[], view_token="benchmark")
        optimized.append((time.perf_counter() - started) * 1000)
        assert old == result, "新旧聚合结果不一致"
        expected = result["summary"]
        for _ in range(30):
            started = time.perf_counter()
            instance.browse_circle_listing(page=1, page_size=20)
            hot.append((time.perf_counter() - started) * 1000)
    print(json.dumps({
        "positions": args.positions, "samples": args.samples, "groups": expected["group_count"],
        "baseline_ms": baseline, "optimized_ms": optimized,
        "median_reduction_pct": round((1 - statistics.median(optimized) / statistics.median(baseline)) * 100, 2),
        "hot_samples": len(hot), "hot_p95_ms": sorted(hot)[int(len(hot) * .95) - 1],
        "scope": "合成索引行；包含完整快照计算及热分页，不包含数据库、健康检查和网络",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
