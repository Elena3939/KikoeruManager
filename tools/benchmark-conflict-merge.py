"""隔离合成样本的新旧目录构建对比；不连接生产，不修改运行配置。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core import file_move_protocol as protocol
from app.core import staged_file_move as moves
from app.core import merge_plan as plans
from app.core.folder_compare_service import FolderCompareService


def sample(root, count, size):
    root.mkdir()
    block = b"merge-benchmark" * 4096
    for index in range(count):
        parent = root / str(index % 4)
        parent.mkdir(exist_ok=True)
        with (parent / f"{index:04d}.bin").open("xb") as stream:
            remaining = size
            while remaining:
                chunk = block[:min(len(block), remaining)]
                stream.write(chunk)
                remaining -= len(chunk)


def run_case(home, cross, count, size, repeats):
    compare = FolderCompareService()
    source_parent = cross or home
    with tempfile.TemporaryDirectory(prefix="merge-source-", dir=source_parent) as source_dir:
        new, old = Path(source_dir) / "new", home / "old"
        sample(new, count // 2, size)
        sample(old, count - count // 2, size)
        # 新旧来源保留不同路径，确保是真合并而非无变化。
        for path in list(new.rglob("*.bin")):
            path.rename(path.with_name("new-" + path.name))
        items = compare.build_compare_items(str(new), str(old))
        decisions = compare.build_default_decisions(items)
        plan = plans.build_plan(str(new), str(old), items, decisions, items.source_manifest, items.existing_manifest)
        samples = {"old": [], "new": []}
        config = SimpleNamespace(host_enabled=False, journal_path=str(home / "journals"))
        real_atomic = protocol.atomic_json
        counter = [0]
        def atomic(*args, **kwargs):
            counter[0] += 1
            return real_atomic(*args, **kwargs)
        with patch.object(moves, "move_config", return_value=config), patch.object(plans, "move_config", return_value=config), patch.object(moves, "atomic_json", atomic), patch.object(protocol, "atomic_json", atomic):
            for iteration in range(repeats):
                # 交替顺序，减少固定运行顺序对缓存的影响。
                for method in (("old", "new") if iteration % 2 == 0 else ("new", "old")):
                    destination = home / (method + "-stage")
                    destination.mkdir()
                    counter[0] = 0
                    start = time.perf_counter()
                    if method == "old":
                        compare._populate_merged_directory(str(destination), items, decisions)
                        built = time.perf_counter()
                        moves.copy_path_exclusive_sync(str(destination), str(home / "second-tree"))
                        metrics = {"build_seconds": built - start, "second_tree_seconds": time.perf_counter() - built}
                    else:
                        metrics = plans.populate_plan(plan, str(destination))
                    metrics.update(elapsed_seconds=time.perf_counter() - start, transaction_writes=counter[0],
                                   rpc_count=0, result_bytes=plan.total_bytes,
                                   copied_bytes=plan.total_bytes * (2 if method == "old" else 1))
                    samples[method].append(metrics)
                    shutil.rmtree(destination)
                    if (home / "second-tree").exists():
                        shutil.rmtree(home / "second-tree")
        shutil.rmtree(old)
    summary = {}
    for method, values in samples.items():
        summary[method] = {"median_build_seconds": statistics.median(v["build_seconds"] for v in values),
                           "max_build_seconds": max(v["build_seconds"] for v in values),
                           "median_elapsed_seconds": statistics.median(v["elapsed_seconds"] for v in values),
                           "max_elapsed_seconds": max(v["elapsed_seconds"] for v in values), "runs": values}
    summary["build_reduction_percent"] = 100 * (1 - summary["new"]["median_build_seconds"] / summary["old"]["median_build_seconds"])
    return {"files": count, "bytes": count * size, "cross_filesystem": bool(cross), **summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-parent", required=True)
    parser.add_argument("--cross-source-parent")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="merge-benchmark-", dir=args.target_parent) as directory:
        root = Path(directory)
        for count, size, cross in [(47, 65536, None), (1000, 1024, None), (4, 32 * 1024 * 1024, args.cross_source_parent)]:
            if count == 4 and not cross:
                continue
            results.append(run_case(root, cross, count, size, args.repeats))
    report = json.dumps({"platform": sys.platform, "host_executor": False, "synthetic": True, "cases": results}, indent=2)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
