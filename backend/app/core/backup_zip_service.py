import asyncio
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config.settings import get_config
from ..models.database import get_db, BackupRecord

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
            "logs": [],
            "speed": "0 MB/s",
            "eta": "未知"
        }
        self._start_time = None
        self._last_update_time = 0
        self._pre_size = 0  # 压缩前大小
        self._backup_start_time = None # 文件名中的起始时间
        self._backup_end_time = None   # 文件名中的结束时间

    def _append_log(self, message: str):
        line = f"{datetime.now().strftime('%H:%M:%S')} {message}"
        self._status["logs"].append(line)
        if len(self._status["logs"]) > 300:
            self._status["logs"] = self._status["logs"][-300:]
        logger.info(f"[BackupZip] {message}")

    def _set_progress(self, progress: int, step: str, speed: str = "", eta: str = ""):
        self._status["progress"] = max(0, min(100, int(progress)))
        self._status["step"] = step
        # 强制更新，允许空字符串清除旧值
        self._status["speed"] = speed if speed else "计算中..."
        self._status["eta"] = eta if eta else "计算中..."

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
            "logs": [],
            "speed": "0 MB/s",
            "eta": "未知"
        }
        self._start_time = datetime.now()
        self._last_update_time = 0
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

            # 获取上次备份的时间
            last_backup_time = self._get_last_backup_end_time()
            self._backup_start_time = last_backup_time
            self._backup_end_time = datetime.now()
            
            start_date_str = self._backup_start_time.strftime("%Y%m%d")
            end_date_str = self._backup_end_time.strftime("%Y%m%d")
            
            if start_date_str == end_date_str:
                date_range_str = end_date_str
            else:
                date_range_str = f"{start_date_str}-{end_date_str}"
            
            archive_format = (backup_config.archive_format or "zip").lower()
            if archive_format not in {"zip", "7z"}:
                raise RuntimeError(f"不支持的压缩格式: {archive_format}")
            compression_level = max(1, min(9, int(backup_config.compression_level or 9)))

            # 计算压缩前大小
            self._set_progress(2, "计算库存大小")
            self._pre_size = await asyncio.to_thread(self._get_dir_size, source_path)
            pre_size_gb = self._pre_size / (1024 * 1024 * 1024)
            self._append_log(f"待压缩库存大小: {pre_size_gb:.2f} GB")

            if backup_config.copy_structure_before_zip:
                self._set_progress(5, "复制目录结构")
                snapshot_base_dir = os.path.abspath((backup_config.path_copy_target or output_dir).strip())
                os.makedirs(snapshot_base_dir, exist_ok=True)
                copied_count = await asyncio.to_thread(self._copy_structure_direct, source_path, snapshot_base_dir)
                self._status["path_snapshot_dir"] = snapshot_base_dir
                self._append_log(f"目录结构复制完成，共 {copied_count} 个目录")
            else:
                self._append_log("已跳过目录结构复制")

            self._set_progress(10, "准备压缩")

            password = (backup_config.password or "").strip()
            if not password:
                raise RuntimeError("压缩密码不能为空")

            archive_path = self._unique_path(os.path.join(output_dir, f"ASMR_{date_range_str}.{archive_format}"))
            self._status["output_zip_path"] = archive_path

            seven_zip = self._find_7z_executable(config.extract.seven_zip_path)
            self._append_log(f"使用 7z: {seven_zip}")

            source_parent = str(Path(source_path).parent)
            source_name = Path(source_path).name

            # 优化压缩参数
            # ZIP 格式下，mfb=258 和 mpass=15 会导致压缩极慢
            # 建议使用更均衡的参数
            mfb = 64 if compression_level > 5 else 32
            mpass = 3 if compression_level > 5 else 1
            
            cmd = [
                seven_zip,
                "a",
                f"-t{archive_format}",
                f"-mx={compression_level}",
                f"-mfb={mfb}",
                f"-mpass={mpass}",
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

            self._set_progress(15, "开始压缩")
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
            
            # 记录最终汇总
            now = datetime.now()
            total_elapsed = (now - self._start_time).total_seconds()
            m, s = divmod(int(total_elapsed), 60)
            h, m = divmod(m, 60)
            duration_str = f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
            
            # 获取输出文件大小
            try:
                out_size = os.path.getsize(archive_path)
                size_str = f"{out_size / (1024 * 1024 * 1024):.2f} GB" if out_size > 1024 * 1024 * 1024 else f"{out_size / (1024 * 1024):.2f} MB"
                avg_speed = out_size / total_elapsed if total_elapsed > 0 else 0
                avg_speed_str = f"{avg_speed / (1024 * 1024):.2f} MB/s" if avg_speed > 1024 * 1024 else f"{avg_speed / 1024:.2f} KB/s"
                
                # 计算压缩率
                ratio = out_size / self._pre_size if self._pre_size > 0 else 0
                ratio_percent = ratio * 100
                
                self._append_log(f"压缩完成！耗时: {duration_str}, 大小: {size_str}, 平均速度: {avg_speed_str}, 压缩率: {ratio_percent:.2f}%")
                
                # 保存到数据库
                self._save_backup_record(
                    filename=os.path.basename(archive_path),
                    output_path=archive_path,
                    source_path=source_path,
                    pre_size=self._pre_size,
                    post_size=out_size,
                    duration=int(total_elapsed),
                    speed_avg=avg_speed_str,
                    ratio=ratio
                )
            except Exception as e:
                logger.error(f"保存备份记录失败: {e}")
                self._append_log(f"压缩完成！耗时: {duration_str}")
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
            return

        # 尝试解析 7z 的进度输出
        # 典型格式:  12% 123/1000 5678/100000000
        percent_match = re.search(r"(\d{1,3})%", line)
        if percent_match:
            raw_percent = int(percent_match.group(1))
            # 7z 阶段占 15% - 100%
            mapped = 15 + int(max(0, min(100, raw_percent)) * 0.85)
            
            # 提取已处理字节数以计算速度
            # 7z 的进度行通常包含多个 x/y 部分，通常最后一个是字节
            matches = re.findall(r"(\d+)/\d+", line)
            speed_str = ""
            eta_str = ""
            
            if matches:
                # 取最后一个匹配作为已处理字节数
                current_bytes = int(matches[-1])
                now = datetime.now()
                elapsed = (now - self._start_time).total_seconds()
                
                if elapsed > 0:
                    speed = current_bytes / elapsed  # bytes/s
                    if speed > 1024 * 1024:
                        speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
                    elif speed > 1024:
                        speed_str = f"{speed / 1024:.2f} KB/s"
                    else:
                        speed_str = f"{speed:.0f} B/s"
                    
                    if raw_percent > 0:
                        total_seconds = elapsed * 100 / raw_percent
                        remaining_seconds = total_seconds - elapsed
                        if remaining_seconds > 0:
                            m, s = divmod(int(remaining_seconds), 60)
                            h, m = divmod(m, 60)
                            if h > 0:
                                eta_str = f"{h:d}:{m:02d}:{s:02d}"
                            else:
                                eta_str = f"{m:02d}:{s:02d}"

            # 只有当进度或速度有显著变化时才更新（减少前端刷新压力）
            current_time = datetime.now().timestamp()
            if current_time - self._last_update_time >= 1 or raw_percent == 100:
                self._last_update_time = current_time
                self._set_progress(min(99, mapped), f"压缩中 {raw_percent}%", speed_str, eta_str)

        if line.startswith("Error") or "Error:" in line:
            self._append_log(line)
        elif line.startswith("WARN") or line.startswith("Warning"):
            self._append_log(line)
        elif line.startswith("Everything is Ok"):
            # 提取最终汇总信息
            pass # 可以在这里解析最终统计数据

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

    def _get_last_backup_end_time(self) -> datetime:
        """从数据库获取上次成功备份的结束时间"""
        db = next(get_db())
        try:
            from sqlalchemy import desc
            last_record = db.query(BackupRecord).filter(
                BackupRecord.status == 'completed'
            ).order_by(desc(BackupRecord.backup_end_time)).first()
            
            if last_record and last_record.backup_end_time:
                return last_record.backup_end_time
            
            # 如果没有记录，返回一个默认的较早时间（例如 2000-01-01）
            return datetime(2000, 1, 1)
        except Exception as e:
            logger.error(f"获取上次备份时间失败: {e}")
            return datetime.now()
        finally:
            db.close()

    def _get_dir_size(self, path: str) -> int:
        """计算目录总大小（字节）"""
        total_size = 0
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total_size += os.path.getsize(fp)
        except Exception as e:
            logger.error(f"计算目录大小失败: {path}, {e}")
        return total_size

    def _save_backup_record(self, filename, output_path, source_path, pre_size, post_size, duration, speed_avg, ratio):
        """保存备份记录到数据库"""
        db = next(get_db())
        try:
            record = BackupRecord(
                id=str(uuid.uuid4()),
                filename=filename,
                output_path=output_path,
                source_path=source_path,
                pre_size_bytes=pre_size,
                post_size_bytes=post_size,
                compression_ratio=ratio,
                duration_seconds=duration,
                status='completed',
                speed_avg=speed_avg,
                backup_start_time=self._backup_start_time,
                backup_end_time=self._backup_end_time
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
