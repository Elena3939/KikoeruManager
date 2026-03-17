import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config.settings import get_config

logger = logging.getLogger(__name__)


class BackupZipService:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._status = {
            "state": "idle",
            "running": False,
            "progress": 0,
            "step": "待机",
            "error": None,
            "started_at": None,
            "finished_at": None,
            "output_zip_path": "",
            "path_snapshot_dir": "",
            "logs": []
        }

    def _append_log(self, message: str):
        line = f"{datetime.now().strftime('%H:%M:%S')} {message}"
        self._status["logs"].append(line)
        if len(self._status["logs"]) > 300:
            self._status["logs"] = self._status["logs"][-300:]
        logger.info(f"[BackupZip] {message}")

    def _set_progress(self, progress: int, step: str):
        self._status["progress"] = max(0, min(100, int(progress)))
        self._status["step"] = step

    def get_status(self) -> dict:
        return dict(self._status)

    async def start(self) -> dict:
        if self._task and not self._task.done():
            raise RuntimeError("库存打包任务正在执行中")

        self._status = {
            "state": "running",
            "running": True,
            "progress": 0,
            "step": "准备开始",
            "error": None,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "output_zip_path": "",
            "path_snapshot_dir": "",
            "logs": []
        }
        self._append_log("任务已创建")
        self._task = asyncio.create_task(self._run())
        return self.get_status()

    async def cancel(self) -> dict:
        if not self._task or self._task.done():
            return self.get_status()

        self._append_log("收到取消请求")
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        return self.get_status()

    async def _run(self):
        try:
            config = get_config()
            backup_config = config.backup_zip
            source_path = os.path.abspath((backup_config.source_path or config.storage.library_path).strip())
            if not source_path:
                raise RuntimeError("库存路径未配置")
            if not os.path.isdir(source_path):
                raise RuntimeError(f"库存路径不存在: {source_path}")

            output_dir = os.path.abspath((backup_config.output_dir or source_path).strip())
            os.makedirs(output_dir, exist_ok=True)

            date_str = datetime.now().strftime("%Y%m%d")
            archive_format = (backup_config.archive_format or "zip").lower()
            if archive_format not in {"zip", "7z"}:
                raise RuntimeError(f"不支持的压缩格式: {archive_format}")
            compression_level = max(1, min(9, int(backup_config.compression_level or 9)))

            if backup_config.copy_structure_before_zip:
                self._set_progress(8, "复制目录结构")
                snapshot_base_dir = os.path.abspath((backup_config.path_copy_target or output_dir).strip())
                os.makedirs(snapshot_base_dir, exist_ok=True)
                copied_count = await asyncio.to_thread(self._copy_structure_direct, source_path, snapshot_base_dir)
                self._status["path_snapshot_dir"] = snapshot_base_dir
                self._append_log(f"目录结构复制完成，共 {copied_count} 个目录")
            else:
                self._append_log("已跳过目录结构复制")

            self._set_progress(20, "准备压缩")

            password = (backup_config.password or "").strip()
            if not password:
                raise RuntimeError("压缩密码不能为空")

            archive_path = self._unique_path(os.path.join(output_dir, f"ASMR_{date_str}.{archive_format}"))
            self._status["output_zip_path"] = archive_path

            seven_zip = self._find_7z_executable(config.extract.seven_zip_path)
            self._append_log(f"使用 7z: {seven_zip}")

            source_parent = str(Path(source_path).parent)
            source_name = Path(source_path).name

            cmd = [
                seven_zip,
                "a",
                f"-t{archive_format}",
                f"-mx={compression_level}",
                "-mfb=258",
                "-mpass=15",
                "-mmt=on" if backup_config.compression_threads <= 0 else f"-mmt={backup_config.compression_threads}",
                "-bb1",
                "-bsp1",
                "-bso1",
                "-bse1",
                "-y",
                f"-p{password}",
                archive_path,
                source_name
            ]
            if archive_format == "zip":
                cmd.append("-mem=ZipCrypto")
            else:
                cmd.append("-mhe=on")

            self._set_progress(25, "开始压缩")
            self._append_log(f"压缩格式: {archive_format}，压缩强度: {compression_level}")
            self._append_log(f"输出文件: {archive_path}")
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=source_parent,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout_task = asyncio.create_task(self._consume_stream(self._process.stdout, is_error=False))
            stderr_task = asyncio.create_task(self._consume_stream(self._process.stderr, is_error=True))

            return_code = await self._process.wait()
            await stdout_task
            await stderr_task
            self._process = None

            if return_code != 0:
                if os.path.exists(archive_path):
                    try:
                        os.remove(archive_path)
                    except Exception:
                        pass
                raise RuntimeError(f"7z 执行失败，返回码: {return_code}")

            self._set_progress(100, "完成")
            self._status["running"] = False
            self._status["state"] = "completed"
            self._status["finished_at"] = datetime.now().isoformat()
            self._append_log("压缩完成")
        except asyncio.CancelledError:
            self._status["running"] = False
            self._status["state"] = "cancelled"
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "已取消")
            self._append_log("任务已取消")
            raise
        except Exception as exc:
            self._status["running"] = False
            self._status["state"] = "failed"
            self._status["error"] = str(exc)
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "失败")
            self._append_log(f"任务失败: {exc}")

    async def _consume_stream(self, stream: Optional[asyncio.StreamReader], is_error: bool):
        if not stream:
            return
        buffer = ""
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="ignore").replace("\r", "\n")
            buffer += text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                self._parse_progress_line(line.strip(), is_error)
        if buffer.strip():
            self._parse_progress_line(buffer.strip(), is_error)

    def _parse_progress_line(self, line: str, is_error: bool):
        if not line:
            return
        if is_error:
            self._append_log(f"[stderr] {line}")
        else:
            percent_match = re.search(r"(\d{1,3})%", line)
            if percent_match:
                raw = int(percent_match.group(1))
                mapped = 25 + int(max(0, min(100, raw)) * 0.74)
                self._set_progress(min(99, mapped), "压缩中")
            if line.startswith("Error") or "Error:" in line:
                self._append_log(line)
            elif line.startswith("WARN") or line.startswith("Warning"):
                self._append_log(line)

    def _copy_structure_direct(self, source: str, target: str) -> int:
        os.makedirs(target, exist_ok=True)
        dir_count = 0
        for root, dirs, _ in os.walk(source):
            rel = os.path.relpath(root, source)
            mapped = target if rel == "." else os.path.join(target, rel)
            if not os.path.exists(mapped):
                os.makedirs(mapped, exist_ok=True)
            dir_count += 1
            for directory in dirs:
                child = os.path.join(mapped, directory)
                if not os.path.exists(child):
                    os.makedirs(child, exist_ok=True)
        return dir_count

    def _unique_path(self, desired_path: str) -> str:
        if not os.path.exists(desired_path):
            return desired_path
        path_obj = Path(desired_path)
        stem = path_obj.stem
        suffix = path_obj.suffix
        parent = path_obj.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return str(candidate)
            counter += 1

    def _find_7z_executable(self, configured_path: str) -> str:
        configured = (configured_path or "").strip()
        if configured and configured != "7z" and os.path.exists(configured):
            return configured
        from shutil import which
        in_path = which("7z")
        if in_path:
            return in_path
        default_candidates = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ]
        for candidate in default_candidates:
            if os.path.exists(candidate):
                return candidate
        raise RuntimeError("找不到 7z 可执行文件，请在解压配置中设置 7z 路径")


_backup_zip_service: Optional[BackupZipService] = None


def get_backup_zip_service() -> BackupZipService:
    global _backup_zip_service
    if _backup_zip_service is None:
        _backup_zip_service = BackupZipService()
    return _backup_zip_service
