import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Optional
from urllib.parse import quote

import aiohttp
import yaml

from ..config.settings import get_config


def _config_file_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    return os.path.join(project_root, "config", "config.yaml")


def _stats_cache_file_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    data_dir = os.path.join(project_root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "library_stats_cache.json")


def _gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


@dataclass
class SynologyConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    root_path: str = "/"
    session_name: str = "FileStation"
    timeout: int = 30
    verify_ssl: bool = True
    otp_code: str = ""
    device_name: str = ""
    device_id: str = ""
    enable_device_token: bool = True


@dataclass
class LibraryDefinition:
    id: str
    name: str
    type: str = "local"
    path: str = ""
    browse_path: str = ""
    enabled: bool = True
    writable: bool = True
    description: str = ""
    tags: list[str] = field(default_factory=list)
    synology: Optional[SynologyConfig] = None

    @property
    def root_path(self) -> str:
        if self.type == "synology_filestation" and self.synology:
            return self.synology.root_path or self.path or "/"
        return self.path

    @property
    def browse_root_path(self) -> str:
        browse_path = self.browse_path or ""
        if self.type == "synology_filestation":
            return browse_path or self.root_path or "/"
        return browse_path or self.root_path


def load_library_config() -> dict[str, Any]:
    path = _config_file_path()
    data: dict[str, Any] = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}

    storage = data.get("storage") or {}
    runtime_config = get_config().storage

    libraries: list[LibraryDefinition] = []
    for item in storage.get("libraries") or []:
        synology_raw = item.get("synology") or None
        synology = SynologyConfig(**synology_raw) if synology_raw else None
        libraries.append(
            LibraryDefinition(
                id=item["id"],
                name=item.get("name") or item["id"],
                type=(item.get("type") or "local").lower(),
                path=item.get("path") or "",
                browse_path=item.get("browse_path") or "",
                enabled=item.get("enabled", True),
                writable=item.get("writable", True),
                description=item.get("description") or "",
                tags=item.get("tags") or [],
                synology=synology,
            )
        )

    active_libraries = [library for library in libraries if library.enabled] or libraries

    if not libraries:
        libraries = [
            LibraryDefinition(
                id="default-local",
                name="默认库存",
                type="local",
                path=runtime_config.library_path,
                browse_path="",
                enabled=True,
                writable=True,
            )
        ]
        active_libraries = libraries

    return {
        "libraries": libraries,
        "default_library_id": storage.get("default_library_id") or active_libraries[0].id,
        "default_extract_library_id": storage.get("default_extract_library_id") or storage.get("default_library_id") or active_libraries[0].id,
        "health_warning_free_gb": storage.get("health_warning_free_gb", 200.0),
        "stats_cache_ttl_seconds": storage.get("stats_cache_ttl_seconds", 300),
    }


class SynologyFileStationClient:
    def __init__(self, config: SynologyConfig):
        self.config = config
        self._sid: Optional[str] = None
        self._device_id: str = config.device_id or ""

    async def _request(self, api: str, method: str, version: int, params: dict[str, Any], files=None):
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if not self._sid and api != "SYNO.API.Auth":
                await self._login(session)

            payload = {"api": api, "method": method, "version": str(version), **params}
            if self._sid and api != "SYNO.API.Auth":
                payload["_sid"] = self._sid

            url = f"{self.config.base_url.rstrip('/')}/webapi/entry.cgi"
            if files:
                form = aiohttp.FormData()
                for key, value in payload.items():
                    form.add_field(key, str(value))
                for file_key, file_value in files:
                    form.add_field(file_key, file_value[0], filename=file_value[1], content_type="application/octet-stream")
                async with session.post(url, data=form, ssl=self.config.verify_ssl) as response:
                    data = await response.json()
            else:
                async with session.get(url, params=payload, ssl=self.config.verify_ssl) as response:
                    data = await response.json()

            if not data.get("success"):
                raise RuntimeError(f"群晖 FileStation 请求失败: {data}")
            return data.get("data") or {}

    async def _login(self, session: aiohttp.ClientSession):
        url = f"{self.config.base_url.rstrip('/')}/webapi/auth.cgi"
        params = {
            "api": "SYNO.API.Auth",
            "method": "login",
            "version": "6",
            "account": self.config.username,
            "passwd": self.config.password,
            "session": self.config.session_name,
            "format": "sid",
        }
        if self.config.otp_code:
            params["otp_code"] = self.config.otp_code
        if self.config.device_name:
            params["device_name"] = self.config.device_name
        if self.config.device_id:
            params["device_id"] = self.config.device_id
        if self.config.enable_device_token:
            params["enable_device_token"] = "yes"
        async with session.get(url, params=params, ssl=self.config.verify_ssl) as response:
            data = await response.json()
        if not data.get("success") and (data.get("error") or {}).get("code") == 403:
            auth_errors = (data.get("error") or {}).get("errors") or {}
            auth_types = [item.get("type") for item in auth_errors.get("types") or [] if item.get("type")]
            if "otp" in auth_types:
                raise RuntimeError(f"群晖登录失败：当前账号启用了二步验证，需要填写一次性验证码(OTP)。{data}")
        if not data.get("success"):
            raise RuntimeError(f"群晖登录失败: {data}")
        login_data = data.get("data") or {}
        self._sid = login_data.get("sid")
        self._device_id = login_data.get("did") or self._device_id
        if not self._sid:
            raise RuntimeError("群晖登录成功但未返回 sid")

    @property
    def device_id(self) -> str:
        return self._device_id

    async def test_connection(self, folder_path: str) -> dict[str, Any]:
        if folder_path in ("", "/"):
            await self.list_share(offset=0, limit=1, sort_by="name", sort_direction="asc")
        else:
            await self.list(folder_path, offset=0, limit=1, sort_by="name", sort_direction="asc")
        return {
            "device_id": self.device_id,
            "web_url": build_synology_web_url(self.config.base_url, folder_path),
        }

    async def list(self, folder_path: str, offset: int = 0, limit: int = 200, sort_by: str = "name", sort_direction: str = "asc"):
        return await self._request(
            "SYNO.FileStation.List",
            "list",
            2,
            {
                "folder_path": folder_path,
                "offset": offset,
                "limit": limit,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "additional": '["time","size"]',
            },
        )

    async def list_share(self, offset: int = 0, limit: int = 200, sort_by: str = "name", sort_direction: str = "asc"):
        return await self._request(
            "SYNO.FileStation.List",
            "list_share",
            2,
            {
                "offset": offset,
                "limit": limit,
                "sort_by": sort_by,
                "sort_direction": sort_direction,
                "additional": '["time","size"]',
            },
        )

    async def stat(self, path: str):
        return await self._request(
            "SYNO.FileStation.List",
            "getinfo",
            2,
            {
                "path": f'["{path}"]',
                "additional": '["real_path","size","time","perm"]',
            },
        )

    async def start_dir_size(self, path: str):
        return await self._request(
            "SYNO.FileStation.DirSize",
            "start",
            2,
            {
                "path": f'"{path}"',
            },
        )

    async def dir_size_status(self, taskid: str):
        return await self._request(
            "SYNO.FileStation.DirSize",
            "status",
            2,
            {
                "taskid": f'"{taskid}"',
            },
        )

    async def create_folder(self, parent_path: str, name: str):
        return await self._request(
            "SYNO.FileStation.CreateFolder",
            "create",
            2,
            {
                "folder_path": parent_path,
                "name": name,
                "force_parent": "true",
            },
        )

    async def rename(self, path: str, new_name: str):
        return await self._request(
            "SYNO.FileStation.Rename",
            "rename",
            2,
            {
                "path": f'["{path}"]',
                "name": f'["{new_name}"]',
            },
        )

    async def delete(self, path: str):
        return await self._request(
            "SYNO.FileStation.Delete",
            "delete",
            2,
            {
                "path": f'["{path}"]',
                "accurate_progress": "true",
            },
        )

    async def upload_file(self, dest_folder: str, local_path: str):
        with open(local_path, "rb") as handle:
            await self._request(
                "SYNO.FileStation.Upload",
                "upload",
                2,
                {
                    "path": dest_folder,
                    "create_parents": "true",
                    "overwrite": "false",
                },
                files=[("file", (handle, os.path.basename(local_path)))],
            )


