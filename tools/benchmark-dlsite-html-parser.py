"""用冻结的旧服务和当前服务交错比较 DLsite 列表解析，不访问网络或数据库。"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def load_services(baseline):
    from app.core.dlsite_service import DLsiteApiService

    name = "app.core._dlsite_ab_baseline"
    spec = importlib.util.spec_from_file_location(name, baseline)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return {
        "A": module.DLsiteApiService.__new__(module.DLsiteApiService),
        "B": DLsiteApiService.__new__(DLsiteApiService),
    }


def peak_rss_bytes():
    # tracemalloc 看不到 Lexbor 的原生堆；这里测整个独立进程的峰值工作集。
    if sys.platform != "win32":
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform == "darwin" else value * 1024
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def parse(service, text, mode):
    if mode == "summary":
        return service._extract_summaries_from_listing_html(text)
    # 覆盖生产调用的完整同步解析链，包括额外的作品号扫描和站点判别。
    class Response:
        pass
    response = Response()
    response.text = text
    return service._parse_listing_response_sync(response, include_touch_ids=True)


def normalize(result, mode):
    # 只在正确性比较时转字典，不把验收序列化开销混入生产解析计时。
    if mode == "summary":
        return [asdict(item) for item in result]
    summaries, worknos, looks_like = result
    return {"summaries": [asdict(item) for item in summaries], "worknos": worknos, "looks_like": looks_like}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--html", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rounds", type=int, default=21)
    parser.add_argument("--batch", type=int, default=3)
    parser.add_argument("--expected-differences", type=Path, help="人工复核后的精确差异清单，包含页面 SHA-256")
    parser.add_argument("--memory-worker", choices=["A", "B"])
    args = parser.parse_args()
    if args.rounds < 1 or args.batch < 1:
        parser.error("rounds 和 batch 必须大于零")
    expected = json.loads(args.expected_differences.read_text(encoding="utf-8")) if args.expected_differences else {}
    services = load_services(args.baseline)
    pages = [(path, path.read_text(encoding="utf-8")) for path in args.html]
    if args.memory_worker:
        gc.collect()
        before = peak_rss_bytes()
        for _ in range(3):
            for _, text in pages:
                parse(services[args.memory_worker], text, "pipeline")
        print(json.dumps({"before_peak_bytes": before, "after_peak_bytes": peak_rss_bytes()}))
        return
    report = {
        "python": platform.python_version(), "platform": platform.platform(),
        "selectolax": version("selectolax"),
        "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "current_sha256": hashlib.sha256((ROOT / "backend/app/core/dlsite_service.py").read_bytes()).hexdigest(),
        "rounds": args.rounds, "batch": args.batch, "warmup": 3,
        "network_included": False, "pages": [], "memory": {},
    }
    for path, text in pages:
        row = {"file": str(path), "bytes": path.stat().st_size,
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "results": {}}
        for mode in ("summary", "pipeline"):
            outputs = {key: normalize(parse(service, text, mode), mode) for key, service in services.items()}
            left = outputs["A"] if mode == "summary" else outputs["A"]["summaries"]
            right = outputs["B"] if mode == "summary" else outputs["B"]["summaries"]
            diffs = []
            a_by_code = {item["workno"]: item for item in left}
            b_by_code = {item["workno"]: item for item in right}
            for code in sorted(a_by_code.keys() | b_by_code.keys()):
                a, b = a_by_code.get(code), b_by_code.get(code)
                if a != b:
                    diffs.append({"workno": code, "fields": {
                        key: {"A": (a or {}).get(key), "B": (b or {}).get(key)}
                        for key in (a or b) if (a or {}).get(key) != (b or {}).get(key)
                    }})
            for _ in range(3):
                for service in services.values():
                    parse(service, text, mode)
            timings = {"A": [], "B": []}
            for index in range(args.rounds):
                # A/B、B/A 交错，避免固定先后顺序影响 CPU 热态。
                for key in (("A", "B") if index % 2 == 0 else ("B", "A")):
                    started = time.perf_counter_ns()
                    for _ in range(args.batch):
                        parse(services[key], text, mode)
                    timings[key].append((time.perf_counter_ns() - started) / args.batch / 1e6)
            measured = {key: {"median_ms": statistics.median(values),
                               "p95_ms": sorted(values)[math.ceil(.95 * len(values)) - 1]}
                        for key, values in timings.items()}
            measured.update(equal=outputs["A"] == outputs["B"], A_count=len(left), B_count=len(right),
                            differences=diffs,
                            speedup=measured["A"]["median_ms"] / measured["B"]["median_ms"])
            measured["non_date_fields_equal"] = (
                [{k: v for k, v in item.items() if k != "release_date"} for item in left]
                == [{k: v for k, v in item.items() if k != "release_date"} for item in right]
            )
            measured["accepted"] = measured["equal"] or (
                measured["non_date_fields_equal"]
                and diffs == expected.get(row["sha256"])
                and (mode == "summary" or all(outputs["A"][k] == outputs["B"][k] for k in ("worknos", "looks_like")))
            )
            row["results"][mode] = measured
            print(path.name, mode, json.dumps({k: v for k, v in measured.items() if k != "differences"}), flush=True)
        report["pages"].append(row)
    for key in services:
        values = []
        for _ in range(3):
            command = [sys.executable, __file__, "--baseline", str(args.baseline),
                       "--html", *map(str, args.html), "--memory-worker", key]
            values.append(json.loads(subprocess.check_output(command, text=True, encoding="utf-8")))
        report["memory"][key] = values
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("memory", json.dumps(report["memory"]), flush=True)
    print("全字段及顺序一致:", all(row["results"]["pipeline"]["equal"] for row in report["pages"]), flush=True)
    accepted = all(result["accepted"] for row in report["pages"] for result in row["results"].values())
    print("结果符合精确验收清单:", accepted, flush=True)
    if not accepted:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
