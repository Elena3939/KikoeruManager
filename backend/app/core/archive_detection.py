"""压缩包探测小工具。"""

import logging
import os
import struct
import zipfile
import zlib
from typing import Optional

logger = logging.getLogger(__name__)


def detect_embedded_7z_offset(path: str) -> Optional[int]:
    """有界分块查找前缀壳内的 7z，并校验起始头，避免把图片内容误判为压缩包。

    最多搜索前 8 MiB，不扫描整个媒体文件；起始头的 CRC 和下一头位置
    必须有效。只探测，不复制或修改原文件，7zz 可直接处理这个偏移。
    """
    signature = b"7z\xbc\xaf\x27\x1c"
    search_limit = 8 * 1024 * 1024
    chunk_size = 64 * 1024
    try:
        with open(path, "rb") as fp:
            file_size = os.fstat(fp.fileno()).st_size
            end = min(file_size, search_limit + 32)
            position = 0
            while position < end:
                fp.seek(position)
                chunk = fp.read(min(chunk_size + 31, end - position))
                if position == 0 and chunk.startswith((
                    signature, b'PK\x03\x04', b'Rar!', b'\x1f\x8b', b'BZh', b'\xfd7zXZ',
                )):
                    return None
                start = 0
                while (index := chunk.find(signature, start)) >= 0:
                    offset = position + index
                    header = chunk[index:index + 32]
                    if 0 < offset <= search_limit and len(header) == 32 and header[6] == 0:
                        expected_crc = struct.unpack_from("<I", header, 8)[0]
                        next_offset, next_size = struct.unpack_from("<QQ", header, 12)
                        if (
                            zlib.crc32(header[12:32]) == expected_crc
                            and offset + 32 + next_offset + next_size <= file_size
                        ):
                            return offset
                    start = index + 1
                position += chunk_size
    except (OSError, ValueError):
        return None
    return None


def detect_embedded_zip_offset(path: str) -> Optional[int]:
    """检测“前面有伪装/媒体壳，后面是真 ZIP”的文件。

    Bandizip 会自动扫描这类 prepended ZIP，但 7zz / Linux 常规链路通常只看
    文件头，看到 MP4/其它壳后直接判非压缩包。这里只读 ZIP 中央目录和首个
    local header，不做全文件扫描。
    """
    if not path:
        return None
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < 32:
            return None
        with zipfile.ZipFile(path) as zf:
            infos = [info for info in zf.infolist() if int(info.header_offset) >= 0]
        if not infos:
            return None
        offset = min(int(info.header_offset) for info in infos)
        if offset <= 0:
            return None
        with open(path, "rb") as fp:
            fp.seek(offset)
            if fp.read(4) != b"PK\x03\x04":
                return None
        return offset
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        return None
    except Exception:
        logger.debug("探测嵌入 ZIP 失败: %s", path, exc_info=True)
        return None


def has_embedded_zip_archive(path: str) -> bool:
    return detect_embedded_zip_offset(path) is not None
