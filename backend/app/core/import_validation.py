"""导入、重命名共用的数据完整性检查，失败时必须停止文件操作。"""


class ImportDataError(RuntimeError):
    def __init__(self, reason: str, stage: str = "metadata"):
        super().__init__(reason)
        self.stage = stage


def require_import_metadata(metadata: dict) -> None:
    if not metadata:
        raise ImportDataError("DLsite 元数据为空，已停止重命名或入库")
    reason = api_rename_metadata_skip_reason(metadata, metadata.get("rjcode"))
    if reason:
        raise ImportDataError(reason)


def require_complete_linkage(linked_works: dict) -> None:
    if not linked_works or any(
        str(getattr(work, "evidence_status", "") or "").strip().lower() != "verified"
        for work in linked_works.values()
    ):
        raise ImportDataError("DLsite 关联数据获取失败或未经验证，无法确认作品关系", "linkage")


def api_rename_metadata_skip_reason(metadata: dict, rjcode: str) -> str:
    from .dlsite_metadata_trust import attach_dlsite_metadata_verification

    attach_dlsite_metadata_verification(metadata, rjcode)
    source = str(metadata.get("metadata_source") or "").strip().lower()
    if source == "minimal":
        if metadata.get("dlsite_circuit_open"):
            return "DLsite 元数据短熔断中，已跳过重命名"
        return "DLsite 元数据不可用，已跳过重命名"

    verification_status = str(
        metadata.get("metadata_verification_status") or ""
    ).strip().lower()
    verification_reason = str(
        metadata.get("metadata_verification_reason") or ""
    ).strip()
    if verification_status != "verified":
        return verification_reason or "DLsite 元数据未经验证，已跳过重命名"

    normalized_rj = str(rjcode or metadata.get("rjcode") or "").strip().upper()
    work_name = str(metadata.get("work_name") or "").strip()
    maker_name = str(metadata.get("maker_name") or "").strip()
    if not work_name:
        return "DLsite 元数据缺少作品名称，已停止重命名"
    has_any_detail = any(
        [
            str(metadata.get("cover_url") or "").strip(),
            str(metadata.get("release_date") or "").strip(),
            metadata.get("tags") or [],
            metadata.get("cvs") or [],
        ]
    )

    if not maker_name and work_name.upper() == normalized_rj and not has_any_detail:
        return "元数据不完整，已跳过重命名"
    return ""
