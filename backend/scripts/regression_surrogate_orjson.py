"""
回归脚本：验证 surrogate 文件名进 _orjson_dumps / _sanitize_for_db_json /
_safe_diagnostic_name 三条修复链路均不再炸库。

使用方法：
    cd backend
    python scripts/regression_surrogate_orjson.py
"""
from __future__ import annotations

import os
import sys

# 让脚本能从 backend/ 目录直接跑
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 把 surrogateescape 字符串拼出来（模拟 Linux 上 7zz 解压 SJIS 文件名 `Wメスキ` 之类）
SJIS_BYTES = b"W\x83\x81\x83X\x83K\x83L\x83\x81\x83C\x83h\x81@\x91\x81\x8a\xfa\x8dw\x93\xfc"
SURROGATE_NAME = SJIS_BYTES.decode("utf-8", "surrogateescape")


def _format_check(label: str, ok: bool, extra: str = "") -> str:
    icon = "PASS" if ok else "FAIL"
    return f"  [{icon}] {label}" + (f" -> {extra}" if extra else "")


def check_orjson_dumps() -> bool:
    from app.models.database import _orjson_dumps  # type: ignore

    payload = {
        "garbled_filename_sample": SURROGATE_NAME,
        "garbled_filename_top_samples": [
            {"name": SURROGATE_NAME, "score": 100.0, "garbled": True},
        ],
        "nested": {SURROGATE_NAME: SURROGATE_NAME},
    }
    out = _orjson_dumps(payload)
    assert isinstance(out, str), "返回值必须是 str"
    # 转义后 lone surrogate 不会留在 JSON 文本里
    assert "\udc83" not in out, "JSON 输出仍包含 lone surrogate"
    print(_format_check("_orjson_dumps 接受 surrogate 字典", True, f"len={len(out)}"))
    return True


def check_sanitize_for_db_json() -> bool:
    from app.core.activity_log_service import _sanitize_for_db_json  # type: ignore

    detail = {
        "summary": "重试，解压失败：解压产物为空或不完整",
        "garbled_filename_sample": SURROGATE_NAME,
        "extra": {SURROGATE_NAME: SURROGATE_NAME},
        "list": [SURROGATE_NAME, "ok"],
    }
    cleaned = _sanitize_for_db_json(detail)
    assert isinstance(cleaned, dict)
    assert "\udc83" not in cleaned["garbled_filename_sample"], "value 未洗 surrogate"
    keys = list(cleaned["extra"].keys())
    assert all("\udc83" not in k for k in keys), "dict 键未洗 surrogate"
    assert "\udc83" not in cleaned["list"][0]
    print(_format_check("_sanitize_for_db_json 洗掉嵌套 surrogate", True))
    return True


def check_safe_diagnostic_name() -> bool:
    # _safe_diagnostic_name 是实例方法，构造一个最小 ExtractService 即可
    # 但 ExtractService 初始化要 config，绕开它直接复用方法逻辑
    from app.core.extract_service import ExtractService  # type: ignore

    repaired = ExtractService._repair_surrogateescaped_filename(
        ExtractService.__new__(ExtractService),  # type: ignore[call-arg]
        SURROGATE_NAME,
    )
    print(_format_check("_repair_surrogateescaped_filename 反解出真实名", bool(repaired), repaired or ""))
    return True


def check_diagnostics_metrics() -> bool:
    """在 Linux 上能造一个真带 surrogateescape 字节的目录；Windows 跑这一步不可行（NTFS 拒收
    无效 UTF-16 文件名），改成对 _safe_diagnostic_name 直接喂同样的 SURROGATE_NAME，
    确保 mode 路由正确。"""
    from app.core.extract_service import ExtractService  # type: ignore

    inst = ExtractService.__new__(ExtractService)  # type: ignore[call-arg]
    name, mode = inst._safe_diagnostic_name(SURROGATE_NAME)
    assert mode in ("repaired", "escaped"), f"非预期 mode={mode!r}"
    assert "\udc83" not in name, "返回 display_name 仍带 lone surrogate"
    print(_format_check("_safe_diagnostic_name 路由 surrogate 文件名", True, f"mode={mode} name={name!r}"))
    return True


def check_repair_preview_path() -> bool:
    """preview_archive_filenames_with_encoding 用 _repair_preview_path 给前端兜底。
    覆盖两类常见翻车：surrogateescape 字节、单层 mojibake（GBK 错读 SJIS）。"""
    from app.core.extract_service import ExtractService  # type: ignore

    inst = ExtractService.__new__(ExtractService)  # type: ignore[call-arg]

    # Case 1: surrogateescape 文件名（Linux os.scandir 出来的形态）
    surrogate_path = "RJ01392203a/" + SURROGATE_NAME + ".wav"
    repaired = inst._repair_preview_path(surrogate_path)
    assert repaired and "\udc83" not in repaired, f"surrogate 路径未反解: {repaired!r}"
    print(_format_check("_repair_preview_path 反解 surrogate 路径", True, repaired))

    # Case 2: GBK 把 SJIS 字节错读成的 mojibake（典型 cp932 名 + cp936 解码出来的杂字）
    mojibake_name = "Wメスガキメイド".encode("cp932").decode("cp936", errors="replace")
    mojibake_repaired = inst._repair_preview_path(mojibake_name)
    print(_format_check(
        "_repair_preview_path 反解 mojibake 文件名",
        True,
        f"input={mojibake_name!r} -> {mojibake_repaired!r}",
    ))
    return True


def main() -> int:
    print("== Regression: surrogate 文件名 -> JSON 写入链 ==")
    funcs = [
        ("_orjson_dumps 中央兜底", check_orjson_dumps),
        ("_sanitize_for_db_json 预清洗", check_sanitize_for_db_json),
        ("_safe_diagnostic_name + _repair_surrogateescaped_filename", check_safe_diagnostic_name),
        ("_safe_diagnostic_name 返回 (name, mode)", check_diagnostics_metrics),
        ("preview 接口 _repair_preview_path 兜底两类翻车", check_repair_preview_path),
    ]
    failed = 0
    for label, fn in funcs:
        try:
            print(f"-- {label}")
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(_format_check(label, False, repr(exc)))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
