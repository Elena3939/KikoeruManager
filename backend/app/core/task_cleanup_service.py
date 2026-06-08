import logging
import os
import shutil
import stat
import time
from typing import Any, Dict, Iterable, List, Set

logger = logging.getLogger(__name__)

_REIMPORT_SOURCE_ACTIONS = {"reimport_local_download_root", "reimport_downloaded_session"}
_DOWNLOAD_ROW_KEYS = ("local_path", "final_path", "file_path", "path")
_DOWNLOAD_ROW_COLLECTIONS = ("download_files", "downloaded_files", "failed_files")


def cleanup_task_download_artifacts(task: Any) -> Dict[str, Any]:
    """清理取消下载任务留下的产物，严禁把公共下载根目录当任务目录删除。"""
    metadata = dict(getattr(task, "task_metadata", None) or {})
    task_type = _value(getattr(task, "type", ""))
    source_action = str(metadata.get("source_action") or "").strip()
    cleanup_mode = str(metadata.get("cleanup_mode") or "").strip().lower()

    result = {
        "mode": "none",
        "cleaned": 0,
        "cleaned_paths": [],
        "skipped_paths": [],
        "errors": [],
    }

    if source_action in _REIMPORT_SOURCE_ACTIONS or cleanup_mode == "none":
        result["mode"] = "skipped"
        _log_cleanup_result(task, result, source_action=source_action, cleanup_mode=cleanup_mode)
        return result

    if task_type == "http_download" or cleanup_mode == "files_only":
        result["mode"] = "files_only"
        _cleanup_download_files(task, metadata, result)
        _log_cleanup_result(task, result, source_action=source_action, cleanup_mode=cleanup_mode)
        return result

    owned_roots = _task_owned_cleanup_roots(task, metadata, task_type)
    if owned_roots:
        result["mode"] = "owned_roots"
        for root in owned_roots:
            _remove_directory(root, result)
        _log_cleanup_result(task, result, source_action=source_action, cleanup_mode=cleanup_mode)
        return result

    result["mode"] = "files_only"
    _cleanup_download_files(task, metadata, result)
    _log_cleanup_result(task, result, source_action=source_action, cleanup_mode=cleanup_mode)
    return result


def _log_cleanup_result(task: Any, result: Dict[str, Any], *, source_action: str, cleanup_mode: str) -> None:
    log_method = logger.warning if result.get("errors") else logger.info
    log_method(
        "下载产物清理摘要: task_id=%s task_type=%s mode=%s source_action=%s cleanup_mode=%s cleaned=%s skipped=%s errors=%s",
        getattr(task, "id", ""),
        _value(getattr(task, "type", "")),
        result.get("mode"),
        source_action,
        cleanup_mode,
        result.get("cleaned", 0),
        len(result.get("skipped_paths") or []),
        len(result.get("errors") or []),
    )


def _cleanup_download_files(task: Any, metadata: Dict[str, Any], result: Dict[str, Any]) -> None:
    boundaries = _cleanup_boundaries(task, metadata)
    candidates = _download_file_candidates(metadata, boundaries)
    for candidate in sorted(candidates):
        if not _path_allowed_for_file_cleanup(candidate, boundaries):
            _skip(result, candidate, "不在下载根内或指向下载根目录")
            continue
        _remove_file(candidate, result)

    deleted_files = [
        path for path in result["cleaned_paths"]
        if not str(path).lower().endswith(".aria2")
    ]
    _cleanup_empty_parent_dirs(deleted_files, boundaries, result)


