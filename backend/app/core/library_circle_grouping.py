"""纯本地社团分类：整批共用恢复意图、索引提交与统计落盘。"""
import logging
import os
import re
import time
import uuid

logger = logging.getLogger(__name__)


def group_local_folders(manager, library, paths, parse_circle, mutation_service, *, preview=False):
    started = time.perf_counter()
    prepare_ms = filesystem_ms = finalize_ms = 0.0
    root = os.path.abspath(library.root_path)
    real_root = os.path.normcase(os.path.realpath(root))
    results, groups, seen = [], {}, set()
    normalized = [os.path.abspath(str(p).strip()) for p in paths]
    selected = {os.path.normcase(p) for p in normalized}
    overlapping = set()
    for source in normalized:
        parent = os.path.dirname(source)
        while parent != os.path.dirname(parent):
            if os.path.normcase(parent) in selected:
                overlapping.update((os.path.normcase(source), os.path.normcase(parent)))
            parent = os.path.dirname(parent)

    def relative(path):
        return os.path.relpath(path, root).replace(os.sep, "/")

    def effects(source, destination, *, merged=False):
        if merged:
            return [{"kind": "reconcile", "relative_path": relative(p), "scope": "subtree"}
                    for p in (source, destination)]
        return [
            {"kind": "move", "relative_path": relative(source), "scope": "subtree",
             "target_library_id": library.id, "target_path": relative(destination),
             "payload": {"old_absolute_path": source, "new_absolute_path": destination}},
            {"kind": "reconcile", "relative_path": relative(destination), "scope": "subtree"},
        ]

    for raw, source in zip(paths, normalized):
        item = {"path": raw, "row_path": source, "success": False}
        results.append(item)
        try:
            key = os.path.normcase(source)
            if key in seen:
                item.update(success=True, skipped=True, message="重复路径，已跳过")
                continue
            seen.add(key)
            real_source = os.path.normcase(os.path.realpath(source))
            if os.path.commonpath([real_root, real_source]) != real_root or real_source == real_root:
                raise ValueError("目标文件夹不在所选库存内，或为库存根目录")
            if key in overlapping:
                raise ValueError("不能同时分类父目录和子目录，请分别选择")
            if not os.path.isdir(source):
                raise ValueError("目标必须是文件夹")
            circle = parse_circle(os.path.basename(source))
            if not circle:
                raise ValueError("未能从文件夹名识别社团，未操作该目录")
            safe = re.sub(r'[<>:"/\\|?*]', '_', circle)
            safe = re.sub(r'[\x00-\x1f\x7f]', '', safe).rstrip(' .')
            if not safe or safe in (".", ".."):
                raise ValueError("社团名无法转换为合法文件夹名")
            target = os.path.join(root, safe)
            if os.path.commonpath([real_root, os.path.normcase(os.path.realpath(target))]) != real_root:
                raise ValueError("目标社团目录指向库存外部")
            item.update(circle_name=circle, safe_circle_name=safe, target_dir=target,
                        final_path=os.path.join(target, os.path.basename(source)))
            if os.path.normcase(os.path.dirname(source)) == os.path.normcase(target):
                item.update(success=True, skipped=True, message="已经在社团目录下，无需移动")
            elif preview:
                item.update(success=True, preview=True, message=f"将移动到 {target}")
            else:
                groups.setdefault(target, []).append(item)
        except (ValueError, OSError) as exc:
            item.update(error=str(exc), message=str(exc))

    mutation = None
    if groups:
        planned = [effect for items in groups.values() for item in items
                   for effect in effects(item["row_path"], item["final_path"])]
        # 恢复范围覆盖整个目标社团，包含文件撞名后生成的实际 suffix 路径。
        planned.extend({"kind": "reconcile", "relative_path": relative(target), "scope": "subtree"}
                       for target in groups)
        prepare_started = time.perf_counter()
        prepared = mutation_service.prepare(kind="auto_circle_group",
            effects_by_library={library.id: planned}, idempotency_key=f"auto-circle:{uuid.uuid4().hex}")
        prepare_ms = (time.perf_counter() - prepare_started) * 1000
        actual, moved, deltas = [], [], []
        try:
            mutation_service.mark_filesystem_started(prepared.operation_id)
            filesystem_started = time.perf_counter()
            for target, items in groups.items():
                try:
                    existed = os.path.isdir(target)
                    os.makedirs(target, exist_ok=True)
                    if not existed:
                        deltas.append((library, target, 1))
                        actual.append({"kind": "upsert", "relative_path": relative(target), "scope": "exact",
                            "payload": {"entry_snapshot": {"entry_type": "dir", "absolute_path": target,
                                "name": os.path.basename(target), "mtime": int(os.stat(target).st_mtime * 1000)}}})
                    # 同名目录会递归合并，即使只完成一部分也必须校正源和目标。
                    merging = [i for i in items if os.path.isdir(i["final_path"])]
                    actual.extend(e for i in merging for e in effects(i["row_path"], i["final_path"], merged=True))
                    result = manager._move_local_items_sync(library, library,
                        [i["row_path"] for i in items], target, "suffix", True, deferred_stats=deltas)
                    by_source = {m["source"]: m for m in result.get("moved", [])}
                    moved.extend(result.get("moved", []))
                    errors = "; ".join(str(f.get("error", "")) for f in result.get("failed", []))
                    for item in items:
                        move = by_source.get(item["row_path"])
                        if move:
                            item.update(success=True, final_path=move["destination"], message=f"已移动到《{item['safe_circle_name']}》")
                            if not move.get("merged"):
                                actual.extend(effects(move["source"], move["destination"]))
                        else:
                            item.update(error=errors or "目录未完整移动，已保留剩余文件")
                except Exception as exc:
                    # 移动可能已经部分落地，保留整组校正范围。
                    actual.extend(e for i in items for e in effects(i["row_path"], i["final_path"], merged=True))
                    for item in items:
                        item.update(error=str(exc))
            filesystem_ms = (time.perf_counter() - filesystem_started) * 1000
            finalize_started = time.perf_counter()
            mutation = mutation_service.finalize(prepared.operation_id,
                actual_effects_by_library={library.id: actual}, actual_result={"moved": moved})
            finalize_ms = (time.perf_counter() - finalize_started) * 1000
        except Exception as exc:
            mutation_service.mark_reconcile_required(prepared.operation_id, exc)
            raise
        finally:
            # 只计算顶层数量差值，不扫作品内容；整批失效、持久化各一次。
            browse_root = os.path.normcase(os.path.abspath(library.browse_root_path or root))
            top_deltas = [(p, d) for _, p, d in deltas if os.path.normcase(os.path.dirname(p)) == browse_root]
            try:
                if top_deltas:
                    manager._local_top_level_delta(library, top_deltas[0][0], sum(d for _, d in top_deltas))
                else:
                    manager._invalidate_local_browse_caches(library.id)
            except Exception:
                logger.exception("社团分类统计落盘失败")

    response = {"message": "批量按社团分类完成", "results": results, "result": mutation,
            "success_count": sum(bool(i["success"] and not i.get("skipped")) for i in results),
            "skipped_count": sum(bool(i.get("skipped")) for i in results),
            "failed_count": sum(not i["success"] for i in results)}
    logger.info("[社团分类] library=%s items=%d groups=%d success=%d skipped=%d failed=%d prepare_ms=%.2f filesystem_ms=%.2f finalize_ms=%.2f total_ms=%.2f",
                library.id, len(paths), len(groups), response["success_count"], response["skipped_count"],
                response["failed_count"], prepare_ms, filesystem_ms, finalize_ms, (time.perf_counter() - started) * 1000)
    return response
