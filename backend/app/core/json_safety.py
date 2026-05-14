from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional


def has_surrogate(value: str) -> bool:
    return any("\ud800" <= char <= "\udfff" for char in value)


def sqlite_safe_text(value: Optional[str]) -> Optional[str]:
    """SQLite JSON/TEXT 只能绑定合法 UTF-8，Linux 坏文件名字节要先转义。"""
    if value is None:
        return None
    text = str(value)
    if not has_surrogate(text):
        return text
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def safe_text(value: Any, *, strip: bool = False) -> str:
    text = sqlite_safe_text(str(value or "")) or ""
    return text.strip() if strip else text


def safe_json_value(value: Any) -> Any:
    """递归清洗要落库或返回给前端的 JSON 值，保留结构但去掉非法 UTF-8。"""
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return sqlite_safe_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return sqlite_safe_text(str(value))
    if isinstance(value, dict):
        return {
            sqlite_safe_text(str(key)) or "": safe_json_value(current)
            for key, current in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [safe_json_value(current) for current in value]
    return sqlite_safe_text(str(value))