def _download_file_candidates(metadata: Dict[str, Any], boundaries: List[str]) -> Set[str]:
    paths: Set[str] = set()
    primary_root = boundaries[0] if boundaries else ""

    for row in _iter_download_rows(metadata):
        for key in _DOWNLOAD_ROW_KEYS:
            raw_path = str(row.get(key) or "").strip()
            if _looks_like_local_path(raw_path):
                paths.add(os.path.abspath(os.path.normpath(raw_path)))

        relative_path = str(row.get("relative_path") or "").strip()
        if primary_root and relative_path and _looks_like_local_path(relative_path):
            paths.add(os.path.abspath(os.path.normpath(os.path.join(primary_root, relative_path))))

    final_output_path = str(metadata.get("final_output_path") or "").strip()
    if _looks_like_local_path(final_output_path):
        paths.add(os.path.abspath(os.path.normpath(final_output_path)))

    with_fragments = set(paths)
    for path in paths:
        if not path.lower().endswith(".aria2"):
            with_fragments.add(path + ".aria2")
    return with_fragments


def _iter_download_rows(metadata: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for key in _DOWNLOAD_ROW_COLLECTIONS:
        for item in list(metadata.get(key) or []):
            if isinstance(item, dict):
                yield item


def _cleanup_boundaries(task: Any, metadata: Dict[str, Any]) -> List[str]:
    roots: List[str] = []
    for raw in (
        metadata.get("download_root"),
        metadata.get("staging_dir"),
        getattr(task, "output_path", ""),
    ):
        path = str(raw or "").strip()
        if path and os.path.isdir(path):
            roots.append(os.path.abspath(os.path.normpath(path)))

    task_type = _value(getattr(task, "type", ""))
    if task_type == "http_download":
        try:
            from ..config.settings import get_config

            configured_root = str(getattr(get_config().http_downloader, "download_root", "") or "").strip()
            if configured_root and os.path.isdir(configured_root):
                roots.append(os.path.abspath(os.path.normpath(configured_root)))
        except Exception:
            logger.debug("读取 HTTP 下载根目录失败", exc_info=True)

    unique_roots: List[str] = []
    for root in roots:
        if root and root not in unique_roots:
            unique_roots.append(root)
    return unique_roots


def _path_allowed_for_file_cleanup(path: str, boundaries: List[str]) -> bool:
    if not path or not boundaries:
        return False
    normalized = os.path.abspath(os.path.normpath(path))
    for root in boundaries:
        if _same_path(normalized, root):
            return False
        if _is_under(normalized, root):
            return True
    return False


def _task_owned_cleanup_roots(task: Any, metadata: Dict[str, Any], task_type: str) -> List[str]:
    roots: List[str] = []
    for raw in (metadata.get("staging_dir"), metadata.get("download_root")):
        root = str(raw or "").strip()
        if not root or not os.path.isdir(root):
            continue
        normalized = os.path.abspath(os.path.normpath(root))
        if _same_path(normalized, str(metadata.get("download_base_path") or "")):
            continue
        if raw == metadata.get("staging_dir") and _is_known_owned_staging_root(task, metadata, normalized):
            roots.append(normalized)
            continue
        if _is_known_owned_download_root(task, metadata, task_type, normalized):
            roots.append(normalized)

    unique_roots: List[str] = []
    for root in roots:
        if root and root not in unique_roots:
            unique_roots.append(root)
    return unique_roots


def _is_known_owned_download_root(task: Any, metadata: Dict[str, Any], task_type: str, root: str) -> bool:
    if task_type != "asmr_sync_download":
        return False
    if str(metadata.get("download_mode") or "").strip().lower() != "enhanced":
        return False
    task_id = str(getattr(task, "id", "") or "").strip()
    basename = os.path.basename(root)
    if task_id and task_id[:8] not in basename:
        return False

    for base in _known_download_root_bases(metadata):
        if base and _is_under(root, base):
            return True
    return False


def _is_known_owned_staging_root(task: Any, metadata: Dict[str, Any], root: str) -> bool:
    task_id = str(getattr(task, "id", "") or "").strip()
    basename = os.path.basename(root)
    if task_id and (basename == task_id or task_id[:8] in basename):
        return True

    download_root = str(metadata.get("download_root") or "").strip()
    if download_root:
        staging_parent = os.path.abspath(os.path.normpath(os.path.join(download_root, ".baidu-netdisk-staging")))
        if not _same_path(root, staging_parent) and _is_under(root, staging_parent):
            return True
    return False


def _known_download_root_bases(metadata: Dict[str, Any]) -> List[str]:
    bases: List[str] = []
    download_base_path = str(metadata.get("download_base_path") or "").strip()
    if download_base_path:
        bases.append(os.path.abspath(os.path.normpath(download_base_path)))
    try:
        from ..config.settings import get_config

        temp_path = str(getattr(get_config().storage, "temp_path", "") or "").strip()
        if temp_path:
            bases.append(os.path.abspath(os.path.normpath(os.path.join(temp_path, "asmr_enhanced"))))
    except Exception:
        logger.debug("读取临时目录失败", exc_info=True)
    return bases


def _cleanup_empty_parent_dirs(paths: List[str], boundaries: List[str], result: Dict[str, Any]) -> None:
    for path in paths:
        parent = os.path.abspath(os.path.normpath(os.path.dirname(path)))
        while parent and not any(_same_path(parent, boundary) for boundary in boundaries):
            if not any(_is_under(parent, boundary) for boundary in boundaries):
                break
            try:
                os.rmdir(parent)
                _cleaned(result, parent)
            except OSError:
                break
            parent = os.path.abspath(os.path.normpath(os.path.dirname(parent)))


def _remove_file(path: str, result: Dict[str, Any]) -> None:
    if not os.path.exists(path):
        return
    if os.path.isdir(path):
        _skip(result, path, "文件级清理跳过目录")
        return
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass
    try:
        os.remove(path)
        _cleaned(result, path)
    except Exception as exc:
        _error(result, path, exc)


def _remove_directory(path: str, result: Dict[str, Any]) -> None:
    if not os.path.exists(path):
        return
    if not os.path.isdir(path):
        _remove_file(path, result)
        return
    try:
        _robust_rmtree(path)
        _cleaned(result, path)
    except Exception as exc:
        _error(result, path, exc)


def _robust_rmtree(path: str, retries: int = 3, delay: float = 0.3) -> None:
    def _onerror(func, fpath, exc_info):
        exc = exc_info[1]
        if getattr(exc, "winerror", None) == 5:
            try:
                os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
                func(fpath)
                return
            except Exception:
                pass
        raise exc

    last_exc = None
    for attempt in range(retries):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except Exception as exc:
            last_exc = exc
            if getattr(exc, "winerror", None) == 32 and attempt < retries - 1:
                time.sleep(delay)
                continue
            break
    if last_exc:
        raise last_exc


def _looks_like_local_path(path: str) -> bool:
    if not path:
        return False
    lowered = path.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "magnet:")):
        return False
    if "://" in path:
        return False
    return True


def _is_under(path: str, base_path: str) -> bool:
    try:
        if not path or not base_path:
            return False
        target = os.path.abspath(os.path.normpath(path))
        base = os.path.abspath(os.path.normpath(base_path))
        if os.name == "nt":
            target = os.path.normcase(target)
            base = os.path.normcase(base)
        return os.path.commonpath([base, target]) == base
    except Exception:
        return False


def _same_path(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left_abs = os.path.abspath(os.path.normpath(left))
    right_abs = os.path.abspath(os.path.normpath(right))
    if os.name == "nt":
        left_abs = os.path.normcase(left_abs)
        right_abs = os.path.normcase(right_abs)
    return left_abs == right_abs


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _cleaned(result: Dict[str, Any], path: str) -> None:
    result["cleaned"] += 1
    result["cleaned_paths"].append(path)


def _skip(result: Dict[str, Any], path: str, reason: str) -> None:
    result["skipped_paths"].append({"path": path, "reason": reason})
    logger.warning("跳过下载清理路径: %s, reason=%s", path, reason)


def _error(result: Dict[str, Any], path: str, exc: Exception) -> None:
    result["errors"].append({"path": path, "error": str(exc)})
    logger.warning("清理下载产物失败: %s", path, exc_info=True)
