#!/usr/bin/env python3
"""
Performance benchmark for backup compression optimization.

Compares "before" (old defaults) vs "after" (optimized lookup-table params)
for 7z and zip formats at various compression levels.

Usage:
    python backend/benchmark_backup.py --size 100
    python backend/benchmark_backup.py --size 500 --formats zip,7z --levels 5,9
"""

import argparse
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── psutil (graceful fallback) ────────────────────────────────────
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Optimized parameter lookup tables (mirrors backup_zip_service) ─
_7Z_PARAMS: Dict[int, Tuple[int, int, str, bool]] = {
    1: (32, 1, "4m", False), 2: (32, 1, "4m", False), 3: (32, 1, "4m", False),
    4: (64, 1, "16m", False), 5: (64, 1, "16m", False),
    6: (64, 3, "32m", True), 7: (64, 3, "32m", True),
    8: (128, 5, "64m", True), 9: (128, 5, "64m", True),
}

_ZIP_PARAMS: Dict[int, Tuple[int, int]] = {
    1: (32, 1), 2: (32, 1), 3: (32, 1),
    4: (64, 1), 5: (64, 1),
    6: (128, 3), 7: (128, 3),
    8: (128, 7), 9: (128, 7),
}

IO_BUFFER_SIZE = 65536  # 64 KB – optimized value


# ── 7z executable discovery ───────────────────────────────────────

def find_7z() -> str:
    """Locate 7z executable using the same logic as the backup service."""
    from shutil import which
    in_path = which("7z")
    if in_path:
        return in_path
    for candidate in [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ]:
        if os.path.exists(candidate):
            return candidate
    sys.exit("ERROR: 7z executable not found. Install 7-Zip or add it to PATH.")


# ── Test data generation ──────────────────────────────────────────

