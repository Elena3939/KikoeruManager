"""多作品压缩包的父任务身份，不使用其中一个作品代表整个合集。"""
import re


def aggregate_rjcodes(metadata):
    metadata = metadata or {}
    if not metadata.get("aggregate_archive") or metadata.get("rjcode_lock"):
        return []
    codes = metadata.get("aggregate_rjcodes")
    if not isinstance(codes, list):
        return []
    codes = list(dict.fromkeys(
        str(code).strip().upper() for code in codes
        if re.fullmatch(r"[RVB]J(?:\d{8}|\d{6})", str(code).strip(), re.I)
    ))
    return codes if len(codes) >= 2 else []


def aggregate_archive_title(metadata, source_path):
    codes = aggregate_rjcodes(metadata)
    if not codes:
        return ""
    name = re.split(r"[\\/]", str(source_path or "").rstrip("\\/"))[-1] or "合集压缩包"
    return f"{name}（{len(codes)} 个作品）"
