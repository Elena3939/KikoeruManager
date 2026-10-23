"""固定合成社团的缓存计算基准；不含数据库、Redis 与外网耗时。

在仓库根目录用 backend/venv/Scripts/python.exe 执行。
"""
import asyncio
import argparse
from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
import types
import gc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.core import circle_completion_service as current
from app.core.resource_source_service import get_resource_source_service


def baseline_module(ref):
    source = subprocess.check_output(
        ['git', 'show', f'{ref}:backend/app/core/circle_completion_service.py'], cwd=ROOT).decode('utf-8')
    if 'from .circle_completion_presentation import present_completion_rows' in source:
        presentation = types.ModuleType('app.core.circle_completion_presentation_baseline')
        presentation.__package__ = 'app.core'
        original = subprocess.check_output(
            ['git', 'show', f'{ref}:backend/app/core/circle_completion_presentation.py'], cwd=ROOT).decode('utf-8')
        exec(compile(original, presentation.__name__, 'exec'), presentation.__dict__)
        sys.modules[presentation.__name__] = presentation
    source = source.replace('from .circle_completion_presentation import present_completion_rows',
                            'from .circle_completion_presentation_baseline import present_completion_rows')
    module = types.ModuleType('app.core.circle_completion_baseline')
    module.__package__ = 'app.core'
    sys.modules[module.__name__] = module
    exec(compile(source, module.__name__, 'exec'), module.__dict__)
    return module


def snapshot():
    items = []
    for index in range(5000):
        code = f'RJ{10000000 + index:08}'
        items.append(dict(canonical_rjcode=code, display_rjcode=code, title=f'固定作品{index}',
                          owned=False, has_dlsite=True, has_asmr_one=True, linked_rjcodes=[code],
                          asmr_available_rjcode=code, release_date='2026-01-01', bonus_works=[]))
    return dict(catalog=dict(circle_id='BENCH', circle_name='基准社团', source_mask='dlsite',
                             last_indexed_at=None), items=items)


def metrics(values):
    return dict(median_ms=round(statistics.median(values), 3),
                p95_ms=round(sorted(values)[int(len(values) * .95) - 1], 3))


async def measure(module, changes=20):
    service = module.CircleCompletionService()
    service._completion_redis_service = lambda: None
    service._schedule_view_cover_cache = lambda *args: None
    async def resolve(scope):
        return scope
    service._resolve_completion_scope = resolve
    module.SessionLocal = lambda: nullcontext(None)
    data = snapshot()
    builds = 0
    stages = {}
    # 同步阶段独立计时，嵌套阶段不能相加当作总耗时。
    for name in ('_completion_items_with_resources', '_filter_completion_items_for_tab',
                 '_completion_group_bonus_items', '_sort_completion_items', '_completion_summary_from_items'):
        original = getattr(service, name)
        def timed(*args, _fn=original, _name=name, **kwargs):
            start = time.perf_counter()
            try:
                return _fn(*args, **kwargs)
            finally:
                stages.setdefault(_name, []).append((time.perf_counter() - start) * 1000)
        setattr(service, name, timed)

    def build(scope):
        nonlocal builds
        builds += 1
        return deepcopy(data)

    service._build_completion_view_state_uncached = build
    async def page():
        state = await service._get_completion_view_state('BENCH', readonly=True)
        return service._list_circle_completion_works_sync(
            'BENCH', state, service._completion_version_tag('BENCH'), page=1, page_size=100)

    await page()
    hot = []
    for _ in range(100):
        start = time.perf_counter()
        result = await page()
        assert len(result['items']) == 100
        hot.append((time.perf_counter() - start) * 1000)
    source_changes = []
    stages.clear()
    gc_before = [entry['collections'] for entry in gc.get_stats()]
    for _ in range(changes):
        start = time.perf_counter()
        if hasattr(service, 'invalidate_completion_resource_cache'):
            service.invalidate_completion_resource_cache('BENCH')
        else:
            service.invalidate_completion_view_cache('BENCH')
        await page()
        source_changes.append((time.perf_counter() - start) * 1000)
    return dict(hot_page=metrics(hot), source_change=metrics(source_changes), base_builds=builds,
                stages={name: metrics(values) for name, values in stages.items()},
                gc_collections=[entry['collections'] - before for entry, before in zip(gc.get_stats(), gc_before)])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True, help='修改前 Git 提交号')
    parser.add_argument('--rounds', type=int, default=3, help='交替顺序的对比轮数')
    parser.add_argument('--changes', type=int, default=200, help='每轮来源失效样本数')
    args = parser.parse_args()
    get_resource_source_service().decorate_items = lambda db, items: None
    before = baseline_module(args.baseline)
    runs = []
    for index in range(args.rounds):
        run = {}
        for label, module in ([('before', before), ('after', current)] if index % 2 == 0
                              else [('after', current), ('before', before)]):
            gc.collect()
            run[label] = await measure(module, args.changes)
        runs.append(run)
    result = dict(dataset=f'5000作品，100条分页；100次热读，{args.changes}次来源变化；纯缓存计算',
                  baseline=args.baseline, rounds=runs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