def _random_text(size_bytes: int) -> bytes:
    """Generate pseudo-random text content."""
    chars = string.ascii_letters + string.digits + " \n\t"
    block = "".join(random.choices(chars, k=min(size_bytes, 4096)))
    repeats = (size_bytes // len(block)) + 1
    return (block * repeats)[:size_bytes].encode("utf-8")


def _random_binary(size_bytes: int) -> bytes:
    """Generate random binary content."""
    return os.urandom(size_bytes)


def create_test_dataset(base_dir: str, total_mb: int) -> str:
    """
    Create a test dataset directory with mixed file types.
    Returns the path to the created directory.
    """
    dataset_dir = os.path.join(base_dir, "test_dataset")
    os.makedirs(dataset_dir, exist_ok=True)

    total_bytes = total_mb * 1024 * 1024
    written = 0

    # Allocation: 40% text, 30% binary, 15% small files, 15% large files
    text_budget = int(total_bytes * 0.40)
    binary_budget = int(total_bytes * 0.30)
    small_budget = int(total_bytes * 0.15)
    large_budget = total_bytes - text_budget - binary_budget - small_budget

    print(f"  Creating test dataset: {total_mb} MB in {dataset_dir}")

    # --- Text files (medium: 100KB-1MB each) ---
    text_dir = os.path.join(dataset_dir, "text")
    os.makedirs(text_dir, exist_ok=True)
    idx = 0
    remaining = text_budget
    while remaining > 0:
        size = min(remaining, random.randint(100 * 1024, 1024 * 1024))
        with open(os.path.join(text_dir, f"doc_{idx:04d}.txt"), "wb") as f:
            f.write(_random_text(size))
        remaining -= size
        written += size
        idx += 1
    print(f"    Text files: {idx} files, {text_budget / (1024*1024):.1f} MB")

    # --- Binary files (medium: 500KB-2MB each) ---
    bin_dir = os.path.join(dataset_dir, "binary")
    os.makedirs(bin_dir, exist_ok=True)
    idx = 0
    remaining = binary_budget
    while remaining > 0:
        size = min(remaining, random.randint(500 * 1024, 2 * 1024 * 1024))
        with open(os.path.join(bin_dir, f"data_{idx:04d}.bin"), "wb") as f:
            f.write(_random_binary(size))
        remaining -= size
        written += size
        idx += 1
    print(f"    Binary files: {idx} files, {binary_budget / (1024*1024):.1f} MB")

    # --- Small files (1KB-10KB each) ---
    small_dir = os.path.join(dataset_dir, "small")
    os.makedirs(small_dir, exist_ok=True)
    idx = 0
    remaining = small_budget
    while remaining > 0:
        size = min(remaining, random.randint(1024, 10 * 1024))
        content = _random_text(size) if idx % 2 == 0 else _random_binary(size)
        ext = ".txt" if idx % 2 == 0 else ".dat"
        with open(os.path.join(small_dir, f"small_{idx:05d}{ext}"), "wb") as f:
            f.write(content)
        remaining -= size
        written += size
        idx += 1
    print(f"    Small files: {idx} files, {small_budget / (1024*1024):.1f} MB")

    # --- Large files (10MB-50MB each) ---
    large_dir = os.path.join(dataset_dir, "large")
    os.makedirs(large_dir, exist_ok=True)
    idx = 0
    remaining = large_budget
    while remaining > 0:
        max_size = min(remaining, 50 * 1024 * 1024)
        size = min(remaining, random.randint(10 * 1024 * 1024, max(10 * 1024 * 1024, max_size)))
        content = _random_text(size) if idx % 2 == 0 else _random_binary(size)
        ext = ".log" if idx % 2 == 0 else ".blob"
        with open(os.path.join(large_dir, f"large_{idx:03d}{ext}"), "wb") as f:
            f.write(content)
        remaining -= size
        written += size
        idx += 1
    print(f"    Large files: {idx} files, {large_budget / (1024*1024):.1f} MB")
    print(f"  Total written: {written / (1024*1024):.1f} MB")
    return dataset_dir


# ── Metrics capture ───────────────────────────────────────────────

class Metrics:
    """Captures wall time, CPU, memory, and disk I/O around a subprocess."""

    def __init__(self):
        self.wall_time: float = 0.0
        self.cpu_percent: float = 0.0
        self.peak_memory_mb: float = 0.0
        self.disk_read_mb: float = 0.0
        self.disk_write_mb: float = 0.0
        self.output_size: int = 0
        self.compression_ratio: float = 0.0

    def as_dict(self) -> dict:
        return {
            "wall_time": round(self.wall_time, 2),
            "cpu_percent": round(self.cpu_percent, 1),
            "peak_memory_mb": round(self.peak_memory_mb, 1),
            "disk_read_mb": round(self.disk_read_mb, 1),
            "disk_write_mb": round(self.disk_write_mb, 1),
            "output_size_mb": round(self.output_size / (1024 * 1024), 2),
            "compression_ratio": round(self.compression_ratio * 100, 2),
        }


def run_with_metrics(cmd: List[str], cwd: str, output_path: str,
                     input_size: int) -> Metrics:
    """Run a 7z command and capture performance metrics."""
    m = Metrics()

    # Pre-run snapshots
    if HAS_PSUTIL:
        disk_before = psutil.disk_io_counters()
        psutil.cpu_percent(interval=None)  # prime the counter

    t0 = time.perf_counter()

    # Run 7z
    creationflags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=creationflags,
    )

    peak_mem = 0.0
    if HAS_PSUTIL:
        try:
            ps_proc = psutil.Process(proc.pid)
        except psutil.NoSuchProcess:
            ps_proc = None
    else:
        ps_proc = None

    # Poll for peak memory while process runs
    while proc.poll() is None:
        if ps_proc:
            try:
                mem_info = ps_proc.memory_info()
                peak_mem = max(peak_mem, mem_info.rss / (1024 * 1024))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        time.sleep(0.1)

    proc.wait()
    t1 = time.perf_counter()

    m.wall_time = t1 - t0
    m.peak_memory_mb = peak_mem

    # Post-run snapshots
    if HAS_PSUTIL:
        m.cpu_percent = psutil.cpu_percent(interval=None)
        disk_after = psutil.disk_io_counters()
        if disk_before and disk_after:
            m.disk_read_mb = (disk_after.read_bytes - disk_before.read_bytes) / (1024 * 1024)
            m.disk_write_mb = (disk_after.write_bytes - disk_before.write_bytes) / (1024 * 1024)

    # Output size and ratio
    if os.path.exists(output_path):
        m.output_size = os.path.getsize(output_path)
        m.compression_ratio = m.output_size / input_size if input_size > 0 else 0.0

    return m


