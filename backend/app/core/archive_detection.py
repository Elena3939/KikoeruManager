"""压缩包探测小工具。"""

import logging
import os
import zipfile
from typing import Optional

logger = logging.getLogger(__name__)


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