def build_synology_web_url(base_url: str, root_path: str) -> str:
    normalized_base = (base_url or "").rstrip("/")
    normalized_path = root_path or "/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    launch_param = quote(f"path={normalized_path}", safe="")
    return f"{normalized_base}//file/?launchApp=SYNO.SDS.App.FileStation3.Instance&launchParam={launch_param}"


class LibraryManager:
    def __init__(self):
        self._stats_cache: dict[str, dict[str, Any]] = {}
        self._stats_tasks: dict[str, asyncio.Task] = {}
        self._size_cache: dict[str, dict[str, Any]] = {}
        self._remote_size_tasks: dict[str, asyncio.Task] = {}
        self._load_persisted_stats()

    def load_config(self) -> dict[str, Any]:
        return load_library_config()

    def _active_libraries(self, cfg: Optional[dict[str, Any]] = None) -> list[LibraryDefinition]:
        cfg = cfg or self.load_config()
        active = [library for library in cfg["libraries"] if library.enabled]
        return active or cfg["libraries"]

    def _load_persisted_stats(self):
        path = _stats_cache_file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle) or {}
            remote_stats = data.get("remote_stats") or {}
            if isinstance(remote_stats, dict):
                self._stats_cache.update(remote_stats)
        except Exception:
            return

    def _persist_stats(self):
        payload = {
            "remote_stats": {
                key: value
                for key, value in self._stats_cache.items()
                if value.get("library_type") == "synology_filestation"
            }
        }
        path = _stats_cache_file_path()
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception:
            return

    def list_libraries(self) -> list[dict[str, Any]]:
        cfg = self.load_config()
        warning_free_gb = float(cfg["health_warning_free_gb"])
        result = []
        for library in self._active_libraries(cfg):
            health = self._health_for_library(library, warning_free_gb)
            result.append(
                {
                    "id": library.id,
                    "name": library.name,
                    "type": library.type,
                    "path": library.browse_root_path,
                    "root_path": library.root_path,
                    "browse_path": library.browse_path or "",
                    "browse_root_path": library.browse_root_path,
                    "web_url": build_synology_web_url(library.synology.base_url, library.root_path) if library.type == "synology_filestation" and library.synology else None,
                    "description": library.description,
                    "writable": library.writable,
                    "health": health,
                }
            )
        return result

    def get_library_definition(self, library_id: Optional[str] = None) -> LibraryDefinition:
        cfg = self.load_config()
        selected = library_id or cfg["default_library_id"]
        for library in self._active_libraries(cfg):
            if library.id == selected:
                return library
        return self._active_libraries(cfg)[0]

    def _library_from_payload(self, payload: dict[str, Any]) -> LibraryDefinition:
        library_type = (payload.get("type") or "local").lower()
        synology_payload = payload.get("synology") or {}
        if library_type == "synology_filestation":
            root_path = synology_payload.get("root_path") or payload.get("path") or "/"
            synology_payload = {
                **synology_payload,
                "root_path": root_path,
            }
        synology = SynologyConfig(**synology_payload) if library_type == "synology_filestation" else None
        return LibraryDefinition(
            id=payload.get("id") or "temp-library",
            name=payload.get("name") or payload.get("id") or "临时库存",
            type=library_type,
            path=(payload.get("path") or (synology.root_path if synology else "")),
            browse_path=payload.get("browse_path") or "",
            enabled=payload.get("enabled", True),
            writable=payload.get("writable", True),
            description=payload.get("description") or "",
            tags=payload.get("tags") or [],
            synology=synology,
        )

    def default_extract_library_id(self) -> str:
        cfg = self.load_config()
        extract_id = cfg["default_extract_library_id"]
        for library in self._active_libraries(cfg):
            if library.id == extract_id:
                return extract_id
        return self._active_libraries(cfg)[0].id

    def _health_for_library(self, library: LibraryDefinition, warning_free_gb: float) -> dict[str, Any]:
        if library.type == "local":
            if not library.root_path:
                return {"status": "error", "warnings": [], "errors": ["未配置路径"]}
            exists = os.path.exists(library.root_path)
            readable = exists and os.access(library.root_path, os.R_OK)
            writable = readable and os.access(library.root_path, os.W_OK)
            warnings: list[str] = []
            errors: list[str] = []
            free_gb = None
            total_gb = None
            if not readable:
                errors.append("路径不存在或不可读")
            else:
                try:
                    usage = shutil.disk_usage(library.root_path)
                    free_gb = _gb(usage.free)
                    total_gb = _gb(usage.total)
                    if warning_free_gb and usage.free < warning_free_gb * (1024 ** 3):
                        warnings.append(f"剩余空间低于 {warning_free_gb:.0f} GB")
                except Exception as exc:
                    warnings.append(f"无法读取磁盘空间: {exc}")
            status = "healthy"
            if errors:
                status = "error"
            elif warnings:
                status = "warning"
            return {
                "status": status,
                "warnings": warnings,
                "errors": errors,
                "is_accessible": readable,
                "is_writable": writable,
                "free_space_gb": free_gb,
                "total_space_gb": total_gb,
            }

        warnings = []
        errors = []
        accessible = bool(library.synology and library.synology.base_url and library.synology.username)
        if not accessible:
            errors.append("远程库配置不完整")
        status = "healthy"
        if errors:
            status = "error"
        elif warnings:
            status = "warning"
        return {
            "status": status,
            "warnings": warnings,
            "errors": errors,
            "is_accessible": accessible,
            "is_writable": accessible and library.writable,
            "free_space_gb": None,
            "total_space_gb": None,
        }

    async def list_files(self, library_id: Optional[str], page: int = 1, page_size: int = 200, search: str = "", current_path: Optional[str] = None) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._list_local_files, library, page, page_size, search, current_path)
        return await self._list_remote_files(library, page, page_size, search, current_path)

    def _list_local_files(self, library: LibraryDefinition, page: int, page_size: int, search: str, current_path: Optional[str]) -> dict[str, Any]:
        browse_root = os.path.abspath(library.browse_root_path or library.root_path)
        target_path = os.path.abspath(current_path or browse_root)
        if not os.path.exists(browse_root):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": browse_root, "browse_root_path": browse_root}
        if not (target_path == browse_root or target_path.startswith(browse_root + os.sep)):
            target_path = browse_root
        if not os.path.isdir(target_path):
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": target_path, "browse_root_path": browse_root}

        search_lower = search.lower().strip()
        items = []
        try:
            entries = list(os.scandir(target_path))
        except OSError:
            return {"files": [], "page": page, "page_size": page_size, "total": 0, "current_path": target_path, "browse_root_path": browse_root}

        for item_id, entry in enumerate(entries):
            if self._should_skip_entry(entry.name):
                continue
            rjcode = self._extract_rjcode(entry.name)
            if search_lower and search_lower not in entry.name.lower() and search_lower not in (rjcode or "").lower():
                continue
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            is_directory = entry.is_dir(follow_symlinks=False)
            items.append(
                {
                    "id": f"{library.id}:{item_id}",
                    "name": entry.name,
                    "path": entry.path,
                    "rjcode": rjcode,
                    "size": self._cached_path_size(entry.path) if is_directory else stat.st_size,
                    "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "unzip_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_directory": is_directory,
                    "library_id": library.id,
                    "library_name": library.name,
                    "_sort_time": stat.st_mtime,
                }
            )

        items = self._sort_local_items_by_size(items)
        total = len(items)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = items[start:end]
        for item in page_items:
            item.pop("_sort_time", None)
        return {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if target_path == browse_root else os.path.dirname(target_path),
        }

    async def _list_remote_files(self, library: LibraryDefinition, page: int, page_size: int, search: str) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("远程库存未配置群晖连接参数")

        client = SynologyFileStationClient(library.synology)
        offset = max(0, (page - 1) * page_size)
        if library.root_path in ("", "/"):
            data = await client.list_share(offset=offset, limit=page_size, sort_by="name", sort_direction="asc")
            raw_items = data.get("shares") or data.get("files") or []
        else:
            data = await client.list(library.root_path, offset=offset, limit=page_size, sort_by="mtime", sort_direction="desc")
            raw_items = data.get("files") or []
        files = []
        for index, item in enumerate(raw_items, start=offset):
            name = item.get("name") or ""
            if search and search.lower() not in name.lower():
                continue
            additional = item.get("additional", {}) or {}
            timestamp = additional.get("time", {}).get("mtime", int(time.time()))
            files.append(
                {
                    "id": f"{library.id}:{index}",
                    "name": name,
                    "path": item.get("path") or item.get("real_path") or name,
                    "rjcode": self._extract_rjcode(name),
                    "size": additional.get("size"),
                    "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "unzip_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "is_directory": item.get("isdir", True),
                    "library_id": library.id,
                    "library_name": library.name,
                }
            )
        return {
            "files": files,
            "page": page,
            "page_size": page_size,
            "total": data.get("total", len(files)),
        }

    async def folder_contents(self, library_id: str, path: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_folder_contents, library, path)
        raise RuntimeError("远程库暂不支持递归文件明细预览")

    def _local_folder_contents(self, library: LibraryDefinition, path: str) -> dict[str, Any]:
        library_root = os.path.abspath(library.root_path)
        target_path = os.path.abspath(path)
        if not (target_path == library_root or target_path.startswith(library_root + os.sep)):
            raise PermissionError("只能查看库存目录内的文件夹")
        if not os.path.isdir(target_path):
            raise FileNotFoundError("目标文件夹不存在")

        items = []
        item_id = 0
        for root, _, filenames in os.walk(target_path):
            for filename in filenames:
                if filename.startswith("."):
                    continue
                file_path = os.path.join(root, filename)
                stat = os.stat(file_path)
                relative_path = os.path.relpath(file_path, target_path).replace("\\", "/")
                items.append(
                    {
                        "id": f"{library.id}:content:{item_id}",
                        "name": filename,
                        "path": file_path,
                        "relative_path": relative_path,
                        "size": stat.st_size,
                        "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )
                item_id += 1
        items.sort(key=lambda item: item["relative_path"])
        return {
            "folder_name": os.path.basename(target_path),
            "folder_path": target_path,
            "total_files": len(items),
            "items": items,
        }

    async def rename(self, library_id: str, path: str, new_name: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_rename, library, path, new_name)
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        target_path = self._normalize_remote_path(path)
        if not self._remote_path_is_within_root(target_path, browse_root):
            raise PermissionError("只能重命名当前库存范围内的项目")
        client = SynologyFileStationClient(library.synology)
        await client.rename(target_path, new_name)
        new_path = str(PurePosixPath(target_path).parent / new_name)
        return {"message": "重命名成功", "new_path": new_path}

    def _local_rename(self, library: LibraryDefinition, path: str, new_name: str) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        parent_dir = os.path.dirname(path)
        new_path = os.path.join(parent_dir, new_name)
        os.rename(path, new_path)
        return {"message": "重命名成功", "new_path": new_path}

    async def delete(self, library_id: str, path: str, confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_delete, library, path, confirmed)
        if not confirmed:
            return {"need_confirm": True, "type": "remote", "name": PurePosixPath(path).name, "path": path, "size": None}
        client = SynologyFileStationClient(library.synology)
        await client.delete(path)
        return {"message": "删除成功", "path": path}

    def _local_delete(self, library: LibraryDefinition, path: str, confirmed: bool) -> dict[str, Any]:
        self._assert_local_path_in_library(library, path)
        if not confirmed:
            size = self._path_size(path)
            return {
                "need_confirm": True,
                "type": "folder" if os.path.isdir(path) else "file",
                "name": os.path.basename(path),
                "path": path,
                "size": size,
            }

        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return {"message": "删除成功", "path": path}

    async def batch_delete(self, library_id: str, paths: list[str], confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type != "local":
            raise RuntimeError("远程库暂不支持批量删除")
        return await asyncio.to_thread(self._local_batch_delete, library, paths, confirmed)

    def _local_batch_delete(self, library: LibraryDefinition, paths: list[str], confirmed: bool) -> dict[str, Any]:
        for path in paths:
            self._assert_local_path_in_library(library, path)
        if not confirmed:
            total_size = sum(self._path_size(path) for path in paths)
            return {"need_confirm": True, "total_count": len(paths), "total_size": total_size}
        success_count = 0
        failed_paths = []
        for path in paths:
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                success_count += 1
            except Exception as exc:
                failed_paths.append({"path": path, "error": str(exc)})
        return {"message": "批量删除完成", "success_count": success_count, "failed_paths": failed_paths}

    async def open_folder(self, library_id: str, path: str, force_local: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "synology_filestation":
            return {
                "message": "远程库存请使用群晖链接访问",
                "mode": "remote",
                "remote_url": library.synology.base_url if library.synology else "",
                "web_url": build_synology_web_url(library.synology.base_url, path) if library.synology else "",
                "path": path,
            }
        return {"message": "可直接打开", "mode": "direct", "path": path}

    async def test_connection(self, library_data: dict[str, Any]) -> dict[str, Any]:
        library = self._library_from_payload(library_data)
        health = self._health_for_library(library, warning_free_gb=0)
        if library.type == "local":
            return {
                "ok": health.get("is_accessible", False),
                "type": "local",
                "health": health,
                "message": "本地库存可访问" if health.get("is_accessible", False) else "本地库存不可访问",
            }

        if not library.synology:
            raise RuntimeError("远程库存缺少群晖连接参数")
        client = SynologyFileStationClient(library.synology)
        result = await client.test_connection(library.root_path)
        return {
            "ok": True,
            "type": "synology_filestation",
            "health": health,
            "device_id": result.get("device_id") or "",
            "web_url": result.get("web_url") or "",
            "message": "群晖连接成功",
        }

    async def ensure_stats(self, force: bool = False) -> dict[str, Any]:
        cfg = self.load_config()
        ttl = int(cfg["stats_cache_ttl_seconds"])
        for library in self._active_libraries(cfg):
            cached = self._stats_cache.get(library.id)
            expired = not cached or (time.time() - cached.get("updated_at", 0)) > ttl
            task = self._stats_tasks.get(library.id)
            should_refresh = force if library.type == "synology_filestation" else (force or expired)
            if should_refresh:
                if task is None or task.done():
                    self._stats_cache[library.id] = {
                        "library_id": library.id,
                        "library_name": library.name,
                        "library_type": library.type,
                        "status": "pending",
                        "folder_count": int((cached or {}).get("folder_count", 0) or 0),
                        "total_size_bytes": int((cached or {}).get("total_size_bytes", 0) or 0),
                        "total_size_gb": _gb(int((cached or {}).get("total_size_bytes", 0) or 0)),
                        "health": self._health_for_library(library, float(cfg["health_warning_free_gb"])),
                        "last_completed_at": (cached or {}).get("last_completed_at"),
                        "updated_at": time.time(),
                    }
                    task = asyncio.create_task(self._refresh_stats_for_library(library))
                    self._stats_tasks[library.id] = task

        libraries = []
        total_folders = 0
        total_bytes = 0
        warning_free_gb = float(cfg["health_warning_free_gb"])
        for library in self._active_libraries(cfg):
            cached = self._stats_cache.get(library.id)
            if not cached:
                cached = {
                    "library_id": library.id,
                    "library_name": library.name,
                    "library_type": library.type,
                    "status": "idle" if library.type == "synology_filestation" else "pending",
                    "folder_count": 0,
                    "total_size_bytes": 0,
                    "total_size_gb": 0,
                    "health": self._health_for_library(library, warning_free_gb),
                    "last_completed_at": None,
                }
            libraries.append(cached)
            total_folders += int(cached.get("folder_count", 0) or 0)
            total_bytes += int(cached.get("total_size_bytes", 0) or 0)

        return {
            "libraries": libraries,
            "all_libraries": {
                "folder_count": total_folders,
                "total_size_bytes": total_bytes,
                "total_size_gb": _gb(total_bytes),
            },
        }

    async def _refresh_stats_for_library(self, library: LibraryDefinition):
        if library.type == "local":
            stats = await asyncio.to_thread(self._collect_local_stats, library)
        else:
            stats = {
                "library_id": library.id,
                "library_name": library.name,
                "status": "unsupported",
                "folder_count": 0,
                "total_size_bytes": 0,
                "total_size_gb": 0,
                "warning": "远程库统计依赖群晖目录遍历，当前版本先返回实时健康信息",
            }
        health = self._health_for_library(library, float(self.load_config()["health_warning_free_gb"]))
        stats["health"] = health
        stats["updated_at"] = time.time()
        self._stats_cache[library.id] = stats

    def _collect_local_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        folder_count = 0
        total_size = 0
        for root, dirs, files in os.walk(library.root_path):
            folder_count += len(dirs)
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except OSError:
                    continue
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "ready",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
        }

    async def upload_directory_to_library(self, library_id: str, source_dir: str, relative_target_dir: Optional[str] = None) -> str:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._move_directory_to_local_library, library, source_dir, relative_target_dir)

        if not library.synology:
            raise RuntimeError("远程库存未配置群晖连接参数")
        client = SynologyFileStationClient(library.synology)
        target_root = PurePosixPath(library.root_path)
        if relative_target_dir:
            target_root = target_root / relative_target_dir

        await self._upload_directory_to_synology(client, source_dir, str(target_root))
        return str(target_root / os.path.basename(source_dir))

    def _move_directory_to_local_library(self, library: LibraryDefinition, source_dir: str, relative_target_dir: Optional[str]) -> str:
        target_root = library.root_path
        if relative_target_dir:
            target_root = os.path.join(target_root, relative_target_dir)
        os.makedirs(target_root, exist_ok=True)
        final_path = os.path.join(target_root, os.path.basename(source_dir))
        counter = 1
        while os.path.exists(final_path):
            final_path = os.path.join(target_root, f"{os.path.basename(source_dir)}_{counter}")
            counter += 1
        shutil.move(source_dir, final_path)
        return final_path

    async def _upload_directory_to_synology(self, client: SynologyFileStationClient, source_dir: str, remote_root: str):
        remote_root = remote_root.rstrip("/")
        await client.create_folder(str(PurePosixPath(remote_root).parent), PurePosixPath(remote_root).name)
        for root, dirs, files in os.walk(source_dir):
            relative = os.path.relpath(root, source_dir)
            remote_dir = remote_root if relative == "." else f"{remote_root}/{relative.replace(os.sep, '/')}"
            for directory in dirs:
                await client.create_folder(remote_dir, directory)
            for filename in files:
                await client.upload_file(remote_dir, os.path.join(root, filename))

    def _assert_local_path_in_library(self, library: LibraryDefinition, path: str):
        library_root = os.path.abspath(library.root_path)
        target_path = os.path.abspath(path)
        if not (target_path == library_root or target_path.startswith(library_root + os.sep)):
            raise PermissionError("目标路径不在当前库存目录中")

    def _path_size(self, path: str) -> int:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for filename in files:
                try:
                    total += os.path.getsize(os.path.join(root, filename))
                except OSError:
                    continue
        return total

    def _cached_path_size(self, path: str) -> int:
        try:
            stat = os.stat(path)
        except OSError:
            return 0

        if not os.path.isdir(path):
            return stat.st_size

        cache_key = os.path.abspath(path)
        current_signature = stat.st_mtime_ns
        cached = self._size_cache.get(cache_key)
        if cached and cached.get("signature") == current_signature:
            return int(cached.get("size", 0))

        size = self._path_size(path)
        self._size_cache[cache_key] = {
            "signature": current_signature,
            "size": size,
            "updated_at": time.time(),
        }
        return size

    def _sort_local_items_by_size(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda value: (
                -int(value.get("size") or 0),
                value.get("name", "").lower(),
                -float(value.get("_sort_time") or 0),
            ),
        )

    def _sort_remote_page_items_by_size(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            items,
            key=lambda value: (
                value.get("size") is None,
                -int(value.get("size") or 0),
                value.get("name", "").lower(),
                -float(value.get("_mtime") or 0),
            ),
        )

    def _should_skip_entry(self, name: str) -> bool:
        return name.startswith("_") or name.startswith(".") or name.lower() in {"#recycle", "@eadir"}

    def _normalize_remote_path(self, path: str) -> str:
        if not path:
            return "/"
        normalized = str(PurePosixPath(path))
        if normalized in {".", ""}:
            return "/"
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _remote_path_is_within_root(self, path: str, root_path: str) -> bool:
        normalized_path = self._normalize_remote_path(path)
        normalized_root = self._normalize_remote_path(root_path)
        if normalized_root == "/":
            return True
        return normalized_path == normalized_root or normalized_path.startswith(f"{normalized_root}/")

    def _resolve_remote_target_path(self, library: LibraryDefinition, current_path: Optional[str]) -> tuple[str, str]:
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        target_path = self._normalize_remote_path(current_path or browse_root)
        if not self._remote_path_is_within_root(target_path, browse_root):
            target_path = browse_root
        return browse_root, target_path

    def _remote_parent_path(self, path: str) -> str:
        normalized = self._normalize_remote_path(path)
        if normalized == "/":
            return "/"
        parent = str(PurePosixPath(normalized).parent)
        return "/" if parent in {".", ""} else parent

    async def _list_remote_directory(self, client: SynologyFileStationClient, folder_path: str) -> list[dict[str, Any]]:
        folder_path = self._normalize_remote_path(folder_path)
        chunk_size = 500
        offset = 0
        items: list[dict[str, Any]] = []
        while True:
            if folder_path == "/":
                data = await client.list_share(offset=offset, limit=chunk_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("shares") or data.get("files") or []
            else:
                data = await client.list(folder_path, offset=offset, limit=chunk_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("files") or []
            items.extend(raw_items)
            total = int(data.get("total", len(items)) or len(items))
            if not raw_items or len(items) >= total:
                break
            offset += len(raw_items)
        return items

    def _first_remote_info_item(self, data: dict[str, Any]) -> Optional[dict[str, Any]]:
        files = data.get("files") or []
        return files[0] if files else None

    async def _remote_collect_stats(self, client: SynologyFileStationClient, folder_path: str) -> tuple[int, int]:
        total_size = 0
        folder_count = 0
        for item in await self._list_remote_directory(client, folder_path):
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            additional = item.get("additional", {}) or {}
            child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
            timestamp = additional.get("time", {}).get("mtime")
            if item.get("isdir", False):
                folder_count += 1
                child_folders, child_size = await self._remote_collect_stats(client, child_path)
                folder_count += child_folders
                total_size += child_size
                self._size_cache[f"remote::{child_path}"] = {
                    "signature": timestamp,
                    "size": child_size,
                    "updated_at": time.time(),
                }
            else:
                total_size += int(additional.get("size") or 0)
        return folder_count, total_size

    async def _remote_collect_folder_count(self, client: SynologyFileStationClient, folder_path: str) -> int:
        total = 0
        for item in await self._list_remote_directory(client, folder_path):
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            if item.get("isdir", False):
                child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
                total += 1
                total += await self._remote_collect_folder_count(client, child_path)
        return total

    def _update_remote_stats_progress(
        self,
        library: LibraryDefinition,
        folder_count: int,
        total_size: int,
        completed: int,
        total: int,
        last_completed_at: Optional[float],
    ):
        progress_percent = round((completed / total) * 100, 2) if total else 100.0
        self._stats_cache[library.id] = {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "pending",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
            "progress_done": completed,
            "progress_total": total,
            "progress_percent": progress_percent,
            "health": self._health_for_library(library, float(self.load_config()["health_warning_free_gb"])),
            "last_completed_at": last_completed_at,
            "updated_at": time.time(),
        }

    async def _remote_path_size(
        self,
        client: SynologyFileStationClient,
        path: str,
        is_directory: bool,
        modified_ts: Optional[int] = None,
        initial_size: Optional[int] = None,
    ) -> int:
        normalized_path = self._normalize_remote_path(path)
        cache_key = f"remote::{normalized_path}"
        cached = self._size_cache.get(cache_key)
        if cached and modified_ts is not None and cached.get("signature") == modified_ts:
            return int(cached.get("size", 0))

        if is_directory:
            start_data = await client.start_dir_size(normalized_path)
            taskid = str(start_data.get("taskid") or start_data.get("task_id") or "")
            size = 0
            if taskid:
                deadline = time.time() + max(int(client.config.timeout), 30)
                while time.time() < deadline:
                    status_data = await client.dir_size_status(taskid)
                    size = self._extract_dir_size_value(status_data)
                    if self._dir_size_finished(status_data):
                        break
                    await asyncio.sleep(0.5)
        else:
            size = int(initial_size or 0)
            if not size:
                info = await client.stat(normalized_path)
                item = self._first_remote_info_item(info) or {}
                additional = item.get("additional", {}) or {}
                size = int(additional.get("size") or item.get("size") or 0)

        self._size_cache[cache_key] = {
            "signature": modified_ts,
            "size": size,
            "updated_at": time.time(),
        }
        return size

    def _dir_size_finished(self, data: dict[str, Any]) -> bool:
        for key in ("finished", "is_finished", "complete"):
            value = data.get(key)
            if isinstance(value, bool):
                return value
        if data.get("status") in {"finished", "done", "completed"}:
            return True
        if data.get("progress") == 100:
            return True
        return False

    def _extract_dir_size_value(self, data: dict[str, Any]) -> int:
        for key in ("total_size", "size"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return int(value)
        for key in ("result", "results", "files"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        nested = self._extract_dir_size_value(item)
                        if nested:
                            return nested
            elif isinstance(value, dict):
                nested = self._extract_dir_size_value(value)
                if nested:
                    return nested
        return 0

    def _get_remote_cached_size(self, path: str, modified_ts: Optional[int], is_directory: bool) -> tuple[Optional[int], str]:
        if not is_directory:
            return None, "ready"
        cache_key = f"remote::{self._normalize_remote_path(path)}"
        cached = self._size_cache.get(cache_key)
        if cached and modified_ts is not None and cached.get("signature") == modified_ts:
            return int(cached.get("size", 0)), "ready"
        if cached:
            return int(cached.get("size", 0)), "stale"
        return None, "pending"

    def _ensure_remote_size_task(self, library: LibraryDefinition, path: str, modified_ts: Optional[int]):
        cache_key = f"remote::{self._normalize_remote_path(path)}"
        running = self._remote_size_tasks.get(cache_key)
        if running and not running.done():
            return
        self._remote_size_tasks[cache_key] = asyncio.create_task(self._refresh_remote_path_size(library, path, modified_ts))

    async def _refresh_remote_path_size(self, library: LibraryDefinition, path: str, modified_ts: Optional[int]):
        try:
            if not library.synology:
                return
            client = SynologyFileStationClient(library.synology)
            await self._remote_path_size(client, path, True, modified_ts)
        except Exception:
            pass

    async def _remote_delete_preview(self, client: SynologyFileStationClient, path: str) -> dict[str, Any]:
        normalized_path = self._normalize_remote_path(path)
        info = await client.stat(normalized_path)
        item = self._first_remote_info_item(info)
        if not item:
            raise FileNotFoundError("鐩爣鏂囦欢涓嶅瓨鍦?")
        additional = item.get("additional", {}) or {}
        timestamp = additional.get("time", {}).get("mtime")
        is_directory = bool(item.get("isdir", False))
        size = await self._remote_path_size(
            client,
            normalized_path,
            is_directory,
            timestamp,
            initial_size=additional.get("size"),
        )
        return {
            "type": "folder" if is_directory else "file",
            "name": item.get("name") or PurePosixPath(normalized_path).name,
            "path": normalized_path,
            "size": size,
        }

    async def _list_remote_files(self, library: LibraryDefinition, page: int, page_size: int, search: str, current_path: Optional[str]) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("杩滅▼搴撳瓨鏈厤缃兢鏅栬繛鎺ュ弬鏁?")

        client = SynologyFileStationClient(library.synology)
        browse_root, target_path = self._resolve_remote_target_path(library, current_path)
        search_lower = search.lower().strip()
        if search_lower:
            raw_items = await self._list_remote_directory(client, target_path)
            items_with_index = list(enumerate(raw_items))
        else:
            offset = max(0, (page - 1) * page_size)
            if target_path == "/":
                data = await client.list_share(offset=offset, limit=page_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("shares") or data.get("files") or []
            else:
                data = await client.list(target_path, offset=offset, limit=page_size, sort_by="name", sort_direction="asc")
                raw_items = data.get("files") or []
            items_with_index = list(enumerate(raw_items, start=offset))
        files = []
        for index, item in items_with_index:
            name = item.get("name") or ""
            if self._should_skip_entry(name):
                continue
            rjcode = self._extract_rjcode(name)
            if search_lower and search_lower not in name.lower() and search_lower not in (rjcode or "").lower():
                continue
            additional = item.get("additional", {}) or {}
            timestamp = additional.get("time", {}).get("mtime", int(time.time()))
            files.append(
                {
                    "id": f"{library.id}:{index}",
                    "name": name,
                    "path": self._normalize_remote_path(item.get("path") or item.get("real_path") or name),
                    "rjcode": rjcode,
                    "size": additional.get("size"),
                    "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "unzip_time": datetime.fromtimestamp(timestamp).isoformat(),
                    "is_directory": item.get("isdir", True),
                    "library_id": library.id,
                    "library_name": library.name,
                    "_mtime": timestamp,
                }
            )
        if search_lower:
            total = len(files)
            start = max(0, (page - 1) * page_size)
            end = start + page_size
            page_items = files[start:end]
        else:
            total = int(data.get("total", len(files)) or len(files))
            page_items = files
        for item in page_items:
            is_directory = bool(item["is_directory"])
            cached_size, size_status = self._get_remote_cached_size(item["path"], item.get("_mtime"), is_directory)
            if is_directory:
                item["size"] = cached_size
                item["size_status"] = size_status
                if size_status != "ready":
                    self._ensure_remote_size_task(library, item["path"], item.get("_mtime"))
            else:
                item["size"] = int(item.get("size") or 0)
                item["size_status"] = "ready"
        page_items = self._sort_remote_page_items_by_size(page_items)
        for item in page_items:
            item.pop("_mtime", None)
        return {
            "files": page_items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "current_path": target_path,
            "browse_root_path": browse_root,
            "parent_path": None if target_path == browse_root else self._remote_parent_path(target_path),
        }

    async def _remote_folder_contents(self, library: LibraryDefinition, path: str) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("杩滅▼搴撳瓨鏈厤缃兢鏅栬繛鎺ュ弬鏁?")
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        target_path = self._normalize_remote_path(path)
        if not self._remote_path_is_within_root(target_path, browse_root):
            raise PermissionError("鍙兘鏌ョ湅褰撳墠搴撳瓨鑼冨洿鍐呯殑鏂囦欢澶?")

        client = SynologyFileStationClient(library.synology)
        info = await client.stat(target_path)
        info_item = self._first_remote_info_item(info)
        if not info_item or not info_item.get("isdir", False):
            raise FileNotFoundError("鐩爣鏂囦欢澶逛笉瀛樺湪")

        items: list[dict[str, Any]] = []
        counter = 0

        async def walk(folder_path: str):
            nonlocal counter
            children = await self._list_remote_directory(client, folder_path)
            for child in children:
                name = child.get("name") or ""
                if self._should_skip_entry(name):
                    continue
                child_path = self._normalize_remote_path(child.get("path") or child.get("real_path") or "")
                additional = child.get("additional", {}) or {}
                timestamp = additional.get("time", {}).get("mtime", int(time.time()))
                if child.get("isdir", False):
                    await walk(child_path)
                    continue
                relative_path = str(PurePosixPath(child_path).relative_to(PurePosixPath(target_path))).replace("\\", "/")
                items.append(
                    {
                        "id": f"{library.id}:content:{counter}",
                        "name": name,
                        "path": child_path,
                        "relative_path": relative_path,
                        "size": int(additional.get("size") or 0),
                        "modified_time": datetime.fromtimestamp(timestamp).isoformat(),
                    }
                )
                counter += 1

        await walk(target_path)
        items.sort(key=lambda item: item["relative_path"])
        return {
            "folder_name": PurePosixPath(target_path).name or target_path,
            "folder_path": target_path,
            "total_files": len(items),
            "items": items,
        }

    async def folder_contents(self, library_id: str, path: str) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_folder_contents, library, path)
        return await self._remote_folder_contents(library, path)

    async def delete(self, library_id: str, path: str, confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_delete, library, path, confirmed)
        if not library.synology:
            raise RuntimeError("杩滅▼搴撳瓨鏈厤缃兢鏅栬繛鎺ュ弬鏁?")
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path or "/")
        target_path = self._normalize_remote_path(path)
        if not self._remote_path_is_within_root(target_path, browse_root):
            raise PermissionError("鐩爣璺緞涓嶅湪褰撳墠搴撳瓨鑼冨洿鍐?")
        client = SynologyFileStationClient(library.synology)
        if not confirmed:
            preview = await self._remote_delete_preview(client, target_path)
            preview["need_confirm"] = True
            return preview
        await client.delete(target_path)
        return {"message": "鍒犻櫎鎴愬姛", "path": target_path}

    async def _remote_batch_delete(self, library: LibraryDefinition, paths: list[str], confirmed: bool) -> dict[str, Any]:
        client = SynologyFileStationClient(library.synology)
        if not confirmed:
            previews = await asyncio.gather(
                *(self._remote_delete_preview(client, path) for path in paths),
                return_exceptions=True,
            )
            total_size = 0
            for preview in previews:
                if isinstance(preview, Exception):
                    continue
                total_size += int(preview.get("size") or 0)
            return {"need_confirm": True, "total_count": len(paths), "total_size": total_size}

        success_count = 0
        failed_paths = []
        for path in paths:
            try:
                await client.delete(path)
                success_count += 1
            except Exception as exc:
                failed_paths.append({"path": path, "error": str(exc)})
        return {"message": "鎵归噺鍒犻櫎瀹屾垚", "success_count": success_count, "failed_paths": failed_paths}

    async def batch_delete(self, library_id: str, paths: list[str], confirmed: bool = False) -> dict[str, Any]:
        library = self.get_library_definition(library_id)
        if library.type == "local":
            return await asyncio.to_thread(self._local_batch_delete, library, paths, confirmed)
        if not library.synology:
            raise RuntimeError("杩滅▼搴撳瓨鏈厤缃兢鏅栬繛鎺ュ弬鏁?")
        browse_root = self._normalize_remote_path(library.browse_root_path or library.root_path)
        normalized_paths = [self._normalize_remote_path(path) for path in paths]
        for path in normalized_paths:
            if not self._remote_path_is_within_root(path, browse_root):
                raise PermissionError("鐩爣璺緞涓嶅湪褰撳墠搴撳瓨鑼冨洿鍐?")
        return await self._remote_batch_delete(library, normalized_paths, confirmed)

    def _collect_local_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        folder_count = 0
        total_size = 0
        target_root = os.path.abspath(library.browse_root_path or library.root_path)
        if not os.path.exists(target_root):
            return {
                "library_id": library.id,
                "library_name": library.name,
                "status": "ready",
                "folder_count": 0,
                "total_size_bytes": 0,
                "total_size_gb": 0,
            }
        for root, dirs, files in os.walk(target_root):
            folder_count += len(dirs)
            for filename in files:
                file_path = os.path.join(root, filename)
                try:
                    total_size += os.path.getsize(file_path)
                except OSError:
                    continue
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "ready",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
            "scan_mode": "manual_persisted",
        }

    async def _collect_remote_stats(self, library: LibraryDefinition) -> dict[str, Any]:
        if not library.synology:
            raise RuntimeError("杩滅▼搴撳瓨鏈厤缃兢鏅栬繛鎺ュ弬鏁?")
        client = SynologyFileStationClient(library.synology)
        start_path = self._normalize_remote_path(library.browse_root_path or library.root_path)
        top_level_items = [
            item for item in await self._list_remote_directory(client, start_path)
            if not self._should_skip_entry(item.get("name") or "")
        ]
        folder_count = 0
        total_size = 0
        completed = 0
        cached = self._stats_cache.get(library.id) or {}
        last_completed_at = cached.get("last_completed_at")
        self._update_remote_stats_progress(library, folder_count, total_size, completed, len(top_level_items), last_completed_at)
        for item in top_level_items:
            additional = item.get("additional", {}) or {}
            if item.get("isdir", False):
                child_path = self._normalize_remote_path(item.get("path") or item.get("real_path") or "")
                folder_count += 1
                folder_count += await self._remote_collect_folder_count(client, child_path)
                total_size += await self._remote_path_size(
                    client,
                    child_path,
                    True,
                    additional.get("time", {}).get("mtime"),
                    initial_size=additional.get("size"),
                )
            else:
                total_size += int(additional.get("size") or 0)
            completed += 1
            self._update_remote_stats_progress(library, folder_count, total_size, completed, len(top_level_items), last_completed_at)
        return {
            "library_id": library.id,
            "library_name": library.name,
            "library_type": library.type,
            "status": "ready",
            "folder_count": folder_count,
            "total_size_bytes": total_size,
            "total_size_gb": _gb(total_size),
            "scan_mode": "manual_persisted",
            "progress_done": completed,
            "progress_total": len(top_level_items),
            "progress_percent": 100.0,
        }

    async def _refresh_stats_for_library(self, library: LibraryDefinition):
        try:
            if library.type == "local":
                stats = await asyncio.to_thread(self._collect_local_stats, library)
            else:
                stats = await self._collect_remote_stats(library)
        except Exception as exc:
            stats = {
                "library_id": library.id,
                "library_name": library.name,
                "library_type": library.type,
                "status": "error",
                "folder_count": 0,
                "total_size_bytes": 0,
                "total_size_gb": 0,
                "warning": str(exc),
            }
        health = self._health_for_library(library, float(self.load_config()["health_warning_free_gb"]))
        stats["health"] = health
        stats["updated_at"] = time.time()
        stats["last_completed_at"] = time.time()
        self._stats_cache[library.id] = stats
        if library.type == "synology_filestation":
            self._persist_stats()

    def _extract_rjcode(self, value: str) -> Optional[str]:
        import re

        match = re.search(r"[RVB]J(\d{6}|\d{8})(?!\d)", value, re.IGNORECASE)
        return match.group(0).upper() if match else None


_library_manager: Optional[LibraryManager] = None


def get_library_manager() -> LibraryManager:
    global _library_manager
    if _library_manager is None:
        _library_manager = LibraryManager()
    return _library_manager