# ── Command builders ──────────────────────────────────────────────

def build_before_cmd(seven_zip: str, fmt: str, level: int,
                     archive_path: str, source_name: str) -> List[str]:
    """Build 7z command with OLD default parameters."""
    cmd = [seven_zip, "a", f"-t{fmt}", f"-mx={level}"]

    if level > 5:
        cmd += ["-mfb=64", "-mpass=3"]
    else:
        cmd += ["-mfb=32", "-mpass=1"]

    cmd.append("-mmt=on")
    cmd += ["-bb0", "-bso0", "-bse0", "-y", archive_path, source_name]
    return cmd


def build_after_cmd(seven_zip: str, fmt: str, level: int,
                    archive_path: str, source_name: str) -> List[str]:
    """Build 7z command with NEW optimized parameters."""
    cpu_count = os.cpu_count() or 4
    cmd = [seven_zip, "a", f"-t{fmt}", f"-mx={level}"]

    if fmt == "7z":
        mfb, mpass, md, ms = _7Z_PARAMS.get(level, (64, 3, "32m", True))
        cmd += [f"-mfb={mfb}", f"-mpass={mpass}", f"-md={md}"]
        if ms and level >= 6:
            cmd.append("-ms=on")
    else:
        mfb, mpass = _ZIP_PARAMS.get(level, (64, 3))
        cmd += [f"-mfb={mfb}", f"-mpass={mpass}"]

    cmd.append(f"-mmt={cpu_count}")
    cmd += ["-bb0", "-bso0", "-bse0", "-y", archive_path, source_name]
    return cmd


# ── Report generation ─────────────────────────────────────────────

def _delta_str(before_val: float, after_val: float, lower_is_better: bool = True) -> str:
    """Format a delta as a percentage string with sign."""
    if before_val == 0:
        return "N/A"
    pct = ((after_val - before_val) / before_val) * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def generate_report(results: List[dict], input_size_mb: int) -> str:
    """Generate a markdown comparison table from benchmark results."""
    lines = [
        f"# Compression Benchmark Report",
        f"",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Input size: {input_size_mb} MB",
        f"- CPU count: {os.cpu_count()}",
        f"- psutil available: {HAS_PSUTIL}",
        f"",
        f"## Results",
        f"",
        f"| Metric | Before | After | Delta |",
        f"|--------|--------|-------|-------|",
    ]

    for r in results:
        label = r["label"]
        b = r["before"]
        a = r["after"]

        lines.append(
            f"| Time ({label}) | {b['wall_time']}s | {a['wall_time']}s "
            f"| {_delta_str(b['wall_time'], a['wall_time'], True)} |"
        )
        lines.append(
            f"| CPU Utilization ({label}) | {b['cpu_percent']}% | {a['cpu_percent']}% "
            f"| {_delta_str(b['cpu_percent'], a['cpu_percent'], False)} |"
        )
        lines.append(
            f"| Peak Memory ({label}) | {b['peak_memory_mb']} MB | {a['peak_memory_mb']} MB "
            f"| {_delta_str(b['peak_memory_mb'], a['peak_memory_mb'], True)} |"
        )
        lines.append(
            f"| Disk Read ({label}) | {b['disk_read_mb']} MB | {a['disk_read_mb']} MB "
            f"| {_delta_str(b['disk_read_mb'], a['disk_read_mb'], True)} |"
        )
        lines.append(
            f"| Disk Write ({label}) | {b['disk_write_mb']} MB | {a['disk_write_mb']} MB "
            f"| {_delta_str(b['disk_write_mb'], a['disk_write_mb'], True)} |"
        )
        lines.append(
            f"| Output Size ({label}) | {b['output_size_mb']} MB | {a['output_size_mb']} MB "
            f"| {_delta_str(b['output_size_mb'], a['output_size_mb'], True)} |"
        )
        lines.append(
            f"| Compression Ratio ({label}) | {b['compression_ratio']}% "
            f"| {a['compression_ratio']}% "
            f"| {_delta_str(b['compression_ratio'], a['compression_ratio'], True)} |"
        )

    lines.append("")
    return "\n".join(lines)


