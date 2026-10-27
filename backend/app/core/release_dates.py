"""DLsite 发售日的区间语义，供排序和资源探测共用。"""

import calendar
import re
from datetime import date
from typing import Any, Optional


def release_date_end(value: Any, *, today: Optional[date] = None) -> Optional[date]:
    """模糊日期取区间末日，避免在预计发售区间结束前探测资源。"""
    text = str(value or "").strip()
    current = today or date.today()
    match = re.search(r"(?:(\d{4})[-/.年]\s*)?(\d{1,2})月", text)
    if match is None:
        match = re.search(r"(\d{4})[-/.](\d{1,2})(?!\d)", text)
    if match is None:
        return None
    year, month = int(match.group(1) or current.year), int(match.group(2))
    if not 1 <= month <= 12:
        return None
    suffix = text[match.end():].strip()
    exact = re.match(r"(?:[-/.]\s*)?(\d{1,2})(?!\d)", suffix)
    day = (
        int(exact.group(1)) if exact else
        10 if "上旬" in suffix else
        20 if "中旬" in suffix else
        calendar.monthrange(year, month)[1]
    )
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_unreleased(value: Any, *, today: Optional[date] = None) -> bool:
    text = str(value or "").strip().lower()
    if any(word in text for word in (
        "未定", "未確定", "未确定", "未発表", "未发表", "予定", "tbd", "tba", "coming soon",
    )):
        return True
    end = release_date_end(value, today=today)
    return end is not None and end > (today or date.today())
