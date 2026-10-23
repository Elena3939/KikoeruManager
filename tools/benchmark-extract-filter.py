"""本地过滤规划与恢复记录基准，不读取业务目录或数据库。"""
import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.core.filter_planner import plan_filter, scan_tree
from app.core.filter_recovery_service import FilterRecoveryService


def synthetic(count, mode):
    depth = 'a/b/c/d/e/f/g/h/' if mode == 'deep' else ''
    return [{'relative_path': f'{depth}d{i // 100}/a{i}.mp3' if mode == 'mp3' else f'{depth}d{i // 100}/a{i}.tmp',
             'name': f'a{i}.mp3' if mode == 'mp3' else f'a{i}.tmp', 'type': 'file', 'size': 10}
            for i in range(count)]


async def main(args):
    result = {'planning': [], 'disk': [], 'environment': sys.version, 'note':
              '规划为内存条目；disk 为实际临时文件、原子搬运和持久化，不等同于跨盘吞吐。'}
    delays, stop = [], False
    async def heartbeat():
        while not stop:
            start = time.perf_counter()
            await asyncio.sleep(.01)
            delays.append(max(0, time.perf_counter() - start - .01) * 1000)
    pulse = asyncio.create_task(heartbeat())
    for count in (10000, 50000, 100000):
        for mode in ('wide', 'deep', 'parent', 'mp3', 'zero'):
            items = synthetic(count, mode)
            rules = [SimpleNamespace(name='基准', enabled=True, target='all',
                                     pattern=r'^d\d+$|\.tmp$' if mode == 'parent' else r'no-match' if mode in ('zero', 'mp3') else r'\.tmp$')]
            if mode == 'parent':
                items.extend({'relative_path': f'd{i}', 'name': f'd{i}', 'type': 'dir', 'size': None}
                             for i in range((count + 99) // 100))
            samples = []
            for _ in range(3):
                start = time.perf_counter()
                selected = await asyncio.to_thread(plan_filter, items, rules, True)
                samples.append((time.perf_counter() - start) * 1000)
            result['planning'].append({'files': count, 'mode': mode, 'median_ms': round(statistics.median(samples), 2),
                                       'selected': sum(map(len, selected))})
    def disk_run(count):
        with tempfile.TemporaryDirectory(prefix='kikoerumanager-bench-') as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            for i in range(count):
                (source / f'{i}.tmp').write_bytes(b'x' * 16)
            start = time.perf_counter()
            items, _ = scan_tree(str(source))
            scan_ms = (time.perf_counter() - start) * 1000
            recovery = FilterRecoveryService(str(root / 'recovery'))
            recovery.begin_capture('benchmark')
            writes = 0
            atomic = recovery._atomic_json
            def measured(path, payload):
                nonlocal writes
                writes += 1
                atomic(path, payload)
            recovery._atomic_json = measured
            start = time.perf_counter()
            for item in items:
                recovery.capture_item('benchmark', item['path'], relative_path=item['relative_path'], entry_type='file', size=16)
            capture_ms = (time.perf_counter() - start) * 1000
            start = time.perf_counter()
            summary = recovery.public_summary('benchmark')
            summary_ms = (time.perf_counter() - start) * 1000
            return {'files': count, 'scan_ms': round(scan_ms, 2), 'capture_and_persist_ms': round(capture_ms, 2),
                    'summary_ms': round(summary_ms, 2), 'atomic_record_writes': writes}
    for count in args.disk_counts:
        result['disk'].append(await asyncio.to_thread(disk_run, count))
    stop = True
    await pulse
    result['event_loop_delay_ms'] = {'max': round(max(delays, default=0), 2),
                                     'p95': round(sorted(delays)[int(len(delays) * .95)] if delays else 0, 2)}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-counts', type=int, nargs='+', default=[1000])
    parser.add_argument('--output', required=True)
    asyncio.run(main(parser.parse_args()))
