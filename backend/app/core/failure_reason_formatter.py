"""任务失败原因的人类可读文案。"""
from __future__ import annotations

from typing import Any, Mapping


_EXTRACT_REASON_MESSAGES = {
    "wrong_password": "解压失败：密码未命中（无密码、RJ 号、密码库候选均未通过）",
    "missing_password": "解压失败：压缩包需要密码，但当前没有可用密码",
    "disk_full": "解压失败：临时目录磁盘空间不足",
    "volume_incomplete": "解压失败：分卷压缩包不完整或自解压分卷视图异常",
    "archive_corrupt": "解压失败：压缩包损坏或下载不完整（Headers/Data Error）",
    "path_too_long": "解压失败：路径或文件名过长（Linux 单个文件名通常最多 255 字节）",
    "unsupported_method": "解压失败：当前 7z 不支持该压缩方法",
    "light_probe_unknown": "解压失败：大文件轻量探测无法定性，已停止全量试错",
    "garbled_filename": "解压失败：文件名疑似乱码，需要确认编码",
    "extract_incomplete": "解压失败：解压结果未通过完整性校验",
}


_TEXT_REASON_MARKERS = (
    ("wrong_password", ("无正确密码", "密码错误", "密码不正确", "wrong password", "incorrect password")),
    ("missing_password", ("password required", "missing password", "需要密码")),
    ("disk_full", ("no space left", "磁盘空间不足", "空间不足")),
    ("volume_incomplete", ("missing volume", "分卷", "unexpected end of archive")),
    ("archive_corrupt", ("headers error", "data error", "cannot open the file as archive", "压缩包损坏")),
    ("path_too_long", ("file name too long", "path too long", "路径或文件名过长", "文件名过长")),
    ("unsupported_method", ("unsupported method", "unsupported compression method", "不支持", "e_invalidarg")),
    ("garbled_filename", ("文件名乱码", "乱码")),
    ("extract_incomplete", ("解压产物为空", "不完整", "完整性校验")),
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def infer_extract_failure_reason(metadata: Mapping[str, Any] | None = None, fallback: Any = "") -> str:
    """从结构化 reason 优先，文本 marker 兜底推断解压失败类型。"""
    meta = dict(metadata or {})
    reason = _clean_text(meta.get("extract_failure_reason")).lower()
    if reason:
        return reason

    text = " ".join(
        _clean_text(value)
        for value in (
            fallback,
            meta.get("error_message"),
            meta.get("resolution_error"),
            meta.get("extract_unsupported_method_error"),
            meta.get("extract_path_too_long_error"),
            meta.get("sfx_volume_view_error"),
        )
        if _clean_text(value)
    ).lower()
    for inferred_reason, markers in _TEXT_REASON_MARKERS:
        if any(marker.lower() in text for marker in markers):
            return inferred_reason
    return ""


def format_extract_failure_message(metadata: Mapping[str, Any] | None = None, fallback: Any = "") -> str:
    """把解压失败 reason code 转成不会误导用户的具体文案。"""
    meta = dict(metadata or {})
    reason = infer_extract_failure_reason(meta, fallback)
    message = _EXTRACT_REASON_MESSAGES.get(reason)
    if not message:
        fallback_text = _clean_text(fallback) or _clean_text(meta.get("error_message"))
        return fallback_text or "解压失败：原因未知"

    if reason == "garbled_filename":
        sample = _clean_text(meta.get("garbled_filename_sample"))
        if sample:
            return f"{message}（样本：{sample}）"
    if reason == "unsupported_method":
        method = _clean_text(meta.get("extract_zstd_method") or meta.get("archive_method"))
        if method:
            return f"{message}（方法：{method}）"
    if reason == "extract_incomplete":
        file_count = meta.get("extract_payload_file_count")
        total_bytes = meta.get("extract_payload_total_bytes")
        if file_count is not None or total_bytes is not None:
            return f"{message}（文件数：{file_count or 0}，字节数：{total_bytes or 0}）"
    return message


def format_problem_failure_message(
    metadata: Mapping[str, Any] | None = None,
    fallback: Any = "",
    *,
    stage: Any = "",
) -> str:
    """问题作品 / 通知统一展示的失败文案。"""
    meta = dict(metadata or {})
    stage_text = _clean_text(stage or meta.get("failure_stage")).lower()
    if stage_text == "extract" or infer_extract_failure_reason(meta, fallback):
        return format_extract_failure_message(meta, fallback)
    return _clean_text(fallback) or _clean_text(meta.get("error_message")) or "需要人工处理"
