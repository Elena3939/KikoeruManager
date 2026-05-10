import filecmp
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.settings import get_config

logger = logging.getLogger(__name__)


class FolderCompareService:
    """本地文件夹对比与合并服务"""

    def build_compare_items(self, new_root: str, existing_root: str) -> List[dict[str, Any]]:
        new_root_path = Path(new_root)
        existing_root_path = Path(existing_root)

        new_map = self._collect_entries(new_root_path)
        existing_map = self._collect_entries(existing_root_path)

        compare_items: List[dict[str, Any]] = []
        all_paths = sorted(set(new_map.keys()) | set(existing_map.keys()))

        for relative_path in all_paths:
            new_entry = new_map.get(relative_path)
            existing_entry = existing_map.get(relative_path)
            compare_items.append(self._build_compare_item(relative_path, new_entry, existing_entry))

        return compare_items

    def build_compare_items_from_listing(
        self,
        new_root: str,
        existing_items: List[dict[str, Any]],
        existing_root: str,
    ) -> List[dict[str, Any]]:
        new_root_path = Path(new_root)
        new_map = self._collect_entries(new_root_path)
        existing_map = self._collect_entries_from_listing(existing_items, existing_root)

        compare_items: List[dict[str, Any]] = []
        all_paths = sorted(set(new_map.keys()) | set(existing_map.keys()))
        for relative_path in all_paths:
            new_entry = new_map.get(relative_path)
            existing_entry = existing_map.get(relative_path)
            compare_items.append(
                self._build_compare_item(
                    relative_path,
                    new_entry,
                    existing_entry,
                    allow_exact_compare=bool(new_entry and existing_entry and existing_entry.get("local", False)),
                )
            )
        return compare_items

    def build_default_decisions(self, compare_items: List[dict[str, Any]]) -> Dict[str, str]:
        decisions: Dict[str, str] = {}
        for item in compare_items:
            if item.get("type") != "file":
                continue
            status = str(item.get("status") or "")
            relative_path = str(item.get("relative_path") or "")
            if status == "new_only":
                decisions[relative_path] = "use_new"
            elif status == "old_only":
                decisions[relative_path] = "use_old"
            elif status == "modified":
                decisions[relative_path] = "use_new"
            elif status == "unchanged":
                decisions[relative_path] = "use_old"
        return decisions

    def normalize_decisions(self, compare_items: List[dict[str, Any]], decisions: Dict[str, str]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        for item in compare_items:
            if item.get("type") != "file":
                continue
            relative_path = str(item.get("relative_path") or "")
            requested = str((decisions or {}).get(relative_path) or "").strip().lower()
            if requested not in {"use_new", "use_old", "delete"}:
                requested = self._default_decision_for_status(str(item.get("status") or ""))
            if requested == "use_old" and not item.get("old_path"):
                requested = "use_new" if item.get("new_path") else "delete"
            if requested == "use_new" and not item.get("new_path"):
                requested = "use_old" if item.get("old_path") else "delete"
            normalized[relative_path] = requested
        return normalized

    def build_summary(self, compare_items: List[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "new_only": 0,
            "old_only": 0,
            "modified": 0,
            "unchanged": 0,
            "total_files": 0,
            "total_dirs": 0,
        }
        for item in compare_items:
            if item.get("type") == "dir":
                summary["total_dirs"] += 1
                continue
            if item.get("type") != "file":
                continue
            summary["total_files"] += 1
            status = str(item.get("status") or "")
            if status in summary:
                summary[status] += 1
        return summary

    def apply_merge(
        self,
        new_root: str,
        existing_root: str,
        decisions: Dict[str, str],
        target_path: str,
    ) -> str:
        compare_items = self.build_compare_items(new_root, existing_root)
        merged_dir = self._build_merged_directory(new_root, existing_root, compare_items, decisions)
        return self.safe_replace_directory(merged_dir, target_path)

    def safe_replace_directory(self, source_dir: str, target_path: str) -> str:
        source_dir = os.path.abspath(source_dir)
        target_path = os.path.abspath(target_path)

        if not os.path.isdir(source_dir):
            raise RuntimeError("待写入目录不存在")

        target_parent = os.path.dirname(target_path)
        os.makedirs(target_parent, exist_ok=True)

        backup_path = ""
        try:
            if os.path.exists(target_path):
                backup_path = f"{target_path}.__kikoerumanager_backup__.{uuid.uuid4().hex[:8]}"
                os.replace(target_path, backup_path)
                logger.info("冲突替换前备份旧目录: %s -> %s", target_path, backup_path)

            os.replace(source_dir, target_path)
            logger.info("冲突替换写入完成: %s", target_path)

            if backup_path and os.path.exists(backup_path):
                shutil.rmtree(backup_path, ignore_errors=True)
                logger.info("冲突替换完成后清理备份目录: %s", backup_path)
            return target_path
        except Exception:
            logger.exception("冲突替换失败，准备回滚: %s", target_path)
            if os.path.exists(target_path):
                shutil.rmtree(target_path, ignore_errors=True)
            if backup_path and os.path.exists(backup_path):
                os.replace(backup_path, target_path)
                logger.info("冲突替换已回滚: %s", target_path)
            raise

    def _build_merged_directory(
        self,
        new_root: str,
        existing_root: str,
        compare_items: List[dict[str, Any]],
        decisions: Dict[str, str],
    ) -> str:
        temp_root = get_config().storage.temp_path
        os.makedirs(temp_root, exist_ok=True)
        merge_root = tempfile.mkdtemp(prefix="existing_folder_merge_", dir=temp_root)

        for item in compare_items:
            if item.get("type") != "dir":
                continue
            status = str(item.get("status") or "")
            relative_path = str(item.get("relative_path") or "")
            if status == "old_only" and decisions.get(relative_path) == "delete":
                continue
            target_dir = os.path.join(merge_root, relative_path) if relative_path else merge_root
            os.makedirs(target_dir, exist_ok=True)

        for item in compare_items:
            if item.get("type") != "file":
                continue
            relative_path = str(item.get("relative_path") or "")
            decision = decisions.get(relative_path) or self._default_decision_for_status(str(item.get("status") or ""))
            if decision == "delete":
                continue
            source_path = item.get("new_path") if decision == "use_new" else item.get("old_path")
            if not source_path or not os.path.isfile(source_path):
                continue
            target_file = os.path.join(merge_root, relative_path)
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            shutil.copy2(source_path, target_file)

        return merge_root

    def _default_decision_for_status(self, status: str) -> str:
        if status == "old_only":
            return "use_old"
        return "use_new"

    def _collect_entries_from_listing(self, items: List[dict[str, Any]], existing_root: str) -> Dict[str, dict[str, Any]]:
        result: Dict[str, dict[str, Any]] = {}
        normalized_root = str(existing_root or "")
        for item in items or []:
            relative_path = str(item.get("relative_path") or "").replace("\\", "/").strip("/")
            if not relative_path:
                continue
            item_path = str(item.get("path") or "")
            result[relative_path] = {
                "type": "dir" if item.get("is_directory") else "file",
                "path": item_path or f"{normalized_root}/{relative_path}".rstrip("/"),
                "size": int(item.get("size") or 0),
                "mtime": self._parse_timestamp(item.get("modified_time")),
                "local": False,
            }
            parent_parts = relative_path.split("/")[:-1]
            for index in range(len(parent_parts)):
                parent_relative = "/".join(parent_parts[: index + 1])
                result.setdefault(
                    parent_relative,
                    {
                        "type": "dir",
                        "path": f"{normalized_root}/{parent_relative}".rstrip("/"),
                        "size": 0,
                        "mtime": self._parse_timestamp(item.get("modified_time")),
                        "local": False,
                    },
                )
        return result

    def _parse_timestamp(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
        except Exception:
            return None

    def _collect_entries(self, root: Path) -> Dict[str, dict[str, Any]]:
        result: Dict[str, dict[str, Any]] = {}
        if not root.exists():
            return result

        for current_root, dirs, files in os.walk(root):
            current_path = Path(current_root)
            relative_root = current_path.relative_to(root)
            relative_root_str = "" if str(relative_root) == "." else relative_root.as_posix()

            for dirname in sorted(dirs):
                path = current_path / dirname
                relative_path = f"{relative_root_str}/{dirname}" if relative_root_str else dirname
                stat = path.stat()
                result[relative_path] = {
                    "type": "dir",
                    "path": str(path),
                    "size": 0,
                    "mtime": int(stat.st_mtime),
                    "local": True,
                }

            for filename in sorted(files):
                path = current_path / filename
                relative_path = f"{relative_root_str}/{filename}" if relative_root_str else filename
                stat = path.stat()
                result[relative_path] = {
                    "type": "file",
                    "path": str(path),
                    "size": int(stat.st_size),
                    "mtime": int(stat.st_mtime),
                    "local": True,
                }

        return result

    def _build_compare_item(
        self,
        relative_path: str,
        new_entry: Optional[dict[str, Any]],
        existing_entry: Optional[dict[str, Any]],
        allow_exact_compare: bool = True,
    ) -> dict[str, Any]:
        item_type = (new_entry or existing_entry or {}).get("type", "file")
        status = "unchanged"
        source = "both"
        exact_match = False

        if new_entry and not existing_entry:
            status = "new_only"
            source = "new"
        elif existing_entry and not new_entry:
            status = "old_only"
            source = "old"
        elif new_entry and existing_entry:
            if new_entry.get("type") != existing_entry.get("type"):
                status = "modified"
                source = "both"
            elif item_type == "dir":
                status = "unchanged"
                exact_match = True
            else:
                if allow_exact_compare and new_entry.get("path") and existing_entry.get("path"):
                    exact_match = filecmp.cmp(str(new_entry["path"]), str(existing_entry["path"]), shallow=False)
                else:
                    exact_match = (
                        int(new_entry.get("size") or 0) == int(existing_entry.get("size") or 0)
                        and int(new_entry.get("mtime") or 0) == int(existing_entry.get("mtime") or 0)
                    )
                status = "unchanged" if exact_match else "modified"

        return {
            "id": f"{item_type}:{relative_path}",
            "relative_path": relative_path,
            "name": os.path.basename(relative_path) if relative_path else os.path.basename(new_entry["path"] if new_entry else existing_entry["path"]),
            "type": item_type,
            "source": source,
            "status": status,
            "compare_exact": exact_match,
            "new_path": str(new_entry["path"]) if new_entry else None,
            "old_path": str(existing_entry["path"]) if existing_entry else None,
            "new_size": int(new_entry["size"]) if new_entry else None,
            "old_size": int(existing_entry["size"]) if existing_entry else None,
            "new_mtime": int(new_entry["mtime"]) if new_entry else None,
            "old_mtime": int(existing_entry["mtime"]) if existing_entry else None,
            "compare_basis": "content" if allow_exact_compare else "metadata",
        }


_folder_compare_service: Optional[FolderCompareService] = None


def get_folder_compare_service() -> FolderCompareService:
    global _folder_compare_service
    if _folder_compare_service is None:
        _folder_compare_service = FolderCompareService()
    return _folder_compare_service
