"""library_index 内部共享小工具。

LocalScanner / RemoteScanner / WatcherDriver 都用同一份 RJ 正则与跳过规则。
集中在此避免多处维护 / 走偏。

注意：与 library_manager._extract_rjcode、_should_skip_entry 同源；
改动时请保持一致。
"""
from __future__ import annotations

import re
from typing import Optional

# RJ 正则：与 library_manager._extract_rjcode 一致
_RJ_PATTERN = re.compile(r"[RVB]J(?:\d{6}|\d{8})(?!\d)", re.IGNORECASE)
# 跳过的目录 / 文件名（小写）：群晖回收站、索引目录等
_SKIP_LOWER = {"#recycle", "@eadir", "__macosx"}


def should_skip_name(name: str) -> bool:
    """是否应该跳过该条目。

    - 空名 / None：跳
    - 以 . 开头：跳（隐藏文件、.DS_Store 等）
    - 群晖回收站 / 索引、macOS 压缩包元数据目录：跳

    下划线是合法资源文件名的一部分。ASMR 特典中常见 ``_096.png``
    这类文件，不能再把所有 ``_`` 前缀统一视为内部临时项。
    """
    if not name:
        return True
    if name.startswith("."):
        return True
    return name.lower() in _SKIP_LOWER


def extract_rjcode(value: str) -> Optional[str]:
    """从字符串里提取 RJ 号（首次匹配，统一大写）。"""
    if not value:
        return None
    match = _RJ_PATTERN.search(value)
    return match.group(0).upper() if match else None
