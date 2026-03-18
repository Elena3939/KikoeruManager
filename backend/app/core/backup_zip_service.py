import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from ..config.settings import get_config
from ..models.database import get_db, BackupRecord

logger = logging.getLogger(__name__)

# ── 7z 参数优化查找表 ──────────────────────────────────────────
# 格式: (mfb, mpass, dictionary_size, solid_mode)
_7Z_PARAMS = {
    # level 1-3: 快速
    1: (32, 1, "4m", False), 2: (32, 1, "4m", False), 3: (32, 1, "4m", False),
    # level 4-5: 均衡
    4: (64, 1, "16m", False), 5: (64, 1, "16m", False),
    # level 6-7: 高压缩
    6: (64, 3, "32m", True), 7: (64, 3, "32m", True),
    # level 8-9: 极限
    8: (128, 5, "64m", True), 9: (128, 5, "64m", True),
}

_ZIP_PARAMS = {
    1: (32, 1), 2: (32, 1), 3: (32, 1),
    4: (64, 1), 5: (64, 1),
    6: (128, 3), 7: (128, 3),
    8: (128, 7), 9: (128, 7),
}

IO_BUFFER_SIZE = 65536  # 64KB, 比原来的 4KB 大幅减少 syscall 开销
SPEED_WINDOW_SIZE = 30  # 滑动窗口最大采样数
SPEED_WINDOW_MIN_SECONDS = 3.0  # 窗口最小时间跨度


