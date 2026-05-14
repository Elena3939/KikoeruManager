import os
import re
import shutil
import contextlib

# ZIP 文件名编码名称 → Windows 代码页编号（用于 7zz -mcp=<cp>）
_ENCODING_TO_CP: dict = {
    'shift_jis': 932,
    'shift-jis': 932,
    'cp932': 932,
    'gbk': 936,
    'cp936': 936,
    'big5': 950,
    'cp950': 950,
    'euc_kr': 949,
    'euc-kr': 949,
    'cp949': 949,
}
import subprocess
import asyncio
import sys
import threading
import filetype
import tempfile
from collections import OrderedDict
from typing import Optional, List, Dict, Callable, Tuple, Union, Any
from pathlib import Path
import logging
import hashlib
import time
from datetime import datetime

from ..config.settings import get_config
from ..core.task_engine import Task
from ..core.password_utils import (
    normalize_filename_value,
    normalize_password_value,
    normalize_rjcode_value,
)

logger = logging.getLogger(__name__)

# Windows 上隐藏子进程窗口的标志
if sys.platform == 'win32':
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

class ArchiveInfo:
    """压缩包信息"""
    def __init__(
        self,
        path: str,
        file_list: List[Dict],
        password: Optional[str] = None,
        inferred_rjcode: Optional[str] = None,
    ):
        self.path = path
        self.file_list = file_list  # [{"name": "...", "size": 123, "crc": "..."}, ...]
        self.password = password
        self.inferred_rjcode = inferred_rjcode
        self.is_volume = False
        self.volume_set: Optional[List[str]] = None
        self.detected_encoding: Optional[str] = None  # _list_archive_contents 自动检测到的编码