# ── Benchmark runner ──────────────────────────────────────────────

def run_single_benchmark(seven_zip: str, fmt: str, level: int,
                         dataset_dir: str, work_dir: str,
                         input_size: int) -> dict:
    """Run before/after compression for one format+level combo."""
    source_name = os.path.basename(dataset_dir)
    cwd = os.path.dirname(dataset_dir)
    label = f"{fmt} L{level}"

    # --- BEFORE ---
    before_path = os.path.join(work_dir, f"before_{fmt}_L{level}.{fmt}")
    if os.path.exists(before_path):
        os.remove(before_path)

    print(f"  [{label}] Running BEFORE (old defaults)...")
    cmd_before = build_before_cmd(seven_zip, fmt, level, before_path, source_name)
    m_before = run_with_metrics(cmd_before, cwd, before_path, input_size)
    print(f"    Done: {m_before.wall_time:.2f}s, ratio={m_before.compression_ratio*100:.1f}%")

    # --- AFTER ---
    after_path = os.path.join(work_dir, f"after_{fmt}_L{level}.{fmt}")
    if os.path.exists(after_path):
        os.remove(after_path)

    print(f"  [{label}] Running AFTER (optimized)...")
    cmd_after = build_after_cmd(seven_zip, fmt, level, after_path, source_name)
    m_after = run_with_metrics(cmd_after, cwd, after_path, input_size)
    print(f"    Done: {m_after.wall_time:.2f}s, ratio={m_after.compression_ratio*100:.1f}%")

    # Cleanup archive files
    for p in [before_path, after_path]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    return {
        "label": label,
        "before": m_before.as_dict(),
        "after": m_after.as_dict(),
    }


def get_dir_size(path: str) -> int:
    """Calculate total size of all files in a directory."""
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ── CLI ───────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark compression optimization (before vs after)."
    )
    parser.add_argument(
        "--size", type=int, default=100,
        help="Test dataset size in MB (default: 100)",
    )
    parser.add_argument(
        "--formats", type=str, default="zip,7z",
        help="Comma-separated archive formats to test (default: zip,7z)",
    )
    parser.add_argument(
        "--levels", type=str, default="5,9",
        help="Comma-separated compression levels to test (default: 5,9)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    formats = [f.strip() for f in args.formats.split(",")]
    levels = [int(l.strip()) for l in args.levels.split(",")]

    print("=" * 60)
    print("  Compression Benchmark: Before vs After Optimization")
    print("=" * 60)

    seven_zip = find_7z()
    print(f"  7z executable: {seven_zip}")
    print(f"  CPU count: {os.cpu_count()}")
    print(f"  psutil: {'available' if HAS_PSUTIL else 'NOT installed (limited metrics)'}")
    print()

    # Create temp directory for all benchmark work
    with tempfile.TemporaryDirectory(prefix="bench_backup_") as tmp_dir:
        print("[1/3] Generating test dataset...")
        dataset_dir = create_test_dataset(tmp_dir, args.size)
        input_size = get_dir_size(dataset_dir)
        print()

        print("[2/3] Running benchmarks...")
        results = []
        for fmt in formats:
            for level in levels:
                r = run_single_benchmark(
                    seven_zip, fmt, level, dataset_dir, tmp_dir, input_size
                )
                results.append(r)
        print()

        print("[3/3] Generating report...")
        report = generate_report(results, args.size)

        # Save report
        script_dir = os.path.dirname(os.path.abspath(__file__))
        report_path = os.path.join(script_dir, "benchmark_report.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  Report saved to: {report_path}")
        print()

        # Also print to stdout
        print(report)

    print("Done.")


if __name__ == "__main__":
    main()