class BackupZipService:
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._status = self._make_idle_status()
        self._start_time: Optional[datetime] = None
        self._last_update_time: float = 0
        self._pre_size: int = 0
        self._backup_start_time: Optional[datetime] = None
        self._backup_end_time: Optional[datetime] = None
        # 滑动窗口速度采样: deque of (timestamp, processed_bytes)
        self._speed_samples: deque = deque(maxlen=SPEED_WINDOW_SIZE)
        # 断点续传状态
        self._checkpoint_id: Optional[str] = None
        self._file_manifest: List[Dict] = []
        self._chunks: List[List[Dict]] = []
        self._completed_chunks: List[str] = []
        self._current_chunk_index: int = 0

    # ── 状态管理 ──────────────────────────────────────────────

    @staticmethod
    def _make_idle_status() -> dict:
        return {
            "state": "idle",
            "running": False,
            "progress": 0,
            "step": "待机",
            "error": None,
            "started_at": None,
            "finished_at": None,
            "output_zip_path": "",
            "path_snapshot_dir": "",
            "logs": [],
            "speed": "0 MB/s",
            "eta": "未知",
            "processed_bytes": 0,
            "total_bytes": 0,
            "has_checkpoint": False,
        }

    def _append_log(self, message: str):
        line = f"{datetime.now().strftime('%H:%M:%S')} {message}"
        self._status["logs"].append(line)
        if len(self._status["logs"]) > 300:
            self._status["logs"] = self._status["logs"][-300:]
        logger.info(f"[BackupZip] {message}")

    def _set_progress(self, progress: int, step: str, speed: str = "", eta: str = ""):
        self._status["progress"] = max(0, min(100, int(progress)))
        self._status["step"] = step
        self._status["speed"] = speed if speed else "计算中..."
        self._status["eta"] = eta if eta else "计算中..."

    def get_status(self) -> dict:
        status = dict(self._status)
        status["has_checkpoint"] = self._has_interrupted_checkpoint()
        return status

    # ── 滑动窗口速度/ETA 计算 ─────────────────────────────────

    def _record_speed_sample(self, processed_bytes: int):
        """记录一个速度采样点"""
        self._speed_samples.append((time.monotonic(), processed_bytes))
        self._status["processed_bytes"] = processed_bytes

    def _calc_speed_and_eta(self, raw_percent: int) -> Tuple[str, str]:
        """基于滑动窗口计算瞬时速度和剩余时间"""
        if len(self._speed_samples) < 2:
            return "", ""

        newest_time, newest_bytes = self._speed_samples[-1]
        oldest_time, oldest_bytes = self._speed_samples[0]
        time_span = newest_time - oldest_time

        # 窗口时间不足时回退到累积平均
        if time_span < SPEED_WINDOW_MIN_SECONDS and self._start_time:
            elapsed = (datetime.now() - self._start_time).total_seconds()
            if elapsed > 0 and newest_bytes > 0:
                speed = newest_bytes / elapsed
            else:
                return "", ""
        else:
            byte_delta = newest_bytes - oldest_bytes
            if time_span <= 0 or byte_delta <= 0:
                return "", ""
            speed = byte_delta / time_span

        # 格式化速度
        if speed > 1024 * 1024:
            speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
        elif speed > 1024:
            speed_str = f"{speed / 1024:.2f} KB/s"
        else:
            speed_str = f"{speed:.0f} B/s"

        # 计算 ETA
        eta_str = ""
        total_bytes = self._status.get("total_bytes", 0)
        if raw_percent > 0 and total_bytes > 0 and speed > 0:
            remaining_bytes = total_bytes * (100 - raw_percent) / 100
            remaining_seconds = remaining_bytes / speed
            if remaining_seconds > 0:
                remaining_seconds = int(remaining_seconds)
                m, s = divmod(remaining_seconds, 60)
                h, m = divmod(m, 60)
                eta_str = f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        return speed_str, eta_str

    # ── 7z 参数构建 ──────────────────────────────────────────

    @staticmethod
    def _build_7z_params(archive_format: str, compression_level: int,
                         threads: int, password: str, archive_path: str,
                         dictionary_size_mb: int = 0, solid_archive: bool = True) -> list:
        """根据格式和级别构建优化的 7z 命令参数"""
        cmd = ["a", f"-t{archive_format}", f"-mx={compression_level}"]

        if archive_format == "7z":
            mfb, mpass, md, ms = _7Z_PARAMS.get(compression_level, (64, 3, "32m", True))
            if dictionary_size_mb > 0:
                md = f"{dictionary_size_mb}m"
            cmd += [f"-mfb={mfb}", f"-mpass={mpass}", f"-md={md}"]
            if ms and solid_archive:
                cmd.append("-ms=on")
        else:
            mfb, mpass = _ZIP_PARAMS.get(compression_level, (64, 3))
            cmd += [f"-mfb={mfb}", f"-mpass={mpass}"]

        # 显式线程数：0 → 使用全部 CPU
        thread_count = threads if threads > 0 else (os.cpu_count() or 4)
        cmd.append(f"-mmt={thread_count}")

        cmd += ["-bb1", "-bsp1", "-bso1", "-bse1", "-y", f"-p{password}"]

        if archive_format == "zip":
            cmd.append("-mem=ZipCrypto")
        else:
            cmd.append("-mhe=on")

        cmd.append(archive_path)
        return cmd

    # ── 任务控制 ──────────────────────────────────────────────

    async def start(self) -> dict:
        if self._task and not self._task.done():
            raise RuntimeError("库存打包任务正在执行中")

        self._status = {
            "state": "running", "running": True, "progress": 0,
            "step": "准备开始", "error": None,
            "started_at": datetime.now().isoformat(), "finished_at": None,
            "output_zip_path": "", "path_snapshot_dir": "",
            "logs": [], "speed": "0 MB/s", "eta": "未知",
            "processed_bytes": 0, "total_bytes": 0, "has_checkpoint": False,
        }
        self._start_time = datetime.now()
        self._last_update_time = 0
        self._speed_samples.clear()
        self._completed_chunks = []
        self._current_chunk_index = 0
        self._checkpoint_id = None
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

        # 保存断点
        self._save_checkpoint("interrupted")

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        return self.get_status()

    async def resume(self) -> dict:
        """从断点恢复压缩任务"""
        if self._task and not self._task.done():
            raise RuntimeError("库存打包任务正在执行中")

        checkpoint = self._load_checkpoint()
        if not checkpoint:
            raise RuntimeError("没有可恢复的断点")

        self._status = {
            "state": "running", "running": True,
            "progress": 0, "step": "恢复中...",
            "error": None,
            "started_at": datetime.now().isoformat(), "finished_at": None,
            "output_zip_path": checkpoint.get("archive_path", ""),
            "path_snapshot_dir": "", "logs": [],
            "speed": "0 MB/s", "eta": "未知",
            "processed_bytes": checkpoint.get("processed_bytes", 0),
            "total_bytes": checkpoint.get("total_bytes", 0),
            "has_checkpoint": False,
        }
        self._start_time = datetime.now()
        self._last_update_time = 0
        self._speed_samples.clear()
        self._checkpoint_id = checkpoint["id"]
        self._completed_chunks = checkpoint.get("completed_chunks", [])
        self._current_chunk_index = checkpoint.get("current_chunk_index", 0)
        self._file_manifest = checkpoint.get("file_manifest", [])
        self._pre_size = checkpoint.get("total_bytes", 0)
        self._append_log(f"从断点恢复，已完成 {len(self._completed_chunks)} 个块")
        self._task = asyncio.create_task(self._run_resume(checkpoint))
        return self.get_status()

    def get_checkpoint_info(self) -> Optional[dict]:
        """获取当前断点信息"""
        return self._load_checkpoint()

    # ── 核心压缩流程 ─────────────────────────────────────────

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

            last_backup_time = self._get_last_backup_end_time()
            self._backup_start_time = last_backup_time
            self._backup_end_time = datetime.now()

            start_date_str = self._backup_start_time.strftime("%Y%m%d")
            end_date_str = self._backup_end_time.strftime("%Y%m%d")
            date_range_str = end_date_str if start_date_str == end_date_str else f"{start_date_str}-{end_date_str}"

            archive_format = (backup_config.archive_format or "zip").lower()
            if archive_format not in {"zip", "7z"}:
                raise RuntimeError(f"不支持的压缩格式: {archive_format}")
            compression_level = max(1, min(9, int(backup_config.compression_level or 9)))

            # 计算压缩前大小
            self._set_progress(0, "计算库存大小")
            self._pre_size = await asyncio.to_thread(self._get_dir_size, source_path)
            self._status["total_bytes"] = self._pre_size
            pre_size_gb = self._pre_size / (1024 * 1024 * 1024)
            self._append_log(f"待压缩库存大小: {pre_size_gb:.2f} GB")

            # 构建文件清单（用于断点续传）
            self._set_progress(0, "构建文件清单")
            self._file_manifest = await asyncio.to_thread(self._build_manifest, source_path)
            self._append_log(f"文件清单: {len(self._file_manifest)} 个文件")

            if backup_config.copy_structure_before_zip:
                self._set_progress(0, "复制目录结构")
                snapshot_base_dir = os.path.abspath((backup_config.path_copy_target or output_dir).strip())
                os.makedirs(snapshot_base_dir, exist_ok=True)
                copied_count = await asyncio.to_thread(self._copy_structure_direct, source_path, snapshot_base_dir)
                self._status["path_snapshot_dir"] = snapshot_base_dir
                self._append_log(f"目录结构复制完成，共 {copied_count} 个目录")
            else:
                self._append_log("已跳过目录结构复制")

            self._set_progress(0, "准备压缩")

            password = (backup_config.password or "").strip()
            if not password:
                raise RuntimeError("压缩密码不能为空")

            archive_path = self._unique_path(os.path.join(output_dir, f"ASMR_{date_range_str}.{archive_format}"))
            self._status["output_zip_path"] = archive_path

            seven_zip = self._find_7z_executable(config.extract.seven_zip_path)
            self._append_log(f"使用 7z: {seven_zip}")

            source_parent = str(Path(source_path).parent)
            source_name = Path(source_path).name

            # 分块
            self._chunks = self._split_into_chunks(self._file_manifest)
            total_chunks = len(self._chunks)
            self._append_log(f"分为 {total_chunks} 个压缩块")

            # 创建断点记录
            self._checkpoint_id = str(uuid.uuid4())
            self._save_checkpoint("in_progress", archive_path=archive_path,
                                  source_path=source_path, output_dir=output_dir,
                                  archive_format=archive_format,
                                  compression_level=compression_level,
                                  password=password)

            dict_size_mb = getattr(backup_config, 'dictionary_size_mb', 0)
            solid = getattr(backup_config, 'solid_archive', True)

            # 逐块压缩
            await self._compress_chunks(
                seven_zip, archive_format, compression_level,
                backup_config.compression_threads, password,
                archive_path, source_parent, source_name,
                dict_size_mb, solid, total_chunks
            )

            await self._finalize_success(archive_path, source_path)

        except asyncio.CancelledError:
            self._status["running"] = False
            self._status["state"] = "cancelled"
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "已取消")
            self._append_log("任务已取消")
            raise
        except Exception as exc:
            self._save_checkpoint("interrupted")
            self._status["running"] = False
            self._status["state"] = "failed"
            self._status["error"] = str(exc)
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "失败")
            self._append_log(f"任务失败: {exc}")

    async def _run_resume(self, checkpoint: dict):
        """从断点恢复压缩"""
        try:
            config = get_config()
            backup_config = config.backup_zip
            source_path = checkpoint["source_path"]
            archive_path = checkpoint["archive_path"]
            archive_format = checkpoint["archive_format"]
            compression_level = checkpoint["compression_level"]
            password = (backup_config.password or "").strip()

            if not password:
                raise RuntimeError("压缩密码不能为空")

            # 校验密码一致性
            pw_hash = hashlib.sha256(password.encode()).hexdigest()
            if pw_hash != checkpoint.get("password_hash"):
                raise RuntimeError("密码与断点记录不一致，无法恢复")

            # 校验文件清单
            current_manifest = await asyncio.to_thread(self._build_manifest, source_path)
            if not self._validate_manifest(self._file_manifest, current_manifest):
                self._append_log("警告: 部分文件已变更，将重新压缩变更的块")

            self._status["output_zip_path"] = archive_path
            seven_zip = self._find_7z_executable(config.extract.seven_zip_path)
            source_parent = str(Path(source_path).parent)
            source_name = Path(source_path).name

            self._chunks = self._split_into_chunks(self._file_manifest)
            total_chunks = len(self._chunks)

            dict_size_mb = getattr(backup_config, 'dictionary_size_mb', 0)
            solid = getattr(backup_config, 'solid_archive', True)

            # 跳过已完成的块
            skip_count = len(self._completed_chunks)
            self._current_chunk_index = skip_count
            base_progress = 10 + int(skip_count / total_chunks * 89) if total_chunks > 0 else 10
            self._set_progress(base_progress, f"恢复中，跳过 {skip_count} 个已完成块")

            await self._compress_chunks(
                seven_zip, archive_format, compression_level,
                backup_config.compression_threads, password,
                archive_path, source_parent, source_name,
                dict_size_mb, solid, total_chunks
            )

            await self._finalize_success(archive_path, source_path)

        except asyncio.CancelledError:
            self._status["running"] = False
            self._status["state"] = "cancelled"
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "已取消")
            self._append_log("任务已取消")
            raise
        except Exception as exc:
            self._save_checkpoint("interrupted")
            self._status["running"] = False
            self._status["state"] = "failed"
            self._status["error"] = str(exc)
            self._status["finished_at"] = datetime.now().isoformat()
            self._set_progress(self._status["progress"], "失败")
            self._append_log(f"恢复任务失败: {exc}")

    async def _compress_chunks(self, seven_zip: str, archive_format: str,
                               compression_level: int, threads: int,
                               password: str, archive_path: str,
                               source_parent: str, source_name: str,
                               dict_size_mb: int, solid: bool,
                               total_chunks: int):
        """逐块执行压缩，支持断点续传"""
        if total_chunks <= 1:
            # 单块模式：直接压缩整个目录（兼容原有行为）
            cmd_args = self._build_7z_params(
                archive_format, compression_level, threads, password,
                archive_path, dict_size_mb, solid
            )
            cmd = [seven_zip] + cmd_args + [source_name]

            self._set_progress(0, "开始压缩")
            self._append_log(f"压缩格式: {archive_format}，压缩强度: {compression_level}")
            self._append_log(f"输出文件: {archive_path}")

            return_code = await self._run_7z(cmd, source_parent)
            if return_code != 0:
                self._cleanup_file(archive_path)
                raise RuntimeError(f"7z 执行失败，返回码: {return_code}")
            return

        # 多块模式
        for i in range(self._current_chunk_index, total_chunks):
            self._current_chunk_index = i
            chunk = self._chunks[i]
            chunk_progress_base = 10 + int(i / total_chunks * 89)

            # 创建临时文件列表
            listfile_path = os.path.join(source_parent, f".backup_chunk_{i}.txt")
            try:
                with open(listfile_path, "w", encoding="utf-8") as f:
                    for item in chunk:
                        f.write(os.path.join(source_name, item["path"]) + "\n")

                cmd_args = self._build_7z_params(
                    archive_format, compression_level, threads, password,
                    archive_path, dict_size_mb, solid
                )
                cmd = [seven_zip] + cmd_args + [f"@{listfile_path}"]

                self._set_progress(chunk_progress_base, f"压缩块 {i+1}/{total_chunks}")
                self._append_log(f"压缩块 {i+1}/{total_chunks}，{len(chunk)} 个文件")

                return_code = await self._run_7z(cmd, source_parent)
                if return_code != 0:
                    raise RuntimeError(f"7z 块 {i+1} 执行失败，返回码: {return_code}")

                self._completed_chunks.append(f"chunk_{i}")
                self._save_checkpoint("in_progress")
            finally:
                if os.path.exists(listfile_path):
                    try:
                        os.remove(listfile_path)
                    except Exception:
                        pass

    async def _run_7z(self, cmd: list, cwd: str) -> int:
        """执行 7z 子进程并解析输出"""
        self._process = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_task = asyncio.create_task(self._consume_stream(self._process.stdout, False))
        stderr_task = asyncio.create_task(self._consume_stream(self._process.stderr, True))
        return_code = await self._process.wait()
        await stdout_task
        await stderr_task
        self._process = None
        return return_code

    async def _finalize_success(self, archive_path: str, source_path: str):
        """压缩完成后的收尾工作"""
        self._set_progress(100, "完成")
        self._status["running"] = False
        self._status["state"] = "completed"
        self._status["finished_at"] = datetime.now().isoformat()

        now = datetime.now()
        total_elapsed = (now - self._start_time).total_seconds()
        m, s = divmod(int(total_elapsed), 60)
        h, m = divmod(m, 60)
        duration_str = f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

        try:
            out_size = os.path.getsize(archive_path)
            size_str = f"{out_size / (1024**3):.2f} GB" if out_size > 1024**3 else f"{out_size / (1024**2):.2f} MB"
            avg_speed = out_size / total_elapsed if total_elapsed > 0 else 0
            avg_speed_str = f"{avg_speed / (1024**2):.2f} MB/s" if avg_speed > 1024**2 else f"{avg_speed / 1024:.2f} KB/s"
            ratio = out_size / self._pre_size if self._pre_size > 0 else 0

            self._append_log(f"压缩完成！耗时: {duration_str}, 大小: {size_str}, 平均速度: {avg_speed_str}, 压缩率: {ratio*100:.2f}%")

            self._save_backup_record(
                filename=os.path.basename(archive_path),
                output_path=archive_path, source_path=source_path,
                pre_size=self._pre_size, post_size=out_size,
                duration=int(total_elapsed), speed_avg=avg_speed_str, ratio=ratio
            )
        except Exception as e:
            logger.error(f"保存备份记录失败: {e}")
            self._append_log(f"压缩完成！耗时: {duration_str}")

        # 清理断点
        self._delete_checkpoint()

    # ── 流解析 ────────────────────────────────────────────────

    async def _consume_stream(self, stream: Optional[asyncio.StreamReader], is_error: bool):
        if not stream:
            return
        buffer = ""
        while True:
            chunk = await stream.read(IO_BUFFER_SIZE)
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
            return

        percent_match = re.search(r"(\d{1,3})%", line)
        if percent_match:
            raw_percent = int(percent_match.group(1))

            # 7z -bsp1 只输出百分比，不输出字节数
            # 用百分比反推已处理字节数
            total_bytes = self._status.get("total_bytes", 0)
            if total_bytes > 0:
                estimated_bytes = int(total_bytes * raw_percent / 100)
                self._record_speed_sample(estimated_bytes)

            # 1 秒节流
            current_time = time.monotonic()
            if current_time - self._last_update_time >= 1.0 or raw_percent == 100:
                self._last_update_time = current_time
                speed_str, eta_str = self._calc_speed_and_eta(raw_percent)
                # 进度条直接使用 7z 百分比，但不低于预处理阶段的进度（防止回跳）
                current_progress = self._status.get("progress", 0)
                new_progress = max(current_progress, min(99, raw_percent))
                self._set_progress(new_progress, f"压缩中 {raw_percent}%", speed_str, eta_str)

        if line.startswith("Error") or "Error:" in line:
            self._append_log(line)
        elif line.startswith("WARN") or line.startswith("Warning"):
            self._append_log(line)

    # ── 文件清单与分块 ────────────────────────────────────────

    @staticmethod
    def _build_manifest(source_path: str) -> List[Dict]:
        """遍历目录构建文件清单"""
        manifest = []
        for root, _, files in os.walk(source_path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    stat = os.stat(fp)
                    manifest.append({
                        "path": os.path.relpath(fp, source_path),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
                except OSError:
                    pass
        return manifest

    @staticmethod
    def _split_into_chunks(manifest: List[Dict], chunk_size: int = 2 * 1024 * 1024 * 1024) -> List[List[Dict]]:
        """按累积大小将文件清单分块，每块不超过 chunk_size 字节"""
        if not manifest:
            return [[]]
        total_size = sum(f["size"] for f in manifest)
        if total_size <= chunk_size:
            return [manifest]

        chunks = []
        current_chunk = []
        current_size = 0
        for item in manifest:
            current_chunk.append(item)
            current_size += item["size"]
            if current_size >= chunk_size:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    @staticmethod
    def _validate_manifest(old_manifest: List[Dict], new_manifest: List[Dict]) -> bool:
        """校验文件清单是否一致"""
        old_map = {f["path"]: (f["size"], f["mtime"]) for f in old_manifest}
        new_map = {f["path"]: (f["size"], f["mtime"]) for f in new_manifest}
        return old_map == new_map

    # ── 断点持久化 ────────────────────────────────────────────

    def _save_checkpoint(self, state: str, archive_path: str = "",
                         source_path: str = "", output_dir: str = "",
                         archive_format: str = "", compression_level: int = 0,
                         password: str = ""):
        """保存断点到数据库"""
        if not self._checkpoint_id:
            return
        from ..models.database import BackupCheckpoint
        db = next(get_db())
        try:
            existing = db.query(BackupCheckpoint).filter_by(id=self._checkpoint_id).first()
            if existing:
                existing.state = state
                existing.completed_chunks = json.dumps(self._completed_chunks)
                existing.current_chunk_index = self._current_chunk_index
                existing.processed_files = sum(len(c) for c in self._chunks[:self._current_chunk_index]) if self._chunks else 0
                existing.processed_bytes = self._status.get("processed_bytes", 0)
                existing.updated_at = datetime.now()
            else:
                pw_hash = hashlib.sha256(password.encode()).hexdigest() if password else ""
                record = BackupCheckpoint(
                    id=self._checkpoint_id,
                    source_path=source_path or self._status.get("output_zip_path", ""),
                    output_dir=output_dir,
                    archive_path=archive_path or self._status.get("output_zip_path", ""),
                    archive_format=archive_format,
                    compression_level=compression_level,
                    password_hash=pw_hash,
                    file_manifest=json.dumps(self._file_manifest),
                    completed_chunks=json.dumps(self._completed_chunks),
                    current_chunk_index=self._current_chunk_index,
                    total_chunks=len(self._chunks),
                    total_files=len(self._file_manifest),
                    processed_files=0,
                    total_bytes=self._pre_size,
                    processed_bytes=0,
                    state=state,
                )
                db.add(record)
            db.commit()
        except Exception as e:
            logger.error(f"保存断点失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _load_checkpoint(self) -> Optional[dict]:
        """加载最近的中断断点"""
        from ..models.database import BackupCheckpoint
        db = next(get_db())
        try:
            from sqlalchemy import desc
            record = db.query(BackupCheckpoint).filter_by(
                state="interrupted"
            ).order_by(desc(BackupCheckpoint.updated_at)).first()
            if not record:
                return None
            return {
                "id": record.id,
                "source_path": record.source_path,
                "output_dir": record.output_dir,
                "archive_path": record.archive_path,
                "archive_format": record.archive_format,
                "compression_level": record.compression_level,
                "password_hash": record.password_hash,
                "file_manifest": json.loads(record.file_manifest) if record.file_manifest else [],
                "completed_chunks": json.loads(record.completed_chunks) if record.completed_chunks else [],
                "current_chunk_index": record.current_chunk_index or 0,
                "total_chunks": record.total_chunks or 0,
                "total_files": record.total_files or 0,
                "processed_files": record.processed_files or 0,
                "total_bytes": record.total_bytes or 0,
                "processed_bytes": record.processed_bytes or 0,
            }
        except Exception as e:
            logger.error(f"加载断点失败: {e}")
            return None
        finally:
            db.close()

    def _has_interrupted_checkpoint(self) -> bool:
        """检查是否存在中断的断点"""
        from ..models.database import BackupCheckpoint
        db = next(get_db())
        try:
            count = db.query(BackupCheckpoint).filter_by(state="interrupted").count()
            return count > 0
        except Exception:
            return False
        finally:
            db.close()

    def _delete_checkpoint(self):
        """删除当前断点"""
        if not self._checkpoint_id:
            return
        from ..models.database import BackupCheckpoint
        db = next(get_db())
        try:
            db.query(BackupCheckpoint).filter_by(id=self._checkpoint_id).delete()
            db.commit()
            self._checkpoint_id = None
        except Exception as e:
            logger.error(f"删除断点失败: {e}")
            db.rollback()
        finally:
            db.close()

    # ── 工具方法 ──────────────────────────────────────────────

    @staticmethod
    def _cleanup_file(path: str):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

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
        stem, suffix, parent = path_obj.stem, path_obj.suffix, path_obj.parent
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
        for candidate in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]:
            if os.path.exists(candidate):
                return candidate
        raise RuntimeError("找不到 7z 可执行文件，请在解压配置中设置 7z 路径")

    def _get_last_backup_end_time(self) -> datetime:
        db = next(get_db())
        try:
            from sqlalchemy import desc
            last_record = db.query(BackupRecord).filter(
                BackupRecord.status == 'completed'
            ).order_by(desc(BackupRecord.backup_end_time)).first()
            if last_record and last_record.backup_end_time:
                return last_record.backup_end_time
            return datetime(2000, 1, 1)
        except Exception as e:
            logger.error(f"获取上次备份时间失败: {e}")
            return datetime.now()
        finally:
            db.close()

    def _get_dir_size(self, path: str) -> int:
        total_size = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
        except Exception as e:
            logger.error(f"计算目录大小失败: {path}, {e}")
        return total_size

    def _save_backup_record(self, filename, output_path, source_path,
                            pre_size, post_size, duration, speed_avg, ratio):
        db = next(get_db())
        try:
            record = BackupRecord(
                id=str(uuid.uuid4()), filename=filename,
                output_path=output_path, source_path=source_path,
                pre_size_bytes=pre_size, post_size_bytes=post_size,
                compression_ratio=ratio, duration_seconds=duration,
                status='completed', speed_avg=speed_avg,
                backup_start_time=self._backup_start_time,
                backup_end_time=self._backup_end_time,
            )
            db.add(record)
            db.commit()
            logger.info(f"备份记录已保存到数据库: {filename}")
        except Exception as e:
            logger.error(f"保存备份记录到数据库失败: {e}")
            db.rollback()
        finally:
            db.close()


_backup_zip_service: Optional[BackupZipService] = None


def get_backup_zip_service() -> BackupZipService:
    global _backup_zip_service
    if _backup_zip_service is None:
        _backup_zip_service = BackupZipService()
    return _backup_zip_service