class ExtractService:
    """解压服务"""

    _seven_zip_available_cache: Optional[bool] = None
    _seven_zip_available_path: Optional[str] = None
    _seven_zip_check_lock: Optional[asyncio.Lock] = None
    _seven_zip_semaphore: Optional[asyncio.Semaphore] = None
    _seven_zip_semaphore_limit: Optional[int] = None
    # 存储类型探测结果缓存：{ "C:\\" -> "ssd", "/dev/sda" -> "hdd", ... }
    # 探测失败的目录会缓存为 "unknown"，下次也不再重复试。
    _storage_type_cache: Dict[str, str] = {}
    # _list_archive_contents 最近检测到的编码（archive_path -> encoding_name），
    # 供 _get_archive_info 写入 archive_info.detected_encoding，进而给 _get_mcp_args 使用。
    _archive_encoding_cache: Dict[str, str] = {}
    # 7zz 的 -mcp 参数兼容性检测：24.08+ 某些版本/某些 ZIP 文件对 `-mcp=N` 直接抛
    # `opening : E_INVALIDARG`。第一次检测到后置为 True，后续 _get_mcp_args 直接
    # short-circuit 返回 []，禁止再传 -mcp。事后 _repair_mojibake_filenames_in_place 兜底。
    _seven_zip_mcp_unsupported: bool = False
    # 上次构建 semaphore 时所用的"探测目标路径 + 探测结果"，用于热重载时识别变更
    _seven_zip_semaphore_storage_key: Optional[str] = None
    # ------- 密码探测 / 负缓存 -------
    # 优先走 `7zz t archive <最小条目>`：只测一个小文件的完整 CRC，
    # 密码错秒级非零退出。能抓住 store+AES（压缩包里装 zip）这种用
    # 流式探测拿不住的场景：那种场景 AES 解出来的垃圾数据能一直吐到
    # 尾部才在 CRC 阶段报错，流式探测的"读够 N MB 就重放"会误判为 ok。
    # 拿不到 file_list（如头加密 / 尚未成功读取目录）时回退用流式探测。
    PROBE_BEFORE_EXTRACT: bool = True
    # 策略：魔数探测 → 小条目 t 探测 → 流式探测
    PROBE_ENTRY_MAX_SIZE: int = 5 * 1024 * 1024   # 小条目 t 探测的尺寸上限
    PROBE_ENTRY_TIMEOUT: float = 30.0             # 单条目 t 命令的最大耗时
    PROBE_MAGIC_TIMEOUT: float = 20.0             # 魔数探测（只读前几十字节）超时
    PROBE_MAGIC_ENTRY_LIMIT: int = 3              # 一次密码最多抽样多少个强魔数条目
    PROBE_FULL_TEST_TIMEOUT: float = 600.0        # 无法轻量定性时，最多花 10 分钟做不落盘 t 验证
    PROBE_BYTES: int = 2 * 1024 * 1024            # 流式探测读到 2MB 即认为解压流可信
    PROBE_TIMEOUT_SECONDS: float = 30.0           # 单次流式探测最多等 30s，超时回退完整解压

    # 按文件后缀识别的魔数表：(偏移量, (候选签名, ...))。
    # 有后缀在这里就能用“解压前几十字节 + 对照魔数”秒级判定密码是否正确，
    # 不受文件大小影响。对 store+AES（压缩包里装 zip/mp3/音视频）这种场景特别有用。
    _KNOWN_MAGIC_TABLE: Dict[str, Tuple[int, Tuple[bytes, ...]]] = {
        '.zip':  (0, (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')),
        '.jar':  (0, (b'PK\x03\x04',)),
        '.apk':  (0, (b'PK\x03\x04',)),
        '.docx': (0, (b'PK\x03\x04',)),
        '.xlsx': (0, (b'PK\x03\x04',)),
        '.pptx': (0, (b'PK\x03\x04',)),
        '.7z':   (0, (b'7z\xbc\xaf\x27\x1c',)),
        '.rar':  (0, (b'Rar!\x1a\x07',)),
        '.gz':   (0, (b'\x1f\x8b',)),
        '.bz2':  (0, (b'BZh',)),
        '.xz':   (0, (b'\xfd7zXZ',)),
        '.tar':  (257, (b'ustar',)),  # POSIX tar 头标志在 257偏移
        '.mp3':  (0, (b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2', b'\xff\xfa')),
        '.flac': (0, (b'fLaC',)),
        '.wav':  (0, (b'RIFF',)),
        '.avi':  (0, (b'RIFF',)),
        '.webp': (0, (b'RIFF',)),
        '.ogg':  (0, (b'OggS',)),
        '.opus': (0, (b'OggS',)),
        '.wma':  (0, (b'\x30\x26\xb2\x75',)),
        '.asf':  (0, (b'\x30\x26\xb2\x75',)),
        '.mp4':  (4, (b'ftyp',)),
        '.m4a':  (4, (b'ftyp',)),
        '.m4b':  (4, (b'ftyp',)),
        '.mov':  (4, (b'ftyp',)),
        '.mkv':  (0, (b'\x1a\x45\xdf\xa3',)),
        '.webm': (0, (b'\x1a\x45\xdf\xa3',)),
        '.png':  (0, (b'\x89PNG\r\n\x1a\n',)),
        '.jpg':  (0, (b'\xff\xd8\xff',)),
        '.jpeg': (0, (b'\xff\xd8\xff',)),
        '.gif':  (0, (b'GIF87a', b'GIF89a')),
        '.bmp':  (0, (b'BM',)),
        '.pdf':  (0, (b'%PDF-',)),
        '.psd':  (0, (b'8BPS',)),
    }
    # #3 负缓存：按 "压缩包指纹 × 密码哈希" 记忆失败组合，进程内重试任务时直接跳过。
    _password_negative_cache: Dict[Tuple[str, str], float] = {}
    PASSWORD_NEGATIVE_CACHE_MAX: int = 4096       # 简单兜底，避免长跑任务无限增长
    # #4 预读 list 缓存：避免同一压缩包重复跑 `7zz l`。
    # key = (abs_path, mtime_ns, size)，value = ArchiveInfo 快照。
    # 用 OrderedDict 做简易 LRU，命中 move_to_end。
    # 类变量跨 ExtractService 实例共享：task_engine 主任务和 linked_subtitle probe_task
    # 拿到的是不同实例，但通过这里共享 list 结果。
    # 分卷 / remap 后路径会变 → 新 key，老条目靠 LRU 自然淘汰，不主动 invalidate。
    _archive_info_cache: "OrderedDict[Tuple[str, int, int], ArchiveInfo]" = OrderedDict()
    _archive_info_cache_lock = threading.Lock()
    ARCHIVE_INFO_CACHE_MAX: int = 64
    ARCHIVE_INFO_CACHE_FILE_LIST_LIMIT: int = 50000  # 单条 file_list 超此值不入缓存，避免极端大包占内存
    VERIFY_FULL_FILE_LIMIT = 1200
    VERIFY_SAMPLE_FILE_LIMIT = 240
    NESTED_SCAN_FILE_BUDGET = 5000
    NESTED_SCAN_DIR_BUDGET = 800
    # 小于此尺寸的嵌套压缩包视为潜在字幕源，跳过常规嵌套解压、直接走字幕补配预检
    NESTED_SUBTITLE_SIZE_THRESHOLD = 10 * 1024 * 1024  # 10 MB
    # 嵌套小包"看起来像字幕包"的强语义关键词。
    #
    # 设计原则（用户痛点：之前 < 10MB 一律跳过，命名不规范的奖励包永远漏解压）：
    # 1. 默认所有嵌套小包都走常规解压（safe default = 不漏解压）。
    # 2. 仅当文件名 / 父目录含**强语义**关键词、或 peek 内容**清一色字幕扩展名**时，
    #    才判定为字幕包跳过常规解压。
    # 3. 关键词必须严格 —— "ass" / "srt" / "vtt" 这种短英文片段会误命中
    #    "assets" / "compass" / 任意含 ass 子串的文件名 / 路径，所以**只用整词
    #    （word boundary）匹配**，并去掉这些短英文，只保留语义明确的词。
    NESTED_SUBTITLE_HINTS = (
        "字幕",
        "字幕版",
        "字幕组",
        "字幕組",
        "subtitle",
        "subtitles",
    )
    # 字幕文件扩展名。仅用于 peek 内容判定。
    # 注意：原版含 .txt，但奖励包 / 说明 / readme 也常用 .txt，会让纯文本奖励包
    # 被误判为字幕包跳过解压，所以这里**不再把 .txt 列为字幕扩展名**。
    SUBTITLE_FILE_EXTENSIONS = (
        ".srt",
        ".vtt",
        ".ass",
        ".ssa",
        ".lrc",
        ".sbv",
        ".sub",
        ".idx",
        ".smi",
        ".sami",
    )
    # peek 内容时遇到任何这些扩展名 → 一定不是字幕包 → 走常规解压
    NESTED_SMALL_ARCHIVE_MEDIA_EXTENSIONS = frozenset({
        ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
        ".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif",
        ".psd", ".ai", ".eps",
        ".pdf", ".epub", ".mobi", ".azw3",
        ".html", ".htm", ".xhtml",
        ".doc", ".docx", ".rtf",
        ".xls", ".xlsx", ".csv",
        ".ppt", ".pptx",
        ".zip", ".7z", ".rar",  # 嵌套压缩包再嵌套，肯定不是纯字幕包
        ".exe", ".dll", ".bat",
    })
    NESTED_SKIP_DIRS = {
        "__macosx",
        ".git",
        ".svn",
        "node_modules",
        ".cache",
        "temp",
        "tmp",
        "_conflicts",
        "subtitles",
    }

    @property
    def config(self):
        """动态获取最新配置"""
        from ..config.settings import get_config
        return get_config()

    @property
    def seven_zip(self) -> str:
        """动态获取7z路径"""
        return self._find_7z_executable()

    def _get_mcp_args(
        self,
        archive_path: Optional[str] = None,
        archive_info=None,
        filename_encoding: Optional[Union[str, int]] = None,
    ) -> list:
        """返回 ZIP 文件名代码页参数。

        只对 ZIP 生效：7zz 24.08 之后对 RAR 解析器传 -mcp 会直接
        E_INVALIDARG（One or more arguments are invalid），而 .7z 格式
        文件名是 UTF-8，传 -mcp 也无意义。所以非 zip 一律不传。
        除了 .zip / .zip.NNN 后缀，也识别 ZIP 魔数，覆盖嵌套包被命名成
        .zi / .p 这类截断后缀的场景。
        archive_path 为 None 时（兼容旧调用）按"未知格式"处理，不传。

        当 zip_encoding=0（未配置）时，自动使用 archive_info.detected_encoding
        推断代码页（如日文 ZIP 自动得到 -mcp=932）。

        7zz 24.08+ 某些版本/某些 ZIP 对 -mcp= 直接抛 `opening : E_INVALIDARG`。
        _run_7z_command 检测到该错误会把 _seven_zip_mcp_unsupported 置 True，
        这里 short-circuit 一律返回 []，让 7zz 走默认 UTF-8 解读；文件名 mojibake
        由事后 _repair_mojibake_filenames_in_place 兜底反解。
        """
        if self.__class__._seven_zip_mcp_unsupported:
            return []
        if not archive_path:
            if archive_info is not None:
                archive_path = getattr(archive_info, 'path', None)
            if not archive_path:
                return []
        low = str(archive_path).lower()
        is_zip_like = low.endswith('.zip') or bool(re.search(r'\.zip\.\d+$', low))
        if not is_zip_like:
            with contextlib.suppress(Exception):
                with open(str(archive_path), 'rb') as fp:
                    header = fp.read(8)
                is_zip_like = (
                    header.startswith(b'PK\x03\x04')
                    or header.startswith(b'PK\x05\x06')
                    or header.startswith(b'PK\x07\x08')
                )
        if not is_zip_like:
            return []

        cp = self._filename_encoding_to_codepage(filename_encoding)
        if cp > 0:
            return [f"-mcp={cp}"]
        enc = ""
        if archive_path:
            # ZIP 的真实文件名编码在中央目录里。7z stdout 的编码检测只能解释
            # 7z 输出本身，不能可靠区分 GBK / Shift-JIS ZIP；先用 zipfile 直接嗅探原始字节。
            enc = (self.__class__._archive_encoding_cache.get(str(archive_path)) or '').lower()
            if not enc:
                sniffed = self._sniff_zip_encoding(str(archive_path))
                if sniffed:
                    enc = sniffed.lower()
                    self.__class__._archive_encoding_cache[str(archive_path)] = enc

        if not enc:
            enc = (getattr(archive_info, 'detected_encoding', None) or '').lower()
        cp = _ENCODING_TO_CP.get(enc, 0)

        if cp <= 0:
            cp = int(self.config.extract.zip_encoding or 0)
        if cp <= 0:
            return []
        return [f"-mcp={cp}"]

    @staticmethod
    def _filename_encoding_to_codepage(value: Optional[Union[str, int]]) -> int:
        """把前端/配置传来的 ZIP 文件名编码转换为 7zz -mcp 代码页。"""
        if value is None:
            return 0
        raw = str(value).strip().lower()
        if not raw or raw in {"auto", "default", "0", "none"}:
            return 0
        if raw.isdigit():
            return int(raw)
        return int(_ENCODING_TO_CP.get(raw.replace("_", "-"), 0) or _ENCODING_TO_CP.get(raw, 0) or 0)

    def _manual_filename_encoding_from_task(self, task: Optional[Task]) -> Optional[str]:
        metadata = dict(getattr(task, "task_metadata", None) or {})
        value = (
            metadata.get("manual_retry_filename_encoding")
            or metadata.get("filename_encoding")
            or metadata.get("zip_filename_encoding")
        )
        normalized = str(value or "").strip()
        return normalized or None

    @property
    def _mcp_args(self) -> list:
        """旧调用兼容入口，无路径上下文时不传 -mcp，避免 7zz 24.08 对 RAR 报错。"""
        return []

    def _find_7z_executable(self) -> str:
        """查找 7z 可执行文件"""
        import shutil

        # 首先尝试配置的路径
        configured_path = self.config.extract.seven_zip_path
        if configured_path and configured_path != "7z":
            if os.path.exists(configured_path):
                return configured_path

        # 尝试在 PATH 中查找，Docker 优先使用官方 7zz 以支持 RAR5
        seven_zip_path = shutil.which("7zz") or shutil.which("7z")
        if seven_zip_path:
            return seven_zip_path

        # Windows 默认安装路径
        default_paths = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ]

        for path in default_paths:
            if os.path.exists(path):
                return path

        # 如果都找不到，返回配置的值（后续会报错）
        logger.error("找不到 7z 可执行文件。请安装 7-Zip 并确保它在 PATH 中，或在配置中指定正确路径。")
        return "7z"

    def _find_unar_executable(self) -> Optional[str]:
        return self._find_bundled_or_path_executable("unar")

    def _find_lsar_executable(self) -> Optional[str]:
        return self._find_bundled_or_path_executable("lsar")

    def _find_bundled_or_path_executable(self, name: str) -> Optional[str]:
        """优先使用项目随附工具；Docker/系统环境再回退 PATH。

        Windows 开发和 PyInstaller 包不应依赖系统 PATH。Docker 镜像已经安装
        unar/lsar，那里走 PATH 即可。
        """
        suffix = ".exe" if sys.platform == "win32" else ""
        executable = f"{name}{suffix}"
        candidates: List[str] = []

        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            candidates.append(os.path.join(str(bundle_root), "tools", "unar", executable))

        try:
            project_root = Path(__file__).resolve().parents[3]
            candidates.append(str(project_root / "tools" / "unar" / executable))
        except Exception:
            pass

        candidates.append(os.path.join(os.getcwd(), "tools", "unar", executable))

        for path in candidates:
            if path and os.path.exists(path):
                return path

        return shutil.which(name)

    def _is_rar_archive(self, archive_path: str) -> bool:
        lower_path = str(archive_path).lower()
        if lower_path.endswith(".rar") or bool(re.search(r"\.part0*1\.rar$", lower_path)):
            return True
        with contextlib.suppress(Exception):
            with open(str(archive_path), "rb") as fp:
                return fp.read(8).startswith(b"Rar!")
        return False

    def _needs_filename_garbled_guard(self, archive_path: str) -> bool:
        """只有文件名编码历史上会踩坑的格式需要乱码阻断。"""
        lower_path = str(archive_path or "").lower()
        if self._is_rar_archive(archive_path):
            return True
        if lower_path.endswith(".zip") or bool(re.search(r"\.zip\.\d+$", lower_path)):
            return True
        with contextlib.suppress(Exception):
            with open(str(archive_path), "rb") as fp:
                header = fp.read(8)
            return (
                header.startswith(b"PK\x03\x04")
                or header.startswith(b"PK\x05\x06")
                or header.startswith(b"PK\x07\x08")
            )
        return False

    async def _ensure_7z_available(self) -> bool:
        """异步检查 7z 是否可用，并缓存结果避免高并发重复探测"""
        executable = self.seven_zip
        if (
            self.__class__._seven_zip_available_cache is not None
            and self.__class__._seven_zip_available_path == executable
        ):
            return bool(self.__class__._seven_zip_available_cache)

        if self.__class__._seven_zip_check_lock is None:
            self.__class__._seven_zip_check_lock = asyncio.Lock()

        async with self.__class__._seven_zip_check_lock:
            if (
                self.__class__._seven_zip_available_cache is not None
                and self.__class__._seven_zip_available_path == executable
            ):
                return bool(self.__class__._seven_zip_available_cache)

            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    [executable, "--help"],
                    capture_output=True,
                    timeout=5
                )
                available = result.returncode == 0
            except Exception as e:
                logger.error(f"检查 7z 可用性失败: {e}")
                available = False

            self.__class__._seven_zip_available_cache = available
            self.__class__._seven_zip_available_path = executable
            return available

    @classmethod
    def _detect_storage_type(cls, path: str) -> str:
        """探测路径所在物理盘的存储类型，返回 'ssd' / 'hdd' / 'unknown'。

        - Windows: PowerShell 调用 Get-Partition → Get-Disk → Get-PhysicalDisk 取 MediaType。
        - Linux:   读 /sys/block/<dev>/queue/rotational，1=HDD，0=SSD。
        - 其他平台 / 检测失败 / 网络盘等 → 'unknown'，调用方按保守策略处理。

        结果按"盘根"缓存（Windows: 盘符；Linux: 块设备名）。
        """
        if not path:
            return "unknown"
        try:
            abs_path = os.path.abspath(path)
        except Exception:
            return "unknown"

        if sys.platform == "win32":
            drive_letter = os.path.splitdrive(abs_path)[0].rstrip(":").rstrip("\\")
            cache_key = drive_letter.upper() if drive_letter else abs_path
            cached = cls._storage_type_cache.get(cache_key)
            if cached:
                return cached
            if not drive_letter:
                cls._storage_type_cache[cache_key] = "unknown"
                return "unknown"
            # PowerShell 调用偶尔会被 AV 拦截或加载慢，限制 8s 超时；
            # 失败/超时统一退回 unknown，由上层按 HDD 保守策略处理。
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                (
                    f"$ErrorActionPreference='SilentlyContinue';"
                    f"(Get-Partition -DriveLetter '{drive_letter}' | "
                    f"Get-Disk | Get-PhysicalDisk | Select-Object -First 1).MediaType"
                ),
            ]
            try:
                creationflags = CREATE_NO_WINDOW
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=8,
                    text=True,
                    creationflags=creationflags,
                )
                output = (result.stdout or "").strip().lower()
            except Exception as exc:
                logger.warning("存储类型探测失败 (Windows, drive=%s): %s", drive_letter, exc)
                cls._storage_type_cache[cache_key] = "unknown"
                return "unknown"

            if "ssd" in output:
                detected = "ssd"
            elif "hdd" in output:
                detected = "hdd"
            else:
                # MediaType 可能返回 Unspecified / 空字符串：通常出现在 USB / 虚拟盘 / NVMe over USB
                detected = "unknown"
            cls._storage_type_cache[cache_key] = detected
            return detected

        if sys.platform.startswith("linux"):
            # st_dev → 主次设备号 → /sys/dev/block/<major>:<minor>/queue/rotational
            try:
                st = os.stat(abs_path)
                major = os.major(st.st_dev)
                minor = os.minor(st.st_dev)
                cache_key = f"{major}:{minor}"
                cached = cls._storage_type_cache.get(cache_key)
                if cached:
                    return cached
                rotational_path = f"/sys/dev/block/{major}:{minor}/queue/rotational"
                if not os.path.exists(rotational_path):
                    # 尝试逐级回溯到父块设备（partition → disk）
                    sysfs = os.path.realpath(f"/sys/dev/block/{major}:{minor}")
                    candidate = os.path.join(sysfs, "..", "queue", "rotational")
                    rotational_path = candidate if os.path.exists(candidate) else rotational_path
                if os.path.exists(rotational_path):
                    with open(rotational_path, "r", encoding="utf-8", errors="ignore") as fh:
                        flag = fh.read().strip()
                    detected = "hdd" if flag == "1" else "ssd"
                else:
                    detected = "unknown"
                cls._storage_type_cache[cache_key] = detected
                return detected
            except Exception as exc:
                logger.warning("存储类型探测失败 (Linux, path=%s): %s", abs_path, exc)
                return "unknown"

        return "unknown"

    def _resolve_extract_concurrency(self) -> Tuple[int, str]:
        """返回 (并发上限, 决策来源描述)。"""
        configured_extract = int(getattr(self.config.extract, 'max_concurrent_extractions', 0) or 0)
        configured_workers = max(1, int(self.config.processing.max_workers or 1))

        if configured_extract > 0:
            return max(1, configured_extract), f"用户固定 {configured_extract}"

        # auto 模式：根据 temp_path 所在盘的存储类型决策。
        # 优先 storage.temp_path（解压目标，IO 密集点），其次 library_path、input_path。
        probe_paths: List[str] = []
        storage_cfg = getattr(self.config, 'storage', None)
        for attr in ("temp_path", "library_path", "input_path"):
            value = getattr(storage_cfg, attr, None) if storage_cfg else None
            if value:
                probe_paths.append(str(value))
        probe_paths.append(os.getcwd())

        detected = "unknown"
        used_path = ""
        for candidate in probe_paths:
            detected = self._detect_storage_type(candidate)
            used_path = candidate
            if detected in ("ssd", "hdd"):
                break

        if detected == "ssd":
            limit = max(1, min(configured_workers, 3))
            reason = f"auto: 检测到 SSD ({used_path}) → {limit}"
        elif detected == "hdd":
            limit = 1
            reason = f"auto: 检测到 HDD ({used_path}) → 1（机械盘并发寻道伤性能伤寿命）"
        else:
            limit = 1
            reason = f"auto: 存储类型未知 ({used_path}) → 1（保守默认）"
        return limit, reason

    def _get_7z_semaphore(self) -> asyncio.Semaphore:
        limit, reason = self._resolve_extract_concurrency()
        # 把决策来源也作为 cache key 一部分，配置热重载切换 SSD↔HDD 时能重建 semaphore。
        storage_key = f"{limit}:{reason}"
        if (
            self.__class__._seven_zip_semaphore is None
            or self.__class__._seven_zip_semaphore_limit != limit
            or self.__class__._seven_zip_semaphore_storage_key != storage_key
        ):
            self.__class__._seven_zip_semaphore = asyncio.Semaphore(limit)
            self.__class__._seven_zip_semaphore_limit = limit
            self.__class__._seven_zip_semaphore_storage_key = storage_key
            logger.info("设置 7z 并发上限: %s (%s)", limit, reason)
        return self.__class__._seven_zip_semaphore

    def _get_seven_zip_mmt_args(self) -> List[str]:
        """返回给 7z 的多线程参数。空字符串=不传，让 7z 自己决定。"""
        raw = str(getattr(self.config.extract, 'seven_zip_threads', '') or '').strip()
        if not raw:
            return []
        if raw.lower() == 'auto':
            raw = 'on'
        return [f'-mmt={raw}']

    @staticmethod
    def _is_semaphore_locked(semaphore: asyncio.Semaphore) -> bool:
        """兼容不同 Python 版本的 semaphore locked 判断。"""
        try:
            return bool(semaphore.locked())
        except Exception:
            return False

    @staticmethod
    def _is_extract_subprocess_command(cmd: List[str]) -> bool:
        if len(cmd) < 2:
            return False
        action = str(cmd[1] or "").strip().lower()
        return action in {"x", "e"}

    def _set_extract_meta(self, task: Task, **values):
        if task.task_metadata is None:
            task.task_metadata = {}
        for key, value in values.items():
            task.task_metadata[key] = value

    async def extract(self, task: Task) -> Optional[str]:
        """
        解压压缩包
        返回解压后的目录路径
        """
        # 首先检查 7z 是否可用
        if not await self._ensure_7z_available():
            raise Exception("找不到 7z 可执行文件。请安装 7-Zip 并确保它在 PATH 中，或在配置中指定正确路径。")

        archive_path = task.source_path

        # 检查是否被取消
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 已被取消，跳过解压")
            return None

        # 1. 等待文件稳定
        self._set_extract_meta(
            task,
            extract_stage="wait_stable",
            extract_started_at=datetime.now().isoformat(),
            archive_size=os.path.getsize(archive_path) if os.path.exists(archive_path) else 0,
        )
        task.update_progress(5, "等待文件写入完成")
        await self._wait_file_stable(archive_path, task)

        # 检查暂停和取消
        await task.wait_if_paused()
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 在等待文件稳定后被取消")
            return None

        # 2. 修复后缀名
        self._set_extract_meta(task, extract_stage="detect_type")
        task.update_progress(10, "检测文件类型")
        archive_path = await self._repair_extension(archive_path)

        # 更新任务的 source_path，确保归档时使用正确的路径
        if archive_path != task.source_path:
            logger.info(f"[Extract] 文件路径已更新: {task.source_path} -> {archive_path}")
            task.source_path = archive_path

        # 3. 检查是否是分卷
        volume_set = self._detect_volume_set(archive_path)
        if volume_set:
            self._set_extract_meta(task, extract_stage="wait_volume_set")
            task.update_progress(15, "等待分卷组完整")
            if not await self._wait_for_complete_set(volume_set, task):
                raise Exception("分卷组不完整或等待超时")
            archive_path = volume_set.entry_path or volume_set.volumes[0]

            # 自解压 .exe + .eNN 国产 SFX 工具命名 7z/RAR 都不能直接识别多卷
            # （`7zz l x.exe` 报 returncode=2）。先探测内嵌档真实格式，再按
            # 7z 多卷（.7z.NNN）或 RAR 多卷（.partN.rar）规范重命名，让现有
            # 7zz / unar fallback 通道正常工作。
            if volume_set.type == 'exe_e_sequence':
                self._set_extract_meta(task, extract_stage="remap_exe_e_sfx")
                task.update_progress(17, "重命名自解压分卷为标准多卷格式")
                volume_set = await self._remap_exe_e_sequence(volume_set, task)
                archive_path = volume_set.entry_path or volume_set.volumes[0]
                if archive_path != task.source_path:
                    logger.info(
                        f"[Extract] 自解压分卷已重命名: {task.source_path} -> {archive_path}"
                    )
                    task.source_path = archive_path

            # .zip 主卷 + .NNN 纯数字分卷（首卷 .001 被改名为 .zip 的非标准分卷）
            # 同样需要先重命名为标准 .zip.NNN 多卷格式，让 7zz 按 split file 协议读取。
            if volume_set.type == 'zip_numeric_split':
                self._set_extract_meta(task, extract_stage="remap_zip_numeric_split")
                task.update_progress(17, "重命名 .zip + .NNN 分卷为标准多卷格式")
                volume_set = await self._remap_zip_numeric_split(volume_set, task)
                archive_path = volume_set.entry_path or volume_set.volumes[0]
                if archive_path != task.source_path:
                    logger.info(
                        f"[Extract] .zip 数字分卷已重命名: {task.source_path} -> {archive_path}"
                    )
                    task.source_path = archive_path

            # WinRAR 自解压多卷（首卷 X.part1.exe + 兄弟 X.partN.rar）：
            # 7zz 不会从 .exe 首卷按 .partN.rar 文件名规则续接兄弟卷，必然失败。
            # 把 .partN.exe 改名为 .partN.rar（RAR 数据签名前允许任意头部数据，
            # 改名不破坏文件），让 7zz 按标准 RAR 多卷协议读取。
            if volume_set.type == 'part' and any(
                re.search(r'\.part\d+\.exe$', os.path.basename(p), re.IGNORECASE)
                for p in volume_set.volumes
            ):
                self._set_extract_meta(task, extract_stage="remap_part_exe")
                task.update_progress(17, "重命名 .partN.exe 自解压分卷为标准 RAR 多卷格式")
                volume_set = await self._remap_part_exe_volumes(volume_set, task)
                archive_path = volume_set.entry_path or volume_set.volumes[0]
                if archive_path != task.source_path:
                    logger.info(
                        f"[Extract] .partN.exe 自解压分卷已重命名: {task.source_path} -> {archive_path}"
                    )
                    task.source_path = archive_path

        manual_retry_password = normalize_password_value(
            (task.task_metadata or {}).get("manual_retry_password")
        )
        manual_retry_password_only = bool((task.task_metadata or {}).get("manual_retry_password_only"))
        manual_filename_encoding = self._manual_filename_encoding_from_task(task)
        manual_ignore_garbled = bool((task.task_metadata or {}).get("manual_retry_ignore_garbled"))

        password_candidates: List[Dict[str, Optional[str]]] = []
        hinted_rjcode = None
        if manual_retry_password and manual_retry_password_only:
            password_candidates = [{
                "password": manual_retry_password,
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }]
        else:
            # 3.5 如果密码库是按文件名匹配到的，且条目里带 RJ 号，则只注入 RJ 提示。
            # 不改源文件名，避免监控链路还在等旧路径导致超时。
            password_candidates = await self._get_password_candidates_for_archive(archive_path)
            hinted_rjcode = self._apply_filename_password_rj_hint(archive_path, task, password_candidates)

        # 检查暂停和取消
        await task.wait_if_paused()
        if task.is_cancelled():
            logger.info(f"任务 {task.id} 在等待分卷后被取消")
            return None

        # 4. 获取压缩包内文件列表
        self._set_extract_meta(task, extract_stage="list_archive")
        task.update_progress(20, "读取压缩包内容")
        archive_info = await self._get_archive_info(archive_path, password_candidates=password_candidates, task=task)
        archive_info_from_listing = archive_info is not None
        if not archive_info:
            logger.warning("预读取压缩包内容失败，回退为直接尝试解压: %s", archive_path)
            archive_info = ArchiveInfo(archive_path, [], None)
            task.update_progress(24, "压缩包预读失败，尝试直接解压")

        # 5. 确定输出路径
        output_name = str(hinted_rjcode or Path(archive_path).stem).strip()  # 去除首尾空格，避免Windows路径错误
        # 移除其他Windows不允许的字符
        output_name = re.sub(r'[<>:"|?*]', '', output_name)
        output_path = tempfile.mkdtemp(
            prefix=f"{output_name}_{task.id[:8]}_",
            dir=self.config.storage.temp_path
        )
        task.task_metadata = {
            **(task.task_metadata or {}),
            "temp_extract_path": output_path,
        }

        # 6. 尝试解压
        try:
            self._set_extract_meta(task, extract_stage="extract")
            task.update_progress(30, "开始解压")
            success, success_password, extract_failure_reason = await self._try_extract(
                archive_info,
                output_path,
                task,
                password_candidates=password_candidates,
            )
        except Exception:
            await self._cleanup_extract_path(output_path)
            await self._rollback_exe_e_remap(task)
            await self._rollback_zip_numeric_remap(task)
            await self._rollback_part_exe_remap(task)
            raise

        if not success:
            # 用户取消：task.cancel() 里已经把状态写成 "用户取消"，不要再 task.fail()
            # 把它覆盖成 "原因未知"。直接清理临时目录后返回。
            if extract_failure_reason == "cancelled" or task.is_cancelled():
                logger.info(f"任务 {task.id}: 用户取消，跳过失败标记")
                await self._cleanup_extract_path(output_path)
                # 取消时也尝试把自解压分卷文件名还原（避免 .exe + .eNN 留下乱七八糟改名结果）
                await self._rollback_exe_e_remap(task)
                await self._rollback_zip_numeric_remap(task)
                await self._rollback_part_exe_remap(task)
                return None
            # 更新任务状态为失败，并设置更准确的错误信息
            if extract_failure_reason == "disk_full":
                error_msg = "解压失败：临时目录磁盘空间不足"
            elif extract_failure_reason == "archive_corrupt":
                error_msg = "解压失败：压缩包损坏或不完整（Headers/Data Error）"
            elif extract_failure_reason == "wrong_password":
                error_msg = "解压失败：无正确密码"
            elif extract_failure_reason == "garbled_filename":
                error_msg = "解压失败：文件乱码"
            elif extract_failure_reason == "extract_incomplete":
                error_msg = "解压失败：解压产物为空或不完整"
            else:
                error_msg = "解压失败：无法解压压缩包（原因未知）"
            self._set_extract_meta(task, extract_failure_reason=extract_failure_reason)
            task.fail(error_msg)
            logger.error(f"任务 {task.id}: {error_msg}")
            # 清理已创建的解压目录（包括部分解压的残留文件）
            await self._cleanup_extract_path(output_path)
            # 自解压分卷重命名失败时，把文件名还原回 .exe + .eNN，方便用户手工排查
            await self._rollback_exe_e_remap(task)
            # .zip + .NNN 非标准分卷重命名失败时，把文件名还原回 .zip + .NNN
            await self._rollback_zip_numeric_remap(task)
            # .partN.exe WinRAR 自解压分卷重命名失败时，把文件名还原回 .partN.exe
            await self._rollback_part_exe_remap(task)
            return None

        try:
            # 记录成功使用的密码
            self._set_extract_meta(task, extract_stage="extracted")
            logger.info(f"外层压缩包解压成功，使用密码: {success_password or '无密码'}")

            payload_summary = await self._summarize_extracted_payload(output_path)
            if payload_summary["file_count"] <= 0 or payload_summary["total_bytes"] <= 0:
                self._set_extract_meta(
                    task,
                    extract_failure_reason="extract_incomplete",
                    extract_payload_file_count=payload_summary["file_count"],
                    extract_payload_total_bytes=payload_summary["total_bytes"],
                )
                raise RuntimeError("解压失败：解压产物为空或全部为 0 字节")
            self._set_extract_meta(
                task,
                extract_payload_file_count=payload_summary["file_count"],
                extract_payload_total_bytes=payload_summary["total_bytes"],
            )

            # 检查暂停和取消
            await task.wait_if_paused()
            if task.is_cancelled():
                logger.info(f"任务 {task.id} 在解压完成后被取消，清理已解压文件")
                await self._cleanup_extract_path(output_path)
                return None

            # 7. 验证解压完整性
            if archive_info_from_listing:
                verify_mode = "sample" if len([item for item in archive_info.file_list if not item.get('is_dir')]) > self.VERIFY_FULL_FILE_LIMIT else "full"
                self._set_extract_meta(task, extract_stage="verify", verify_mode=verify_mode)
                task.update_progress(90, "验证解压完整性")
                if not await self._verify_extraction(archive_info, output_path):
                    raise Exception("解压验证失败，文件不完整")
            else:
                logger.warning("解压前未能读取到压缩包目录，跳过基于清单的完整性校验: %s", archive_path)

            # 8. 检查并解压嵌套压缩包
            if self.config.extract.extract_nested_archives:
                self._set_extract_meta(task, extract_stage="nested_scan")
                task.update_progress(95, "检查嵌套压缩包")
                nested_count = await self._extract_nested_archives(
                    output_path,
                    task,
                    max_depth=self.config.extract.max_nested_depth,
                    parent_password=success_password,  # 传递成功使用的密码给嵌套压缩包
                    parent_encoding=getattr(archive_info, 'detected_encoding', None),  # 传递外层编码供嵌套 ZIP 使用
                )
                if nested_count > 0:
                    logger.info(f"解压了 {nested_count} 个嵌套压缩包")
                self._set_extract_meta(task, nested_archive_count=nested_count)
            else:
                logger.debug("嵌套压缩包解压已禁用")

            # 最终兜底：所有解压/嵌套解压结束后，只检查路径名，不读文件内容。
            # 前面的 unar 修复阶段用采样保证多密码尝试轻量；这里仅跑一次全树短路扫描。
            self._set_extract_meta(task, extract_stage="filename_encoding_guard")
            task.update_progress(97, "检查文件名编码")
            if await self._reject_if_garbled_after_extract(
                archive_path,
                output_path,
                cleanup=lambda: self._cleanup_extract_path(output_path),
                context="final_guard",
                task=task,
                ignore_garbled=bool((task.task_metadata or {}).get("manual_retry_ignore_garbled")),
            ):
                garbled_sample = str((task.task_metadata or {}).get("garbled_filename_sample") or "")
                final_garbled_score = float((task.task_metadata or {}).get("garbled_filename_score_after") or 0.0)
                task.update_progress(
                    97,
                    f"检测到疑似乱码文件名: {garbled_sample}",
                )
                raise RuntimeError(f"解压失败：文件名疑似乱码（样本：{garbled_sample}，评分：{final_garbled_score:.1f}）")

            self._set_extract_meta(task, extract_stage="done", extract_finished_at=datetime.now().isoformat())
            return output_path
        except Exception:
            await self._cleanup_extract_path(output_path)
            await self._rollback_exe_e_remap(task)
            await self._rollback_zip_numeric_remap(task)
            await self._rollback_part_exe_remap(task)
            raise

    def _pick_filename_matched_rjcode(self, password_candidates: List[Dict[str, Optional[str]]]) -> Optional[str]:
        for item in password_candidates or []:
            if item.get("source") != "密码库-文件名":
                continue
            normalized_rjcode = normalize_rjcode_value(item.get("rjcode"))
            if normalized_rjcode:
                return normalized_rjcode
        return None

    def _apply_filename_password_rj_hint(
        self,
        archive_path: str,
        task: Task,
        password_candidates: List[Dict[str, Optional[str]]],
    ) -> Optional[str]:
        matched_rjcode = self._pick_filename_matched_rjcode(password_candidates)
        if not matched_rjcode:
            return None

        if task.task_metadata is None:
            task.task_metadata = {}
        # 密码库同时填写了 filename + rjcode，视为用户显式权威绑定：
        # 强制覆盖任务 RJ、推断 RJ 和元数据 RJ，后续查重/重命名/分类统一用这个 RJ。
        task.task_metadata["inferred_rjcode"] = matched_rjcode
        task.task_metadata["rjcode"] = matched_rjcode
        task.task_metadata["inferred_rjcode_source"] = "password_entry_filename_match"
        task.task_metadata["rjcode_source"] = "password_entry_filename_match"
        task.task_metadata["rjcode_lock"] = True
        task.rjcode = matched_rjcode
        logger.info(
            "[Extract] 密码库按文件名+RJ 权威绑定，强制覆盖任务 RJ: source=%s rj=%s",
            archive_path,
            matched_rjcode,
        )
        return matched_rjcode

    async def lookup_filename_bound_rjcode(self, archive_path: str) -> Optional[str]:
        """预检阶段轻量查询：若密码库条目同时填写了 filename 和 rjcode，则返回其 rjcode。

        用于在解压前把任务的权威 RJ 切换到密码库绑定的 RJ，驱动查重/命名链路。
        """
        if not archive_path or not os.path.isfile(archive_path):
            return None
        from ..models.database import PasswordEntry, get_db

        filename_candidates = self._build_filename_candidates(archive_path)
        if not filename_candidates:
            return None

        db = next(get_db())
        try:
            entries = (
                db.query(PasswordEntry)
                .filter(PasswordEntry.filename.in_(filename_candidates))
                .all()
            )
            for entry in entries:
                normalized_rjcode = normalize_rjcode_value(entry.rjcode)
                if normalized_rjcode:
                    return normalized_rjcode
            return None
        finally:
            db.close()

    async def get_archive_info(self, archive_path: str) -> Optional[ArchiveInfo]:
        """Public wrapper for archive listing."""
        return await self._get_archive_info(archive_path)

    async def extract_selected_entries(
        self,
        archive_path: str,
        entry_names: List[str],
        output_path: Optional[str] = None,
    ) -> str:
        """
        Extract only the selected archive entries into a temporary directory.

        This reuses the existing password discovery flow and preserves the
        original relative paths inside the archive.
        """
        if not await self._ensure_7z_available():
            raise RuntimeError("找不到 7z 可执行文件，无法提取指定条目")

        normalized_entries: List[str] = []
        seen_entries = set()
        for item in entry_names or []:
            name = str(item or "").strip()
            if not name or name in seen_entries:
                continue
            seen_entries.add(name)
            normalized_entries.append(name)

        if not normalized_entries:
            raise ValueError("没有可提取的压缩包条目")

        archive_info = await self._get_archive_info(archive_path)
        if not archive_info:
            archive_info = ArchiveInfo(archive_path, [], None)

        created_temp_dir = False
        if output_path:
            os.makedirs(output_path, exist_ok=True)
        else:
            safe_name = re.sub(r'[<>:\"|?*]', '', Path(archive_path).stem.strip()) or "selected_extract"
            output_path = tempfile.mkdtemp(
                prefix=f"{safe_name}_selected_",
                dir=self.config.storage.temp_path
            )
            created_temp_dir = True

        list_file_path = os.path.join(output_path, "_selected_entries.txt")
        with open(list_file_path, "w", encoding="utf-8", newline="\n") as fp:
            for name in normalized_entries:
                fp.write(name)
                fp.write("\n")

        def cleanup_attempt_output():
            for name in os.listdir(output_path):
                current_path = os.path.join(output_path, name)
                if os.path.abspath(current_path) == os.path.abspath(list_file_path):
                    continue
                try:
                    if os.path.isdir(current_path):
                        shutil.rmtree(current_path, ignore_errors=True)
                    else:
                        os.remove(current_path)
                except Exception:
                    logger.debug("清理选择性解压残留失败: %s", current_path, exc_info=True)

        password_candidates = await self._get_password_candidates_for_archive(archive_info.path)
        vault_passwords = [item["password"] for item in password_candidates]
        rj_passwords = self._get_rj_passwords(archive_info.path)
        password_list = []
        password_list.extend(rj_passwords)
        password_list.extend(vault_passwords)
        if archive_info.password and archive_info.password not in password_list:
            password_list.append(archive_info.password)
        password_list.append("")
        password_list.extend(self.config.extract.password_list)

        seen_passwords = set()
        unique_passwords = []
        for password in password_list:
            if password in seen_passwords:
                continue
            seen_passwords.add(password)
            unique_passwords.append(password)

        for password in unique_passwords:
            await asyncio.to_thread(cleanup_attempt_output)
            password_args = [f"-p{password}"] if password else ["-p"]
            cmd = [
                self.seven_zip,
                "x",
                "-y",
                f"-o{output_path}",
                *self._get_seven_zip_mmt_args(),  # 指定 7z 多线程（默认 -mmt=on）
                *self._get_mcp_args(archive_info.path, archive_info),  # ZIP 文件名编码（仅 .zip 生效，避免 7zz 24.08 对 RAR 报 E_INVALIDARG）
                *password_args,
                archive_info.path,
                f"@{list_file_path}",
            ]

            result = await self._run_7z_command(cmd, capture_stdout=False)
            if result.returncode == 0:
                archive_info.password = password
                return output_path

        await asyncio.to_thread(cleanup_attempt_output)
        if created_temp_dir:
            try:
                await asyncio.to_thread(os.remove, list_file_path)
            except OSError:
                pass
        raise RuntimeError("选择性解压失败：未能使用现有密码策略提取目标条目")

    async def _classify_nested_small_archive(
        self,
        file_path: str,
        filename: str,
        current_root: str,
        scan_root: str,
        parent_password: Optional[str],
    ) -> str:
        """对 < NESTED_SUBTITLE_SIZE_THRESHOLD 的嵌套压缩包判断"是不是字幕包"。

        ★ 设计原则（修复用户痛点：命名不规范的奖励包漏解压）：
            **默认结果是 ``non_subtitle``，仅在"确凿是字幕包"时才返回 ``subtitle``。**
            漏判一个字幕包 → 字幕被解压到主目录（容易处理）；
            漏判一个奖励包 → 用户永远拿不到里面的内容（严重）；
            所以策略应当 **bias 向解压**，让字幕预检走"明确证据"路径。

        返回:
            ``"subtitle"``     - 仅当"强证据"指向字幕包时（关键词 + peek 一致）
            ``"non_subtitle"`` - 一切其他情况：命名不规范、peek 失败、含任何媒体 / 文档 / 嵌套包
                                这两个返回值在调用方完全等价（"unknown" 也走解压），保留两个值仅为日志可读

        强字幕证据（任一即跳过常规解压）：
        1. 文件名（去后缀）/ 父目录名 **以独立 token 形式** 含 NESTED_SUBTITLE_HINTS。
           整词匹配避免 "ass" 误命中 "assets" / "compass"。
        2. peek 内容清单：**至少 1 个字幕扩展名 且 0 个非字幕扩展名**（媒体 / 文档 /
           嵌套压缩包 / .txt 等都算非字幕，立即否决）。
        3. peek 失败（密码错 / 损坏 / 没条目）→ 一律 ``non_subtitle``，
           交由常规嵌套解压用密码列表逐个尝试，保证用户的奖励包不会漏。
        """
        try:
            stem = Path(filename).stem
        except Exception:
            stem = filename

        # 父级目录名也参与判定，覆盖 "folder/字幕组/RJxxx.zip" 这种结构。
        # 但只取相对 scan_root 的层级，避免把 scan_root 自身的前缀也卷进来。
        parent_segments: List[str] = []
        try:
            rel = os.path.relpath(current_root, scan_root)
            if rel and rel != ".":
                parent_segments = [seg for seg in re.split(r"[\\/]+", rel) if seg]
        except Exception:
            parent_segments = []

        # 整词匹配：把 stem / 父目录名按非字母数字字符切成 token
        # （考虑到中文不分词，中文关键词用 substring 匹配，英文关键词用 token 匹配）
        def _split_tokens(text: str) -> List[str]:
            return [tok for tok in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", text or "") if tok]

        all_tokens_lower: List[str] = []
        for segment in [stem, *parent_segments]:
            for tok in _split_tokens(segment):
                all_tokens_lower.append(tok.lower())
        joined_text = " ".join(all_tokens_lower)

        def _contains_chinese(text: str) -> bool:
            return any("\u4e00" <= ch <= "\u9fff" for ch in text)

        # 1. 字幕关键词命中
        for hint in self.NESTED_SUBTITLE_HINTS:
            hint_lower = hint.lower()
            if _contains_chinese(hint):
                # 中文关键词：substring 匹配（中文不分词）
                if hint_lower in joined_text:
                    logger.debug(
                        "嵌套小包命中字幕关键词（中文 substring）'%s'，判定为 subtitle: %s",
                        hint, filename,
                    )
                    return "subtitle"
            else:
                # 英文关键词：必须以独立 token 形式出现，避免子串误命中
                if hint_lower in all_tokens_lower:
                    logger.debug(
                        "嵌套小包命中字幕关键词（英文 token）'%s'，判定为 subtitle: %s",
                        hint, filename,
                    )
                    return "subtitle"

        # 2. peek 内容兜底
        file_list = None
        try:
            file_list = await self._list_archive_contents(file_path, parent_password or "")
            if file_list is None and parent_password:
                file_list = await self._list_archive_contents(file_path, "")
        except Exception as exc:
            logger.debug(
                "peek 嵌套小包内容失败（保守按 non_subtitle 走常规解压）: %s, %s",
                filename, exc,
            )
            file_list = None

        if not file_list:
            return "non_subtitle"

        subtitle_exts = {ext.lower() for ext in self.SUBTITLE_FILE_EXTENSIONS}
        non_subtitle_exts = self.NESTED_SMALL_ARCHIVE_MEDIA_EXTENSIONS

        subtitle_file_count = 0
        non_subtitle_file_count = 0
        unknown_ext_count = 0  # 既不是字幕也不在 non_subtitle_exts 里（含 .txt / 无后缀 / 私有扩展名）

        for entry in file_list:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            if entry.get("is_dir") or name.endswith("/") or name.endswith("\\"):
                continue
            ext = Path(name).suffix.lower()
            if ext in subtitle_exts:
                subtitle_file_count += 1
            elif ext in non_subtitle_exts:
                non_subtitle_file_count += 1
            else:
                # 例如 .txt / .nfo / .url / 无后缀 / 自定义后缀
                unknown_ext_count += 1

        # 强证据：至少 1 个字幕文件 + 0 个非字幕文件 + 0 个未知扩展名
        # 任何一个非字幕 / 未知扩展名都直接否决（说明是混合包，可能是奖励 + 说明 + 字幕，
        # 这种保守按"普通包"解压更安全）
        if subtitle_file_count > 0 and non_subtitle_file_count == 0 and unknown_ext_count == 0:
            logger.debug(
                "嵌套小包内容清一色字幕文件（%d 个），判定为 subtitle: %s",
                subtitle_file_count, filename,
            )
            return "subtitle"

        if non_subtitle_file_count > 0:
            logger.debug(
                "嵌套小包内含 %d 个媒体 / 文档 / 嵌套压缩包，走常规解压: %s",
                non_subtitle_file_count, filename,
            )
        elif unknown_ext_count > 0:
            logger.debug(
                "嵌套小包含 %d 个未知 / 文本类扩展名（保守走常规解压避免漏放）: %s",
                unknown_ext_count, filename,
            )
        else:
            logger.debug(
                "嵌套小包 peek 后无任何文件 / 全是空目录，按 non_subtitle 走常规解压: %s",
                filename,
            )
        return "non_subtitle"

    async def _extract_nested_archives(self, directory: str, task: Task, max_depth: int = 5, current_depth: int = 0, processed_paths: Optional[set] = None, parent_password: Optional[str] = None, parent_encoding: Optional[str] = None) -> int:
        """
        递归解压目录中的嵌套压缩包

        实现策略：先一次性扫描完本层目录树，收集到所有需要解压的嵌套压缩包，
        然后用 asyncio.gather 并发执行解压 + 删源 + 递归。底层 7z 子进程并发数
        仍由 ``_seven_zip_semaphore`` 限流（默认 2-3），所以不会把磁盘 / CPU 打爆，
        但能避免合集包场景下「7 个独立 RJ 内嵌包逐个 await」导致的串行阻塞。

        Args:
            directory: 要检查的目录
            task: 任务对象
            max_depth: 最大递归深度
            current_depth: 当前递归深度
            processed_paths: 已处理的文件路径集合（防止循环）
            parent_password: 外层压缩包使用的密码（优先尝试）

        Returns:
            解压的嵌套压缩包数量
        """
        if processed_paths is None:
            processed_paths = set()

        # 检查深度限制
        if current_depth >= max_depth:
            logger.warning(f"达到最大嵌套深度 {max_depth}，停止解压嵌套压缩包")
            return 0

        # 检查任务状态
        if task.is_cancelled():
            logger.info("任务被取消，停止解压嵌套压缩包")
            return 0
        await task.wait_if_paused()

        extracted_count = 0
        scanned_files = 0
        scanned_dirs = 0
        archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz'}

        # 阶段 0：残缺后缀修复 pass
        # 上传 / 打包过程中常见 `.partN.exe → .partN.ex`、`.partN.rar → .partN.ra` 这类后缀
        # 被截断 1 字符的情况，会让分卷组完全被嵌套扫描忽略（PE 头不在魔数表 / partN 非首卷跳过）。
        # 在正式扫描前先识别并改名，让原有的 VolumeSet / 分卷模式自动接管。
        try:
            rename_map = await self._repair_truncated_archive_extensions(directory)
            if rename_map:
                logger.info(
                    "[残缺后缀修复] 共修复 %s 个文件: %s",
                    len(rename_map),
                    directory,
                )
                # 修复后老路径也加入 processed_paths，避免后续扫描误处理已删除的旧名
                for old_path in rename_map.keys():
                    try:
                        processed_paths.add(os.path.realpath(old_path))
                    except OSError:
                        pass
        except Exception as exc:
            logger.warning("[残缺后缀修复] 入口修复失败（忽略，继续扫描）: %s", exc)

        # 阶段 1：扫描整个目录树，收集本层所有需要解压的嵌套压缩包。
        # 此阶段只做 IO 元数据扫描和魔数探测，不动 7z 子进程，逐项加入 ``pending``。
        # 字幕小包、分卷非首卷、已处理文件等仍按原规则就地跳过。
        pending: List[Dict[str, object]] = []
        stop_scan = False
        try:
            for root, dirs, files in os.walk(directory):
                dirs[:] = [
                    item for item in dirs
                    if item.lower() not in self.NESTED_SKIP_DIRS
                    and not item.lower().startswith((".git", "__pycache__"))
                ]
                scanned_dirs += 1
                if scanned_dirs > self.NESTED_SCAN_DIR_BUDGET:
                    logger.warning("嵌套压缩包目录扫描达到预算上限，停止扫描: %s", directory)
                    break
                if task.is_cancelled():
                    break
                await task.wait_if_paused()

                for filename in files:
                    scanned_files += 1
                    if scanned_files > self.NESTED_SCAN_FILE_BUDGET:
                        logger.warning("嵌套压缩包文件扫描达到预算上限，停止扫描: %s", directory)
                        stop_scan = True
                        break
                    file_path = os.path.join(root, filename)

                    # 检查是否已经处理过（防止循环）
                    file_real_path = os.path.realpath(file_path)
                    if file_real_path in processed_paths:
                        logger.debug(f"跳过已处理的文件: {filename}")
                        continue

                    # 检查后缀名或通过魔数检测
                    is_archive = False
                    ext = Path(filename).suffix.lower()
                    detected_archive_type = ""
                    if ext in archive_extensions:
                        is_archive = True
                        detected_archive_type = ext.lstrip(".")
                    else:
                        # 通过后缀名无法识别，尝试魔数检测
                        detected_archive_type = await self._detect_by_magic_bytes(file_path) or ""
                        is_archive = bool(detected_archive_type)

                    if not is_archive:
                        continue

                    # 分卷非首卷一律跳过
                    part_match = re.search(r'\.part(\d+)\.', filename, re.IGNORECASE)
                    if part_match and int(part_match.group(1)) > 1:
                        continue
                    if re.search(r'\.z\d{2}$', filename, re.IGNORECASE):
                        continue

                    logger.info(
                        f"发现嵌套压缩包: {filename} "
                        f"(深度: {current_depth + 1}, 父密码: {parent_password or '无'})"
                    )

                    # 小型压缩包（< NESTED_SUBTITLE_SIZE_THRESHOLD）的处理：
                    # 历史版本一律标记为字幕源、跳过常规解压，导致命名不规范的奖励包
                    # （bonus.zip / extra.zip / RJxxx特典.zip）永远漏解压。
                    # 现在改为"默认解压、仅在确凿是字幕包时跳过"：
                    #   - 文件名 / 父目录含字幕关键词（整词匹配，避免 ass 子串误命中）
                    #     → subtitle，跳过常规解压走字幕预检
                    #   - peek 内容清一色字幕扩展名（无任何媒体 / 文档 / .txt / 嵌套包）
                    #     → subtitle
                    #   - 其他一切（命名不规范 / peek 失败 / 含媒体 / 含说明 .txt）
                    #     → non_subtitle，走常规解压让密码列表逐个尝试，保证不漏奖励
                    try:
                        nested_archive_size = os.path.getsize(file_path)
                    except OSError:
                        nested_archive_size = 0
                    if 0 < nested_archive_size < self.NESTED_SUBTITLE_SIZE_THRESHOLD:
                        # subtitle_probe_mode：专门用于字幕补配预检的临时解包，直接展开小包
                        _is_probe = bool((task.task_metadata or {}).get("subtitle_probe_mode"))
                        if not _is_probe:
                            classification = await self._classify_nested_small_archive(
                                file_path,
                                filename,
                                root,
                                directory,
                                parent_password,
                            )
                            if classification == "subtitle":
                                logger.info(
                                    "嵌套压缩包 %.1fMB < 阈值 %.0fMB，识别为字幕源，跳过常规解压: %s",
                                    nested_archive_size / 1024 / 1024,
                                    self.NESTED_SUBTITLE_SIZE_THRESHOLD / 1024 / 1024,
                                    filename,
                                )
                                if task.task_metadata is None:
                                    task.task_metadata = {}
                                pending_subtitles = task.task_metadata.setdefault("nested_subtitle_archive_filenames", [])
                                if filename not in pending_subtitles:
                                    pending_subtitles.append(filename)
                                processed_paths.add(file_real_path)
                                continue  # 跳过常规嵌套解压
                            logger.info(
                                "嵌套压缩包 %.1fMB 但分类为非字幕（%s），走常规嵌套解压: %s",
                                nested_archive_size / 1024 / 1024,
                                classification,
                                filename,
                            )
                        else:
                            logger.info(
                                "[字幕预检] 嵌套小包 %.1fMB，字幕预检模式直接展开: %s",
                                nested_archive_size / 1024 / 1024,
                                filename,
                            )

                    if task.is_cancelled():
                        stop_scan = True
                        break

                    # 决定解压目标目录（避免重名）
                    archive_name = Path(filename).stem
                    nested_output_dir = os.path.join(root, archive_name)
                    counter = 1
                    original_output_dir = nested_output_dir
                    while os.path.exists(nested_output_dir):
                        nested_output_dir = f"{original_output_dir}_{counter}"
                        counter += 1
                    os.makedirs(nested_output_dir, exist_ok=True)

                    # 提前标记 processed，避免后续递归 / 折叠路径再次命中本文件。
                    # 即使阶段 2 失败，processed_paths 里多一个标记不会有副作用。
                    processed_paths.add(file_real_path)

                    pending.append({
                        "file_path": file_path,
                        "filename": filename,
                        "root": root,
                        "nested_output_dir": nested_output_dir,
                        "archive_type": detected_archive_type,
                    })

                if stop_scan:
                    break
        except Exception as e:
            logger.error(f"扫描嵌套压缩包时出错: {e}")

        if not pending:
            return 0

        # 阶段 2：并发解压。每个并发单元独立解压 → 删源 → 递归 → 折叠目录。
        # 底层 7z 子进程并发数仍由 ``_seven_zip_semaphore`` 控制，
        # 上层 gather 只是消除 await 串行阻塞。
        if len(pending) > 1:
            logger.info(
                "本层共发现 %d 个嵌套压缩包，启动并发解压（深度 %d）",
                len(pending), current_depth + 1,
            )

        async def _process_one(item: Dict[str, object]) -> int:
            file_path = str(item["file_path"])
            filename = str(item["filename"])
            root_dir = str(item["root"])
            nested_output_dir = str(item["nested_output_dir"])
            archive_type = str(item.get("archive_type") or "").strip().lower()

            if task.is_cancelled():
                return 0
            await task.wait_if_paused()

            try:
                task.update_progress(
                    95,
                    f"解压嵌套压缩包 {filename} (层{current_depth + 1})",
                )
                # 嵌套 ZIP 预填编码缓存：让 _try_extract_nested_direct → _get_mcp_args
                # 能取到父级检测到的编码（如 shift_jis→-mcp=932），避免日文嵌套 ZIP 乱码。
                # 继承优先级：
                #   1. 父级是非 UTF-8 有效编码 → 直接继承
                #   2. 父级是 UTF-8/空（7z/RAR 外层或无信息）→ 对嵌套 ZIP 做轻量嗅探
                _utf8_like = {'utf-8', 'utf_8', 'ascii', None}
                low_fp = file_path.lower()
                _is_zip_file = (
                    archive_type == "zip"
                    or low_fp.endswith('.zip')
                    or bool(re.search(r'\.zip\.\d+$', low_fp))
                )
                if _is_zip_file:
                    if parent_encoding and parent_encoding.lower() not in _utf8_like:
                        self.__class__._archive_encoding_cache.setdefault(file_path, parent_encoding)
                    elif file_path not in self.__class__._archive_encoding_cache:
                        # 父级无有效编码信息 → 用 zipfile 快速嗅探嵌套文件名字节流
                        sniffed = self._sniff_zip_encoding(file_path)
                        if sniffed:
                            logger.debug(f"[嵌套编码嗅探] {filename} → {sniffed}")
                            self.__class__._archive_encoding_cache[file_path] = sniffed
                nested_encoding = self.__class__._archive_encoding_cache.get(file_path) or parent_encoding
                success, nested_success_password = await self._try_extract_nested_direct(
                    file_path, nested_output_dir, parent_password
                )

                if not success:
                    logger.warning(f"无法解压嵌套压缩包: {filename} (已尝试所有密码)")
                    if os.path.exists(nested_output_dir):
                        try:
                            await asyncio.to_thread(shutil.rmtree, nested_output_dir, ignore_errors=True)
                        except Exception:
                            pass
                    raise RuntimeError(f"嵌套压缩包解压失败: {filename}")

                logger.info(
                    f"成功解压嵌套压缩包: {filename} "
                    f"(使用密码: {nested_success_password or '无密码'})"
                )

                # 删除原始的嵌套压缩包文件（含分卷）
                try:
                    volume_set = self._detect_volume_set(file_path)
                    if volume_set:
                        for volume_path in volume_set.volumes:
                            if os.path.exists(volume_path):
                                await asyncio.to_thread(os.remove, volume_path)
                                logger.info(f"已删除嵌套压缩包分卷文件: {volume_path}")
                    else:
                        await asyncio.to_thread(os.remove, file_path)
                        logger.info(f"已删除嵌套压缩包文件: {file_path}")
                except Exception as e:
                    logger.warning(f"删除嵌套压缩包文件失败: {file_path}, 错误: {e}")

                # 递归检查解压出来的目录，传递成功使用的密码和编码
                sub_count = await self._extract_nested_archives(
                    nested_output_dir,
                    task,
                    max_depth,
                    current_depth + 1,
                    processed_paths,
                    nested_success_password,
                    nested_encoding,
                )
                # 若解压目录为纯容器（无直接文件），折叠到父目录以节省磁盘空间
                await self._collapse_wrapper_dir(nested_output_dir, root_dir)
                return 1 + sub_count
            except Exception as e:
                logger.error(f"解压嵌套压缩包失败 {filename}: {e}")
                if os.path.exists(nested_output_dir):
                    try:
                        await asyncio.to_thread(shutil.rmtree, nested_output_dir, ignore_errors=True)
                    except Exception:
                        pass
                raise

        results = await asyncio.gather(
            *[_process_one(item) for item in pending],
            return_exceptions=True,
        )
        failed_nested_archives: List[str] = []
        for r in results:
            if isinstance(r, int):
                extracted_count += r
            elif isinstance(r, Exception):
                logger.error("嵌套解压并发任务异常: %s", r)
                failed_nested_archives.append(str(r))

        if failed_nested_archives:
            if task.task_metadata is None:
                task.task_metadata = {}
            task.task_metadata["nested_archive_failures"] = failed_nested_archives
            raise RuntimeError(
                "存在未成功解压的嵌套压缩包，已停止入库: "
                + "；".join(failed_nested_archives[:5])
            )

        return extracted_count

    async def _collapse_wrapper_dir(self, nested_dir: str, parent_dir: str) -> None:
        """若 nested_dir 内只有子目录（无直接文件），将子目录整体移入 parent_dir 后删除空壳。

        用于减少多层嵌套解压产生的中间目录层级，节省峰值磁盘占用。
        遇到同名冲突时跳过该条目，保留原目录结构。
        """
        if not os.path.isdir(nested_dir):
            return
        try:
            entries = os.listdir(nested_dir)
            if not entries:
                # 空目录直接删除
                await asyncio.to_thread(shutil.rmtree, nested_dir, ignore_errors=True)
                logger.debug("删除空嵌套目录: %s", nested_dir)
                return

            # 有直接文件则保留，不做折叠
            has_direct_files = any(
                os.path.isfile(os.path.join(nested_dir, e)) for e in entries
            )
            if has_direct_files:
                return

            # 只有子目录：尝试移入父目录
            moved_any = False
            for name in entries:
                src = os.path.join(nested_dir, name)
                dst = os.path.join(parent_dir, name)
                if os.path.exists(dst):
                    logger.debug("折叠嵌套目录时跳过同名项: %s", dst)
                    continue
                await asyncio.to_thread(shutil.move, src, dst)
                moved_any = True

            # 若目录已空，删除空壳
            remaining = os.listdir(nested_dir)
            if not remaining:
                await asyncio.to_thread(shutil.rmtree, nested_dir, ignore_errors=True)
                if moved_any:
                    logger.info("已折叠纯容器目录: %s -> %s", nested_dir, parent_dir)
        except Exception as e:
            logger.warning("折叠嵌套目录失败: %s, 错误: %s", nested_dir, e)

    async def _get_nested_archive_info(self, archive_path: str, parent_password: Optional[str] = None) -> Optional[ArchiveInfo]:
        """
        获取嵌套压缩包信息
        尝试所有可能的密码，返回能找到的第一个可用密码
        """
        # 构建密码列表：父密码优先，然后无密码，最后通用密码
        password_list = []

        # 1. 优先尝试父密码
        if parent_password:
            password_list.append(parent_password)

        # 2. 尝试无密码
        password_list.append("")

        # 3. 尝试通用密码
        password_list.extend(self.config.extract.password_list)

        # 去重（保持顺序）
        seen = set()
        unique_passwords = []
        for pwd in password_list:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)

        # 尝试所有密码，找到能读取内容的
        for password in unique_passwords:
            file_list = await self._list_archive_contents(archive_path, password)
            if file_list is not None:
                source = "父密码" if password == parent_password else ("无密码" if password == "" else "通用密码")
                logger.info(f"成功读取嵌套压缩包内容，使用: {source} ({password or '无密码'})")
                return ArchiveInfo(archive_path, file_list, password)

        return None

    async def _try_extract_nested(self, archive_info: ArchiveInfo, output_path: str, task: Task, parent_password: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """
        尝试解压嵌套压缩包
        尝试所有可能的密码：已知的密码、父密码、无密码、通用密码
        返回 (是否成功, 成功使用的密码)
        """
        # 构建完整的密码列表
        password_list = []

        # 1. 首先尝试已知的密码（从 _get_nested_archive_info 获取的）
        if archive_info.password:
            password_list.append((archive_info.password, "已知密码"))

        # 2. 尝试父密码（如果和已知密码不同）
        if parent_password and parent_password != archive_info.password:
            password_list.append((parent_password, "父密码"))

        # 3. 尝试无密码（如果还没试过）
        if "" != archive_info.password and "" != parent_password:
            password_list.append(("", "无密码"))

        # 4. 尝试通用密码（配置中的密码列表）
        for pwd in self.config.extract.password_list:
            if pwd and pwd != archive_info.password and pwd != parent_password:
                password_list.append((pwd, "通用密码"))

        logger.info(f"开始尝试解压嵌套压缩包，共 {len(password_list)} 个密码")

        for password, source in password_list:
            cmd = [
                self.seven_zip, 'x',
                '-y',  # 自动确认
                '-o' + output_path,  # 输出目录
                *self._get_seven_zip_mmt_args(),  # 指定 7z 多线程
                *self._get_mcp_args(archive_info.path, archive_info),  # ZIP 文件名编码（仅 .zip 生效）
                archive_info.path
            ]

            if password:
                cmd.append(f'-p{password}')
            else:
                cmd.append('-p')  # 空密码

            try:
                logger.info(f"尝试解压嵌套压缩包使用: {source} ({password or '无密码'})")
                result = await self._run_7z_command(cmd, capture_stdout=False)

                if result.returncode == 0:
                    logger.info(f"嵌套压缩包解压成功，使用: {source} ({password or '无密码'})")
                    # 更新archive_info中的密码，用于传递给下一层
                    archive_info.password = password
                    return True, password
                else:
                    logger.warning(f"密码 {source} ({password or '无密码'}) 解压失败")

            except Exception as e:
                logger.warning(f"嵌套压缩包解压尝试失败: {e}")
                continue

        logger.error(f"嵌套压缩包解压失败，已尝试所有 {len(password_list)} 个密码")
        return False, None

    async def _try_extract_nested_direct(
        self,
        archive_path: str,
        output_path: str,
        parent_password: Optional[str] = None,
    ) -> tuple[bool, Optional[str]]:
        """直接尝试解压嵌套压缩包，一次性收集所有密码候选，跳过多余的 list 步骤。

        密码优先级：父密码 > 无密码 > 配置密码列表 > 密码库查询结果（RJ/文件名/通用）
        返回 (是否成功, 成功使用的密码)
        """
        seen: set = set()
        password_list: List[str] = []

        def add(p: Optional[str]) -> None:
            v = normalize_password_value(p) if p else ""
            if v not in seen:
                seen.add(v)
                password_list.append(v)

        if parent_password:
            add(parent_password)
        add("")  # 无密码
        for pwd in self.config.extract.password_list:
            add(pwd)
        # 密码库查询只做一次，包含 RJ/文件名/通用条目
        vault_candidates = await self._get_password_candidates_for_archive(archive_path)
        for item in vault_candidates:
            add(item.get("password"))

        def clean_output() -> None:
            """清理上次失败尝试留下的残留文件"""
            for name in os.listdir(output_path):
                p = os.path.join(output_path, name)
                try:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
                except Exception:
                    pass

        logger.info("嵌套解压密码候选共 %d 个: %s", len(password_list), archive_path)

        # 嵌套 RAR fast-path：和外层主流程一样，优先用 unar 避开 7zz 24.08 RAR
        # 解析器无法配置文件名编码导致的日文 / 中文乱码（群晖看到 ��� 无法访问）。
        if (
            self.config.extract.prefer_unar_for_rar
            and self._is_rar_archive(archive_path)
            and self._find_unar_executable()
        ):
            unar_unsupported = False
            unar_disk_full = False
            for index, password in enumerate(password_list):
                if index > 0:
                    await asyncio.to_thread(clean_output)
                try:
                    result = await self._try_unar_extract(archive_path, output_path, password)
                    if result.returncode == 0:
                        # 乱码修复：Shift-JIS/GBK RAR 文件名自动编码探测失败时重试
                        await self._fix_unar_garbled_encoding(
                            archive_path, output_path, password,
                        )
                        garbled_sample = self._find_garbled_filename_sample(output_path, max_names=None)
                        if garbled_sample:
                            await asyncio.to_thread(clean_output)
                            logger.error(
                                "嵌套 RAR unar 解压后仍检测到乱码文件名，已清理产物: archive=%s sample=%s",
                                archive_path,
                                garbled_sample,
                            )
                            return False, None
                        logger.info(
                            "嵌套 RAR 用 unar 解压成功，密码: %s",
                            password or "无密码",
                        )
                        return True, password or None
                    stderr_lower = (result.stderr or b"").decode('utf-8', errors='ignore').lower()
                    if any(m in stderr_lower for m in (
                        "no space left on device",
                        "not enough space",
                        "disk full",
                    )):
                        unar_disk_full = True
                        break
                    if any(m in stderr_lower for m in (
                        "not a supported archive format",
                        "isn't a supported archive format",
                        "couldn't recognize the archive format",
                        "couldn't recognize",
                        "is not a recognized archive",
                    )):
                        unar_unsupported = True
                        break
                    logger.debug(
                        "嵌套 RAR unar 失败 (密码=%s, rc=%s): %s",
                        password or "无密码",
                        result.returncode,
                        stderr_lower[:200] if stderr_lower else "(无错误文本)",
                    )
                except Exception as e:
                    logger.warning("嵌套 RAR unar 解压尝试异常: %s", e)

            if unar_disk_full:
                logger.error("嵌套 RAR unar 解压因磁盘空间不足终止: %s", archive_path)
                return False, None

            # unar 没成 → 清空 output 让 7zz 接手
            await asyncio.to_thread(clean_output)
            logger.info(
                "嵌套 RAR unar fast-path 未成功 (unsupported=%s)，回退到 7zz: %s",
                unar_unsupported, archive_path,
            )

        for password in password_list:
            await asyncio.to_thread(clean_output)
            cmd = [self.seven_zip, "x", "-y", f"-o{output_path}", *self._get_seven_zip_mmt_args(), *self._get_mcp_args(archive_path), archive_path]
            cmd.append(f"-p{password}" if password else "-p")
            try:
                result = await self._run_7z_command(cmd, capture_stdout=False)
                if result.returncode == 0:
                    if await self._reject_if_garbled_after_extract(
                        archive_path,
                        output_path,
                        cleanup=lambda: asyncio.to_thread(clean_output),
                        context="嵌套压缩包 7zz",
                        task=None,
                    ):
                        return False, None
                    logger.info("嵌套压缩包解压成功，密码: %s", password or "无密码")
                    return True, password or None
                logger.debug("嵌套解压失败 (密码=%s, rc=%d)", password or "无密码", result.returncode)
            except Exception as e:
                logger.warning("嵌套压缩包解压尝试异常: %s", e)

        logger.warning("嵌套压缩包解压失败，已尝试所有 %d 个密码: %s", len(password_list), archive_path)
        return False, None

    async def _wait_file_stable(self, file_path: str, task: Optional[Task] = None, max_wait: int = 1800):
        """等待文件大小稳定（文件复制完成检测）

        改进点（解决群晖 NAS 上偶发"等 3600 秒超时"的死锁）：
        1. 同时观察 size 和 mtime；任一维度连续稳定 file_stable_checks 次即视为完成。
        2. PermissionError 累计上限：超过 stable_checks * 6 次后，只要 size 已经稳定，
           就认为是 NAS / SMB 临时锁，软放行避免无限循环。
        3. 默认 max_wait 1800 秒（30 分钟），避免单文件检测把任务卡 1 小时。
        4. size 偶发"回退到更小值"按抖动处理（NAS stat 缓存可能瞬时不一致），
           不再 reset stable_count，但会重新对齐 size。
        """
        config = self.config.processing
        previous_size = -1
        previous_mtime = -1.0
        stable_count = 0
        permission_failures = 0
        max_permission_failures = max(20, config.file_stable_checks * 6)
        start_time = asyncio.get_event_loop().time()
        last_progress_time = start_time
        last_max_size = 0

        logger.info(f"开始等待文件复制完成: {file_path}")

        while stable_count < config.file_stable_checks:
            current_time = asyncio.get_event_loop().time()

            # 检查总超时
            if current_time - start_time > max_wait:
                raise TimeoutError(f"等待文件复制完成超时 ({max_wait}秒): {file_path}")

            # 检查任务是否被取消
            if task and task.is_cancelled():
                logger.info(f"任务在等待文件复制时被取消: {file_path}")
                return

            # 检查任务是否暂停
            if task:
                await task.wait_if_paused()

            try:
                # 检查文件是否存在
                if not os.path.exists(file_path):
                    await asyncio.sleep(config.file_stable_interval)
                    continue

                # 获取文件大小 + mtime
                stat = os.stat(file_path)
                current_size = stat.st_size
                current_mtime = stat.st_mtime

                # 检查文件是否为空或太小（可能是刚开始复制）
                if current_size < 1024:  # 小于1KB认为可能是刚开始复制
                    logger.debug(f"文件太小 ({current_size} bytes)，等待更多数据写入...")
                    await asyncio.sleep(config.file_stable_interval)
                    continue

                # NAS / SMB 偶发的"size 瞬时回退"按抖动处理：保留历史最大值，
                # 但只要 size 不再增长就视作"未变化"，避免 stat 缓存抖动让计数永远归零。
                size_grew = current_size > last_max_size
                last_max_size = max(last_max_size, current_size)
                size_stable = (current_size == previous_size) and not size_grew
                mtime_stable = (
                    previous_mtime > 0
                    and abs(current_mtime - previous_mtime) < 1e-3
                )

                if size_stable or mtime_stable:
                    stable_count += 1
                    # 尝试打开文件检查是否被锁定
                    try:
                        with open(file_path, 'rb') as f:
                            f.read(1)
                        permission_failures = 0
                        if stable_count >= config.file_stable_checks:
                            logger.info(
                                f"文件复制完成检测通过: {file_path} ({current_size} bytes, "
                                f"size_stable={size_stable}, mtime_stable={mtime_stable})"
                            )
                            return
                    except (PermissionError, OSError) as exc:
                        permission_failures += 1
                        # 软放行：size 已经稳定但反复读不到（典型 NAS / SMB 临时锁），
                        # 累积超过阈值后认为可以放行，避免 1 小时死锁。
                        if size_stable and permission_failures >= max_permission_failures:
                            logger.warning(
                                "文件 size 稳定但读取持续失败 %d 次，软放行: %s, %s",
                                permission_failures, file_path, exc,
                            )
                            return
                        logger.debug(
                            f"文件仍被锁定 ({permission_failures}/{max_permission_failures}): {file_path}, {exc}"
                        )
                        stable_count = 0
                else:
                    # 文件还在变化
                    if stable_count > 0:
                        logger.info(f"文件仍在复制中，当前大小: {current_size} bytes")
                    stable_count = 0
                    last_progress_time = current_time

                previous_size = current_size
                previous_mtime = current_mtime

                # 如果长时间没有进度，发出警告
                if current_time - last_progress_time > 60:  # 1分钟没有变化
                    logger.warning(f"文件复制可能已停滞: {file_path}, 当前大小: {current_size} bytes")

            except Exception as e:
                logger.warning(f"等待文件稳定时出错: {e}")
                await asyncio.sleep(config.file_stable_interval)
                continue

            await asyncio.sleep(config.file_stable_interval)

    async def _repair_extension(self, file_path: str) -> str:
        """修复文件后缀名和文件名

        处理情况：
        1. 有常见压缩后缀名但类型不匹配 → 修复后缀名
        2. 无后缀名或后缀名不常见，但检测到是压缩文件 → 规范化文件名并添加正确的后缀名

        文件名规范化：
        - 39.RJ01570159 → RJ01570159.rar
        - 01503161 → RJ01503161.zip
        """
        if not self.config.extract.auto_repair_extension:
            return file_path

        filename = Path(file_path).name
        current_ext = Path(file_path).suffix.lower()

        # 跳过自解压文件（.exe）
        if filename.lower().endswith('.exe'):
            logger.info(f"跳过自解压文件后缀名修复: {file_path}")
            return file_path

        # 跳过分卷压缩文件（包括 WinRAR 自解压分卷首卷 .part1.exe）
        import re
        if re.search(r'\.part\d+\.(rar|zip|7z|exe)$', filename, re.IGNORECASE):
            logger.info(f"跳过分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 跳过无扩展名的分卷压缩文件 (.part1, .part2, ...)
        if re.search(r'\.part\d+$', filename, re.IGNORECASE):
            logger.info(f"跳过无扩展名的分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 跳过 ZIP 分卷压缩文件 (.z01, .z02, ...)
        if re.search(r'\.z\d+$', filename, re.IGNORECASE):
            logger.info(f"跳过 ZIP 分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 跳过 7z 分卷压缩文件 (.7z.001, .7z.002, ...)
        if re.search(r'\.7z\.\d{3}$', filename, re.IGNORECASE):
            logger.info(f"跳过 7z 分卷压缩文件后缀名修复: {file_path}")
            return file_path

        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}

        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if not real_type:
            logger.warning(f"无法检测文件类型: {file_path}")
            return file_path

        correct_ext = self._get_correct_extension(real_type)

        # 情况1: 文件有常见压缩后缀名，检查是否需要修复
        if current_ext in common_archive_extensions:
            if current_ext != f".{correct_ext}":
                new_path = await asyncio.to_thread(self._rename_with_extension, file_path, correct_ext)
                logger.info(f"修复后缀名: {file_path} -> {new_path}")
                return new_path
            return file_path

        # 情况2: 文件无后缀名或后缀名不常见，但检测到是压缩文件
        # 需要规范化文件名并添加后缀名
        # 注意：使用完整文件名而不是 stem，因为 Path.suffix 可能误识别
        # 例如：39.RJ01570159 的 stem 是 "39"，suffix 是 ".RJ01570159"
        full_filename = Path(file_path).name  # 获取完整文件名
        normalized_name = self._normalize_filename(full_filename)
        new_path = self._rename_with_normalized_name(file_path, normalized_name, correct_ext)
        logger.info(f"规范文件名并添加后缀: {file_path} -> {new_path}")
        return new_path

    def _normalize_filename(self, filename: str) -> str:
        """规范化文件名，提取或构造RJ号

        例如:
        - 39.RJ01570159 → RJ01570159
        - 01503161 → RJ01503161
        - RJ123456 → RJ123456
        """
        # 先匹配标准RJ号格式，8位优先于6位
        rj_match = re.search(r'[RVB]J(\d{8}|\d{6})(?!\d)', filename, re.IGNORECASE)
        if rj_match:
            return rj_match.group(0).upper()

        # 匹配纯数字，8位优先于6位
        num_match = re.search(r'(\d{8}|\d{6})(?!\d)', filename)
        if num_match:
            return f"RJ{num_match.group(1)}"

        return filename

    def _rename_with_normalized_name(self, file_path: str, new_name: str, ext: str) -> str:
        """用规范化的文件名重命名文件并添加后缀"""
        path = Path(file_path)
        new_filename = f"{new_name}.{ext}"
        new_path = path.parent / new_filename

        counter = 1
        while new_path.exists():
            new_filename = f"{new_name}({counter}).{ext}"
            new_path = path.parent / new_filename
            counter += 1

        os.rename(file_path, new_path)
        return str(new_path)

    async def normalize_archive_filename(self, file_path: str) -> str:
        """规范化压缩包文件名（在任务创建前调用）

        如果文件名需要规范化，会重命名文件并返回新路径
        如果不需要规范化，返回原路径

        对于分卷压缩文件，会统一规范化整个分卷组
        """
        if not self.config.extract.auto_repair_extension:
            return file_path

        path = Path(file_path)
        filename = path.name
        current_ext = path.suffix.lower()

        # 检查是否是分卷压缩文件
        volume_set = self._detect_volume_set(file_path)
        if volume_set:
            # 对于 .7z.xxx 格式的分卷，完全跳过规范化（这种格式已经是正确的）
            if volume_set.type == '7z_volume_with_ext':
                logger.info(f"[VolumeNormalize] .7z.xxx 格式的分卷，跳过规范化: {filename}")
                return file_path
            return await self._normalize_volume_set(file_path, volume_set)

        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}

        # 如果文件已有常见压缩后缀名，不需要规范化文件名
        if current_ext in common_archive_extensions:
            return file_path

        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if not real_type:
            logger.info(f"[Normalize] 无法检测文件类型，保持原样: {file_path}")
            return file_path

        correct_ext = self._get_correct_extension(real_type)

        # 规范化文件名
        normalized_name = self._normalize_filename(filename)

        # 检查是否需要重命名
        # 1. 文件名需要规范化
        # 2. 或者文件缺少后缀需要添加
        need_rename = normalized_name != filename

        # 检查文件是否缺少后缀（当前无后缀或后缀不是常见压缩格式）
        current_has_valid_ext = current_ext in common_archive_extensions

        if not need_rename and current_has_valid_ext:
            # 文件名已规范化且有有效后缀，无需处理
            return file_path

        if not need_rename and not current_has_valid_ext:
            # 文件名已规范化但缺少后缀，只添加后缀
            new_filename = f"{normalized_name}.{correct_ext}"
            new_path = os.path.join(os.path.dirname(file_path), new_filename)
            logger.info(f"[RENAME] 添加缺失的后缀: {file_path} -> {new_path}")

            # 处理重名
            counter = 1
            while os.path.exists(new_path):
                new_filename = f"{normalized_name}({counter}).{correct_ext}"
                new_path = os.path.join(os.path.dirname(file_path), new_filename)
                counter += 1

            await asyncio.to_thread(os.rename, file_path, new_path)
            return new_path

        # 文件名需要规范化，重命名文件
        new_path = await asyncio.to_thread(self._rename_with_normalized_name, file_path, normalized_name, correct_ext)
        logger.info(f"[RENAME] 文件名规范化: {file_path} -> {new_path}")
        return new_path

    async def _normalize_volume_set(self, file_path: str, volume_set: 'VolumeSet') -> str:
        """规范化分卷压缩包组的文件名

        例如: 39.RJ123456.part1.rar, 39.RJ123456.part2.rar -> RJ123456.part1.rar, RJ123456.part2.rar

        对于 .7z.xxx 格式的分卷，保持 .7z.xxx 后缀不变
        """
        base_name = volume_set.base_name
        vtype = volume_set.type

        # 对于 .7z.xxx 格式的分卷，完全跳过规范化（这种格式是正确的）
        if vtype == '7z_volume_with_ext':
            # 检查首卷文件名格式
            first_volume = volume_set.entry_path or (volume_set.volumes[0] if volume_set.volumes else file_path)
            first_filename = os.path.basename(first_volume)
            # 检查是否符合 RJxxxxxx.7z.001 格式（RJ号开头，然后是 .7z.分卷号）
            if re.match(r'^RJ\d+\.7z\.\d{3}$', first_filename, re.IGNORECASE):
                logger.info(f"[VolumeNormalize] 分卷文件名已是标准格式，无需修改: {first_filename}")
                return file_path

        normalized_base = self._normalize_filename(base_name)

        logger.info(f"[VolumeNormalize] base_name={base_name}, normalized_base={normalized_base}, vtype={vtype}")

        if normalized_base == base_name:
            logger.info(f"分卷组文件名无需规范化: {base_name}")
            return file_path

        directory = os.path.dirname(file_path)
        rename_map = []

        for volume_path in volume_set.volumes:
            volume_filename = os.path.basename(volume_path)
            pattern = self._get_volume_pattern(volume_filename)
            logger.info(f"[VolumeNormalize] 处理分卷: {volume_filename}, pattern={pattern}")
            if pattern:
                suffix = pattern.group(0)
                new_filename = f"{normalized_base}{suffix}"
                new_path = os.path.join(directory, new_filename)
                rename_map.append((volume_path, new_path))
                logger.info(f"[VolumeNormalize] 计划重命名: {volume_filename} -> {new_filename}")

        if not rename_map:
            logger.warning(f"[VolumeNormalize] 没有找到需要重命名的分卷文件")
            return file_path

        for old_path, new_path in rename_map:
            if old_path != new_path and os.path.exists(old_path):
                await asyncio.to_thread(os.rename, old_path, new_path)
                logger.info(f"[RENAME] 分卷重命名: {old_path} -> {new_path}")

        target_entry_path = volume_set.entry_path or file_path
        for old_path, new_path in rename_map:
            if old_path == target_entry_path:
                return new_path
        return rename_map[0][1]

    def _get_volume_pattern(self, filename: str) -> Optional[re.Match]:
        """获取分卷后缀模式匹配"""
        patterns = [
            r'\.7z\.\d{3}$',                # .7z.001, .7z.002 (7z分卷，带.7z扩展名)
            r'\.part\d+\.(rar|zip|7z|exe)$',  # 带扩展名的分卷，WinRAR SFX 首卷是 .part1.exe
            r'\.part\d+$',                  # 无扩展名的分卷 (如 .part1)
            r'\.z\d{2}$',
            r'\.r\d{2}$',
            r'\.zip$',
            r'\.rar$',
            r'\.\d{3}$',
            r'\.\d{2}$',
        ]
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return match
        return None

    def _get_volume_set_normalized_filename(self, file_path: str, volume_set: 'VolumeSet') -> Optional[str]:
        """获取分卷组规范化后的首卷文件名（不执行重命名）

        返回首卷的规范化文件名，如果不需要规范化则返回 None
        """
        base_name = volume_set.base_name
        normalized_base = self._normalize_filename(base_name)

        if normalized_base == base_name:
            logger.debug(f"[Normalize] 分卷组文件名无需规范化: {base_name}")
            return None

        first_volume = volume_set.entry_path or (volume_set.volumes[0] if volume_set.volumes else file_path)
        first_filename = os.path.basename(first_volume)
        pattern = self._get_volume_pattern(first_filename)

        if pattern:
            suffix = pattern.group(0)
            result = f"{normalized_base}{suffix}"
            logger.info(f"[Normalize] 需要规范化分卷组: {base_name} -> {normalized_base}, 首卷: {first_filename} -> {result}")
            return result

        return None

    async def get_normalized_filename(self, file_path: str) -> Optional[str]:
        """获取规范化后的文件名（不执行重命名）

        返回规范化后的完整文件名，如果不需要规范化则返回 None

        对于分卷压缩文件，返回首卷的规范化文件名
        """
        if not self.config.extract.auto_repair_extension:
            logger.debug(f"[Normalize] auto_repair_extension 未启用")
            return None

        path = Path(file_path)
        filename = path.name
        current_ext = path.suffix.lower()

        logger.debug(f"[Normalize] 检查文件: {filename}, 当前后缀: {current_ext}")

        # 检查是否是分卷压缩文件
        volume_set = self._detect_volume_set(file_path)
        if volume_set:
            return self._get_volume_set_normalized_filename(file_path, volume_set)

        # 常见压缩后缀名
        common_archive_extensions = {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.z01', '.z'}

        # 如果文件已有常见压缩后缀名，不需要规范化
        if current_ext in common_archive_extensions:
            logger.debug(f"[Normalize] 已有常见压缩后缀，跳过: {current_ext}")
            return None

        # 规范化文件名
        normalized_name = self._normalize_filename(filename)
        logger.debug(f"[Normalize] 规范化结果: {filename} -> {normalized_name}")

        if normalized_name == filename:
            logger.debug(f"[Normalize] 文件名不需要变化")
            return None

        # 检测真实文件类型
        real_type = await self._detect_real_type(file_path)
        if real_type:
            correct_ext = self._get_correct_extension(real_type)
            logger.debug(f"[Normalize] 检测到类型: {real_type}, 正确后缀: {correct_ext}")
        else:
            # 如果检测不到类型，尝试从文件名推断
            if re.search(r'\.(rar|zip|7z)$', filename, re.IGNORECASE):
                match = re.search(r'\.(rar|zip|7z)$', filename, re.IGNORECASE)
                correct_ext = match.group(1).lower()
            else:
                # 默认使用 rar
                correct_ext = 'rar'
            logger.debug(f"[Normalize] 无法检测类型，使用默认: {correct_ext}")

        result = f"{normalized_name}.{correct_ext}"
        logger.info(f"[Normalize] 需要规范化: {filename} -> {result}")
        return result

    async def _detect_real_type(self, file_path: str) -> Optional[str]:
        """检测文件真实类型"""
        # 方法1: 使用 filetype 库（添加重试机制）
        max_retries = 3
        for retry in range(max_retries):
            try:
                kind = filetype.guess(file_path)
                if kind:
                    return kind.extension
                break
            except PermissionError:
                if retry < max_retries - 1:
                    logger.warning(f"文件访问被拒绝，等待后重试 ({retry + 1}/{max_retries}): {file_path}")
                    await asyncio.sleep(2)  # 等待2秒再试
                else:
                    logger.error(f"文件访问被拒绝，跳过 filetype 检测: {file_path}")

        # 方法2: 使用 7z 测试
        try:
            result = await self._run_7z_command([self.seven_zip, 'l', file_path])
            if result.returncode == 0:
                # 从输出中检测格式
                output = result.stdout.decode('utf-8', errors='ignore')
                if 'Type = 7z' in output:
                    return '7z'
                elif 'Type = zip' in output:
                    return 'zip'
                elif 'Type = rar' in output:
                    return 'rar'
        except Exception as e:
            logger.error(f"7z检测失败: {e}")

        # 方法3: 魔数检测
        magic_result = await self._detect_by_magic_bytes(file_path)
        return magic_result

    async def _repair_truncated_archive_extensions(self, directory: str) -> Dict[str, str]:
        r"""修复嵌套目录里被截断的压缩包后缀。

        典型场景：上传 / 打包过程中文件名后缀被截断 1 字符，导致：
          - `RJxxx.part1.ex` 应是 `.part1.exe`（SFX 自解压首卷，PE/MZ 头不在魔数表）
          - `RJxxx.part2.ra` 应是 `.part2.rar`（虽 Rar! 头能识别，但 .partN. 被判非首卷跳过）
        结果整个分卷组被嵌套扫描忽略。本函数在嵌套扫描入口先扫一遍，识别此类截断
        并用魔数 / SFX 内嵌签名探测真实类型后改名为标准 `.partN.exe / .partN.rar / .partN.7z`。

        策略：
          1. 匹配 `\.part(\d+)\.<1-3 字符>$` 的截断候选（后缀不能在 valid 列表里）
          2. 用 `_detect_truncated_archive_real_ext` 探测真实类型（含 PE 头 SFX 内嵌签名扫描）
          3. 改名为正确后缀；改名失败 / 目标已存在则跳过。

        Returns: `{old_path: new_path}` 修复映射；空 dict 表示无修复。
        """
        rename_map: Dict[str, str] = {}
        # `.partN.X` 中合法的 X：现有 `_detect_volume_set` 已支持的 SFX 分卷后缀
        valid_part_exts = {'exe', 'rar', 'zip', '7z'}
        truncated_pattern = re.compile(r'^(?P<base>.+\.part\d+)\.(?P<ext>[a-z0-9]{1,3})$', re.IGNORECASE)
        try:
            walk_iter = os.walk(directory)
        except Exception as exc:
            logger.warning(f"[残缺后缀修复] 扫描目录失败: {directory}, {exc}")
            return rename_map
        for root, dirs, files in walk_iter:
            dirs[:] = [
                d for d in dirs
                if d.lower() not in self.NESTED_SKIP_DIRS
                and not d.lower().startswith((".git", "__pycache__"))
            ]
            for filename in files:
                m = truncated_pattern.match(filename)
                if not m:
                    continue
                ext = m.group('ext').lower()
                if ext in valid_part_exts:
                    continue  # 已是合法 .partN.X 后缀
                file_path = os.path.join(root, filename)
                try:
                    real_ext = await self._detect_truncated_archive_real_ext(file_path)
                except Exception as exc:
                    logger.debug(f"[残缺后缀修复] 探测真实类型失败: {filename}, {exc}")
                    continue
                if not real_ext:
                    continue
                new_filename = f"{m.group('base')}.{real_ext}"
                new_path = os.path.join(root, new_filename)
                if os.path.exists(new_path):
                    logger.warning(
                        f"[残缺后缀修复] 目标已存在，跳过: {filename} → {new_filename}"
                    )
                    continue
                try:
                    os.rename(file_path, new_path)
                    rename_map[file_path] = new_path
                    logger.info(
                        f"[残缺后缀修复] {filename} → {new_filename} (探测真实格式={real_ext})"
                    )
                except OSError as exc:
                    logger.warning(f"[残缺后缀修复] 改名失败: {filename}, {exc}")
        return rename_map

    async def _detect_truncated_archive_real_ext(self, file_path: str) -> Optional[str]:
        """对后缀不完整的文件，用魔数 + SFX 内嵌签名探测真实压缩格式后缀。

        Returns:
          - 'zip' / 'rar' / '7z'：标准压缩格式
          - 'exe'：PE/MZ 头且前 8MB 内含 7z/RAR 签名的 SFX 自解压
          - None：非压缩文件 / 无法识别
        """
        try:
            with open(file_path, 'rb') as f:
                header = f.read(8)
        except Exception:
            return None
        # 标准压缩格式魔数
        if header.startswith(b'PK\x03\x04') or header.startswith(b'PK\x05\x06') or header.startswith(b'PK\x07\x08'):
            return 'zip'
        if header.startswith(b'Rar!'):
            return 'rar'
        if header.startswith(b'7z\xbc\xaf\x27\x1c'):
            return '7z'
        # PE/MZ 头：可能是 SFX 自解压。复用 _probe_sfx_inner_format 扫前 8MB 找内嵌签名
        if header.startswith(b'MZ'):
            inner_fmt = await asyncio.to_thread(self._probe_sfx_inner_format, file_path)
            if inner_fmt in ('rar', '7z'):
                return 'exe'
        return None

    async def _detect_by_magic_bytes(self, file_path: str) -> Optional[str]:
        """通过魔数检测文件类型"""
        magic_bytes = {
            b'PK\x03\x04': 'zip',
            b'PK\x05\x06': 'zip',  # 空zip
            b'PK\x07\x08': 'zip',  # zip64
            b'Rar!': 'rar',
            b'7z\xBC\xAF\x27\x1C': '7z',
        }

        # 添加重试机制
        max_retries = 3
        for retry in range(max_retries):
            try:
                with open(file_path, 'rb') as f:
                    header = f.read(8)
                    for magic, file_type in magic_bytes.items():
                        if header.startswith(magic):
                            return file_type
                break
            except PermissionError:
                if retry < max_retries - 1:
                    logger.warning(f"魔数检测文件访问被拒绝，等待后重试 ({retry + 1}/{max_retries}): {file_path}")
                    await asyncio.sleep(2)
                else:
                    logger.error(f"魔数检测文件访问被拒绝: {file_path}")
            except Exception as e:
                logger.error(f"魔数检测失败: {e}")
                break

        return None

    def _get_correct_extension(self, file_type: str) -> str:
        """获取正确的后缀名"""
        extension_map = {
            'zip': 'zip',
            'rar': 'rar',
            '7z': '7z',
            'gz': 'gz',
            'bz2': 'bz2',
            'xz': 'xz',
        }
        return extension_map.get(file_type, file_type)

    def _rename_with_extension(self, file_path: str, new_ext: str) -> str:
        """重命名文件并修改后缀（用于已有错误后缀的文件）"""
        path = Path(file_path)
        new_name = f"{path.stem}.{new_ext}"
        new_path = path.parent / new_name

        counter = 1
        while new_path.exists():
            new_name = f"{path.stem}({counter}).{new_ext}"
            new_path = path.parent / new_name
            counter += 1

        os.rename(file_path, new_path)
        return str(new_path)

    def _add_extension(self, file_path: str, ext: str) -> str:
        """为文件添加后缀名（用于无后缀或后缀不正确的压缩文件）

        例如: 39.RJ01570159 -> 39.RJ01570159.rar
              01503161 -> 01503161.zip
        """
        path = Path(file_path)
        new_name = f"{path.name}.{ext}"
        new_path = path.parent / new_name

        counter = 1
        while new_path.exists():
            new_name = f"{path.name}({counter}).{ext}"
            new_path = path.parent / new_name
            counter += 1

        os.rename(file_path, new_path)
        return str(new_path)

    def _detect_volume_set(self, file_path: str) -> Optional['VolumeSet']:
        """检测是否是分卷压缩包"""
        directory = os.path.dirname(file_path)
        filename = os.path.basename(file_path)

        zip_main_match = re.search(r'^(?P<base>.+)\.zip$', filename, re.IGNORECASE)
        zip_part_match = re.search(r'^(?P<base>.+)\.z\d{2}$', filename, re.IGNORECASE)
        if zip_main_match or zip_part_match:
            base_name = (zip_main_match or zip_part_match).group('base')
            volume_set = self._build_zip_volume_set(directory, base_name)
            if volume_set:
                logger.info(f"[VolumeSet] 检测到 ZIP 分卷组: {base_name}")
                return volume_set

        rar_main_match = re.search(r'^(?P<base>.+)\.rar$', filename, re.IGNORECASE)
        rar_part_match = re.search(r'^(?P<base>.+)\.r\d{2}$', filename, re.IGNORECASE)
        if rar_main_match or rar_part_match:
            base_name = (rar_main_match or rar_part_match).group('base')
            volume_set = self._build_rar_old_volume_set(directory, base_name)
            if volume_set:
                logger.info(f"[VolumeSet] 检测到旧式 RAR 分卷组: {base_name}")
                return volume_set

        # 自解压 .exe + .eNN 国产 SFX 分卷组
        exe_main_match = re.search(r'^(?P<base>.+)\.exe$', filename, re.IGNORECASE)
        exe_part_match = re.search(r'^(?P<base>.+)\.e\d{2}$', filename, re.IGNORECASE)
        if exe_main_match or exe_part_match:
            base_name = (exe_main_match or exe_part_match).group('base')
            volume_set = self._build_exe_e_volume_set(directory, base_name)
            if volume_set:
                logger.info(f"[VolumeSet] 检测到自解压分卷组(.exe + .eNN): {base_name}")
                return volume_set

        # 分卷模式识别（按优先级排序，更具体的模式在前）
        # WinRAR 自解压分卷首卷常用 .part1.exe，后续卷继续用 .partN.rar/.exe，
        # 这里把 .exe 一并纳入 partN 模式，避免首卷被当成普通 SFX 单体解压。
        patterns = [
            (r'\.7z\.(\d{3})$', '7z_volume_with_ext'),  # .7z.001, .7z.002 (7z分卷，带.7z扩展名)
            (r'\.part(\d+)\.(rar|zip|7z|exe)$', 'part'),
            (r'\.part(\d+)$', 'part_no_ext'),  # 无扩展名的RAR分卷格式
            (r'\.(\d{3})$', '7z_volume'),  # 纯数字分卷（如 .001, .002）
            (r'\.(\d{2})$', 'generic'),
        ]

        for pattern, vtype in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                # 正确提取base_name，保留完整的基础名称，只移除分卷后缀
                base_name = re.sub(pattern, '', filename)
                logger.info(f"[VolumeSet] 检测到分卷模式: {filename}, base_name={base_name}, pattern={pattern}, vtype={vtype}")

                # 查找目录中所有匹配该基础名称和模式的文件
                volumes = self._find_all_volumes(directory, base_name, pattern)
                logger.info(f"[VolumeSet] 找到 {len(volumes)} 个分卷: {volumes}")

                # 对于 part 类型的分卷，必须有多个文件才算分卷组
                if vtype in ['part', 'part_no_ext'] and len(volumes) > 1:
                    return VolumeSet(base_name, volumes, vtype, entry_path=volumes[0])
                # 对于其他类型的分卷，也需要至少2个文件
                elif len(volumes) > 1:
                    return VolumeSet(base_name, volumes, vtype, entry_path=volumes[0])

        return None

    def _build_zip_volume_set(self, directory: str, base_name: str) -> Optional['VolumeSet']:
        zip_path = os.path.join(directory, f"{base_name}.zip")
        if not os.path.exists(zip_path):
            return None

        # 1. 标准 WinRAR ZIP 分卷 (.zXX)：X.zip + X.z01 + X.z02 + ...
        z_volumes: List[str] = []
        try:
            for file in os.listdir(directory):
                if re.fullmatch(rf'{re.escape(base_name)}\.z\d{{2}}', file, re.IGNORECASE):
                    z_volumes.append(os.path.join(directory, file))
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找 ZIP 分卷失败: {exc}")
            return None

        if z_volumes:
            z_volumes.append(zip_path)
            ordered = sorted(z_volumes, key=self._volume_sort_key)
            return VolumeSet(base_name, ordered, 'zip_volume_main', entry_path=zip_path)

        # 2. 非标准 .zip 主卷 + .NNN 纯数字分卷：X.zip + X.002 + X.003 + ...
        #    这是 7-Zip / 国内分卷工具创建多卷时把首卷 .zip.001 改名为 .zip 留下的格式，
        #    后续 .002/.003/... 单独存在。需要至少一个 .NNN 兄弟卷才视为分卷组，
        #    避免误吞同目录里偶尔存在的无关 .001/.002 数据文件。
        numeric_volumes: List[str] = []
        try:
            for file in os.listdir(directory):
                if re.fullmatch(rf'{re.escape(base_name)}\.\d{{3}}', file, re.IGNORECASE):
                    numeric_volumes.append(os.path.join(directory, file))
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找 ZIP 数字分卷失败: {exc}")
            return None

        if numeric_volumes:
            # 显式按数字递增排序：.zip 作为首卷（part 1 等价）排在最前
            def _numeric_key(path: str) -> int:
                match = re.search(r'\.(\d{3})$', os.path.basename(path))
                return int(match.group(1)) if match else 0

            ordered = [zip_path] + sorted(numeric_volumes, key=_numeric_key)
            logger.info(
                f"[VolumeSet] 检测到 .zip + .NNN 非标准分卷组: {base_name}, "
                f"volumes={[os.path.basename(p) for p in ordered]}"
            )
            return VolumeSet(base_name, ordered, 'zip_numeric_split', entry_path=zip_path)

        return None

    def _build_exe_e_volume_set(self, directory: str, base_name: str) -> Optional['VolumeSet']:
        """构建自解压 .exe + .eNN 分卷组（国产 SFX 工具特有命名）。

        触发条件：同名 .exe 必须存在，且至少有一个 .eNN 伴随文件。
        否则视为普通 SFX，由 7z 自行处理。
        """
        exe_path = os.path.join(directory, f"{base_name}.exe")
        if not os.path.exists(exe_path):
            return None

        try:
            siblings = os.listdir(directory)
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找自解压分卷失败: {exc}")
            return None

        e_volumes: List[tuple] = []
        e_pattern = re.compile(rf'^{re.escape(base_name)}\.e(\d{{2}})$', re.IGNORECASE)
        for file in siblings:
            match = e_pattern.fullmatch(file)
            if match:
                e_volumes.append((int(match.group(1)), os.path.join(directory, file)))

        if not e_volumes:
            return None

        e_volumes.sort(key=lambda item: item[0])
        ordered = [exe_path] + [path for _, path in e_volumes]
        return VolumeSet(base_name, ordered, 'exe_e_sequence', entry_path=exe_path)

    def _probe_sfx_inner_format(self, exe_path: str) -> str:
        """扫描 SFX 头部，识别内嵌档真实格式。

        国产 .exe + .eNN 工具的 SFX 头部通常较小（几 KB），内嵌档魔数会在前几 MB
        出现。这里扫前 8MB 找到第一个匹配即返回。

        Returns: '7z' / 'rar' / 'unknown'
        """
        SCAN_SIZE = 8 * 1024 * 1024  # 8MB
        signatures = (
            (b'7z\xBC\xAF\x27\x1C', '7z'),
            (b'Rar!\x1A\x07\x01\x00', 'rar'),  # RAR5
            (b'Rar!\x1A\x07\x00', 'rar'),       # RAR4
        )
        try:
            with open(exe_path, 'rb') as f:
                chunk = f.read(SCAN_SIZE)
        except Exception as exc:
            logger.warning(f"[ExeESequence] 扫描 SFX 头部失败: {exc}")
            return 'unknown'

        best_offset = None
        best_fmt = 'unknown'
        for sig, fmt in signatures:
            idx = chunk.find(sig)
            if idx >= 0 and (best_offset is None or idx < best_offset):
                best_offset = idx
                best_fmt = fmt
        if best_offset is not None:
            logger.info(
                f"[ExeESequence] 探测 SFX 内嵌档格式: {best_fmt} "
                f"(offset={best_offset}, file={os.path.basename(exe_path)})"
            )
        else:
            logger.warning(
                f"[ExeESequence] 前 {SCAN_SIZE//1024//1024}MB 未找到 7z/RAR 魔数: "
                f"{os.path.basename(exe_path)}"
            )
        return best_fmt

    async def _remap_exe_e_sequence(
        self,
        volume_set: 'VolumeSet',
        task: Optional[Task] = None,
    ) -> 'VolumeSet':
        """把 .exe + .eNN 国产 SFX 分卷组重命名为标准多卷格式。

        策略：
        1. 扫描 .exe 内嵌档魔数（_probe_sfx_inner_format）。
        2. 7z 流 → 重命名为 .7z.001 / .7z.002 / ...，类型 7z_volume_with_ext。
        3. RAR 流（或探测失败默认）→ 重命名为 .part1.rar / .part2.rar / ...，
           类型 part。这样能让现有 unar fallback 在 7zz 失败时自动接管。
        4. 重命名失败任何一卷都整体回滚，返回原 volume_set，上层走原失败链路。
        5. 在 task_metadata 里记录原始/重命名映射，便于解压最终失败时还原文件名。
        """
        if volume_set.type != 'exe_e_sequence' or not volume_set.volumes:
            return volume_set

        exe_path = volume_set.entry_path or volume_set.volumes[0]
        inner_format = self._probe_sfx_inner_format(exe_path)

        if inner_format == 'rar':
            new_type = 'part'

            def make_name(idx: int) -> str:
                return f"{volume_set.base_name}.part{idx}.rar"
        else:
            # 7z 或 unknown 都默认走 7z 命名（实测国产 SFX 大多是 7z 流）；
            # 若实际是 RAR 但探测失败，最终走到 unar 兜底也能多救一次。
            new_type = '7z_volume_with_ext'

            def make_name(idx: int) -> str:
                return f"{volume_set.base_name}.7z.{idx:03d}"

        directory = os.path.dirname(volume_set.volumes[0])
        rename_map: List[Tuple[str, str]] = []
        new_volumes: List[str] = []
        for idx, volume_path in enumerate(volume_set.volumes, start=1):
            new_path = os.path.join(directory, make_name(idx))
            new_volumes.append(new_path)
            if os.path.abspath(volume_path) != os.path.abspath(new_path):
                rename_map.append((volume_path, new_path))

        # 预检：目标文件名不能已经存在（除非就是源自己）。
        for _, new_path in rename_map:
            if os.path.exists(new_path):
                logger.warning(
                    f"[ExeESequence] 目标文件名已存在，跳过重命名以防覆盖: {new_path}"
                )
                return volume_set

        completed: List[Tuple[str, str]] = []
        for old_path, new_path in rename_map:
            try:
                await asyncio.to_thread(os.rename, old_path, new_path)
                completed.append((old_path, new_path))
                logger.info(f"[ExeESequence] 重命名: {old_path} -> {new_path}")
            except Exception as exc:
                logger.error(
                    f"[ExeESequence] 重命名失败，开始回滚: "
                    f"{old_path} -> {new_path}, error={exc}"
                )
                for done_old, done_new in completed:
                    try:
                        await asyncio.to_thread(os.rename, done_new, done_old)
                        logger.info(f"[ExeESequence] 回滚重命名: {done_new} -> {done_old}")
                    except Exception as rollback_exc:
                        logger.error(
                            f"[ExeESequence] 回滚重命名失败: "
                            f"{done_new} -> {done_old}, error={rollback_exc}"
                        )
                return volume_set

        # 把映射记到 task_metadata，方便解压最终失败时把文件名还原。
        if task is not None:
            self._set_extract_meta(
                task,
                exe_e_remap={
                    'inner_format': inner_format,
                    'naming': new_type,
                    'rename_map': [
                        {'original': old, 'renamed': new}
                        for old, new in completed
                    ],
                },
            )

        return VolumeSet(
            volume_set.base_name,
            new_volumes,
            new_type,
            entry_path=new_volumes[0],
        )

    async def _rollback_exe_e_remap(self, task: Task) -> None:
        """解压最终失败时，把 .7z.NNN / .partN.rar 改回原始 .exe + .eNN。

        只在文件还在原目录、且目标名未被占用时回滚；否则保留现状并记日志，
        避免覆盖用户其他文件。
        """
        meta = (task.task_metadata or {}).get('exe_e_remap')
        if not meta or not isinstance(meta, dict):
            return
        rename_map = meta.get('rename_map') or []
        if not rename_map:
            return

        # 反向重命名：先收集再做，避免顺序导致中间撞名
        for entry in reversed(rename_map):
            original = entry.get('original')
            renamed = entry.get('renamed')
            if not original or not renamed:
                continue
            if not os.path.exists(renamed):
                logger.info(
                    f"[ExeESequence] 跳过回滚（文件已不在原位）: {renamed}"
                )
                continue
            if os.path.exists(original):
                logger.warning(
                    f"[ExeESequence] 跳过回滚（原文件名已被占用）: {original}"
                )
                continue
            try:
                await asyncio.to_thread(os.rename, renamed, original)
                logger.info(f"[ExeESequence] 失败回滚: {renamed} -> {original}")
            except Exception as exc:
                logger.error(
                    f"[ExeESequence] 失败回滚出错: {renamed} -> {original}, error={exc}"
                )

        # 回滚后更新 task.source_path：若它指向已被改回原名的文件，更新为原始路径，
        # 避免后续 _record_problem_work_for_extract_failure 的 os.path.exists 检查因
        # 文件已改名而返回 False，导致问题作品无法落库。
        for entry in rename_map:
            original = entry.get('original')
            renamed = entry.get('renamed')
            if original and renamed and str(task.source_path or '') == renamed:
                logger.info(f"[ExeESequence] 回滚后更新 source_path: {renamed} -> {original}")
                task.source_path = original
                break

        # 清掉 metadata 标记，避免重试时再次回滚
        if task.task_metadata is not None:
            task.task_metadata.pop('exe_e_remap', None)

    async def _remap_zip_numeric_split(
        self,
        volume_set: 'VolumeSet',
        task: Optional[Task] = None,
    ) -> 'VolumeSet':
        """把 .zip 主卷 + .NNN 纯数字分卷重命名为标准 .zip.NNN 多卷格式。

        7zz / unar 都按 "split file" 协议读取分卷压缩包，规范命名是
        X.zip.001 / X.zip.002 / ...。如果传入的是 X.zip + X.002 + X.003 + ...
        这种非标准命名，7zz 看不到分卷链条，会把 X.zip 当成单个不完整 ZIP
        强行解析，必然失败（Headers/Data Error）。

        策略：
        1. 把 X.zip 重命名为 X.zip.001，X.NNN 重命名为 X.zip.NNN。
        2. 重命名失败任何一卷整体回滚，返回原 volume_set，上层走原失败链路。
        3. 在 task_metadata 里记录原始/重命名映射，便于解压最终失败时还原文件名。
        4. 重命名后类型改为 7z_volume_with_ext，复用现有 7z 多卷处理通道。
        """
        if volume_set.type != 'zip_numeric_split' or not volume_set.volumes:
            return volume_set

        directory = os.path.dirname(volume_set.volumes[0])

        def make_name(idx: int) -> str:
            return f"{volume_set.base_name}.zip.{idx:03d}"

        rename_map: List[Tuple[str, str]] = []
        new_volumes: List[str] = []
        for idx, volume_path in enumerate(volume_set.volumes, start=1):
            new_path = os.path.join(directory, make_name(idx))
            new_volumes.append(new_path)
            if os.path.abspath(volume_path) != os.path.abspath(new_path):
                rename_map.append((volume_path, new_path))

        # 预检：目标文件名不能已经存在（除非就是源自己）
        for _, new_path in rename_map:
            if os.path.exists(new_path):
                logger.warning(
                    f"[ZipNumericSplit] 目标文件名已存在，跳过重命名以防覆盖: {new_path}"
                )
                return volume_set

        completed: List[Tuple[str, str]] = []
        for old_path, new_path in rename_map:
            try:
                await asyncio.to_thread(os.rename, old_path, new_path)
                completed.append((old_path, new_path))
                logger.info(f"[ZipNumericSplit] 重命名: {old_path} -> {new_path}")
            except Exception as exc:
                logger.error(
                    f"[ZipNumericSplit] 重命名失败，开始回滚: "
                    f"{old_path} -> {new_path}, error={exc}"
                )
                for done_old, done_new in completed:
                    try:
                        await asyncio.to_thread(os.rename, done_new, done_old)
                        logger.info(f"[ZipNumericSplit] 回滚重命名: {done_new} -> {done_old}")
                    except Exception as rollback_exc:
                        logger.error(
                            f"[ZipNumericSplit] 回滚重命名失败: "
                            f"{done_new} -> {done_old}, error={rollback_exc}"
                        )
                return volume_set

        if task is not None:
            self._set_extract_meta(
                task,
                zip_numeric_remap={
                    'rename_map': [
                        {'original': old, 'renamed': new}
                        for old, new in completed
                    ],
                },
            )

        return VolumeSet(
            volume_set.base_name,
            new_volumes,
            '7z_volume_with_ext',
            entry_path=new_volumes[0],
        )

    async def _rollback_zip_numeric_remap(self, task: Task) -> None:
        """解压最终失败时，把 .zip.NNN 改回原始 .zip + .NNN 命名。

        只在文件还在原目录、且目标名未被占用时回滚；否则保留现状并记日志，
        避免覆盖用户其他文件。
        """
        meta = (task.task_metadata or {}).get('zip_numeric_remap')
        if not meta or not isinstance(meta, dict):
            return
        rename_map = meta.get('rename_map') or []
        if not rename_map:
            return

        for entry in reversed(rename_map):
            original = entry.get('original')
            renamed = entry.get('renamed')
            if not original or not renamed:
                continue
            if not os.path.exists(renamed):
                logger.info(f"[ZipNumericSplit] 跳过回滚（文件已不在原位）: {renamed}")
                continue
            if os.path.exists(original):
                logger.warning(
                    f"[ZipNumericSplit] 跳过回滚（原文件名已被占用）: {original}"
                )
                continue
            try:
                await asyncio.to_thread(os.rename, renamed, original)
                logger.info(f"[ZipNumericSplit] 失败回滚: {renamed} -> {original}")
            except Exception as exc:
                logger.error(
                    f"[ZipNumericSplit] 失败回滚出错: {renamed} -> {original}, error={exc}"
                )

        # 回滚后更新 task.source_path：若它指向已被改回原名的文件，更新为原始路径，
        # 避免后续 _record_problem_work_for_extract_failure 的 os.path.exists 检查因
        # 文件已改名而返回 False，导致问题作品无法落库。
        for entry in rename_map:
            original = entry.get('original')
            renamed = entry.get('renamed')
            if original and renamed and str(task.source_path or '') == renamed:
                logger.info(f"[ZipNumericSplit] 回滚后更新 source_path: {renamed} -> {original}")
                task.source_path = original
                break

        if task.task_metadata is not None:
            task.task_metadata.pop('zip_numeric_remap', None)

    async def _remap_part_exe_volumes(
        self,
        volume_set: 'VolumeSet',
        task: Optional[Task] = None,
    ) -> 'VolumeSet':
        """把 WinRAR 自解压分卷里的 .partN.exe 改名为 .partN.rar。

        WinRAR 自解压多卷的命名约定：首卷 `X.part1.exe`（SFX 程序 + RAR 数据），
        后续卷 `X.part2.rar`、`X.part3.rar` …。`7zz x X.part1.exe` 能解 SFX，
        但**不会**按 `.partN.rar` 文件名规则去续接 part2 / part3，所以多卷必
        然失败（typically returncode=2）。RAR 格式允许在 `Rar!` 签名之前存在
        任意数据（这就是 SFX 工作的原理），所以把 `.exe` 改成 `.rar` 不破坏
        数据，7zz 扫到签名就能正常解析。

        策略：
        1. volume_set.type 必须是 'part'，且至少有一卷扩展名是 `.exe`，否则
           原样返回。
        2. 把每一卷 `X.partN.exe` 改名为 `X.partN.rar`；非 `.exe` 卷保持不动。
        3. 任一卷重命名失败整体回滚，返回原 volume_set。
        4. 在 task_metadata 里记录原始/重命名映射，便于解压最终失败时还原。
        5. 重命名后类型仍是 'part'，entry_path 更新为新首卷路径。
        """
        if volume_set.type != 'part' or not volume_set.volumes:
            return volume_set

        # 只在确实存在 .partN.exe 卷时才走重命名通道，避免影响纯 .rar 多卷
        has_exe_volume = any(
            re.search(r'\.part\d+\.exe$', os.path.basename(p), re.IGNORECASE)
            for p in volume_set.volumes
        )
        if not has_exe_volume:
            return volume_set

        directory = os.path.dirname(volume_set.volumes[0])
        rename_map: List[Tuple[str, str]] = []
        new_volumes: List[str] = []
        for volume_path in volume_set.volumes:
            filename = os.path.basename(volume_path)
            new_filename = re.sub(
                r'(\.part\d+)\.exe$', r'\1.rar', filename, flags=re.IGNORECASE
            )
            new_path = os.path.join(directory, new_filename)
            new_volumes.append(new_path)
            if os.path.abspath(volume_path) != os.path.abspath(new_path):
                rename_map.append((volume_path, new_path))

        # 预检：目标文件名不能已经存在（除非就是源自己）
        for _, new_path in rename_map:
            if os.path.exists(new_path):
                logger.warning(
                    f"[PartExeRemap] 目标文件名已存在，跳过重命名以防覆盖: {new_path}"
                )
                return volume_set

        completed: List[Tuple[str, str]] = []
        for old_path, new_path in rename_map:
            try:
                await asyncio.to_thread(os.rename, old_path, new_path)
                completed.append((old_path, new_path))
                logger.info(f"[PartExeRemap] 重命名: {old_path} -> {new_path}")
            except Exception as exc:
                logger.error(
                    f"[PartExeRemap] 重命名失败，开始回滚: "
                    f"{old_path} -> {new_path}, error={exc}"
                )
                for done_old, done_new in completed:
                    try:
                        await asyncio.to_thread(os.rename, done_new, done_old)
                        logger.info(f"[PartExeRemap] 回滚重命名: {done_new} -> {done_old}")
                    except Exception as rollback_exc:
                        logger.error(
                            f"[PartExeRemap] 回滚重命名失败: "
                            f"{done_new} -> {done_old}, error={rollback_exc}"
                        )
                return volume_set

        if task is not None:
            self._set_extract_meta(
                task,
                part_exe_remap={
                    'rename_map': [
                        {'original': old, 'renamed': new}
                        for old, new in completed
                    ],
                },
            )

        return VolumeSet(
            volume_set.base_name,
            new_volumes,
            'part',
            entry_path=new_volumes[0],
        )

    async def _rollback_part_exe_remap(self, task: Task) -> None:
        """解压最终失败时，把 .partN.rar 改回原始 .partN.exe。

        只在文件还在原目录、且目标名未被占用时回滚；否则保留现状并记日志，
        避免覆盖用户其他文件。
        """
        meta = (task.task_metadata or {}).get('part_exe_remap')
        if not meta or not isinstance(meta, dict):
            return
        rename_map = meta.get('rename_map') or []
        if not rename_map:
            return

        for entry in reversed(rename_map):
            original = entry.get('original')
            renamed = entry.get('renamed')
            if not original or not renamed:
                continue
            if not os.path.exists(renamed):
                logger.info(f"[PartExeRemap] 跳过回滚（文件已不在原位）: {renamed}")
                continue
            if os.path.exists(original):
                logger.warning(
                    f"[PartExeRemap] 跳过回滚（原文件名已被占用）: {original}"
                )
                continue
            try:
                await asyncio.to_thread(os.rename, renamed, original)
                logger.info(f"[PartExeRemap] 失败回滚: {renamed} -> {original}")
            except Exception as exc:
                logger.error(
                    f"[PartExeRemap] 失败回滚出错: {renamed} -> {original}, error={exc}"
                )

        # 回滚后更新 task.source_path：若它指向已被改回原名的文件，更新为原始路径，
        # 避免后续 _record_problem_work_for_extract_failure 的 os.path.exists 检查因
        # 文件已改名而返回 False，导致问题作品无法落库。
        for entry in rename_map:
            original = entry.get('original')
            renamed = entry.get('renamed')
            if original and renamed and str(task.source_path or '') == renamed:
                logger.info(f"[PartExeRemap] 回滚后更新 source_path: {renamed} -> {original}")
                task.source_path = original
                break

        if task.task_metadata is not None:
            task.task_metadata.pop('part_exe_remap', None)

    def _build_rar_old_volume_set(self, directory: str, base_name: str) -> Optional['VolumeSet']:
        rar_path = os.path.join(directory, f"{base_name}.rar")
        if not os.path.exists(rar_path):
            return None

        volumes: List[str] = [rar_path]
        try:
            for file in os.listdir(directory):
                if re.fullmatch(rf'{re.escape(base_name)}\.r\d{{2}}', file, re.IGNORECASE):
                    volumes.append(os.path.join(directory, file))
        except Exception as exc:
            logger.error(f"[VolumeSet] 查找旧式 RAR 分卷失败: {exc}")
            return None

        if len(volumes) <= 1:
            return None

        ordered = sorted(volumes, key=self._volume_sort_key)
        return VolumeSet(base_name, ordered, 'rar_volume_main', entry_path=rar_path)

    def _volume_sort_key(self, path: str):
        filename = os.path.basename(path).lower()

        part_match = re.search(r'\.part(\d+)(?:\.(?:rar|zip|7z|exe))?$', filename, re.IGNORECASE)
        if part_match:
            return (0, int(part_match.group(1)), filename)

        sevenzip_match = re.search(r'\.7z\.(\d{3})$', filename, re.IGNORECASE)
        if sevenzip_match:
            return (1, int(sevenzip_match.group(1)), filename)

        pure_numeric_match = re.search(r'\.(\d{3})$', filename, re.IGNORECASE)
        if pure_numeric_match:
            return (2, int(pure_numeric_match.group(1)), filename)

        zip_split_match = re.search(r'\.z(\d{2})$', filename, re.IGNORECASE)
        if zip_split_match:
            return (3, int(zip_split_match.group(1)), filename)

        rar_old_match = re.search(r'\.r(\d{2})$', filename, re.IGNORECASE)
        if rar_old_match:
            return (4, int(rar_old_match.group(1)), filename)

        if filename.endswith('.zip'):
            return (5, 0, filename)
        if filename.endswith('.rar'):
            return (5, 1, filename)

        two_digit_match = re.search(r'\.(\d{2})$', filename, re.IGNORECASE)
        if two_digit_match:
            return (6, int(two_digit_match.group(1)), filename)

        return (9, 0, filename)

    def _find_all_volumes(self, directory: str, base_name: str, pattern: str) -> List[str]:
        """查找所有分卷文件"""
        volumes = []
        logger.debug(f"[FindVolumes] directory={directory}, base_name={base_name}, pattern={pattern}")
        try:
            files = os.listdir(directory)
            logger.debug(f"[FindVolumes] 目录中的文件: {files}")
            for file in files:
                if file.startswith(base_name) and re.search(pattern, file, re.IGNORECASE):
                    volumes.append(os.path.join(directory, file))
                    logger.debug(f"[FindVolumes] 匹配到分卷: {file}")
        except Exception as e:
            logger.error(f"[FindVolumes] 列出目录失败: {e}")
        result = sorted(volumes, key=self._volume_sort_key)
        logger.info(f"[FindVolumes] 找到 {len(result)} 个分卷: {[os.path.basename(v) for v in result]}")
        return result

    async def _wait_for_complete_set(self, volume_set: 'VolumeSet', task: Optional[Task] = None, max_wait: int = 3600) -> bool:
        """等待分卷组完整"""
        start_time = asyncio.get_event_loop().time()
        check_interval = 5

        while asyncio.get_event_loop().time() - start_time < max_wait:
            # 检查任务是否被取消
            if task and task.is_cancelled():
                logger.info(f"任务在等待分卷组时被取消")
                return False

            # 检查任务是否暂停
            if task:
                await task.wait_if_paused()

            all_stable = True
            for volume in volume_set.volumes:
                if not os.path.exists(volume):
                    all_stable = False
                    break
                if not await self._is_file_stable_quick(volume):
                    all_stable = False
                    break

            if all_stable:
                return True

            await asyncio.sleep(check_interval)

        return False

    async def _is_file_stable_quick(self, file_path: str) -> bool:
        """快速检查文件是否稳定（只检查一次）"""
        try:
            size1 = os.path.getsize(file_path)
            await asyncio.sleep(2)
            size2 = os.path.getsize(file_path)
            return size1 == size2
        except OSError:
            return False

    def _build_filename_candidates(self, archive_path: str) -> List[str]:
        path_obj = Path(archive_path)
        filename = path_obj.name
        candidates: List[str] = []
        seen = set()

        def add_candidate(value: str):
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                candidates.append(normalized)

        add_candidate(filename)
        add_candidate(path_obj.stem)

        split_match = re.match(r'^(?P<base>.+\.7z)\.\d{3}$', filename, re.IGNORECASE)
        if split_match:
            add_candidate(split_match.group('base'))

        zip_split_match = re.match(r'^(?P<base>.+)\.z\d{2}$', filename, re.IGNORECASE)
        if zip_split_match:
            add_candidate(f"{zip_split_match.group('base')}.zip")

        rar_split_match = re.match(r'^(?P<base>.+)\.r\d{2}$', filename, re.IGNORECASE)
        if rar_split_match:
            add_candidate(f"{rar_split_match.group('base')}.rar")

        part_match = re.match(r'^(?P<base>.+)\.part\d+(?P<ext>\.(?:rar|zip|7z|exe))?$', filename, re.IGNORECASE)
        if part_match:
            ext = part_match.group('ext') or ''
            add_candidate(f"{part_match.group('base')}{ext}")

        return candidates

    def _compile_filename_password_template(self, template: str) -> Optional[re.Pattern]:
        raw = str(template or "").strip()
        if not raw or "{password}" not in raw:
            return None

        has_name_placeholder = "{name}" in raw
        placeholder_pattern = re.compile(r"\{(name|password)\}")
        pattern_parts: List[str] = [] if has_name_placeholder else [r".*"]
        cursor = 0
        for match in placeholder_pattern.finditer(raw):
            pattern_parts.append(re.escape(raw[cursor:match.start()]))
            key = match.group(1)
            if key == "name":
                pattern_parts.append(r"(?P<name>.+?)")
            else:
                pattern_parts.append(r"(?P<password>[^\\/]+?)")
            cursor = match.end()
        pattern_parts.append(re.escape(raw[cursor:]))
        return re.compile(r"^" + "".join(pattern_parts) + r"$", re.IGNORECASE)

    def _get_filename_password_sniff_targets(self, archive_path: str) -> List[str]:
        targets: List[str] = []
        seen = set()

        def add(value: str):
            normalized = str(value or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                targets.append(normalized)

        for candidate in self._build_filename_candidates(archive_path):
            add(candidate)
            lower = candidate.lower()
            for suffix in (
                ".tar.gz",
                ".tar.bz2",
                ".tar.xz",
                ".zip",
                ".rar",
                ".7z",
                ".tar",
                ".tgz",
                ".tbz2",
                ".txz",
                ".gz",
                ".bz2",
                ".xz",
                ".exe",
            ):
                if lower.endswith(suffix):
                    add(candidate[:-len(suffix)])
                    break

        return targets

    def _get_filename_sniff_passwords(self, archive_path: str) -> List[str]:
        extract_config = getattr(self.config, "extract", None)
        if not bool(getattr(extract_config, "filename_password_sniff_enabled", False)):
            return []

        templates = getattr(extract_config, "filename_password_sniff_templates", None) or []
        compiled_templates = [
            compiled
            for compiled in (self._compile_filename_password_template(item) for item in templates)
            if compiled is not None
        ]
        if not compiled_templates:
            return []

        passwords: List[str] = []
        seen = set()
        for target in self._get_filename_password_sniff_targets(archive_path):
            for template in compiled_templates:
                match = template.match(target)
                if not match:
                    continue
                password = normalize_password_value(match.groupdict().get("password"))
                if not password or password in seen:
                    continue
                if len(password) > 128 or any(sep in password for sep in ("\\", "/")):
                    continue
                seen.add(password)
                passwords.append(password)

        if passwords:
            logger.info("从文件名嗅探到 %s 个候选密码: %s", len(passwords), os.path.basename(archive_path))
        return passwords

    async def _get_password_candidates_for_archive(self, archive_path: str) -> List[Dict[str, Optional[str]]]:
        """从密码库查找适合该压缩包的密码候选，并保留关联的 RJ 信息"""
        from ..models.database import PasswordEntry, get_db

        rjcodes = self._extract_rjcode_candidates(archive_path)
        filename_candidates = self._build_filename_candidates(archive_path)
        db = next(get_db())
        candidates: List[Dict[str, Optional[str]]] = []
        seen_passwords = set()
        dirty_entry_count = 0

        def add_entry(
            password: Optional[str],
            source: str,
            rjcode: Optional[str] = None,
            filename: Optional[str] = None,
            entry_id: Optional[str] = None,
        ):
            normalized_password = normalize_password_value(password)
            if not normalized_password:
                return
            if normalized_password in seen_passwords:
                return
            seen_passwords.add(normalized_password)
            normalized_rjcode = normalize_rjcode_value(rjcode)
            candidates.append({
                "entry_id": entry_id,
                "password": normalized_password,
                "source": source,
                "rjcode": normalized_rjcode,
                "filename": normalize_filename_value(filename),
            })

        try:
            for sniffed_password in self._get_filename_sniff_passwords(archive_path):
                add_entry(sniffed_password, "文件名嗅探", None, os.path.basename(archive_path), None)

            if rjcodes:
                from sqlalchemy import func
                entries = db.query(PasswordEntry).filter(func.upper(PasswordEntry.rjcode).in_(rjcodes)).all()
                for entry in entries:
                    normalized_password = normalize_password_value(entry.password)
                    normalized_rjcode = normalize_rjcode_value(entry.rjcode)
                    normalized_filename = normalize_filename_value(entry.filename)
                    if (
                        normalized_password != str(entry.password or "")
                        or normalized_rjcode != entry.rjcode
                        or normalized_filename != entry.filename
                    ):
                        entry.password = normalized_password
                        entry.rjcode = normalized_rjcode
                        entry.filename = normalized_filename
                        dirty_entry_count += 1
                    add_entry(normalized_password, "密码库-RJ", normalized_rjcode, normalized_filename, entry.id)
                    logger.info(f"找到RJ号匹配的密码: {normalized_rjcode}")

            if filename_candidates:
                entries = db.query(PasswordEntry).filter(PasswordEntry.filename.in_(filename_candidates)).all()
                for entry in entries:
                    normalized_password = normalize_password_value(entry.password)
                    normalized_rjcode = normalize_rjcode_value(entry.rjcode)
                    normalized_filename = normalize_filename_value(entry.filename)
                    if (
                        normalized_password != str(entry.password or "")
                        or normalized_rjcode != entry.rjcode
                        or normalized_filename != entry.filename
                    ):
                        entry.password = normalized_password
                        entry.rjcode = normalized_rjcode
                        entry.filename = normalized_filename
                        dirty_entry_count += 1
                    add_entry(normalized_password, "密码库-文件名", normalized_rjcode, normalized_filename, entry.id)
                    logger.info(f"找到文件名匹配的密码: {normalized_filename}")

            generic_entries = db.query(PasswordEntry).filter(
                PasswordEntry.rjcode.is_(None),
                PasswordEntry.filename.is_(None)
            ).all()
            for entry in generic_entries:
                normalized_password = normalize_password_value(entry.password)
                if normalized_password != str(entry.password or ""):
                    entry.password = normalized_password
                    dirty_entry_count += 1
                add_entry(normalized_password, "密码库-通用", entry.rjcode, entry.filename, entry.id)

            if dirty_entry_count:
                db.commit()
                logger.info("已自动清洗 %s 条密码库脏数据", dirty_entry_count)

            return candidates
        finally:
            db.close()

    async def _get_passwords_for_archive(self, archive_path: str) -> List[str]:
        candidates = await self._get_password_candidates_for_archive(archive_path)
        return [item["password"] for item in candidates]

    def _looks_like_archive_entry(self, entry_name: str) -> bool:
        normalized = str(entry_name or "").strip().lower().replace("\\", "/")
        if not normalized:
            return False

        archive_suffixes = (
            ".zip",
            ".rar",
            ".7z",
            ".tar",
            ".tar.gz",
            ".tgz",
            ".tar.bz2",
            ".tbz2",
            ".tar.xz",
            ".txz",
            ".gz",
            ".bz2",
            ".xz",
        )
        if normalized.endswith(archive_suffixes):
            return True

        if re.search(r"\.(part\d+\.(rar|zip|7z|exe)|7z\.\d{3}|z\d{2})$", normalized, re.IGNORECASE):
            return True

        return False

    def _extract_rjcode_candidates_from_text(self, text: str) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add_code(code: str):
            value = str(code or "").strip().upper()
            if value and value not in seen:
                seen.add(value)
                candidates.append(value)

        normalized_text = str(text or "")
        for match in re.finditer(r'[RVB]J\s*[-_.]?\s*(\d{6}|\d{8})(?!\d)', normalized_text, re.IGNORECASE):
            add_code(f"RJ{match.group(1)}")

        path_parts = re.split(r"[\\/]", normalized_text)
        for part in path_parts:
            part = str(part or "").strip()
            if not part:
                continue
            part_candidates = [part]
            stem = Path(part).stem
            if stem and stem != part:
                part_candidates.append(stem)
            for item in part_candidates:
                cleaned = re.sub(r'^\d+[._-]', '', item)
                number_match = re.fullmatch(r'(\d{6}|\d{8})', cleaned)
                if number_match:
                    add_code(f"RJ{number_match.group(1)}")

        return candidates

    def _extract_rjcode_candidates(self, archive_path: str) -> List[str]:
        candidates: List[str] = []
        seen = set()

        def add_code(code: str):
            code = code.upper()
            if code and code not in seen:
                seen.add(code)
                candidates.append(code)

        path_text = str(archive_path)
        for match in re.finditer(r'[RVB]J\s*[-_.]?\s*(\d{6}|\d{8})(?!\d)', path_text, re.IGNORECASE):
            digits = match.group(1)
            add_code(f"RJ{digits}")

        path_obj = Path(archive_path)
        parts = list(path_obj.parts)
        if path_obj.suffix:
            parts.append(path_obj.stem)
        for part in parts:
            cleaned = re.sub(r'^\d+[._-]', '', part)
            number_match = re.fullmatch(r'(\d{6}|\d{8})', cleaned)
            if number_match:
                add_code(f"RJ{number_match.group(1)}")

        return candidates

    async def infer_rjcode_from_archive(self, archive_path: str, max_nested_depth: int = 1) -> Optional[Dict[str, str]]:
        """在正式解压前，从压缩包目录和内层压缩包中尽力推断 RJ 号。"""
        seen_archives = set()
        return await self._infer_rjcode_from_archive_internal(
            archive_path=str(archive_path or ""),
            max_nested_depth=max(0, int(max_nested_depth)),
            current_depth=0,
            seen_archives=seen_archives,
        )

    def _find_archive_candidates_in_directory(self, directory: str, max_results: int = 8) -> List[str]:
        candidates: List[str] = []
        seen = set()
        root_dir = os.path.abspath(str(directory or ""))
        if not root_dir or not os.path.isdir(root_dir):
            return candidates

        for current_root, dirs, files in os.walk(root_dir):
            dirs.sort()
            files.sort()

            relative_root = os.path.relpath(current_root, root_dir)
            relative_root = "" if relative_root == "." else relative_root
            relative_root_posix = relative_root.replace("\\", "/")
            if relative_root_posix:
                root_candidates = self._extract_rjcode_candidates_from_text(relative_root_posix)
                if root_candidates:
                    return [f"dir::{relative_root_posix}::{root_candidates[0]}"]

            for filename in files:
                file_path = os.path.join(current_root, filename)
                relative_path = os.path.relpath(file_path, root_dir).replace("\\", "/")
                entry_candidates = self._extract_rjcode_candidates_from_text(relative_path)
                if entry_candidates:
                    return [f"path::{relative_path}::{entry_candidates[0]}"]

                is_archive_candidate = self._looks_like_archive_entry(filename)
                if not is_archive_candidate:
                    try:
                        is_archive_candidate = self._detect_by_magic_bytes(file_path) is not None
                    except Exception:
                        is_archive_candidate = False

                if is_archive_candidate and file_path not in seen:
                    seen.add(file_path)
                    candidates.append(file_path)
                    if len(candidates) >= max_results:
                        return candidates

        return candidates

    async def _infer_rjcode_from_archive_internal(
        self,
        archive_path: str,
        max_nested_depth: int,
        current_depth: int,
        seen_archives: set,
    ) -> Optional[Dict[str, str]]:
        normalized_archive_path = os.path.abspath(str(archive_path or ""))
        if not normalized_archive_path or normalized_archive_path in seen_archives:
            return None
        seen_archives.add(normalized_archive_path)

        direct_candidates = self._extract_rjcode_candidates(normalized_archive_path)
        if direct_candidates:
            result = {"rjcode": direct_candidates[0], "source": "archive_path"}
            logger.info(
                "[RJ 推断] 命中压缩包路径: archive=%s rjcode=%s depth=%s",
                normalized_archive_path,
                result["rjcode"],
                current_depth,
            )
            return result

        archive_info = await self._get_archive_info(normalized_archive_path)
        if not archive_info:
            logger.info(
                "[RJ 推断] 无法读取压缩包目录，终止本层预检: archive=%s depth=%s",
                normalized_archive_path,
                current_depth,
            )
            return None

        inferred_rjcode = str(getattr(archive_info, "inferred_rjcode", "") or "").strip().upper()
        if inferred_rjcode:
            result = {"rjcode": inferred_rjcode, "source": "password_entry"}
            logger.info(
                "[RJ 推断] 命中密码库关联: archive=%s rjcode=%s depth=%s",
                normalized_archive_path,
                result["rjcode"],
                current_depth,
            )
            return result

        nested_archive_entries: List[str] = []
        opaque_archive_entries: List[str] = []
        logger.info(
            "[RJ 推断] 开始扫描压缩包条目: archive=%s depth=%s total_entries=%s",
            normalized_archive_path,
            current_depth,
            len(archive_info.file_list or []),
        )
        for item in archive_info.file_list or []:
            entry_name = str((item or {}).get("name") or "").strip()
            if not entry_name:
                continue

            entry_candidates = self._extract_rjcode_candidates_from_text(entry_name)
            if entry_candidates:
                result = {"rjcode": entry_candidates[0], "source": f"archive_entry:{entry_name}"}
                logger.info(
                    "[RJ 推断] 命中压缩包条目: archive=%s entry=%s rjcode=%s depth=%s",
                    normalized_archive_path,
                    entry_name,
                    result["rjcode"],
                    current_depth,
                )
                return result

            if self._looks_like_archive_entry(entry_name):
                nested_archive_entries.append(entry_name)
            elif not bool((item or {}).get("is_dir")):
                entry_suffix = Path(entry_name).suffix.lower()
                entry_size = int((item or {}).get("size") or 0)
                if not entry_suffix and entry_size > 0:
                    opaque_archive_entries.append(entry_name)

        logger.info(
            "[RJ 推断] 条目扫描未直接命中: archive=%s depth=%s nested_candidates=%s opaque_candidates=%s",
            normalized_archive_path,
            current_depth,
            len(nested_archive_entries),
            len(opaque_archive_entries),
        )

        if current_depth >= max_nested_depth:
            logger.info(
                "[RJ 推断] 已达到最大嵌套深度，停止继续向内预检: archive=%s depth=%s max_depth=%s",
                normalized_archive_path,
                current_depth,
                max_nested_depth,
            )
            return None

        probe_entries = list(nested_archive_entries[:5])
        if not probe_entries:
            probe_entries.extend(opaque_archive_entries[:3])

        for entry_name in probe_entries:
            temp_dir = None
            try:
                logger.info(
                    "[RJ 推断] 开始探测内层条目: archive=%s entry=%s depth=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                )
                temp_dir = await self.extract_selected_entries(
                    normalized_archive_path,
                    [entry_name],
                )
                nested_archive_path = os.path.join(temp_dir, *str(entry_name).replace("\\", "/").split("/"))
                if not os.path.exists(nested_archive_path):
                    logger.debug(
                        "[RJ 推断] 内层压缩包条目提取后未找到文件: archive=%s entry=%s temp=%s",
                        normalized_archive_path,
                        entry_name,
                        temp_dir,
                    )

                extracted_tree_candidates = self._find_archive_candidates_in_directory(temp_dir)
                logger.info(
                    "[RJ 推断] 提取内层条目后扫描临时目录: archive=%s entry=%s depth=%s tree_candidates=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                    len(extracted_tree_candidates),
                )
                if extracted_tree_candidates:
                    first_candidate = extracted_tree_candidates[0]
                    if first_candidate.startswith("dir::"):
                        _, relative_dir, inferred_code = first_candidate.split("::", 2)
                        result = {
                            "rjcode": inferred_code,
                            "source": f"nested_directory:{entry_name}->{relative_dir}",
                        }
                        logger.info(
                            "[RJ 推断] 命中提取后的嵌套目录: archive=%s entry=%s relative_dir=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_dir,
                            inferred_code,
                            current_depth + 1,
                        )
                        return result
                    if first_candidate.startswith("path::"):
                        _, relative_path, inferred_code = first_candidate.split("::", 2)
                        result = {
                            "rjcode": inferred_code,
                            "source": f"nested_entry_path:{entry_name}->{relative_path}",
                        }
                        logger.info(
                            "[RJ 推断] 命中提取后的嵌套路径: archive=%s entry=%s relative_path=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_path,
                            inferred_code,
                            current_depth + 1,
                        )
                        return result

                candidate_archive_paths: List[str] = []
                if os.path.exists(nested_archive_path) and os.path.isfile(nested_archive_path):
                    candidate_archive_paths.append(nested_archive_path)
                for candidate_path in extracted_tree_candidates:
                    if candidate_path.startswith(("dir::", "path::")):
                        continue
                    if candidate_path not in candidate_archive_paths:
                        candidate_archive_paths.append(candidate_path)

                for candidate_archive_path in candidate_archive_paths[:5]:
                    nested_result = await self._infer_rjcode_from_archive_internal(
                        archive_path=candidate_archive_path,
                        max_nested_depth=max_nested_depth,
                        current_depth=current_depth + 1,
                        seen_archives=seen_archives,
                    )
                    if nested_result and nested_result.get("rjcode"):
                        nested_source = nested_result.get("source") or "nested_archive"
                        relative_candidate_path = os.path.relpath(candidate_archive_path, temp_dir).replace("\\", "/")
                        nested_result["source"] = f"nested_archive:{entry_name}->{relative_candidate_path}->{nested_source}"
                        logger.info(
                            "[RJ 推断] 命中内层压缩包: archive=%s entry=%s candidate=%s rjcode=%s depth=%s",
                            normalized_archive_path,
                            entry_name,
                            relative_candidate_path,
                            nested_result["rjcode"],
                            current_depth + 1,
                        )
                        return nested_result
            except Exception as exc:
                logger.debug(
                    "[RJ 推断] 检查内层压缩包失败: archive=%s entry=%s depth=%s error=%s",
                    normalized_archive_path,
                    entry_name,
                    current_depth + 1,
                    exc,
                )
            finally:
                if temp_dir and os.path.exists(temp_dir):
                    await asyncio.to_thread(shutil.rmtree, temp_dir, True)

        return None

    async def _record_password_usage(self, password: str, archive_path: str, entry_id: Optional[str] = None):
        """记录密码使用情况"""
        from ..models.database import PasswordEntry, get_db

        db = next(get_db())
        try:
            # 查找并更新使用记录
            entry = None
            if entry_id:
                entry = db.query(PasswordEntry).filter(PasswordEntry.id == entry_id).first()
            if not entry:
                normalized_password = normalize_password_value(password)
                entry = db.query(PasswordEntry).filter(PasswordEntry.password == normalized_password).first()
            if entry:
                # 使用 SQL 表达式更新，避免类型问题
                from sqlalchemy import func
                db.query(PasswordEntry).filter(PasswordEntry.id == entry.id).update({
                    'use_count': PasswordEntry.use_count + 1,
                    'last_used_at': func.now()
                })
                db.commit()
                logger.debug(f"记录密码使用: {entry.rjcode or entry.filename or '通用密码'}, 使用次数+1")
        except Exception as e:
            logger.warning(f"记录密码使用情况失败: {e}")
        finally:
            db.close()

    def _get_rj_passwords(self, archive_path: str) -> List[str]:
        """从压缩包路径提取RJ号并生成密码列表

        返回顺序: RJ号, RJ号+1, RJ号-1
        例如: 对于RJ123456，返回 ['RJ123456', 'RJ123457', 'RJ123455']
        """
        passwords = []
        seen = set()
        rjcodes = self._extract_rjcode_candidates(archive_path)
        for rjcode in rjcodes:
            digits = re.sub(r'^[RVB]J', '', rjcode, flags=re.IGNORECASE)
            if not digits.isdigit():
                continue
            width = len(digits)
            rj_number = int(digits)
            variants = [
                f"RJ{digits}",
                f"RJ{str(rj_number + 1).zfill(width)}",
                f"RJ{str(max(0, rj_number - 1)).zfill(width)}",
            ]
            for pwd in variants:
                if pwd not in seen:
                    seen.add(pwd)
                    passwords.append(pwd)
        if passwords:
            logger.debug(f"从路径提取RJ号生成密码: {passwords}")
        return passwords

    @classmethod
    def _archive_cache_key(cls, archive_path: str) -> Optional[Tuple[str, int, int]]:
        """根据 archive_path 计算缓存 key = (abs_path, mtime_ns, size)。

        文件不存在 / 路径异常返回 None，由调用方跳过缓存。
        """
        try:
            abs_path = os.path.abspath(str(archive_path or ""))
            if not abs_path or not os.path.isfile(abs_path):
                return None
            st = os.stat(abs_path)
            mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
            return (abs_path, int(mtime_ns), int(st.st_size))
        except OSError:
            return None

    @classmethod
    def _load_cached_archive_info(cls, archive_path: str) -> Optional[ArchiveInfo]:
        """命中即返回，LRU 命中端移到末尾；未命中返回 None。"""
        key = cls._archive_cache_key(archive_path)
        if key is None:
            return None
        with cls._archive_info_cache_lock:
            entry = cls._archive_info_cache.get(key)
            if entry is None:
                return None
            cls._archive_info_cache.move_to_end(key)
            return entry

    @classmethod
    def _save_cached_archive_info(cls, archive_path: str, archive_info: ArchiveInfo) -> None:
        """写入缓存。极端大包（清单条目超限）不入缓存，避免内存堆积。"""
        if archive_info is None:
            return
        file_list = getattr(archive_info, "file_list", None) or []
        if len(file_list) > cls.ARCHIVE_INFO_CACHE_FILE_LIST_LIMIT:
            return
        key = cls._archive_cache_key(archive_path)
        if key is None:
            return
        with cls._archive_info_cache_lock:
            cls._archive_info_cache[key] = archive_info
            cls._archive_info_cache.move_to_end(key)
            while len(cls._archive_info_cache) > cls.ARCHIVE_INFO_CACHE_MAX:
                cls._archive_info_cache.popitem(last=False)

    async def _get_archive_info(
        self,
        archive_path: str,
        password_candidates: Optional[List[Dict[str, Optional[str]]]] = None,
        use_cache: bool = True,
        task: Optional[Task] = None,
    ) -> Optional[ArchiveInfo]:
        """获取压缩包信息（文件列表、大小等）

        注意：这里只获取文件列表，不解压。真正能解压的密码在 _try_extract 中确定。
        为了不限制解压时的密码选择，这里尝试找一个能读取内容的密码即可。

        use_cache=True 时优先复用进程内 list 缓存：消除"infer_rjcode → extract"
        这种典型路径上的重复 `7zz l`。分卷 remap 后路径已变，新路径不会误命中老 key。
        """
        if self._manual_filename_encoding_from_task(task):
            use_cache = False
        if use_cache:
            cached = self._load_cached_archive_info(archive_path)
            if cached is not None:
                logger.info(f"[7z][cache] 命中预读取缓存，跳过 list: {archive_path}")
                return cached

        if password_candidates is None:
            # 指定密码重试：从 task 元数据读取，只用指定密码，不查密码库
            _task_meta = (task.task_metadata or {}) if task else {}
            _manual_pw = normalize_password_value(_task_meta.get("manual_retry_password"))
            _manual_only = bool(_task_meta.get("manual_retry_password_only"))
            if _manual_pw and _manual_only:
                password_candidates = [{
                    "password": _manual_pw,
                    "source": "指定密码",
                    "entry_id": None,
                    "rjcode": None,
                }]
            else:
                password_candidates = await self._get_password_candidates_for_archive(archive_path)
        vault_passwords = [item["password"] for item in password_candidates]
        password_source_map = {
            item["password"]: item.get("source")
            for item in password_candidates
            if item.get("password")
        }
        manual_only_passwords = [
            item["password"]
            for item in password_candidates
            if item.get("source") == "指定密码" and item.get("password")
        ]
        password_rjcode_map = {
            item["password"]: item.get("rjcode")
            for item in password_candidates
            if item.get("rjcode")
        }

        if manual_only_passwords:
            password_list = manual_only_passwords
        else:
            # 获取RJ号相关密码
            rj_passwords = self._get_rj_passwords(archive_path)

            # 构建密码列表：RJ号密码优先，然后密码库密码，最后是配置中的默认密码
            password_list = []
            password_list.extend(rj_passwords)  # RJ号密码（RJ号, RJ号+1, RJ号-1）
            password_list.extend(vault_passwords)  # 密码库密码
            password_list.append("")  # 无密码
            password_list.extend(self.config.extract.password_list)  # 默认密码

        # 去重（保持顺序）
        seen = set()
        unique_passwords = []
        for pwd in password_list:
            if pwd not in seen:
                seen.add(pwd)
                unique_passwords.append(pwd)

        for password in unique_passwords:
            file_list = await self._list_archive_contents(
                archive_path,
                password,
                task=task,
                filename_encoding=self._manual_filename_encoding_from_task(task),
            )
            if file_list is not None:
                # 判断密码来源
                if manual_only_passwords:
                    source = "指定密码"
                elif password in rj_passwords:
                    source = "RJ号"
                elif password in password_source_map:
                    source = password_source_map.get(password) or "密码库"
                elif password in self.config.extract.password_list:
                    source = "默认"
                else:
                    source = "无"
                logger.info(f"成功读取压缩包内容，使用密码来源: {source} ({password or '无密码'})")
                # 注意：这里返回的 password 只是能读取内容的密码，不一定能解压
                # 真正能解压的密码会在 _try_extract 中更新
                archive_info = ArchiveInfo(
                    archive_path,
                    file_list,
                    password,
                    inferred_rjcode=password_rjcode_map.get(password),
                )
                # 读取本次 list 检测到的编码，存入 archive_info 供 _get_mcp_args 使用
                archive_info.detected_encoding = self.__class__._archive_encoding_cache.get(archive_path)
                if use_cache:
                    self._save_cached_archive_info(archive_path, archive_info)
                return archive_info

        logger.warning("无法预读取压缩包内容，后续将尝试直接解压: %s", archive_path)
        return None

    async def precheck_archive(
        self,
        task: Task,
        archive_path: Optional[str] = None,
    ) -> Optional[ArchiveInfo]:
        """为 task 异步预读取压缩包清单（用于查重 + list 并行场景）。

        - 内部走类级 list 缓存，命中即直接返回不跑 7zz。
        - 子进程注册到 task，task.cancel() 或本协程被 asyncio.Task.cancel() 都会被 kill。
        - 返回 ArchiveInfo 表示读取成功；返回 None 表示候选密码全部无法列出目录。
        """
        target_path = str(archive_path or getattr(task, "source_path", "") or "")
        if not target_path:
            return None
        # 指定密码重试：预读也只用指定密码，不触碰密码库
        meta = task.task_metadata or {}
        manual_pw = normalize_password_value(meta.get("manual_retry_password"))
        manual_only = bool(meta.get("manual_retry_password_only"))
        if manual_pw and manual_only:
            precheck_candidates: Optional[List[Dict[str, Optional[str]]]] = [{
                "password": manual_pw,
                "source": "指定密码",
                "entry_id": None,
                "rjcode": None,
            }]
        else:
            precheck_candidates = None
        return await self._get_archive_info(target_path, password_candidates=precheck_candidates, task=task)

    async def _list_archive_contents(
        self,
        archive_path: str,
        password: str = "",
        task: Optional[Task] = None,
        filename_encoding: Optional[Union[str, int]] = None,
    ) -> Optional[List[Dict]]:
        """列出压缩包内容，自动检测最佳编码

        task 不为 None 时把 7zz 子进程注册到 task，cancel/pause 或协程级
        asyncio.Task.cancel() 都会立刻 kill 子进程。
        """
        password_args = [f'-p{password}'] if password else []
        mcp_args = self._get_mcp_args(archive_path, filename_encoding=filename_encoding)
        commands = [
            [self.seven_zip, 'l', '-ba', *mcp_args, *password_args, archive_path],
            [self.seven_zip, 'l', '-slt', *mcp_args, *password_args, archive_path],
        ]

        for index, cmd in enumerate(commands):
            try:
                logger.debug(f"[7z] 执行命令: {' '.join(cmd)}")
                result = await self._run_7z_command(cmd, task=task)
                if result.returncode != 0:
                    logger.warning(
                        f"[7z] 列出压缩包内容失败，返回码: {result.returncode}, 错误: {result.stderr.decode('utf-8', errors='ignore')[:500]}"
                    )
                    continue

                raw_bytes = result.stdout
                best_encoding = self._detect_best_encoding(raw_bytes)
                logger.info(f"[7z] 自动检测编码: {best_encoding}")
                # 记录本次编码检测结果，供 _get_archive_info → _get_mcp_args 使用。
                # 如果前面已通过 ZIP 中央目录嗅探出编码，不用 7z stdout 的编码猜测覆盖它。
                self.__class__._archive_encoding_cache.setdefault(archive_path, best_encoding)
                decoded = raw_bytes.decode(best_encoding, errors='ignore')
                file_list = (
                    self._parse_7z_list_output(decoded)
                    if index == 0
                    else self._parse_7z_technical_output(decoded)
                )
                if file_list:
                    return file_list
            except Exception as e:
                logger.error(f"列出压缩包内容失败: {e}")
        return None

    def _sniff_zip_encoding(self, file_path: str) -> Optional[str]:
        """
        轻量级 ZIP 文件名编码嗅探：直接用 zipfile 读取中央目录头（不解压），
        对前 20 个含高位字节的文件名进行多编码评分。
        - 纯 ASCII 或 UTF-8 flag 置位 (bit 11) 的文件名直接跳过
        - 返回最佳编码名，无法判断时返回 None
        """
        import zipfile as _zipfile
        try:
            sample_bytes_list: list[bytes] = []
            with _zipfile.ZipFile(file_path, 'r') as zf:
                for info in zf.infolist():
                    # bit 11 = UTF-8 flag，已是标准 UTF-8，跳过
                    if info.flag_bits & 0x800:
                        continue
                    raw = info.orig_filename.encode('cp437') if isinstance(info.orig_filename, str) else info.filename.encode('utf-8')
                    # 只采集含高位字节的条目
                    if any(b > 0x7F for b in raw):
                        sample_bytes_list.append(raw)
                    if len(sample_bytes_list) >= 20:
                        break
            if not sample_bytes_list:
                return None
            combined = b'\n'.join(sample_bytes_list)
            result = self._detect_best_encoding(combined)
            # utf-8 得分最高说明本身就是 UTF-8 文件名，无需 -mcp
            if result in ('utf-8', 'utf_8', 'ascii'):
                return None
            return result
        except Exception as e:
            logger.debug(f"[编码嗅探] {file_path} 失败: {e}")
            return None

    def _detect_best_encoding(self, raw_bytes: bytes) -> str:
        """
        自动检测压缩包文件名的最佳编码
        依次尝试: utf-8 -> shift_jis -> gbk -> cp936 -> big5 -> euc_kr
        """
        # UTF-8 优先：7z/unar 的 stdout 如果被 GBK 误解，会产出 `鍋靛伃...`
        # 这类合法 CJK mojibake。旧逻辑把 CJK 全部加分，导致 GBK 抢赢。
        encodings = ['utf-8', 'shift_jis', 'gbk', 'cp936', 'big5', 'euc_kr']

        best_encoding = 'utf-8'
        best_score = -1

        for encoding in encodings:
            try:
                decoded = raw_bytes.decode(encoding, errors='replace')
                score = self._score_decoded_text(decoded)
                garbled_score = self._garbled_text_score(decoded)
                if garbled_score >= 30.0:
                    score -= int(garbled_score * 20)
                logger.debug(f"[编码检测] {encoding}: 得分 {score}")

                if score > best_score:
                    best_score = score
                    best_encoding = encoding
            except Exception as e:
                logger.debug(f"[编码检测] {encoding} 解码失败: {e}")
                continue

        return best_encoding

    def _score_decoded_text(self, text: str) -> int:
        """
        评估解码后文本的质量分数
        分数越高表示编码越可能是正确的
        """
        if not text:
            return 0

        score = 0

        # 1. 惩罚替换字符（乱码标志）
        replacement_count = text.count('\ufffd')
        score -= replacement_count * 10

        # 2. 惩罚控制字符（除换行、制表符外）
        control_chars = sum(1 for c in text if ord(c) < 32 and c not in '\n\r\t')
        score -= control_chars * 5

        # 3. 奖励常见字符（日文假名、中文、字母数字）
        for c in text:
            # 日文平假名、片假名
            if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff':
                score += 2
            # 中日韩统一表意文字
            elif '\u4e00' <= c <= '\u9fff':
                score += 1
            # 字母数字
            elif c.isalnum() or c in '._-+/\\':
                score += 1
            # 常见符号
            elif c in '（）()[]【】「」『』・·':
                score += 1
            # 空格
            elif c == ' ':
                score += 0.5

        # 4. 检测常见乱码模式（GBK解码Shift_JIS时出现的特征）
        # 例如：日文假名被错误解码成生僻汉字
        garbled_patterns = [
            r'[\u9e\u9f][\u00-\x7f]',  # 部分乱码特征
        ]
        for pattern in garbled_patterns:
            if re.search(pattern, text):
                score -= 20

        return int(score)

    def _parse_7z_list_output(self, output: str) -> List[Dict]:
        """解析7z列表输出"""
        files = []
        # 7z l -ba 输出格式: 日期 时间 属性 大小 压缩大小 文件名
        pattern = r'^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+([D.][R.][H.][S.][A.])\s+(\d+)\s+(\d+)?\s+(.+)$'

        for line in output.strip().split('\n'):
            match = re.match(pattern, line)
            if match:
                size = int(match.group(4))
                name = match.group(6)
                files.append({
                    'name': name,
                    'size': size,
                    'is_dir': 'D' in match.group(3)
                })

        return files

    def _parse_7z_technical_output(self, output: str) -> List[Dict]:
        """解析 7z l -slt 输出，作为 -ba 失败时的兜底"""
        files: List[Dict] = []
        current: Dict[str, str] = {}

        def flush_current():
            if not current:
                return
            path_value = current.get('Path')
            size_value = current.get('Size')
            attr_value = current.get('Attributes', '')
            if path_value and size_value is not None:
                try:
                    files.append({
                        'name': path_value,
                        'size': int(size_value or 0),
                        'is_dir': 'D' in attr_value
                    })
                except ValueError:
                    pass

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line:
                flush_current()
                current = {}
                continue
            if ' = ' not in line:
                continue
            key, value = line.split(' = ', 1)
            current[key.strip()] = value.strip()

        flush_current()
        return files

    async def _try_extract(
        self,
        archive_info: ArchiveInfo,
        output_path: str,
        task: Task,
        password_candidates: Optional[List[Dict[str, Optional[str]]]] = None,
    ) -> tuple[bool, Optional[str], str]:
        """尝试解压，返回 (是否成功, 成功使用的密码)"""
        if password_candidates is None:
            password_candidates = await self._get_password_candidates_for_archive(archive_info.path)
        vault_passwords = [item["password"] for item in password_candidates]
        password_source_map = {
            item["password"]: item.get("source")
            for item in password_candidates
            if item.get("password")
        }
        password_entry_id_map = {
            item["password"]: item.get("entry_id")
            for item in password_candidates
            if item.get("entry_id")
        }
        password_rjcode_map = {
            item["password"]: item.get("rjcode")
            for item in password_candidates
            if item.get("rjcode")
        }

        manual_retry_password = normalize_password_value(
            (task.task_metadata or {}).get("manual_retry_password")
        )
        manual_retry_password_only = bool((task.task_metadata or {}).get("manual_retry_password_only"))

        if manual_retry_password and manual_retry_password_only:
            unique_passwords = [manual_retry_password]
            vault_passwords = []
            rj_passwords = []
        else:
            # 获取RJ号相关密码
            rj_passwords = self._get_rj_passwords(archive_info.path)

            # 构建密码列表：预读成功密码优先，减少同一压缩包重复失败尝试。
            password_list = []
            if archive_info.password:
                password_list.append(archive_info.password)
            password_list.extend(rj_passwords)  # RJ号密码（RJ号, RJ号+1, RJ号-1）
            password_list.extend(vault_passwords)  # 密码库密码
            password_list.append("")  # 无密码
            password_list.extend(self.config.extract.password_list)  # 默认密码

            # 去重（保持顺序）
            seen = set()
            unique_passwords = []
            for pwd in password_list:
                if pwd not in seen:
                    seen.add(pwd)
                    unique_passwords.append(pwd)

        # 预读目录可用说明压缩包结构至少可读；后续若遇疑似"损坏"特征，
        # 更可能是头加密 + 错密码，而不是真的坏包，用于最后定性判断。
        listing_available = bool(getattr(archive_info, "file_list", None))
        encountered_wrong_password = False
        last_corrupt_stderr: Optional[str] = None

        # ========== RAR fast-path: 优先用 unar 解压日文 / 中文 RAR ==========
        # 7zz 24.08 的 RAR 解析器不接受 -mcp 参数，遇到 Shift-JIS / GBK 命名的 RAR
        # 时只能按本机 locale 解释 ANSI 字节 → 必然出乱码 → 群晖看到 ��� 无法访问。
        # 这里在主密码循环之前先用 unar 跑一遍密码列表，unar 的 ICU 编码自动探测
        # 能给日文 / 中文 RAR 出干净的 UTF-8 文件名。
        # unar 不可用 / 不识别该 RAR 变体时，自动回退到下面的 7zz 老流程。
        is_rar_archive = self._is_rar_archive(archive_info.path)
        garbled_toc_sample = (
            self._archive_file_list_garbled_sample(getattr(archive_info, "file_list", None))
            if is_rar_archive else None
        )
        if self.config.extract.prefer_unar_for_rar and is_rar_archive:
            if self._find_unar_executable():
                unar_success, unar_password, unar_reason = await self._try_extract_rar_with_unar(
                    archive_info,
                    output_path,
                    task,
                    unique_passwords,
                    vault_passwords,
                    password_entry_id_map,
                    password_rjcode_map,
                    manual_retry_password_only,
                    password_source_map=password_source_map,
                    rj_passwords=rj_passwords if not manual_retry_password_only else [],
                )
                if unar_success:
                    return True, unar_password, ""
                if unar_reason == "cancelled":
                    return False, None, "cancelled"
                if unar_reason == "disk_full":
                    return False, None, "disk_full"
                if unar_reason == "wrong_password":
                    return False, None, "wrong_password"
                if garbled_toc_sample and unar_reason != "partial_output":
                    logger.error(
                        "RAR 目录清单已疑似乱码且 unar 未能处理，拒绝回退 7zz 以免产出乱码文件: archive=%s sample=%s reason=%s",
                        archive_info.path,
                        garbled_toc_sample,
                        unar_reason,
                    )
                    return False, None, "garbled_filename"
                await self._cleanup_extract_attempt(output_path)
                logger.info(
                    "RAR unar fast-path 未成功 (%s)，回退到 7zz 流程: %s",
                    unar_reason, archive_info.path,
                )
            elif garbled_toc_sample:
                logger.error(
                    "RAR 目录清单已疑似乱码但运行环境缺少 unar，拒绝使用 7zz 解压: archive=%s sample=%s",
                    archive_info.path,
                    garbled_toc_sample,
                )
                return False, None, "garbled_filename"

        # #3 负缓存：同一压缩包同一密码近期失败过，直接跳过；指纹拿不到就不缓存。
        archive_fingerprint = self._archive_fingerprint(archive_info.path)

        for password in unique_passwords:
            password_args = [f'-p{password}'] if password else []
            cmd = [
                self.seven_zip, 'x',
                '-y',  # 自动确认
                '-o' + output_path,  # 输出目录
                '-bsp1', # 启用进度输出
                '-bso1', # 将进度输出到 stdout
                *self._get_seven_zip_mmt_args(),  # 指定 7z 多线程（默认 -mmt=on）
                *self._get_mcp_args(archive_info.path, archive_info, filename_encoding=manual_filename_encoding),  # ZIP 文件名编码（仅 .zip 生效）
                *password_args,
                archive_info.path
            ]

            try:
                # 判断密码来源
                if manual_retry_password and manual_retry_password_only:
                    password_source = "指定密码"
                elif password in rj_passwords:
                    password_source = "RJ号"
                elif password in password_source_map:
                    password_source = password_source_map.get(password) or "密码库"
                elif password == archive_info.password:
                    password_source = "已知"
                elif password == "":
                    password_source = "无"
                else:
                    password_source = "默认"

                # #3 命中负缓存：跳过，不再启动 7z
                cache_key = (
                    self._password_cache_key(archive_fingerprint, password)
                    if archive_fingerprint else None
                )
                if cache_key and cache_key in ExtractService._password_negative_cache:
                    logger.info(
                        "密码 %s (%s) 命中负缓存，跳过本次尝试",
                        password_source,
                        password or '无密码',
                    )
                    encountered_wrong_password = True
                    continue

                # 每轮入口先响应取消 / 暂停，避免用户点了按钮但还会换下一个密码继续跑
                if task.is_cancelled():
                    return False, None, "cancelled"
                await task.wait_if_paused()
                if task.is_cancelled():
                    return False, None, "cancelled"

                # 流式预验证：错密码秒级淘汰，避免跑完整解压才发现 CRC Failed
                if self.PROBE_BEFORE_EXTRACT:
                    task.update_progress(38, f"探测密码 (来源: {password_source})")
                    probe_result = await self._probe_password(
                        archive_info.path,
                        password,
                        probe_bytes=self.PROBE_BYTES,
                        timeout=self.PROBE_TIMEOUT_SECONDS,
                        file_list=getattr(archive_info, 'file_list', None),
                        task=task,
                    )
                    # 探测期间被 cancel/pause kill 掉，按 stop_reason 决策
                    if task.is_cancelled():
                        return False, None, "cancelled"
                    if probe_result == 'unknown' and task.consume_stop_reason() == 'pause':
                        await task.wait_if_paused()
                        if task.is_cancelled():
                            return False, None, "cancelled"
                        # 用户恢复后重试本轮密码的完整解压（跳过探测，不再迫追探测结果）
                        probe_result = 'ok'
                    if probe_result == 'wrong_password':
                        encountered_wrong_password = True
                        if cache_key:
                            self._remember_negative_password(cache_key)
                        logger.info(
                            "密码 %s (%s) 探测阶段判定为密码错误，跳过完整解压",
                            password_source,
                            password or '无密码',
                        )
                        continue
                    if probe_result == 'corrupt':
                        last_corrupt_stderr = last_corrupt_stderr or 'probe: corrupt'
                        if cache_key:
                            self._remember_negative_password(cache_key)
                        logger.warning(
                            "密码 %s (%s) 探测阶段命中疑似损坏特征，跳过完整解压",
                            password_source,
                            password or '无密码',
                        )
                        continue
                    if probe_result == 'ok':
                        logger.info(
                            "密码 %s (%s) 探测通过，进入完整解压",
                            password_source,
                            password or '无密码',
                        )
                    elif probe_result == 'unknown':
                        logger.info(
                            "密码 %s (%s) 探测无法定性，进入完整解压兜底",
                            password_source,
                            password or '无密码',
                        )
                    # 'ok' / 'unknown' 都让其继续走完整解压：
                    #   - ok: 大概率密码正确，直接进入 x
                    #   - unknown: 探测无法定性（如超时 / 7zz 输出特殊），保持旧行为兜底

                # 创建进度解析回调
                start_time = datetime.now()
                last_update = 0
                last_percent = -1

                def progress_callback(line: str):
                    nonlocal last_update, last_percent
                    # 解析 7z 进度行，例如:  12% 123/1000 5678/100000000
                    percent_match = re.search(r"(\d{1,3})%", line)
                    if percent_match:
                        raw_percent = int(percent_match.group(1))
                        # 解压阶段占 10% - 95%
                        mapped = 10 + int(raw_percent * 0.85)

                        now = datetime.now()
                        elapsed = (now - start_time).total_seconds()

                        speed_str = ""
                        eta_str = ""

                        # 提取已处理字节数以计算速度
                        # 7z 的进度行通常包含多个 x/y 部分，通常最后一个是字节
                        matches = re.findall(r"(\d+)/\d+", line)
                        if matches and elapsed > 0:
                            current_bytes = int(matches[-1])
                            speed = current_bytes / elapsed
                            if speed > 1024 * 1024:
                                speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
                            elif speed > 1024:
                                speed_str = f"{speed / 1024:.2f} KB/s"
                            else:
                                speed_str = f"{speed:.0f} B/s"

                            if raw_percent > 0:
                                total_seconds = elapsed * 100 / raw_percent
                                remaining = total_seconds - elapsed
                                if remaining > 0:
                                    m, s = divmod(int(remaining), 60)
                                    h, m = divmod(m, 60)
                                    eta_str = f"{h:d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

                        # 控制更新频率
                        current_ts = now.timestamp()
                        if raw_percent == last_percent and raw_percent != 100:
                            return
                        if current_ts - last_update >= 1.5 or raw_percent == 100:
                            last_update = current_ts
                            last_percent = raw_percent
                            task.update_progress(min(99, mapped), f"解压中 {raw_percent}%" + (f" ({speed_str}, 剩余 {eta_str})" if speed_str else ""))

                # 对同一个密码重试完整解压：被暂停 kill 掉后，恢复时希望从同一个密码
                # 重新跑 x，而不是跳到下一个密码（那会导致恢复后丢掉85%进度并跳密码）。
                while True:
                    task.update_progress(40, f"准备解压 (密码来源: {password_source})")
                    result = await self._run_7z_command(
                        cmd,
                        progress_callback=progress_callback,
                        capture_stdout=False,
                        task=task,
                    )
                    if task.is_cancelled():
                        return False, None, "cancelled"
                    # 被暂停 kill 掉了：returncode 非零 + stop_reason == 'pause'
                    if result.returncode != 0 and task.consume_stop_reason() == 'pause':
                        logger.info(
                            f"任务 {task.id} 被暂停中断了当前解压，等待恢复后重试同一密码: {password_source}"
                        )
                        await task.wait_if_paused()
                        if task.is_cancelled():
                            return False, None, "cancelled"
                        continue  # 重跑同一个 cmd
                    break

                if result.returncode == 0:
                    if await self._reject_if_garbled_after_extract(
                        archive_info.path,
                        output_path,
                        cleanup=lambda: self._cleanup_extract_attempt(output_path),
                        context="7zz",
                        task=task,
                        ignore_garbled=manual_ignore_garbled,
                    ):
                        return False, None, "garbled_filename"
                    if not await self._verify_extraction(archive_info, output_path):
                        await self._cleanup_extract_attempt(output_path)
                        return False, None, "extract_incomplete"
                    # 记录成功使用的密码
                    if password and password in vault_passwords:
                        await self._record_password_usage(
                            password,
                            archive_info.path,
                            entry_id=password_entry_id_map.get(password),
                        )
                    # 更新 archive_info 中的密码，用于传递给嵌套压缩包
                    archive_info.password = password
                    inferred_rjcode = password_rjcode_map.get(password)
                    if inferred_rjcode:
                        archive_info.inferred_rjcode = inferred_rjcode
                        task.task_metadata['inferred_rjcode'] = inferred_rjcode
                        task.task_metadata['rjcode'] = inferred_rjcode
                        task.task_metadata['inferred_rjcode_source'] = 'password_entry'
                        if not getattr(task, 'rjcode', None) or str(task.rjcode).strip() in {'', '未知'}:
                            task.rjcode = inferred_rjcode
                    logger.info(f"解压成功，使用{password_source}密码: {password or '无密码'}")
                    return True, password, ""

                stderr_text = (result.stderr or b"").decode('utf-8', errors='ignore')
                stderr_lower = stderr_text.lower()

                disk_full_markers = (
                    "磁盘空间不足",
                    "there is not enough space",
                    "not enough space",
                    "no space left on device",
                    "cannot set length for output file",
                    "write error",
                )
                if any(marker in stderr_lower or marker in stderr_text for marker in disk_full_markers):
                    logger.error(
                        "检测到解压目标磁盘空间不足，停止密码重试: %s",
                        stderr_text[:300] if stderr_text else "(无错误文本)",
                    )
                    return False, None, "disk_full"

                # 扩展加密错误识别：不同版本 p7zip / 7zz 的密码错措辞差异较大，
                # 只靠 "wrong password" 一个关键字会漏判，导致后面误走损坏分支。
                encryption_markers = (
                    "wrong password",
                    "password is incorrect",
                    "password?",                 # "Wrong password?" / "Enter password?"
                    "passphrase",
                    "cannot open encrypted",
                    "is encrypted",
                )
                if any(marker in stderr_lower for marker in encryption_markers):
                    encountered_wrong_password = True
                    if cache_key:
                        self._remember_negative_password(cache_key)
                    logger.warning(f"密码 {password_source} ({password or '无密码'}) 解压失败: 密码错误")
                    continue

                archive_corrupt_markers = (
                    "headers error",
                    "unconfirmed start of archive",
                    "unexpected end of archive",
                    "cannot open the file as archive",
                    "can not open the file as archive",
                    "e_invalidarg",
                )
                if any(marker in stderr_lower for marker in archive_corrupt_markers):
                    if self._is_rar_archive(archive_info.path):
                        unar_result = await self._try_unar_extract(
                            archive_info.path,
                            output_path,
                            password,
                            task=task,
                        )
                        if unar_result.returncode == 0:
                            # 乱码修复：Shift-JIS/GBK RAR 文件名自动编码探测失败时重试
                            await self._fix_unar_garbled_encoding(
                                archive_info.path, output_path, password, task=task,
                            )
                            if password and password in vault_passwords:
                                await self._record_password_usage(
                                    password,
                                    archive_info.path,
                                    entry_id=password_entry_id_map.get(password),
                                )
                            archive_info.password = password
                            inferred_rjcode = password_rjcode_map.get(password)
                            if inferred_rjcode:
                                archive_info.inferred_rjcode = inferred_rjcode
                                task.task_metadata['inferred_rjcode'] = inferred_rjcode
                                task.task_metadata['rjcode'] = inferred_rjcode
                                task.task_metadata['inferred_rjcode_source'] = 'password_entry'
                                if not getattr(task, 'rjcode', None) or str(task.rjcode).strip() in {'', '未知'}:
                                    task.rjcode = inferred_rjcode
                            logger.info(f"RAR fallback 解压成功，使用{password_source}密码: {password or '无密码'}")
                            return True, password, ""
                        unar_stderr = (unar_result.stderr or b"").decode('utf-8', errors='ignore').lower()
                        if "password" in unar_stderr or "passphrase" in unar_stderr:
                            encountered_wrong_password = True
                            logger.warning(f"RAR fallback 密码 {password_source} ({password or '无密码'}) 解压失败: 密码错误")
                            continue
                    # 不再立刻判定损坏：头加密 7z + 错密码同样会输出 "Headers Error" /
                    # "Cannot open the file as archive"（p7zip/7zz 多版本文案不稳定），
                    # 立刻 return 会导致密码库里剩下的真密码永远没机会被试到。
                    # 改为记录最后一次疑似损坏的 stderr，把剩余密码跑完再统一定性。
                    last_corrupt_stderr = stderr_text or stderr_lower
                    logger.warning(
                        "密码 %s (%s) 返回疑似损坏/头加密特征，继续尝试下一个密码: %s",
                        password_source,
                        password or '无密码',
                        (stderr_text or stderr_lower)[:300] if (stderr_text or stderr_lower) else "(无错误文本)",
                    )
                    continue

                if "data error" in stderr_lower:
                    last_corrupt_stderr = stderr_text or stderr_lower
                    logger.warning(
                        "7z 返回 Data Error，按密码失败继续尝试，避免把加密包误判为损坏: source=%s stderr=%s",
                        password_source,
                        stderr_text[:300] if stderr_text else "(无错误文本)",
                    )
                    continue

            except Exception as e:
                logger.warning(f"解压尝试失败: {e}")
                continue

        # 所有密码都失败后的统一定性：
        # 1) 预读目录成功 或 曾经命中明确的加密错误 → 视为密码错误（用户多半是密码库没录对）
        # 2) 否则若曾遇到疑似损坏特征 → 判损坏
        # 3) 其他兜底 → 密码错误
        if listing_available or encountered_wrong_password:
            if last_corrupt_stderr:
                logger.warning(
                    "所有密码尝试失败，但压缩包结构看似可读/曾命中加密错误，判为密码错误而非损坏。最后一次疑似损坏 stderr: %s",
                    last_corrupt_stderr[:300],
                )
            return False, None, "wrong_password"
        if last_corrupt_stderr:
            logger.error(
                "所有密码尝试均失败，且全程未能读取压缩包目录，判定为损坏：%s",
                last_corrupt_stderr[:300],
            )
            return False, None, "archive_corrupt"
        return False, None, "wrong_password"

    async def _verify_extraction(self, archive_info: ArchiveInfo, output_path: str) -> bool:
        """验证解压完整性"""
        if not self.config.extract.verify_after_extract:
            return True

        if not archive_info.file_list:
            logger.warning("压缩包预读清单为空，跳过完整性验证: %s", archive_info.path)
            return True

        file_entries = [item for item in archive_info.file_list if not item.get('is_dir')]
        total_files = len(file_entries)
        verify_mode = "full"
        if total_files > self.VERIFY_FULL_FILE_LIMIT:
            verify_mode = "sample"
            head_count = self.VERIFY_SAMPLE_FILE_LIMIT // 3
            tail_count = self.VERIFY_SAMPLE_FILE_LIMIT // 3
            stride_count = max(0, self.VERIFY_SAMPLE_FILE_LIMIT - head_count - tail_count)
            stride = max(1, total_files // max(1, stride_count))
            sampled = file_entries[:head_count]
            sampled.extend(file_entries[head_count:total_files - tail_count:stride][:stride_count])
            sampled.extend(file_entries[-tail_count:])
            seen_names = set()
            file_entries = [
                item for item in sampled
                if not (item.get('name') in seen_names or seen_names.add(item.get('name')))
            ]
            logger.info(
                "压缩包文件数 %s，使用抽样完整性验证 %s/%s: %s",
                total_files,
                len(file_entries),
                total_files,
                archive_info.path,
            )

        missing_files = []
        size_mismatch_files = []

        # 用一次 scandir 递归把 {相对路径(已规范化为正斜杠): 大小} 全部拿到，
        # 后续匹配走 dict O(1) 查表，避免 per-file os.path.exists + os.path.getsize。
        # HDD 上原 per-file 路径会触发 N×3 次 stat（可能伴随 MFT 寻道），
        # 改成一次 scandir 后基本只有顺序 metadata 读取，几千文件从十几秒缩到 1 秒以内。
        def _scan_actual_files() -> Dict[str, int]:
            actual: Dict[str, int] = {}
            stack = [output_path]
            while stack:
                current = stack.pop()
                try:
                    with os.scandir(current) as it:
                        for entry in it:
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(entry.path)
                                    continue
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                                # Windows 上 scandir 返回的 stat 信息已经从 FindFirstFile 取到，
                                # 不会再产生额外 IO；Linux 上 d_type 不带 size，会走一次 fstatat。
                                size = entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                continue
                            rel = os.path.relpath(entry.path, output_path).replace('\\', '/')
                            actual[rel] = size
                except OSError:
                    continue
            return actual

        actual_files = await asyncio.to_thread(_scan_actual_files)

        # 反向 mojibake 修复：把磁盘上的 actual 路径也跑一遍反解，
        # 建立修复后路径 → 原始 actual 键的反向映射，
        # 就算 expected.path 反解失败时，也可以通过 actual 端反解匹配到。
        def _build_inverse_lookup(real: Dict[str, int]) -> Dict[str, str]:
            inv: Dict[str, str] = {}
            for actual_path in real.keys():
                repaired = self._repair_mojibake_relative_path(actual_path)
                if repaired and repaired != actual_path and repaired not in inv:
                    inv[repaired] = actual_path
            return inv

        inverse_actual_lookup = await asyncio.to_thread(_build_inverse_lookup, actual_files)

        critical_zero_byte_files: List[Dict] = []  # expected.size > 0 但 actual.size == 0

        for expected in file_entries:
            expected_name = str(expected.get('name') or '')
            if not expected_name:
                continue
            expected_size = expected['size']
            # 编码兼容：archive 清单可能是 cp932 / utf-8 解释结果，scandir 出来的是
            # NTFS unicode；把 expected 的多种编码变体都查一遍 dict，找到任一即可。
            normalized = expected_name.replace('\\', '/')
            candidates = {
                normalized,
                expected_name.encode('utf-8', errors='ignore').decode('utf-8', errors='ignore').replace('\\', '/'),
                expected_name.encode('cp932', errors='ignore').decode('cp932', errors='ignore').replace('\\', '/'),
            }
            repaired_expected_name = self._repair_mojibake_relative_path(expected_name)
            if repaired_expected_name:
                candidates.add(repaired_expected_name)
            # 反向 lookup：expected 样子匹配修复后的 actual key（标签上 expected 已然是正确的）。
            for variant in tuple(candidates):
                if variant in inverse_actual_lookup:
                    candidates.add(inverse_actual_lookup[variant])
            found_size: Optional[int] = None
            for variant in candidates:
                if variant in actual_files:
                    found_size = actual_files[variant]
                    break

            if found_size is None:
                missing_files.append(expected_name)
                continue

            if found_size != expected_size:
                size_mismatch_files.append({
                    'name': expected_name,
                    'expected': expected_size,
                    'actual': found_size,
                })
                # critical：expected > 0 但 actual == 0 的零字节文件（实际丢数据）
                if expected_size > 0 and found_size == 0:
                    critical_zero_byte_files.append({
                        'name': expected_name,
                        'expected': expected_size,
                    })

        # 如果有文件缺失，记录警告；但缺失过多不能继续放行。
        # 之前会把“清单乱码导致找不到文件”全部当软警告，结果 0 字节落盘也能通过。
        # 现在已把 expected path 的 mojibake 反解候选纳入匹配，仍找不到就更像真的缺失。
        if missing_files:
            logger.warning(f"以下文件可能因编码问题无法验证: {missing_files[:5]}")
            if len(missing_files) > 5:
                logger.warning(f"... 还有 {len(missing_files) - 5} 个文件")

        if size_mismatch_files:
            for mismatch in size_mismatch_files[:5]:
                logger.warning(f"文件大小不匹配: {mismatch['name']} (期望: {mismatch['expected']}, 实际: {mismatch['actual']})")

        # critical：expected > 0 但 actual == 0（零字节文件）无条件拒绝
        if critical_zero_byte_files:
            logger.error(
                "有 %s 个文件期望>0但落盘=0（零字节丢数据），拒绝接受: archive=%s sample=%s",
                len(critical_zero_byte_files),
                archive_info.path,
                critical_zero_byte_files[:3],
            )
            return False

        # 大小不匹配 → 拒绝
        if size_mismatch_files:
            logger.error(f"有 {len(size_mismatch_files)} 个文件大小不匹配，解压可能不完整")
            return False

        # missing 阈值收紧：旧实现是 50%，实测导致 14/30 缺失也判通过。
        # 改成 10% 阈值：如果反解修复工作正常，缺失 有很明显的编码失效。
        if missing_files:
            total_count = max(len(file_entries), 1)
            missing_ratio = len(missing_files) / total_count
            # 绝对阈值：缺失文件 >= 5 个 或 比例 >= 10%，要拒绝。
            if missing_ratio >= 0.1 or len(missing_files) >= 5:
                logger.error(
                    "有 %s/%s (%.0f%%) 个文件无法验证，拒绝接受解压结果: archive=%s",
                    len(missing_files),
                    len(file_entries),
                    missing_ratio * 100.0,
                    archive_info.path,
                )
                return False

        logger.info(
            "解压完整性验证完成: mode=%s checked=%s total=%s archive=%s",
            verify_mode,
            len(file_entries),
            total_files,
            archive_info.path,
        )

        return True

    async def _cleanup_extract_path(self, output_path: str):
        """异步清理解压路径，避免高并发失败时阻塞事件循环"""
        if not os.path.exists(output_path):
            return

        for attempt in range(3):
            try:
                await asyncio.to_thread(shutil.rmtree, output_path)
                logger.info(f"已清理解压目录: {output_path}")
                return
            except FileNotFoundError:
                return
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"清理尝试 {attempt + 1} 失败，1秒后重试: {output_path}")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"清理解压目录失败: {output_path}, {e}")

    async def _run_7z_command(
        self,
        cmd: List[str],
        progress_callback: Optional[Callable[[str], None]] = None,
        capture_stdout: bool = True,
        max_captured_bytes: int = 4 * 1024 * 1024,
        task: Optional[Task] = None,
    ) -> subprocess.CompletedProcess:
        """运行7z命令。传入 task 后会把子进程登记到 task 上，cancel/pause 能立刻 kill。"""
        # 记录命令（显示密码用于调试）
        logger.info(f"执行7z命令: {' '.join(cmd)}")

        semaphore = self._get_7z_semaphore()
        is_extract_command = self._is_extract_subprocess_command(cmd)

        try:
            if task is not None and is_extract_command and self._is_semaphore_locked(semaphore):
                task.update_progress(
                    max(31, int(task.progress or 0)),
                    f"等待解压槽位（当前并发上限 {self.__class__._seven_zip_semaphore_limit or 1}）",
                )
            async with semaphore:
                if task is not None and is_extract_command:
                    task.update_progress(max(40, int(task.progress or 0)), "解压子进程已启动")
                # Windows 上隐藏子进程窗口，避免闪烁
                kwargs = {
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.PIPE,
                    'stdin': subprocess.DEVNULL,
                }
                if sys.platform == 'win32':
                    from subprocess import CREATE_NO_WINDOW
                    kwargs['creationflags'] = CREATE_NO_WINDOW

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    **kwargs
                )
                if task is not None:
                    task.register_process(process)

                stdout_data = bytearray()
                stderr_data = bytearray()

                async def read_stream(stream, buffer, is_stdout=False):
                    while True:
                        chunk = await stream.read(4096)
                        if not chunk:
                            break
                        should_store = (is_stdout and capture_stdout) or (not is_stdout)
                        if should_store and len(buffer) < max_captured_bytes:
                            remain = max_captured_bytes - len(buffer)
                            if remain > 0:
                                buffer.extend(chunk[:remain])
                        if is_stdout and progress_callback:
                            try:
                                text = chunk.decode('utf-8', errors='ignore')
                                for line in text.replace('\r', '\n').split('\n'):
                                    if line.strip():
                                        progress_callback(line.strip())
                            except Exception:
                                pass

                try:
                    await asyncio.gather(
                        read_stream(process.stdout, stdout_data, is_stdout=True),
                        read_stream(process.stderr, stderr_data)
                    )

                    return_code = await process.wait()
                    await asyncio.sleep(0.1)
                except asyncio.CancelledError:
                    # 协程级取消（asyncio.Task.cancel()）不同于 task.cancel()：
                    # task.cancel() 会通过 _active_processes 主动 kill 子进程；
                    # 单纯的 asyncio.Task.cancel() 只让本协程退出，注册过的 7z 子进程
                    # 不会被自动 kill。这里显式 kill，避免并发场景下 list 子进程在
                    # 协程被取消后继续后台跑，浪费 CPU / IO（方案 B 并行查重+list 依赖）。
                    if process.returncode is None:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        except Exception:
                            logger.debug("CancelledError 时 kill 7z 子进程失败（忽略）", exc_info=True)
                    raise
                finally:
                    if task is not None:
                        task.unregister_process(process)

                if return_code != 0:
                    logger.error(f"7z命令执行失败，返回码: {return_code}")
                    err_text_for_retry = ''
                    try:
                        # Linux 容器 stderr 是 UTF-8，Windows 7-Zip 多为 GBK。
                        # 优先 UTF-8，失败再按平台回退，避免把 UTF-8 中文路径
                        # 误当 GBK 解出一堆乱码（例如把 `解压码0504` 错成 `瑙ｅ帇鐮0504`）。
                        fallback_encoding = 'gbk' if sys.platform == 'win32' else 'utf-8'
                        try:
                            err_text = bytes(stderr_data).decode('utf-8')
                        except UnicodeDecodeError:
                            err_text = bytes(stderr_data).decode(fallback_encoding, errors='replace')
                        err_text_for_retry = err_text
                        logger.error(f"错误输出: {err_text[:500]}")
                    except Exception as e:
                        logger.error(f"执行7z命令失败: {e}")
                    # E_INVALIDARG + -mcp= 兼容性自动重试：
                    # 7zz 24.08+ 某些版本/某些 ZIP 文件组合对 `-mcp=N` 直接抛
                    # `opening : E_INVALIDARG`，导致 list / 解压都失败。这里检测到后
                    # 标记类属性 _seven_zip_mcp_unsupported = True（后续 _get_mcp_args
                    # 一律 short-circuit 返回 []），并剥掉 -mcp 重试一次。
                    # 标志位 True 之后递归调用走 _get_mcp_args short-circuit，无无限递归风险。
                    if (
                        'E_INVALIDARG' in err_text_for_retry
                        and any(isinstance(arg, str) and arg.startswith('-mcp=') for arg in cmd)
                        and not self.__class__._seven_zip_mcp_unsupported
                    ):
                        self.__class__._seven_zip_mcp_unsupported = True
                        cleaned_cmd = [
                            arg for arg in cmd
                            if not (isinstance(arg, str) and arg.startswith('-mcp='))
                        ]
                        logger.warning(
                            "[7z] 检测到 -mcp 参数不被该 7zz 版本接受 (E_INVALIDARG)，"
                            "标记 _seven_zip_mcp_unsupported 并剥掉 -mcp 重试: %s",
                            ' '.join(cleaned_cmd),
                        )
                        return await self._run_7z_command(
                            cleaned_cmd,
                            progress_callback=progress_callback,
                            capture_stdout=capture_stdout,
                            max_captured_bytes=max_captured_bytes,
                            task=task,
                        )
                    return subprocess.CompletedProcess(
                        args=cmd,
                        returncode=return_code,
                        stdout=bytes(stdout_data),
                        stderr=bytes(stderr_data)
                    )

                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=return_code,
                    stdout=bytes(stdout_data),
                    stderr=bytes(stderr_data)
                )
        except Exception as e:
            logger.error(f"执行7z命令异常: {e}")
            raise

    # ---------------------------------------------------------------
    # 密码探测 / 负缓存
    # ---------------------------------------------------------------

    def _archive_fingerprint(self, path: str) -> Optional[str]:
        """用 (绝对路径|大小|mtime) 当压缩包指纹，文件被替换/编辑后会自动失效。"""
        try:
            st = os.stat(path)
        except OSError:
            return None
        return f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"

    def _password_cache_key(self, fingerprint: str, password: str) -> Tuple[str, str]:
        pwd_bytes = (password or '').encode('utf-8', errors='ignore')
        pwd_hash = hashlib.sha1(pwd_bytes if password else b'<empty>').hexdigest()[:16]
        return (fingerprint, pwd_hash)

    def _remember_negative_password(self, cache_key: Tuple[str, str]) -> None:
        cache = ExtractService._password_negative_cache
        # 简单容量上限：超出阈值时丢掉最早写入的一批，避免长跑任务无限增长。
        if len(cache) >= self.PASSWORD_NEGATIVE_CACHE_MAX:
            try:
                drop_count = max(1, self.PASSWORD_NEGATIVE_CACHE_MAX // 8)
                for old_key in list(cache.keys())[:drop_count]:
                    cache.pop(old_key, None)
            except Exception:
                cache.clear()
        cache[cache_key] = time.time()

    def _pick_probe_entry(self, file_list: Optional[List[Dict]]) -> Optional[Dict]:
        """从压缩包目录里选一个适合拿来 t 探测的条目：非目录、非空、尺寸不超阈值。按大小升序选最小。"""
        if not file_list:
            return None
        candidates = []
        for f in file_list:
            try:
                if f.get('is_dir'):
                    continue
                size = int(f.get('size') or 0)
                name = f.get('name') or ''
                if size <= 0 or not name:
                    continue
                if size > self.PROBE_ENTRY_MAX_SIZE:
                    continue
                candidates.append((size, name))
            except Exception:
                continue
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        size, name = candidates[0]
        return {'name': name, 'size': size}

    def _pick_magic_entries(self, file_list: Optional[List[Dict]]) -> List[Dict]:
        """挑多个后缀在魔数表里的条目，用于流式读前几十字节做魔数校验。"""
        if not file_list:
            return []
        candidates = []
        for f in file_list:
            try:
                if f.get('is_dir'):
                    continue
                size = int(f.get('size') or 0)
                name = f.get('name') or ''
                if size <= 0 or not name:
                    continue
                ext = os.path.splitext(name)[1].lower()
                magic_info = self._KNOWN_MAGIC_TABLE.get(ext)
                if not magic_info:
                    continue
                candidates.append((size, name, magic_info))
            except Exception:
                continue
        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0])
        entries = []
        seen_names = set()
        for size, name, (offset, magics) in candidates:
            if name in seen_names:
                continue
            seen_names.add(name)
            entries.append({
                'name': name,
                'size': size,
                'magic_offset': offset,
                'magics': magics,
            })
            if len(entries) >= self.PROBE_MAGIC_ENTRY_LIMIT:
                break
        return entries

    async def _probe_by_magic(
        self,
        archive_path: str,
        password: str,
        entry: Dict,
        timeout: float,
        task: Optional[Task] = None,
    ) -> str:
        """用 `7zz x -so archive -i!<entry>` 流式解压指定条目，只读前几十字节对照魔数。

        密码错时 AES 输出是随机字节，魔数绝不会碰巧命中→直接判 wrong_password。
        密码对时前几十字节就是真实文件头，解压出来的 magic 和表里对得上→ok。
        整个过程读盘量极小，单个大文件也不需要拆出来完整 t。
        """
        entry_name = entry['name']
        magic_offset: int = entry['magic_offset']
        magics: Tuple[bytes, ...] = entry['magics']
        max_magic_len = max(len(m) for m in magics)
        need_bytes = magic_offset + max_magic_len + 4  # 多读几字节容错

        cmd = [
            self.seven_zip, 'x', '-so', '-y',
            '-bso0', '-bsp0',
            *self._get_mcp_args(archive_path),
        ]
        cmd.append(f'-p{password}' if password else '-p')
        cmd.append(archive_path)
        cmd.append(f'-i!{entry_name}')

        kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'stdin': subprocess.DEVNULL,
        }
        if sys.platform == 'win32':
            from subprocess import CREATE_NO_WINDOW as _CNW
            kwargs['creationflags'] = _CNW

        def _match_magic(data: bytes) -> Optional[bool]:
            """返回 True=命中、False=不命中、None=数据不够无法判断。"""
            if len(data) < magic_offset:
                return None
            for m in magics:
                need = magic_offset + len(m)
                if len(data) >= need:
                    if data[magic_offset:need] == m:
                        return True
            # 数据够长但一条 magic 都没对上 → 不命中
            if len(data) >= magic_offset + max_magic_len:
                return False
            return None

        semaphore = self._get_7z_semaphore()
        async with semaphore:
            try:
                process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            except Exception as e:
                logger.warning(f"密码探测（magic）无法启动 7z 进程，回退: {e}")
                return 'unknown'
            if task is not None:
                task.register_process(process)

            stdout_buf = bytearray()
            stderr_chunks: List[bytes] = []
            enough_data = False

            async def consume_stdout():
                nonlocal enough_data
                try:
                    while len(stdout_buf) < need_bytes:
                        chunk = await process.stdout.read(256)
                        if not chunk:
                            return
                        stdout_buf.extend(chunk)
                    enough_data = True
                except Exception:
                    return

            async def consume_stderr():
                try:
                    while True:
                        chunk = await process.stderr.read(4096)
                        if not chunk:
                            return
                        stderr_chunks.append(chunk)
                        if sum(len(c) for c in stderr_chunks) > 32 * 1024:
                            return
                except Exception:
                    return

            stdout_task = asyncio.create_task(consume_stdout())
            stderr_task = asyncio.create_task(consume_stderr())
            wait_task = asyncio.create_task(process.wait())

            try:
                await asyncio.wait(
                    {stdout_task, wait_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except Exception:
                pass

            async def _terminate():
                if process.returncode is None:
                    try:
                        process.kill()
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except Exception:
                        pass
                for t in (stdout_task, stderr_task, wait_task):
                    if not t.done():
                        t.cancel()
                        try:
                            await t
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            pass

            # 读够了魔数需要的字节数 → 立即对照并摄停进程
            if enough_data:
                await _terminate()
                if task is not None:
                    task.unregister_process(process)
                verdict = _match_magic(bytes(stdout_buf))
                if verdict is True:
                    return 'ok'
                if verdict is False:
                    return 'wrong_password'
                return 'unknown'

            # 进程仍在跑（高于阈值的巨大文件头很罕见，正常是由于解压极慢/中断）
            if process.returncode is None:
                await _terminate()
                if task is not None:
                    task.unregister_process(process)
                return 'unknown'

            # 进程已退出但字节不够：读完 stderr 做关键字判定
            try:
                await asyncio.wait_for(stderr_task, timeout=2.0)
            except Exception:
                pass
            for t in (stdout_task, wait_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
            if task is not None:
                task.unregister_process(process)

        stderr_text = b''.join(stderr_chunks).decode('utf-8', errors='ignore').lower()

        # 小于 need_bytes 的小文件：即使密码正确也可能字节不够。退得干净 +
        # 已有的字节能匹配魔数前缀 → ok；全不匹配 → wrong_password。
        if process.returncode == 0 and stdout_buf:
            for m in magics:
                match_len = min(len(stdout_buf) - magic_offset, len(m))
                if match_len <= 0:
                    continue
                if bytes(stdout_buf[magic_offset:magic_offset + match_len]) == m[:match_len]:
                    return 'ok'
            return 'wrong_password'

        encryption_markers = (
            "wrong password", "password is incorrect", "password?",
            "passphrase", "cannot open encrypted", "is encrypted",
            "data error in encrypted", "crc failed in encrypted", "crc failed",
        )
        if any(m in stderr_text for m in encryption_markers):
            return 'wrong_password'

        corrupt_markers = (
            "headers error", "unexpected end of archive", "unexpected end of data",
            "is not archive", "cannot open the file as archive",
            "can not open the file as archive",
        )
        if any(m in stderr_text for m in corrupt_markers):
            return 'corrupt'

        return 'unknown'

    async def _probe_by_smallest_entry(
        self,
        archive_path: str,
        password: str,
        entry: Dict,
        timeout: float,
        task: Optional[Task] = None,
    ) -> str:
        """用 `7zz t archive <entry>` 对单个小条目跑完整 CRC 测试。

        这是针对 store + AES（无压缩加密）压缩包的正确探测方式：
        这种压缩包里的子文件（例如 .zip / .mp3 / 已编码媒体）不再走压缩器，
        错密码解出垃圾数据后 LZMA 没机会报错，必须等 CRC 校验才能发现密码错。测单
        个小条目能把这种场景的探测耗时压到秒级。
        """
        entry_name = entry['name']
        cmd = [
            self.seven_zip, 't',
            '-bso0', '-bsp0',
            *self._get_mcp_args(archive_path),
        ]
        cmd.append(f'-p{password}' if password else '-p')
        cmd.append(archive_path)
        # 用 `-i!条目` 缩小范围，比直接带文件名参数对 7zz 较新版本更稳。
        cmd.append(f'-i!{entry_name}')

        kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'stdin': subprocess.DEVNULL,
        }
        if sys.platform == 'win32':
            from subprocess import CREATE_NO_WINDOW as _CNW
            kwargs['creationflags'] = _CNW

        semaphore = self._get_7z_semaphore()
        async with semaphore:
            try:
                process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            except Exception as e:
                logger.warning(f"密码探测（条目）无法启动 7z 进程，回退流式探测: {e}")
                return 'unknown'
            if task is not None:
                task.register_process(process)

            try:
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(process.wait(), timeout=2.0)
                        except Exception:
                            pass
                    logger.warning(
                        "密码探测（条目）超时（%.1fs），返回 unknown 由上层兜底: %s",
                        timeout,
                        os.path.basename(archive_path),
                    )
                    return 'unknown'
            finally:
                if task is not None:
                    task.unregister_process(process)

        stderr_text = (stderr_bytes or b'').decode('utf-8', errors='ignore')
        stderr_lower = stderr_text.lower()

        if process.returncode == 0:
            # 条目完整 CRC 验证通过 → 密码正确。
            return 'ok'

        encryption_markers = (
            "wrong password",
            "password is incorrect",
            "password?",
            "passphrase",
            "cannot open encrypted",
            "is encrypted",
            "data error in encrypted",
            "crc failed in encrypted",
            "crc failed",          # store + AES 错密码的典型文案
            "data error",          # 同上
        )
        if any(m in stderr_lower for m in encryption_markers):
            return 'wrong_password'

        corrupt_markers = (
            "headers error",
            "unexpected end of archive",
            "unexpected end of data",
            "is not archive",
            "cannot open the file as archive",
            "can not open the file as archive",
        )
        if any(m in stderr_lower for m in corrupt_markers):
            return 'corrupt'

        return 'unknown'

    async def _probe_by_full_test(
        self,
        archive_path: str,
        password: str,
        timeout: float,
        task: Optional[Task] = None,
    ) -> str:
        cmd = [
            self.seven_zip, 't',
            '-bso0', '-bsp0',
            *self._get_mcp_args(archive_path),
        ]
        cmd.append(f'-p{password}' if password else '-p')
        cmd.append(archive_path)

        kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'stdin': subprocess.DEVNULL,
        }
        if sys.platform == 'win32':
            from subprocess import CREATE_NO_WINDOW as _CNW
            kwargs['creationflags'] = _CNW

        semaphore = self._get_7z_semaphore()
        async with semaphore:
            try:
                process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            except Exception as e:
                logger.warning(f"密码探测（完整测试）无法启动 7z 进程，回退完整解压: {e}")
                return 'unknown'
            if task is not None:
                task.register_process(process)

            try:
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(), timeout=timeout
                    )
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        try:
                            process.kill()
                        except Exception:
                            pass
                        try:
                            await asyncio.wait_for(process.wait(), timeout=2.0)
                        except Exception:
                            pass
                    logger.warning(
                        "密码探测（完整测试）超时（%.1fs），返回 unknown 由上层兜底: %s",
                        timeout,
                        os.path.basename(archive_path),
                    )
                    return 'unknown'
            finally:
                if task is not None:
                    task.unregister_process(process)

        stderr_text = (stderr_bytes or b'').decode('utf-8', errors='ignore')
        stderr_lower = stderr_text.lower()

        if process.returncode == 0:
            return 'ok'

        encryption_markers = (
            "wrong password",
            "password is incorrect",
            "password?",
            "passphrase",
            "cannot open encrypted",
            "is encrypted",
            "data error in encrypted",
            "crc failed in encrypted",
            "crc failed",
            "data error",
        )
        if any(m in stderr_lower for m in encryption_markers):
            return 'wrong_password'

        corrupt_markers = (
            "headers error",
            "unexpected end of archive",
            "unexpected end of data",
            "is not archive",
            "cannot open the file as archive",
            "can not open the file as archive",
        )
        if any(m in stderr_lower for m in corrupt_markers):
            return 'corrupt'

        return 'unknown'

    async def _probe_password(
        self,
        archive_path: str,
        password: str,
        probe_bytes: int = 2 * 1024 * 1024,
        timeout: float = 30.0,
        file_list: Optional[List[Dict]] = None,
        task: Optional[Task] = None,
    ) -> str:
        """轻量探测密码是否正确。

        优先走条目测试分支（`_probe_by_smallest_entry`）：能处理 store+AES。
        拿不到 file_list 或没有合适小条目时，回退到原流式探测。

        返回值：
          - 'ok'             探测通过，建议进入完整解压
          - 'wrong_password' 命中加密相关错误关键字 / CRC 失败 / 魔数不匹配
          - 'corrupt'        命中疑似损坏关键字
          - 'unknown'        无法定性（超时 / 输出特殊），让上层走原有完整流程兜底

        优先级：
          1. 魔数探测（有已知后缀条目时）：不受文件大小影响，最快最准。
          2. 小条目 t 探测（有 <=5MB 的条目但无已知后缀时）：运行单文件 CRC。
          3. 流式探测（没 file_list 的头加密包兜底）：注意对 store+AES 可能漏判。
        """
        is_rar = self._is_rar_archive(archive_path)
        if not is_rar:
            magic_entries = self._pick_magic_entries(file_list)
            for magic_entry in magic_entries:
                logger.debug(
                    "密码探测（magic）选择条目: %s (%s bytes)",
                    magic_entry.get('name'),
                    magic_entry.get('size'),
                )
                result = await self._probe_by_magic(
                    archive_path,
                    password,
                    magic_entry,
                    timeout=self.PROBE_MAGIC_TIMEOUT,
                    task=task,
                )
                if result != 'unknown':
                    return result
            if magic_entries:
                logger.debug(
                    "魔数探测对 %s 的 %s 个条目均无法定性，回退到小条目 t 探测",
                    os.path.basename(archive_path),
                    len(magic_entries),
                )
        else:
            logger.debug(
                "RAR 密码探测跳过 magic/流式解压探测，避免错密码垃圾流误判: %s",
                os.path.basename(archive_path),
            )

        entry = self._pick_probe_entry(file_list)
        if entry is not None:
            result = await self._probe_by_smallest_entry(
                archive_path,
                password,
                entry,
                timeout=self.PROBE_ENTRY_TIMEOUT,
                task=task,
            )
            if result != 'unknown':
                return result
            logger.debug(
                "小条目测试对 %s 无法定性，回退到流式探测",
                os.path.basename(archive_path),
            )

        if file_list:
            logger.debug(
                "轻量探测无法定性，先执行完整 t 验证避免无效落盘解压: %s",
                os.path.basename(archive_path),
            )
            result = await self._probe_by_full_test(
                archive_path,
                password,
                timeout=self.PROBE_FULL_TEST_TIMEOUT,
                task=task,
            )
            if result != 'unknown':
                return result
        if is_rar:
            return 'unknown'
        # ---- 以下是原有流式探测逻辑（无 file_list 时的兜底） ----
        cmd = [
            self.seven_zip, 'x', '-so', '-y',
            '-bso0', '-bsp0',  # 关掉进度/消息，stdout 只剩解压数据
            *self._get_mcp_args(archive_path),
        ]
        cmd.append(f'-p{password}' if password else '-p')
        cmd.append(archive_path)

        kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'stdin': subprocess.DEVNULL,
        }
        if sys.platform == 'win32':
            from subprocess import CREATE_NO_WINDOW as _CNW
            kwargs['creationflags'] = _CNW

        semaphore = self._get_7z_semaphore()
        async with semaphore:
            try:
                process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            except Exception as e:
                logger.warning(f"密码探测无法启动 7z 进程，回退完整解压: {e}")
                return 'unknown'
            if task is not None:
                task.register_process(process)

            stdout_bytes = 0
            stderr_chunks: List[bytes] = []
            threshold_reached = False

            async def consume_stdout():
                nonlocal stdout_bytes, threshold_reached
                try:
                    while True:
                        chunk = await process.stdout.read(65536)
                        if not chunk:
                            return
                        stdout_bytes += len(chunk)
                        if stdout_bytes >= probe_bytes:
                            threshold_reached = True
                            return
                except Exception:
                    return

            async def consume_stderr():
                try:
                    while True:
                        chunk = await process.stderr.read(4096)
                        if not chunk:
                            return
                        stderr_chunks.append(chunk)
                        if sum(len(c) for c in stderr_chunks) > 64 * 1024:
                            return
                except Exception:
                    return

            stdout_task = asyncio.create_task(consume_stdout())
            stderr_task = asyncio.create_task(consume_stderr())
            wait_task = asyncio.create_task(process.wait())

            try:
                await asyncio.wait(
                    {stdout_task, wait_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except Exception:
                pass

            async def _terminate():
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except Exception:
                        pass
                for t in (stdout_task, stderr_task, wait_task):
                    if not t.done():
                        t.cancel()
                        try:
                            await t
                        except Exception:
                            pass

            # 分支 1：阈值达成 → 密码正确
            if threshold_reached:
                await _terminate()
                if task is not None:
                    task.unregister_process(process)
                return 'ok'

            # 分支 2：进程仍在跑 → 超时或被外部 kill（如 cancel/pause）
            if process.returncode is None:
                await _terminate()
                if task is not None:
                    task.unregister_process(process)
                logger.warning(
                    "密码探测超时或被中断（%.1fs），回退到完整解压验证: %s",
                    timeout,
                    os.path.basename(archive_path),
                )
                return 'unknown'

            # 分支 3：进程已退出，等 stderr 读完做关键字判定
            try:
                await asyncio.wait_for(stderr_task, timeout=2.0)
            except Exception:
                pass
            for t in (stdout_task, wait_task):
                if not t.done():
                    t.cancel()
                    try:
                        await t
                    except Exception:
                        pass

            stderr_text = b''.join(stderr_chunks).decode('utf-8', errors='ignore')
            stderr_lower = stderr_text.lower()

            if task is not None:
                task.unregister_process(process)

            # 进程正常结束（returncode == 0）且有数据吐出 → 包很小已经全部输出，密码正确
            if process.returncode == 0 and stdout_bytes > 0:
                return 'ok'

            encryption_markers = (
                "wrong password",
                "password is incorrect",
                "password?",
                "passphrase",
                "cannot open encrypted",
                "is encrypted",
                "data error in encrypted",
                "crc failed in encrypted",
            )
            if any(m in stderr_lower for m in encryption_markers):
                return 'wrong_password'

            corrupt_markers = (
                "headers error",
                "unexpected end of archive",
                "unexpected end of data",
                "is not archive",
                "cannot open the file as archive",
                "can not open the file as archive",
            )
            if any(m in stderr_lower for m in corrupt_markers):
                return 'corrupt'

            # 兜底：无法定性，让上层走原有 x 流程，避免漏掉真密码
            return 'unknown'

    async def _run_subprocess_command(
        self,
        cmd: List[str],
        task: Optional[Task] = None,
        running_step: str = "解压子进程已启动",
    ) -> subprocess.CompletedProcess:
        """跑非 7z 子进程（unar 等）。
        传入 task 时把子进程登记到 task 上，cancel / pause 能立刻 kill —— 修复
        unar 解压大包时无法响应取消的问题。
        """
        semaphore = self._get_7z_semaphore()
        try:
            if task is not None and self._is_semaphore_locked(semaphore):
                task.update_progress(
                    max(31, int(task.progress or 0)),
                    f"等待解压槽位（当前并发上限 {self.__class__._seven_zip_semaphore_limit or 1}）",
                )
            async with semaphore:
                if task is not None and running_step:
                    task.update_progress(max(40, int(task.progress or 0)), running_step)
                kwargs = {
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.PIPE,
                    'stdin': subprocess.DEVNULL,
                }
                if sys.platform == 'win32':
                    from subprocess import CREATE_NO_WINDOW
                    kwargs['creationflags'] = CREATE_NO_WINDOW

                process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
                if task is not None:
                    task.register_process(process)
                try:
                    stdout_data, stderr_data = await process.communicate()
                finally:
                    if task is not None:
                        task.unregister_process(process)
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=process.returncode,
                    stdout=stdout_data,
                    stderr=stderr_data,
                )
        except Exception as e:
            logger.error(f"执行子进程命令失败: {e}")
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=-1,
                stdout=b"",
                stderr=str(e).encode('utf-8'),
            )

    async def _cleanup_extract_attempt(self, output_path: str) -> None:
        """清掉上一轮密码尝试在 output_path 里留下的残留文件 / 目录。

        unar / 7zz 的 -f / -y 是文件级覆盖，但目录级残留（错密码下解出的部分文件、
        乱码目录名）会在下一轮成功解压时残留下来污染结果。所以每个密码 attempt
        前清空一次最稳妥。
        """
        if not os.path.exists(output_path):
            return

        def _do_cleanup() -> None:
            try:
                names = os.listdir(output_path)
            except OSError:
                return
            for name in names:
                target = os.path.join(output_path, name)
                try:
                    if os.path.isdir(target):
                        shutil.rmtree(target, ignore_errors=True)
                    else:
                        os.remove(target)
                except Exception:
                    logger.debug("清理上一轮解压残留失败: %s", target, exc_info=True)

        await asyncio.to_thread(_do_cleanup)

    async def _try_extract_rar_with_unar(
        self,
        archive_info: ArchiveInfo,
        output_path: str,
        task: Task,
        passwords: List[str],
        vault_passwords: List[str],
        password_entry_id_map: Dict[str, Optional[int]],
        password_rjcode_map: Dict[str, Optional[str]],
        manual_retry_password_only: bool,
        password_source_map: Optional[Dict[str, Optional[str]]] = None,
        rj_passwords: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str], str]:
        """对 RAR 文件优先用 unar 解压，遍历整个密码列表。

        ★ 解决用户痛点：群晖上看到 ``2.�C���X�g`` 这种乱码作品。
        根因：7zz 24.08 的 RAR 解析器不接受 ``-mcp`` 文件名代码页参数（传了会
        E_INVALIDARG），所以遇到日文 Shift-JIS / 中文 GBK 命名的 RAR 时，只能
        用本机 locale（Linux/Docker = UTF-8）解释 ANSI 字节 → 必然出乱码 →
        群晖 / NAS 文件管理器读到非法 UTF-8 字节就显示成 ``�`` 替换符。
        unar 自带 ICU 文件名编码自动探测，对日文 / 中文 RAR 友好。

        返回 ``(success, password_used, failure_reason)``：

        - ``(True, password, '')``：成功
        - ``(False, None, 'cancelled')``：用户取消
        - ``(False, None, 'disk_full')``：磁盘空间不足
        - ``(False, None, 'unsupported')``：unar 不识别该 RAR 变体（罕见的
          RAR5 加密 / 损坏头），调用方应回退到原 7zz 流程
        - ``(False, None, 'unar_unavailable')``：unar 可执行文件不存在，调用
          方应回退到原 7zz 流程
        - ``(False, None, 'wrong_password')``：所有密码都被 unar 拒绝，调用方
          仍可走 7zz 兜底（万一 7zz 能开但 unar 不行）
        """
        if not self._find_unar_executable():
            return False, None, "unar_unavailable"

        rj_password_set = set(rj_passwords or [])
        vault_password_set = set(vault_passwords or [])
        password_source_map = password_source_map or {}

        encountered_wrong_password = False
        last_unsupported = False
        last_disk_full = False

        # lsar 预检：在密码循环之前一次性探测文件名编码（秒级，只读 TOC）。
        # 多数 RAR 文件名头部未加密，无需密码即可检测。
        # 探测成功后所有密码尝试都用同一编码；探测失败则 encoding=None，事后由
        # _fix_unar_garbled_encoding 兜底。
        _hint_pw = next(
            (p for p in (passwords or []) if p and p in (rj_passwords or [])),
            passwords[0] if passwords else None,
        )
        detected_unar_encoding: Optional[str] = await self._detect_rar_encoding_with_lsar(
            archive_info.path, hint_password=_hint_pw,
        )
        if detected_unar_encoding:
            logger.info(
                "[unar编码] 预检确定编码 %s，后续解压均使用该编码: %s",
                detected_unar_encoding, archive_info.path,
            )

        for index, password in enumerate(passwords):
            if task.is_cancelled():
                return False, None, "cancelled"
            await task.wait_if_paused()
            if task.is_cancelled():
                return False, None, "cancelled"

            # 判断密码来源（仅用于日志）
            if manual_retry_password_only:
                password_source = "指定密码"
            elif password in rj_password_set:
                password_source = "RJ号"
            elif password in password_source_map:
                password_source = password_source_map.get(password) or "密码库"
            elif password in vault_password_set:
                password_source = "密码库"
            elif password == archive_info.password:
                password_source = "已知"
            elif password == "":
                password_source = "无"
            else:
                password_source = "默认"

            # 第二个密码起每轮先清空 output，避免上一轮残留干扰
            if index > 0:
                await self._cleanup_extract_attempt(output_path)

            task.update_progress(
                40,
                f"unar 解压 (密码来源: {password_source})",
            )
            result = await self._try_unar_extract(
                archive_info.path, output_path, password, task=task,
                encoding=detected_unar_encoding,
            )

            if task.is_cancelled():
                return False, None, "cancelled"

            stderr_text = (result.stderr or b"").decode('utf-8', errors='ignore')
            stderr_lower = stderr_text.lower()

            # 有些 unar/RAR 组合会在已经完整写出文件后仍返回 rc=1，且 stderr 为空。
            # 如果这个密码本来就是 7zz list 预读确认过的密码，先校验产物；通过就接受，
            # 避免无谓回退到 7zz 造成 RAR 文件名乱码。
            likely_verified_password = manual_retry_password_only or (
                password == getattr(archive_info, "password", None)
            )
            if likely_verified_password and self._has_extracted_payload(output_path):
                payload_summary = await self._summarize_extracted_payload(output_path)
                archive_summary = self._summarize_archive_file_list(archive_info)
                if payload_summary["nonempty_file_count"] <= 0 or payload_summary["total_bytes"] <= 0:
                    await self._cleanup_extract_attempt(output_path)
                    logger.warning(
                        "unar 返回 rc=%s 但只留下 0 字节产物，拒绝接受本次 RAR 解压: archive=%s files=%s expected_bytes=%s",
                        result.returncode,
                        archive_info.path,
                        payload_summary["file_count"],
                        archive_summary["total_bytes"],
                    )
                    return False, None, "partial_output"
                # 收紧：非空文件数不能明显少于清单期望（防止 "1 个正常 + N 个 0 字节" 的部分解压）。
                expected_nonempty = archive_summary["nonempty_file_count"]
                if expected_nonempty > 0 and payload_summary["nonempty_file_count"] < expected_nonempty:
                    await self._cleanup_extract_attempt(output_path)
                    logger.warning(
                        "unar 返回 rc=%s 且非空文件数不足，拒绝接受: archive=%s actual_nonempty=%s/%s",
                        result.returncode,
                        archive_info.path,
                        payload_summary["nonempty_file_count"],
                        expected_nonempty,
                    )
                    return False, None, "partial_output"
                # 尺寸校验：容忍 5% 元数据先后差异，大幅缺少则拒绝。
                if archive_summary["total_bytes"] > 0 and payload_summary["total_bytes"] < archive_summary["total_bytes"] * 0.95:
                    await self._cleanup_extract_attempt(output_path)
                    logger.warning(
                        "unar 返回 rc=%s 且产物大小不足，拒绝接受本次 RAR 解压: archive=%s actual=%s expected=%s",
                        result.returncode,
                        archive_info.path,
                        payload_summary["total_bytes"],
                        archive_summary["total_bytes"],
                    )
                    return False, None, "partial_output"
                await self._fix_unar_garbled_encoding(
                    archive_info.path, output_path, password, task=task,
                )
                if self._find_garbled_filename_sample(output_path, max_names=None):
                    await self._cleanup_extract_attempt(output_path)
                    return False, None, "garbled_filename"
                if await self._verify_extraction(archive_info, output_path):
                    archive_info.password = password
                    inferred_rjcode = password_rjcode_map.get(password) if password else None
                    if inferred_rjcode:
                        archive_info.inferred_rjcode = inferred_rjcode
                        if task.task_metadata is None:
                            task.task_metadata = {}
                        task.task_metadata['inferred_rjcode'] = inferred_rjcode
                        task.task_metadata['rjcode'] = inferred_rjcode
                        task.task_metadata['inferred_rjcode_source'] = 'password_entry'
                        if not getattr(task, 'rjcode', None) or str(task.rjcode).strip() in {'', '未知'}:
                            task.rjcode = inferred_rjcode
                    if password and password in vault_password_set:
                        await self._record_password_usage(
                            password,
                            archive_info.path,
                            entry_id=password_entry_id_map.get(password),
                        )
                    logger.info(
                        "unar 返回 rc=%s 但产物校验通过，接受本次 RAR 解压结果，使用 %s 密码: %s",
                        result.returncode,
                        password_source,
                        password or '无密码',
                    )
                    return True, password, ""
                await self._cleanup_extract_attempt(output_path)
                logger.warning(
                    "unar 返回 rc=%s 且产物校验失败，准备回退 7zz 解压内容: archive=%s",
                    result.returncode,
                    archive_info.path,
                )
                return False, None, "partial_output"

            if result.returncode == 0:
                # 乱码修复：若 lsar 预检未指定编码（或预检不可用），用事后扫描兜底。
                # 若 lsar 已预检确定编码，则理论上此步骤无需重试，快速跳过。
                if detected_unar_encoding is None:
                    await self._fix_unar_garbled_encoding(
                        archive_info.path, output_path, password, task=task,
                    )
                garbled_sample = self._find_garbled_filename_sample(output_path, max_names=None)
                if garbled_sample:
                    await self._cleanup_extract_attempt(output_path)
                    logger.error(
                        "unar 解压后仍检测到乱码文件名，已清理产物并阻止继续入库: archive=%s sample=%s",
                        archive_info.path,
                        garbled_sample,
                    )
                    return False, None, "garbled_filename"
                # 成功，更新 archive_info 元信息
                archive_info.password = password
                inferred_rjcode = password_rjcode_map.get(password) if password else None
                if inferred_rjcode:
                    archive_info.inferred_rjcode = inferred_rjcode
                    if task.task_metadata is None:
                        task.task_metadata = {}
                    task.task_metadata['inferred_rjcode'] = inferred_rjcode
                    task.task_metadata['rjcode'] = inferred_rjcode
                    task.task_metadata['inferred_rjcode_source'] = 'password_entry'
                    if not getattr(task, 'rjcode', None) or str(task.rjcode).strip() in {'', '未知'}:
                        task.rjcode = inferred_rjcode
                if password and password in vault_password_set:
                    await self._record_password_usage(
                        password,
                        archive_info.path,
                        entry_id=password_entry_id_map.get(password),
                    )
                logger.info(
                    "unar 解压 RAR 成功，使用 %s 密码: %s",
                    password_source, password or '无密码',
                )
                return True, password, ""

            # 密码错（unar 措辞会随版本/locale 变，多关键字兜底）
            wrong_password_markers = (
                "wrong password",
                "password was incorrect",
                "password is incorrect",
                "incorrect password",
                "wrong password?",
                "passphrase",
                "unable to decrypt",
            )
            if any(m in stderr_lower for m in wrong_password_markers):
                encountered_wrong_password = True
                logger.info(
                    "unar 密码 %s (%s) 失败: 密码错误",
                    password_source, password or '无密码',
                )
                continue

            # 磁盘满（继续试更多密码也没用）
            disk_full_markers = (
                "no space left on device",
                "not enough space",
                "disk full",
            )
            if any(m in stderr_lower for m in disk_full_markers):
                last_disk_full = True
                logger.error(
                    "unar 解压失败：磁盘空间不足: %s",
                    stderr_text[:300] if stderr_text else "(无错误文本)",
                )
                break

            # unar 不认这个格式 → 让 7zz 接手
            unsupported_markers = (
                "not a supported archive format",
                "isn't a supported archive format",
                "couldn't recognize the archive format",
                "unsupported file format",
                "is not a recognized archive",
                "couldn't recognize",
            )
            if any(m in stderr_lower for m in unsupported_markers):
                last_unsupported = True
                logger.warning(
                    "unar 不识别该 RAR 变体，将回退到 7zz: %s",
                    stderr_text[:300] if stderr_text else "(无错误文本)",
                )
                break  # 直接退出循环，让上层 fallback

            # 其他错误：当作潜在密码错继续试下一个
            logger.warning(
                "unar 密码 %s (%s) 失败 (rc=%s): %s",
                password_source,
                password or '无密码',
                result.returncode,
                stderr_text[:300] if stderr_text else "(无错误文本)",
            )

        if last_disk_full:
            return False, None, "disk_full"
        if last_unsupported:
            return False, None, "unsupported"
        if encountered_wrong_password:
            return False, None, "wrong_password"
        return False, None, "wrong_password"

    # Shift-JIS 日文被 GBK/cp936/Big5 错解后高频出现的 CJK 字符集合。
    # 旧版 ~60 字符不够：对 cp936 错读 SJIS 后产生的短串评分漏判。
    # 新增字符来自实际 RAR 样本反查（集中在 0x504x-0x507x 等 SJIS hiragana 错读性高区）。
    _CJK_MOJIBAKE_CHARS: frozenset = frozenset(
        # 经典旧集合
        "僠儍僾僞乕乽乿偺偟偱偨傜傪傞傝傑丄丒丅"
        "怣彈巕靛伃澹掓儭宀烘湷囧仧哄亰婂仾"
        "鍍儮儔儕儖儞儊儂儚儛"
        # 新增：SJIS hiragana 错读 cp936 的高频处
        "偭偪壒惡岺朳悇偟偺偊偶傷偈傂傆傃傜偪傣"
        "偐偑偒偓偔偗偙偛偞偠偢偣偤偦偧偩偫偬偯偰偶偹偼偽"
        # 新增：SJIS katakana 错读的高频处
        "僀僂僄僅僈僉僋僌僎僐僒僔僖僘僚僛僜僝僡僢僤僥僨僩僪僫僬僭僮僯僰僱僲僳僴僵僶僷僸僺僻僽僾僿"
        "儀儁儂儃億儅儆儇儈儉儊儋儌儍儎儏儐儑儒儓儔儕儖儗儘儚儛儜儝儞償"
        # 新增：用户日志中出现的片段
        "烘湷囧仧哄亰婂仾鏀濇綀宸曞嗗兗峰熷伜婂仾"
    )

    # 文件名乱码评分缓存：同一 name 在一次解压中经常被评分 N 次（find_sample/repair/filename_score）。
    # 用 LRU 缓存直接把最热的 4096 条结果缓存下来，得到 95%+ 命中率。
    _score_cache: Dict[str, float] = {}
    _SCORE_CACHE_MAX: int = 4096

    @classmethod
    def _filename_text_stats(cls, text: str) -> Dict[str, float]:
        total_nonascii = 0
        kana = 0
        cjk = 0
        hangul = 0
        marker = 0
        for ch in text or "":
            cp = ord(ch)
            if cp <= 127:
                continue
            total_nonascii += 1
            if 0x3040 <= cp <= 0x30FF:
                kana += 1
            elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
                cjk += 1
                if ch in cls._CJK_MOJIBAKE_CHARS:
                    marker += 1
            elif 0xAC00 <= cp <= 0xD7AF:
                hangul += 1
        return {
            "total_nonascii": float(total_nonascii),
            "kana": float(kana),
            "cjk": float(cjk),
            "hangul": float(hangul),
            "marker": float(marker),
            "marker_ratio": marker / max(total_nonascii, 1),
            "kana_ratio": kana / max(total_nonascii, 1),
        }

    @classmethod
    def _mojibake_marker_count(cls, text: str) -> int:
        return sum(1 for ch in text if ch in cls._CJK_MOJIBAKE_CHARS)

    @classmethod
    def _mojibake_markers(cls, text: str, limit: int = 12) -> List[str]:
        out: List[str] = []
        seen = set()
        for ch in text or "":
            if ch in cls._CJK_MOJIBAKE_CHARS and ch not in seen:
                seen.add(ch)
                out.append(ch)
                if len(out) >= limit:
                    break
        return out

    @staticmethod
    def _has_hard_garbled_signal(text: str) -> bool:
        """不可逆的硬乱码信号：surrogate / 替换符 / 大量 Latin-1 扩展字节。"""
        latin_ext = 0
        nonascii = 0
        for ch in text:
            cp = ord(ch)
            if 0xD800 <= cp <= 0xDFFF or ch == '\ufffd':
                return True
            if cp > 127:
                nonascii += 1
                if 0x0080 <= cp <= 0x00FF:
                    latin_ext += 1
        return latin_ext >= 3 and latin_ext / max(nonascii, 1) >= 0.35

    @classmethod
    def _has_reversible_mojibake_signal(cls, text: str) -> bool:
        """CJK mojibake 必须能反解出更像正常日文的文件名，避免误伤普通汉字名。"""
        if not text:
            return False
        original_score = cls._garbled_text_score(text)
        original_stats = cls._filename_text_stats(text)
        if original_score < 15.0 and cls._mojibake_marker_count(text) < 3:
            return False

        def accepts(candidate: str) -> bool:
            if not candidate or candidate == text:
                return False
            if "/" in candidate or "\\" in candidate or "\x00" in candidate:
                return False
            candidate_score = cls._garbled_text_score(candidate)
            if candidate_score >= 30.0 or not cls._looks_japanese_filename(candidate):
                return False
            candidate_stats = cls._filename_text_stats(candidate)
            kana_ratio_delta = candidate_stats["kana_ratio"] - original_stats["kana_ratio"]
            score_delta = original_score - candidate_score
            return kana_ratio_delta >= 0.20 or score_delta >= 25.0

        for wrong_codec, correct_codec in cls._MOJIBAKE_CODEC_PAIRS:
            try:
                candidate = text.encode(wrong_codec).decode(correct_codec)
            except (UnicodeError, LookupError):
                continue
            if accepts(candidate):
                return True
        for wrong_codec, correct_codec in cls._MOJIBAKE_CODEC_PAIRS:
            try:
                candidate = text.encode(wrong_codec, errors='ignore').decode(correct_codec, errors='ignore')
            except LookupError:
                continue
            if len(candidate) < len(text) * 0.4:
                continue
            if accepts(candidate):
                return True
        outer_pairs = (("gbk", "utf-8"), ("cp936", "utf-8"))
        inner_pairs = (("gbk", "cp932"), ("cp936", "cp932"), ("gbk", "shift_jis"), ("cp936", "shift_jis"))
        for outer_wrong, outer_correct in outer_pairs:
            try:
                intermediate = text.encode(outer_wrong, errors='ignore').decode(outer_correct, errors='ignore')
            except (UnicodeError, LookupError):
                continue
            if not intermediate or intermediate == text:
                continue
            for inner_wrong, inner_correct in inner_pairs:
                try:
                    candidate = intermediate.encode(inner_wrong).decode(inner_correct)
                except (UnicodeError, LookupError):
                    try:
                        candidate = intermediate.encode(inner_wrong, errors='ignore').decode(inner_correct, errors='ignore')
                    except (UnicodeError, LookupError):
                        continue
                if len(candidate) < len(text) * 0.4:
                    continue
                if candidate != intermediate and accepts(candidate):
                    return True
        return False

    @classmethod
    def _garbled_text_score(cls, text: str) -> float:
        """文件名乱码评分。分数越高越像编码被猜错。

        判断依据：
        - 出现 surrogate 字符 → 底层文件名字节不是合法 UTF-8，直接判定乱码
        - 出现 Unicode 替换字符 U+FFFD → 直接判定乱码
        - Latin-1 扩展字符大量出现 → 常见 ANSI 字节被当 Latin-1
        - `僠儍僾僞乕` / `鍋靛伃...` 这类 Shift-JIS 被 GBK 解码后的 CJK 乱码：
          字符合法、CRC 也能过，但语义明显坏，必须继续换编码重解。
        """
        # 缓存查询：命中直接返回，避免再跑 N 字符循环。
        cached = cls._score_cache.get(text)
        if cached is not None:
            return cached
        latin_ext = 0
        cjk = 0
        kana = 0
        hangul = 0
        mojibake_marker = 0
        mojibake_marker_run = 0
        max_mojibake_marker_run = 0
        total_nonascii = 0
        # Shift-JIS 日文被 GBK/cp936/Big5 错解后高频出现的字符集合（类属性）。
        cjk_mojibake_chars = cls._CJK_MOJIBAKE_CHARS
        for ch in text:
            cp = ord(ch)
            if 0xD800 <= cp <= 0xDFFF:
                return 100.0
            if cp > 127:
                total_nonascii += 1
                if ch == '\ufffd':
                    return 100.0
                elif 0x0080 <= cp <= 0x00FF:
                    latin_ext += 1
                elif 0x3040 <= cp <= 0x30FF:
                    kana += 1
                elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
                    cjk += 1
                    if ch in cjk_mojibake_chars:
                        mojibake_marker += 1
                        mojibake_marker_run += 1
                        max_mojibake_marker_run = max(max_mojibake_marker_run, mojibake_marker_run)
                    else:
                        mojibake_marker_run = 0
                elif 0xAC00 <= cp <= 0xD7AF:
                    hangul += 1
                    mojibake_marker_run = 0
                else:
                    mojibake_marker_run = 0
            else:
                mojibake_marker_run = 0
        if total_nonascii == 0:
            cls._score_cache[text] = 0.0
            return 0.0

        score = 0.0
        if latin_ext >= 3:
            score += 60.0 * (latin_ext / total_nonascii)

        # CJK marker 只能作为“结构性证据”使用，不能单字定罪。
        # 旧规则里一个 marker + CJK>=4 就能过阈值，导致正常日文汉字名
        # `温泉浜辺.wav` 被 `浜` 这个单字误伤。真正的 mojibake 往往是
        # 多个 marker 高密度出现，且常有连续 run（例如 `僠儍僾僞乕...`）。
        marker_ratio = mojibake_marker / max(total_nonascii, 1)
        if mojibake_marker == 1:
            score += 8.0 * marker_ratio
        if mojibake_marker >= 2:
            score += 22.0 * min(marker_ratio, 1.0)
        if max_mojibake_marker_run >= 2:
            score += 22.0 * min(max_mojibake_marker_run / max(mojibake_marker, 1), 1.0)
        if cjk >= 4 and kana == 0 and hangul == 0 and (mojibake_marker >= 3 or max_mojibake_marker_run >= 2):
            score += 18.0
        if cjk >= 8 and kana == 0 and hangul == 0 and mojibake_marker >= 3:
            score += 12.0
        if cjk >= 20 and kana == 0 and mojibake_marker >= 4:
            score += 15.0
        # 写入缓存（限制总条数）
        cache = cls._score_cache
        if len(cache) >= cls._SCORE_CACHE_MAX:
            cache.clear()  # 简单 LRU：超限清空（均摊下两次无关系）
        cache[text] = score
        return score

    @classmethod
    def _has_garbled_text(cls, text: str) -> bool:
        score = cls._garbled_text_score(text)
        if score < 30.0:
            return False
        if cls._has_hard_garbled_signal(text):
            return True
        stats = cls._filename_text_stats(text)
        if stats["kana"] >= 1 and stats["marker_ratio"] < 0.40:
            return False
        # 纯 CJK 的“像乱码”只能算弱证据。正常日文汉字文件名也可能命中
        # `浜/鎮/鍋` 这类 marker；必须能按常见错编链路反解出假名才拦截。
        return cls._has_reversible_mojibake_signal(text)

    def _has_garbled_filenames(self, directory: str) -> bool:
        """检测目录中是否存在 ANSI 多字节（Shift-JIS/GBK）被误当 Latin-1 解读的乱码文件名。"""
        return self._find_garbled_filename_sample(directory, max_names=240) is not None

    def _find_garbled_filename_sample(
        self,
        directory: str,
        *,
        max_names: Optional[int] = 240,
    ) -> Optional[str]:
        """返回一个疑似乱码文件名样本；max_names=None 表示全树短路扫描。"""
        diagnostic = self._filename_garbled_diagnostics(
            directory,
            max_names=max_names,
            top_limit=1,
            short_circuit=True,
        )
        return str(diagnostic.get("sample") or "") or None

    def _filename_garbled_diagnostics(
        self,
        directory: str,
        *,
        max_names: Optional[int] = 240,
        top_limit: int = 8,
        short_circuit: bool = False,
    ) -> Dict[str, Any]:
        """单次扫描目录树，返回乱码诊断。只按单文件名判断，不再拼接全量文件名放大误判。"""
        total = 0
        flagged = 0
        sample = ""
        best_score = 0.0
        top_samples: List[Dict[str, Any]] = []
        stack = [directory]
        while stack and (max_names is None or total < max_names):
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        name = entry.name
                        total += 1
                        score = self._garbled_text_score(name)
                        is_garbled = self._has_garbled_text(name)
                        best_score = max(best_score, score)
                        if score > 0 or is_garbled:
                            top_samples.append({
                                "name": name,
                                "score": round(score, 1),
                                "markers": self._mojibake_markers(name),
                                "garbled": bool(is_garbled),
                            })
                            top_samples.sort(key=lambda item: (bool(item.get("garbled")), float(item.get("score") or 0)), reverse=True)
                            if len(top_samples) > top_limit:
                                top_samples.pop()
                        if is_garbled:
                            flagged += 1
                            if not sample:
                                sample = name
                            if short_circuit:
                                return {
                                    "sample": sample,
                                    "score": round(best_score, 1),
                                    "total_names": total,
                                    "garbled_count": flagged,
                                    "garbled_ratio": round(flagged / max(total, 1), 4),
                                    "top_samples": top_samples,
                                }
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        if max_names is not None and total >= max_names:
                            break
            except OSError:
                continue
        return {
            "sample": sample or None,
            "score": round(best_score, 1),
            "total_names": total,
            "garbled_count": flagged,
            "garbled_ratio": round(flagged / max(total, 1), 4),
            "top_samples": top_samples,
        }

    def _filename_garbled_score(self, directory: str, *, max_names: Optional[int] = 240) -> float:
        """返回目录树文件名最高乱码评分。"""
        return float(self._filename_garbled_diagnostics(directory, max_names=max_names, top_limit=1).get("score") or 0.0)

    # mojibake 反解 codec_pair：(错误编码 wrong, 真实编码 correct)。
    # 顺序按"日文 RAR / ZIP 最常踩的 mojibake 类型"排，命中早可短路。
    _MOJIBAKE_CODEC_PAIRS: tuple = (
        # SJIS 字节被 GBK/cp936 错读（最常见 mojibake 类型）
        ("gbk", "cp932"),
        ("cp936", "cp932"),
        ("gbk", "shift_jis"),
        ("cp936", "shift_jis"),
        # SJIS 字节被 Big5 错读
        ("big5", "cp932"),
        ("big5", "shift_jis"),
        # UTF-8 字节被 GBK/cp936 错读（直接存为 UTF-8 的 RAR）
        ("gbk", "utf-8"),
        ("cp936", "utf-8"),
        ("big5", "utf-8"),
        # GBK 字节被 SJIS/cp932 错读（中文重打包被日文工具读）
        ("cp932", "gbk"),
        ("shift_jis", "gbk"),
        ("cp932", "cp936"),
        ("shift_jis", "cp936"),
    )

    @staticmethod
    def _looks_japanese_filename(text: Optional[str]) -> bool:
        """反解结果是否含合法日文假名 / 片假名。含假名的词几乎一定是日文。"""
        if not text:
            return False
        for ch in text:
            cp = ord(ch)
            if 0x3040 <= cp <= 0x309F or 0x30A0 <= cp <= 0x30FF:
                return True
        return False

    def _repair_mojibake_filename(self, name: str) -> Optional[str]:
        """还原常见的"日文/中文文件名编码被解错"的 mojibake。

        层次：
        1. 入口判定相对旧版放宽：评分 >= 15 或含 `_CJK_MOJIBAKE_CHARS` 任一字符都尝试。
        2. codec_pair 扩展到 13 个，覆盖 SJIS/UTF-8/GBK 之间的常见错读。
        3. 接受标准：反解出现合法假名则优先采纳，否则要求评分显著下降。
        """
        if not name:
            return None
        # 缓存查询：同一文件名可能在 _find_garbled_sample, _repair_in_place, _verify_extraction 等多个地方重复反解。
        # 用 sentinel object 区分 "None 是缓存的反解失败结果" 和 "缓存未命中"。
        cls = type(self)
        if not hasattr(cls, "_repair_cache"):
            cls._repair_cache = {}  # type: ignore[attr-defined]
        repair_cache = cls._repair_cache  # type: ignore[attr-defined]
        if name in repair_cache:
            return repair_cache[name]
        # 入口限制：低分 marker 不能触发反解。正常日文汉字如 `温泉浜辺`
        # 可被 GBK→CP932 错误“反解”成半角片假名/杂字，不能因为单字 marker 被改名。
        original_score = self._garbled_text_score(name)
        if original_score < 15.0:
            repair_cache[name] = None
            return None

        best_name: Optional[str] = None
        best_score = original_score
        for wrong_codec, correct_codec in self._MOJIBAKE_CODEC_PAIRS:
            try:
                candidate = name.encode(wrong_codec).decode(correct_codec)
            except (UnicodeError, LookupError):
                continue
            if not candidate or candidate == name:
                continue
            if "/" in candidate or "\\" in candidate or "\x00" in candidate:
                continue
            candidate_score = self._garbled_text_score(candidate)
            # 优先采纳"反解出现合法假名"：mojibake 几乎不可能想伪造出假名。
            if self._looks_japanese_filename(candidate) and not self._looks_japanese_filename(best_name or name):
                best_name = candidate
                best_score = candidate_score
                continue
            if candidate_score < best_score and (candidate_score < 30.0 or best_score - candidate_score >= 25.0):
                best_name = candidate
                best_score = candidate_score

        # Fallback：strict 反解全部失败时，降级到 errors='ignore' 模式重试。
        # 如 `01_鏉鏇囧掓儭涔畐av涓扴E鍋佸倽涔` 这种字符串含有两种不同编码 mojibake，
        # strict encode 整段失败。降级后要求反解含合法假名（强信号）才接受，避免误改真实中文。
        if best_name is None:
            for wrong_codec, correct_codec in self._MOJIBAKE_CODEC_PAIRS:
                try:
                    candidate = name.encode(wrong_codec, errors='ignore').decode(correct_codec, errors='ignore')
                except LookupError:
                    continue
                if not candidate or candidate == name:
                    continue
                if "/" in candidate or "\\" in candidate or "\x00" in candidate:
                    continue
                # 降级模式下，接受标准极端严格：必须含假名 + 反解评分明显下降。
                if not self._looks_japanese_filename(candidate):
                    continue
                candidate_score = self._garbled_text_score(candidate)
                if candidate_score >= 30.0:
                    continue
                # 失真率：若 ignore 丢失字符比例 > 25%，不接受（防止大量非ASCII 字被吞掉）。
                if len(candidate) < len(name) * 0.75:
                    continue
                best_name = candidate
                best_score = candidate_score
                break

        # 双层 mojibake 反解 pass：
        # 场景：SJIS 字节 → 被 cp936 错读 → utf-8 落盘 → 被 cp936 再次错读（如 7zz 出来的 `鍋靛伃...`）。
        # 反解需要 (gbk→utf-8) + (gbk→cp932)。
        if best_name is None:
            outer_pairs = (("gbk", "utf-8"), ("cp936", "utf-8"))
            inner_pairs = (("gbk", "cp932"), ("cp936", "cp932"), ("gbk", "shift_jis"), ("cp936", "shift_jis"))
            for outer_wrong, outer_correct in outer_pairs:
                try:
                    intermediate = name.encode(outer_wrong, errors='ignore').decode(outer_correct, errors='ignore')
                except (UnicodeError, LookupError):
                    continue
                if not intermediate or intermediate == name:
                    continue
                for inner_wrong, inner_correct in inner_pairs:
                    try:
                        candidate = intermediate.encode(inner_wrong).decode(inner_correct)
                    except (UnicodeError, LookupError):
                        try:
                            candidate = intermediate.encode(inner_wrong, errors='ignore').decode(inner_correct, errors='ignore')
                        except (UnicodeError, LookupError):
                            continue
                    if not candidate or candidate == name or candidate == intermediate:
                        continue
                    if "/" in candidate or "\\" in candidate or "\x00" in candidate:
                        continue
                    # 双层反解结果必须含合法假名（强信号），否则不接受（避免误改真实中文）。
                    if not self._looks_japanese_filename(candidate):
                        continue
                    candidate_score = self._garbled_text_score(candidate)
                    if candidate_score >= 30.0:
                        continue
                    # 双层反解允许较大的长度折损（ignore 模式必然碰少字符），但仍需限成原长的 40% 以上，避免大量字符丢失后的增量无意义结果。
                    if len(candidate) < len(name) * 0.4:
                        continue
                    best_name = candidate
                    best_score = candidate_score
                    break
                if best_name is not None:
                    break

        # 缓存持续增长时清空（简单 LRU）
        if len(repair_cache) >= 4096:
            repair_cache.clear()
        repair_cache[name] = best_name
        return best_name

    def _repair_mojibake_relative_path(self, path: str) -> Optional[str]:
        """按路径片段还原可逆 mojibake，供完整性验证匹配重命名后的落盘路径。"""
        normalized = str(path or "").replace("\\", "/")
        if not normalized:
            return None
        changed = False
        repaired_parts: List[str] = []
        for part in normalized.split("/"):
            if not part:
                repaired_parts.append(part)
                continue
            repaired = self._repair_mojibake_filename(part)
            if repaired:
                repaired_parts.append(repaired)
                changed = True
            else:
                repaired_parts.append(part)
        if not changed:
            return None
        return "/".join(repaired_parts)

    def _repair_mojibake_filenames_in_place(self, directory: str) -> int:
        """自底向上重命名目录树中的可逆 mojibake 文件名。"""
        if not directory or not os.path.isdir(directory):
            return 0

        repaired = 0
        for current, dirnames, filenames in os.walk(directory, topdown=False):
            for name in list(filenames) + list(dirnames):
                fixed_name = self._repair_mojibake_filename(name)
                if not fixed_name:
                    continue
                old_path = os.path.join(current, name)
                new_path = os.path.join(current, fixed_name)
                if old_path == new_path or os.path.exists(new_path):
                    continue
                try:
                    os.rename(old_path, new_path)
                    repaired += 1
                    logger.debug("[unar编码] 反乱码重命名: %s -> %s", old_path, new_path)
                except OSError as exc:
                    logger.warning(
                        "[unar编码] 反乱码重命名失败: %s -> %s error=%s",
                        old_path,
                        new_path,
                        exc,
                    )
        return repaired

    def _archive_file_list_garbled_sample(self, file_list: Optional[List[Dict]]) -> Optional[str]:
        """从压缩包目录清单里找疑似乱码条目；只看文件名，不触碰文件内容。"""
        if not file_list:
            return None
        for item in file_list[:500]:
            try:
                name = str(item.get("name") or "")
            except Exception:
                continue
            if not name:
                continue
            for part in str(name).replace("\\", "/").split("/"):
                if part and self._has_garbled_text(part):
                    return name
        return None

    async def preview_archive_filenames_with_encoding(
        self,
        archive_path: str,
        *,
        filename_encoding: Optional[Union[str, int]] = None,
        password: str = "",
        limit: int = 80,
    ) -> Dict[str, Any]:
        """按指定 ZIP 文件名编码读取目录清单，用于问题作品页重试前预览。"""
        normalized_path = str(archive_path or "").strip()
        if not normalized_path or not os.path.exists(normalized_path):
            raise FileNotFoundError("压缩包不存在")
        file_list = await self._list_archive_contents(
            normalized_path,
            password=normalize_password_value(password) if password else "",
            filename_encoding=filename_encoding,
        )
        entries = list(file_list or [])[: max(1, min(int(limit or 80), 300))]
        names = [str(item.get("name") or "") for item in entries if str(item.get("name") or "")]
        diagnostics = []
        for name in names[:80]:
            diagnostics.append({
                "name": name,
                "score": round(self._garbled_text_score(name), 1),
                "markers": self._mojibake_markers(name),
                "garbled": self._has_garbled_text(name),
            })
        return {
            "encoding": str(filename_encoding or "auto"),
            "codepage": self._filename_encoding_to_codepage(filename_encoding),
            "file_count": len(file_list or []),
            "items": entries,
            "diagnostics": diagnostics,
            "garbled_sample": next((item["name"] for item in diagnostics if item.get("garbled")), None),
            "max_score": max([float(item.get("score") or 0) for item in diagnostics] or [0.0]),
        }

    async def _reject_if_garbled_after_extract(
        self,
        archive_path: str,
        output_path: str,
        *,
        cleanup,
        context: str,
        task: Optional[Task] = None,
        ignore_garbled: bool = False,
    ) -> bool:
        """解压成功后检查文件名乱码；先尝试反解修复，仍乱码才清理并返回 True。"""
        if not self._needs_filename_garbled_guard(archive_path):
            return False
        diagnostics_before = self._filename_garbled_diagnostics(output_path, max_names=None)
        sample = str(diagnostics_before.get("sample") or "")
        if not sample:
            return False

        score_before = float(diagnostics_before.get("score") or 0.0)
        logger.warning(
            "[garbled_guard] %s 解压后检测到疑似乱码文件名，尝试反解修复: archive=%s sample=%s score=%.1f flagged=%s/%s",
            context,
            archive_path,
            sample,
            score_before,
            diagnostics_before.get("garbled_count"),
            diagnostics_before.get("total_names"),
        )
        try:
            repaired_count = await asyncio.to_thread(
                self._repair_mojibake_filenames_in_place,
                output_path,
            )
        except Exception as exc:
            repaired_count = 0
            logger.warning(
                "[garbled_guard] %s 文件名反乱码修复异常，继续按原样复检: archive=%s error=%s",
                context,
                archive_path,
                exc,
            )
        diagnostics_after = self._filename_garbled_diagnostics(output_path, max_names=None)
        sample_after = str(diagnostics_after.get("sample") or "")
        score_after = float(diagnostics_after.get("score") or 0.0)
        if task is not None:
            self._set_extract_meta(
                task,
                extract_failure_reason="garbled_filename" if sample_after else (task.task_metadata or {}).get("extract_failure_reason"),
                garbled_filename_sample=sample_after or sample,
                garbled_filename_score_before=score_before,
                garbled_filename_score_after=score_after,
                garbled_filename_score=score_after,
                garbled_filename_repaired_count=repaired_count,
                garbled_filename_codec_pairs_tried=len(self._MOJIBAKE_CODEC_PAIRS),
                garbled_filename_guard_origin=context,
                garbled_filename_top_samples=diagnostics_after.get("top_samples") or diagnostics_before.get("top_samples") or [],
                garbled_filename_total_names=diagnostics_after.get("total_names"),
                garbled_filename_garbled_count=diagnostics_after.get("garbled_count"),
                garbled_filename_garbled_ratio=diagnostics_after.get("garbled_ratio"),
            )
        if not sample_after:
            if repaired_count:
                logger.info(
                    "[garbled_guard] %s 文件名反乱码修复完成，复检通过: archive=%s repaired=%s score_before=%.1f score_after=%.1f",
                    context,
                    archive_path,
                    repaired_count,
                    score_before,
                    score_after,
                )
            return False
        sample = sample_after
        if repaired_count:
            logger.warning(
                "[garbled_guard] %s 文件名反乱码修复 %s 条后仍疑似乱码: archive=%s sample=%s score_before=%.1f score_after=%.1f",
                context,
                repaired_count,
                archive_path,
                sample,
                score_before,
                score_after,
            )
        else:
            logger.warning(
                "[garbled_guard] %s 文件名反乱码修复未命中可逆 mojibake，继续按评分结果阻断: archive=%s sample=%s score=%.1f",
                context,
                archive_path,
                sample,
                score_before,
            )

        if ignore_garbled or bool(getattr(self.config.extract, "bypass_filename_garbled_check", False)):
            if task is not None:
                self._set_extract_meta(
                    task,
                    garbled_filename_bypassed=True,
                    garbled_filename_bypass_origin="task_retry" if ignore_garbled else "global_config",
                    garbled_filename_bypassed_at=datetime.now().isoformat(),
                )
            logger.warning(
                "[garbled_guard] %s 已按显式 bypass 放行疑似乱码文件名: archive=%s sample=%s score=%.1f",
                context,
                archive_path,
                sample,
                score_after,
            )
            return False

        await cleanup()
        logger.error(
            "[garbled_guard] %s 解压后检测到疑似乱码文件名，已清理产物并阻止继续入库: archive=%s sample=%s score=%.1f",
            context,
            archive_path,
            sample,
            score_after,
        )
        return True

    def _has_extracted_payload(self, directory: str) -> bool:
        """粗略判断解压目录里是否已有实质产物。"""
        if not directory or not os.path.isdir(directory):
            return False
        stack = [directory]
        visited = 0
        while stack and visited < 400:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        visited += 1
                        try:
                            if entry.is_file(follow_symlinks=False):
                                return True
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
        return False

    async def _summarize_extracted_payload(self, directory: str) -> Dict[str, int]:
        """统计解压产物，用于阻断空目录 / 全 0 字节产物继续入库。"""
        def _scan() -> Dict[str, int]:
            summary = {
                "file_count": 0,
                "nonempty_file_count": 0,
                "total_bytes": 0,
            }
            if not directory or not os.path.isdir(directory):
                return summary

            stack = [directory]
            while stack:
                current = stack.pop()
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    stack.append(entry.path)
                                    continue
                                if not entry.is_file(follow_symlinks=False):
                                    continue
                                size = int(entry.stat(follow_symlinks=False).st_size or 0)
                            except OSError:
                                continue
                            summary["file_count"] += 1
                            summary["total_bytes"] += size
                            if size > 0:
                                summary["nonempty_file_count"] += 1
                except OSError:
                    continue
            return summary

        return await asyncio.to_thread(_scan)

    def _summarize_archive_file_list(self, archive_info: ArchiveInfo) -> Dict[str, int]:
        """统计压缩包清单里的文件数量和期望解压后字节数。"""
        summary = {
            "file_count": 0,
            "nonempty_file_count": 0,
            "total_bytes": 0,
        }
        for item in getattr(archive_info, "file_list", None) or []:
            if item.get("is_dir"):
                continue
            try:
                size = int(item.get("size") or 0)
            except Exception:
                size = 0
            summary["file_count"] += 1
            summary["total_bytes"] += max(0, size)
            if size > 0:
                summary["nonempty_file_count"] += 1
        return summary

    async def _detect_rar_encoding_with_lsar(
        self,
        archive_path: str,
        hint_password: Optional[str] = None,
    ) -> Optional[str]:
        """用 lsar 轻量读取 RAR 目录树，选择文件名编码。

        lsar 只读 TOC/中央目录，秒级完成，不解压数据。多数 RAR 的文件名头部
        未加密，无需密码即可列出文件名，因此可以在密码循环前一次性探测。
        返回 None 表示自动探测已经足够好，或 lsar 不可用 / 无法判断。
        """
        lsar_path = self._find_lsar_executable()
        if not lsar_path:
            return None

        for attempt_password in ([None] + ([hint_password] if hint_password else [])):
            candidates: List[Tuple[Optional[str], float]] = []
            for enc in self._unar_filename_encoding_candidates(include_auto=True):
                enc_cmd = [lsar_path]
                if enc:
                    enc_cmd.extend(["-e", enc])
                if attempt_password:
                    enc_cmd.extend(["-p", attempt_password])
                enc_cmd.append(archive_path)
                try:
                    enc_result = await asyncio.wait_for(
                        self._run_subprocess_command(enc_cmd),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.debug("[unar编码] lsar 预检超时: %s", archive_path)
                    return None
                except Exception as e:
                    logger.debug("[unar编码] lsar 预检异常: %s", e)
                    return None
                if enc_result.returncode == 0:
                    enc_output = (enc_result.stdout or b"").decode("utf-8", errors="replace")
                    candidates.append((enc, self._garbled_text_score(enc_output)))
            if not candidates:
                continue

            auto_score = next((score for enc, score in candidates if enc is None), None)
            best_encoding, best_score = min(candidates, key=lambda item: item[1])
            logger.debug(
                "[unar编码] lsar 文件名编码评分 archive=%s scores=%s",
                archive_path,
                {enc or "auto": round(score, 1) for enc, score in candidates},
            )
            if best_encoding is None:
                return None
            if auto_score is not None and auto_score < 30.0:
                return None
            if best_score < (auto_score if auto_score is not None else 100.0):
                logger.info(
                    "[unar编码] lsar 预检选择文件名编码: %s score=%.1f auto=%.1f",
                    best_encoding,
                    best_score,
                    auto_score if auto_score is not None else -1.0,
                )
                return best_encoding
            if auto_score is None and best_score < 30.0:
                logger.info(
                    "[unar编码] lsar 预检选择文件名编码: %s score=%.1f",
                    best_encoding,
                    best_score,
                )
                return best_encoding
            return None

        return None

    async def _rank_rar_encodings_after_garbled_extract(
        self,
        archive_path: str,
        password: Optional[str],
        baseline_score: float,
    ) -> List[Tuple[str, float]]:
        """解压后发现乱码时，用 lsar 给编码候选排序。"""
        lsar_path = shutil.which("lsar")
        if not lsar_path:
            return []

        scores: List[Tuple[str, float]] = []
        for enc in self._unar_filename_encoding_candidates(include_auto=False):
            cmd = [lsar_path, "-e", enc]
            if password:
                cmd.extend(["-p", password])
            cmd.append(archive_path)
            try:
                result = await asyncio.wait_for(
                    self._run_subprocess_command(cmd),
                    timeout=30.0,
                )
            except Exception:
                continue
            if result.returncode != 0:
                continue
            output = (result.stdout or b"").decode("utf-8", errors="replace")
            scores.append((enc, self._garbled_text_score(output)))
        if not scores:
            return []

        scores.sort(key=lambda item: item[1])
        logger.debug(
            "[unar编码] 解压后 lsar 编码评分 archive=%s scores=%s baseline=%.1f",
            archive_path,
            {enc: round(score, 1) for enc, score in scores},
            baseline_score,
        )
        return scores

    async def _detect_rar_encoding_after_garbled_extract(
        self,
        archive_path: str,
        password: Optional[str],
        baseline_score: float,
    ) -> Optional[str]:
        """解压后发现乱码时，用 lsar 再轻量选一次编码，避免三次完整重解。"""
        scores = await self._rank_rar_encodings_after_garbled_extract(
            archive_path, password, baseline_score,
        )
        if not scores:
            return None

        best_encoding, best_score = scores[0]
        if best_score < baseline_score:
            logger.info(
                "[unar编码] 解压后 lsar 选择文件名编码: %s score=%.1f baseline=%.1f",
                best_encoding,
                best_score,
                baseline_score,
            )
            return best_encoding
        return None

    @staticmethod
    def _unar_filename_encoding_candidates(*, include_auto: bool = False) -> Tuple[Optional[str], ...]:
        """RAR 文件名编码候选。

        `UTF-8` 必须放在 `SHIFT_JIS` 前面：不少同人音声包本身就是 UTF-8 文件名，
        但 7z/unar 自动探测偶尔会按 GBK/CP936 解读，产出 `鍋靛伃...` 这类合法
        CJK mojibake；只尝试日文 ANSI 会把正确路径错过。
        """
        candidates: Tuple[Optional[str], ...] = ("UTF-8", "SHIFT_JIS", "GBK", "CP936", "BIG5")
        return (None, *candidates) if include_auto else candidates

    async def _fix_unar_garbled_encoding(
        self,
        archive_path: str,
        output_path: str,
        password: Optional[str],
        task: Optional[Task] = None,
    ) -> None:
        """若 output_path 中存在乱码文件名，依次以 SHIFT_JIS / GBK / BIG5 重新解压修复。

        不抛异常：若所有编码均无法修复，则回退重解一遍自动探测结果，确保目录有内容。
        """
        baseline_score = self._filename_garbled_score(output_path)
        if baseline_score < 30.0:
            return

        logger.warning(
            "[unar编码] 检测到疑似乱码文件名(score=%.1f)，准备轻量嗅探编码: %s",
            baseline_score,
            output_path,
        )
        repaired_count = await asyncio.to_thread(
            self._repair_mojibake_filenames_in_place,
            output_path,
        )
        if repaired_count:
            repaired_score = self._filename_garbled_score(output_path)
            logger.info(
                "[unar编码] 文件名反乱码重命名完成: count=%s score=%.1f",
                repaired_count,
                repaired_score,
            )
            if repaired_score < 30.0:
                return

        ranked_encodings = await self._rank_rar_encodings_after_garbled_extract(
            archive_path, password, baseline_score,
        )
        tried_encodings: set[str] = set()
        detected_encoding = ranked_encodings[0][0] if ranked_encodings else None
        needs_auto_restore = False
        if detected_encoding:
            await self._cleanup_extract_attempt(output_path)
            needs_auto_restore = True
            tried_encodings.add(detected_encoding)
            r = await self._try_unar_extract(
                archive_path, output_path, password, task=task, encoding=detected_encoding,
            )
            if r.returncode == 0:
                needs_auto_restore = False
                score = self._filename_garbled_score(output_path)
                logger.debug("[unar编码] 编码 %s 重解后乱码评分: %.1f", detected_encoding, score)
                if score < 30.0:
                    logger.info("[unar编码] 乱码修复成功，使用编码: %s score=%.1f", detected_encoding, score)
                    return
                logger.warning(
                    "[unar编码] 嗅探编码 %s 重解后仍疑似乱码 score=%.1f",
                    detected_encoding,
                    score,
                )
            else:
                logger.debug("[unar编码] 嗅探编码 %s 重解失败 rc=%s", detected_encoding, r.returncode)
        else:
            logger.warning(
                "[unar编码] lsar 嗅探不可用或无法改善评分，跳过多次完整重解: %s",
                archive_path,
            )
            return

        for candidate_encoding, candidate_score in ranked_encodings[1:]:
            if candidate_encoding in tried_encodings:
                continue
            if candidate_score >= baseline_score:
                continue
            await self._cleanup_extract_attempt(output_path)
            needs_auto_restore = True
            tried_encodings.add(candidate_encoding)
            logger.info(
                "[unar编码] 继续尝试候选编码: %s lsar_score=%.1f baseline=%.1f",
                candidate_encoding,
                candidate_score,
                baseline_score,
            )
            r = await self._try_unar_extract(
                archive_path, output_path, password, task=task, encoding=candidate_encoding,
            )
            if r.returncode != 0:
                logger.debug("[unar编码] 候选编码 %s 重解失败 rc=%s", candidate_encoding, r.returncode)
                continue
            score = self._filename_garbled_score(output_path)
            logger.debug("[unar编码] 编码 %s 重解后乱码评分: %.1f", candidate_encoding, score)
            if score < 30.0:
                logger.info("[unar编码] 乱码修复成功，使用编码: %s score=%.1f", candidate_encoding, score)
                return
            logger.warning(
                "[unar编码] 候选编码 %s 重解后仍疑似乱码 score=%.1f",
                candidate_encoding,
                score,
            )

        # 嗅探出的编码重解失败时恢复自动探测结果；上层会再次全树检查，仍乱码则失败清理。
        if needs_auto_restore:
            logger.warning("[unar编码] 乱码自动修复失败，回退自动探测结果")
            await self._cleanup_extract_attempt(output_path)
            r = await self._try_unar_extract(archive_path, output_path, password, task=task)
            if r.returncode == 0:
                repaired_count = await asyncio.to_thread(
                    self._repair_mojibake_filenames_in_place,
                    output_path,
                )
                if repaired_count:
                    logger.info(
                        "[unar编码] 回退自动探测后文件名反乱码重命名完成: count=%s score=%.1f",
                        repaired_count,
                        self._filename_garbled_score(output_path),
                    )

    async def _try_unar_extract(
        self,
        archive_path: str,
        output_path: str,
        password: Optional[str],
        task: Optional[Task] = None,
        encoding: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """调用 unar 解压。
        unar 默认会自动探测文件名编码（ICU），对日文 Shift-JIS / 中文 GBK 命名的
        RAR / ZIP 都比 7zz 友好（7zz 24.08 RAR 解析器不接受 -mcp）。
        传入 task 时支持 cancel / pause 立即 kill 子进程。
        encoding 非空时附加 ``-e <encoding>``（如 SHIFT_JIS / GBK / BIG5），
        用于乱码修复重试。
        """
        unar_path = self._find_unar_executable()
        if not unar_path:
            return subprocess.CompletedProcess(
                args=["unar", archive_path],
                returncode=127,
                stdout=b"",
                stderr=b"unar not found",
            )

        cmd = [
            unar_path,
            "-f",
            "-o",
            output_path,
        ]
        if encoding:
            cmd.extend(["-e", encoding])
        if password:
            cmd.extend(["-p", password])
        cmd.append(archive_path)
        logger.info("执行 unar 命令: %s", " ".join(cmd))
        return await self._run_subprocess_command(cmd, task=task, running_step="unar 解压中")

class VolumeSet:
    """分卷组"""
    def __init__(self, base_name: str, volumes: List[str], volume_type: str, entry_path: Optional[str] = None):
        self.base_name = base_name
        self.volumes = volumes
        self.type = volume_type
        self.entry_path = entry_path or (volumes[0] if volumes else "")
        self.is_complete = False
