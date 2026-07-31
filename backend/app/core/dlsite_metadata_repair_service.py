from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_

from .dlsite_metadata_trust import is_translation_placeholder_maker, normalize_rjcode
from .dlsite_service import get_dlsite_service
from .library_manager import get_library_manager
from .rename_service import RenameService
from ..config.settings import get_config
from ..models.database import LibraryIndexEntry, SessionLocal, WorkMetadata


FILESYSTEM_SKIP_RJCODES = {"RJ01645332"}


@dataclass(slots=True)
class RepairCandidate:
    rjcode: str
    old_maker_name: str = ""
    library_id: str = ""
    old_path: str = ""


class DLsiteMetadataRepairService:
    def __init__(self, *, session_factory=SessionLocal, dlsite=None, manager=None) -> None:
        self._session_factory = session_factory
        self._dlsite = dlsite or get_dlsite_service()
        self._manager = manager or get_library_manager()
        self._rename = RenameService()

    def enumerate_candidates(self, rjcodes: Optional[Iterable[str]] = None) -> list[RepairCandidate]:
        requested = {normalize_rjcode(value) for value in (rjcodes or [])}
        requested.discard("")
        db = self._session_factory()
        try:
            metadata_rows = (
                db.query(WorkMetadata)
                .filter(
                    or_(
                        WorkMetadata.maker_name.ilike("%みんなで翻訳%"),
                        WorkMetadata.maker_name.ilike("%大家一起来翻译%"),
                        func.lower(func.trim(WorkMetadata.maker_name)) == "translation",
                    )
                )
                .all()
            )
            polluted = {
                row.rjcode: str(row.maker_name or "")
                for row in metadata_rows
                if is_translation_placeholder_maker(row.maker_name)
            }
            path_rows = (
                db.query(LibraryIndexEntry)
                .filter(
                    LibraryIndexEntry.entry_type == "dir",
                    LibraryIndexEntry.depth <= 2,
                    LibraryIndexEntry.rjcode.isnot(None),
                    or_(
                        LibraryIndexEntry.name.ilike("%みんなで翻訳%"),
                        LibraryIndexEntry.name.ilike("%大家一起来翻译%"),
                        LibraryIndexEntry.name.ilike("%大家一起翻译%"),
                        LibraryIndexEntry.relative_path.ilike("みんなで翻訳/%"),
                        LibraryIndexEntry.relative_path.ilike("大家一起来翻译/%"),
                        LibraryIndexEntry.relative_path.ilike("大家一起翻译/%"),
                    ),
                )
                .order_by(
                    LibraryIndexEntry.library_id.asc(),
                    LibraryIndexEntry.rjcode.asc(),
                    LibraryIndexEntry.depth.asc(),
                    LibraryIndexEntry.generation.desc(),
                    LibraryIndexEntry.materialized_seq.desc(),
                )
                .all()
            )
            shallow_paths: dict[tuple[str, str], LibraryIndexEntry] = {}
            for row in path_rows:
                rjcode = normalize_rjcode(row.rjcode)
                if not rjcode:
                    continue
                if not (
                    is_translation_placeholder_maker(row.name)
                    or is_translation_placeholder_maker(
                        str(row.relative_path or "").replace("\\", "/").split("/", 1)[0]
                    )
                ):
                    continue
                shallow_paths.setdefault((str(row.library_id or ""), rjcode), row)

            candidate_rjs = set(polluted)
            candidate_rjs.update(rjcode for _, rjcode in shallow_paths)
            if requested:
                candidate_rjs &= requested

            result: list[RepairCandidate] = []
            for rjcode in sorted(candidate_rjs):
                matching_paths = [
                    (library_id, row)
                    for (library_id, path_rjcode), row in shallow_paths.items()
                    if path_rjcode == rjcode
                ]
                if not matching_paths:
                    result.append(
                        RepairCandidate(
                            rjcode=rjcode,
                            old_maker_name=polluted.get(rjcode, ""),
                        )
                    )
                    continue
                for library_id, row in matching_paths:
                    result.append(
                        RepairCandidate(
                            rjcode=rjcode,
                            old_maker_name=polluted.get(rjcode, ""),
                            library_id=library_id,
                            old_path=str(row.absolute_path or ""),
                        )
                    )
            return result
        finally:
            db.close()

    async def build_plan(self, candidate: RepairCandidate) -> dict[str, Any]:
        rjcode = candidate.rjcode
        self._dlsite.invalidate_rj_graph_cache(rjcode)
        product_info = await self._dlsite.get_product_info(rjcode, refresh=True)
        verification_status = str(
            (product_info or {}).get("metadata_verification_status") or "unverified"
        ).lower()
        verification_reason = str(
            (product_info or {}).get("metadata_verification_reason") or ""
        )
        evidence_source = str(
            (product_info or {}).get("metadata_evidence_source") or "unknown"
        )
        product = dict((product_info or {}).get("product") or {})
        new_maker_name = str(product.get("maker_name") or "").strip()
        if verification_status != "verified" or is_translation_placeholder_maker(new_maker_name):
            return {
                **asdict(candidate),
                "status": "skipped",
                "reason": verification_reason or "DLsite 元数据未通过可信度验证",
                "evidence_source": evidence_source,
                "evidence_status": verification_status,
            }

        metadata = self._metadata_from_product(rjcode, product)
        new_path = ""
        conflict = False
        filesystem_action = "none"
        if candidate.old_path and candidate.library_id:
            library = self._manager.get_library_definition(candidate.library_id)
            new_name = self._build_api_rename_name(rjcode, metadata)
            safe_maker = self._sanitize_filename(new_maker_name)
            new_path = os.path.join(os.path.abspath(library.root_path), safe_maker, new_name)
            conflict = os.path.exists(new_path) and os.path.normcase(new_path) != os.path.normcase(
                os.path.abspath(candidate.old_path)
            )
            filesystem_action = "skip" if rjcode in FILESYSTEM_SKIP_RJCODES else "rename_and_move"

        return {
            "rjcode": rjcode,
            "old_maker_name": candidate.old_maker_name,
            "new_maker_name": new_maker_name,
            "library_id": candidate.library_id,
            "old_path": candidate.old_path,
            "new_path": new_path,
            "status": "ready" if not conflict else "conflict",
            "reason": "目标路径已存在" if conflict else "",
            "evidence_source": evidence_source,
            "evidence_status": verification_status,
            "filesystem_action": filesystem_action,
            "metadata": metadata,
        }

    async def build_plans(self, rjcodes: Optional[Iterable[str]] = None) -> list[dict[str, Any]]:
        plans = []
        for candidate in self.enumerate_candidates(rjcodes):
            plans.append(await self.build_plan(candidate))
        return plans

    async def apply_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        if plan.get("status") != "ready":
            raise ValueError(f"修复计划不可执行: {plan.get('reason') or plan.get('status')}")
        self._update_metadata(plan["metadata"])
        if plan.get("filesystem_action") != "rename_and_move" or not plan.get("old_path"):
            return {**plan, "applied": True, "final_path": plan.get("old_path") or ""}

        old_path = os.path.abspath(str(plan["old_path"]))
        new_path = os.path.abspath(str(plan["new_path"]))
        library_id = str(plan["library_id"])
        target_dir = os.path.dirname(new_path)
        os.makedirs(target_dir, exist_ok=True)

        current_path = old_path
        new_name = os.path.basename(new_path)
        if os.path.basename(current_path) != new_name:
            renamed = await self._manager.rename(library_id, current_path, new_name)
            current_path = str(renamed.get("new_path") or os.path.join(os.path.dirname(current_path), new_name))
        if os.path.normcase(os.path.dirname(current_path)) != os.path.normcase(target_dir):
            moved = await self._manager.move_local_items(
                source_library_id=library_id,
                target_library_id=library_id,
                paths=[current_path],
                target_path=target_dir,
                conflict_strategy="skip",
            )
            if int(moved.get("success_count") or 0) != 1:
                raise RuntimeError(f"库存移动失败: {moved}")
            current_path = str((moved.get("moved") or [{}])[0].get("destination") or new_path)
        return {**plan, "applied": True, "final_path": current_path}

    def _metadata_from_product(self, rjcode: str, product: dict[str, Any]) -> dict[str, Any]:
        return {
            "rjcode": rjcode,
            "work_name": str(product.get("work_name") or "").strip(),
            "maker_id": str(product.get("maker_id") or "").strip(),
            "maker_name": str(product.get("maker_name") or "").strip(),
            "release_date": str(product.get("regist_date") or "")[:10],
            "series_name": str(product.get("series_name") or "").strip(),
            "series_id": str(product.get("series_id") or "").strip(),
            "age_category": "ADL",
            "tags": [
                str(item.get("name") or "").strip()
                for item in list(product.get("genres") or [])
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
            "cvs": [
                str(item.get("name") or "").strip()
                for item in list(product.get("voice_by") or [])
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
            "cover_url": str((product.get("image_main") or {}).get("url") or "").strip(),
        }

    def _build_api_rename_name(self, rjcode: str, metadata: dict[str, Any]) -> str:
        config = get_config()
        if config.rename.api_rename_follow_template:
            return self._rename._sanitize_filename(self._rename._compile_name(metadata, None))
        return f"{rjcode} {self._sanitize_filename(metadata.get('work_name') or rjcode)}"

    @staticmethod
    def _sanitize_filename(value: Any) -> str:
        text = re.sub(r'[<>:"/\\|?*]', "_", str(value or ""))
        return re.sub(r"[\x00-\x1f\x7f]", "", text).rstrip(" .")

    def _update_metadata(self, metadata: dict[str, Any]) -> None:
        db = self._session_factory()
        try:
            row = db.query(WorkMetadata).filter(WorkMetadata.rjcode == metadata["rjcode"]).first()
            if row is None:
                row = WorkMetadata(rjcode=metadata["rjcode"])
                db.add(row)
            for key in (
                "work_name",
                "maker_id",
                "maker_name",
                "release_date",
                "series_name",
                "series_id",
                "age_category",
                "tags",
                "cvs",
                "cover_url",
            ):
                setattr(row, key, metadata.get(key))
            row.cached_at = datetime.now()
            row.expires_at = datetime.now() + timedelta(hours=24)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
