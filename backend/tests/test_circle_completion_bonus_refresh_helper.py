"""``_refresh_circle_bonus_fields`` helper + 浏览路径纯读化的回归测试。

★ 用户反馈痛点："每次点击社团都执行一遍找特典操作，效率太低，应该都移到
创建刷新索引的时候去做"。

本测试覆盖三层语义：

1) ``build_circle_completion_view`` 不再触发 bonus 补刷——浏览路径纯 DB 读。
2) ``_refresh_circle_bonus_fields`` 在写路径里能把
   ``lazy_refresh_bonus_for_cached_rjcodes`` 的结果同步到当前社团的
   ``circle_works`` 行。
3) ``canonical_filter`` 能把 bonus 同步范围限定到指定 canonical（refresh_circle_works
   只刷新选中作品时用），不动同社团里其他行。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
import uuid

import pytest

import app.core.circle_completion_service as circle_completion_module
from app.core.circle_completion_service import CircleCompletionService
from app.models.database import (
    CircleCatalog,
    CircleWork,
    WorkMetadata,
)


@pytest.fixture
def service(db_session, monkeypatch: pytest.MonkeyPatch) -> CircleCompletionService:
    monkeypatch.setattr(circle_completion_module, "SessionLocal", lambda: db_session)
    return CircleCompletionService()


def _seed_circle(
    db_session,
    *,
    circle_id: str,
    canonical_rjcode: str,
    is_bonus_work_in_circle_work: bool = False,
    bonus_info_checked_at: datetime | None = None,
    is_bonus_work_in_metadata: bool = False,
) -> None:
    db_session.add(
        CircleCatalog(
            circle_id=circle_id,
            circle_name="生ハメ堕ち部★LACK",
            circle_name_normalized="生ハメ堕ち部 lack",
            source_mask="dlsite",
            last_indexed_at=datetime(2025, 10, 1, 0, 0, 0),
        )
    )
    db_session.add(
        CircleWork(
            id=str(uuid.uuid4()),
            circle_id=circle_id,
            canonical_rjcode=canonical_rjcode,
            display_rjcode=canonical_rjcode,
            title="!3大早期購入特典!",
            maker_id="RG_X",
            maker_name="生ハメ堕ち部★LACK",
            source_mask="dlsite",
            linked_rjcodes=[canonical_rjcode],
            has_kikoeru=False,
            kikoeru_found_rjcodes=[],
            kikoeru_subtitle_rjcodes=[],
            has_dlsite=True,
            has_asmr_one=False,
            asmr_available_rjcode=None,
            image_url="",
            price_text="",
            is_bonus_work=is_bonus_work_in_circle_work,
            has_bonus=False,
        )
    )
    db_session.add(
        WorkMetadata(
            rjcode=canonical_rjcode,
            work_name="!3大早期購入特典!",
            maker_id="RG_X",
            maker_name="生ハメ堕ち部★LACK",
            release_date="2026-03-07",
            tags=["音声・ASMR"],
            cvs=["山田じぇみ子"],
            cover_url="",
            is_bonus_work=is_bonus_work_in_metadata,
            has_bonus=False,
            bonus_info_checked_at=bonus_info_checked_at,
            expires_at=datetime(2099, 1, 1),
        )
    )
    db_session.commit()


@pytest.mark.asyncio
async def test_build_view_does_not_trigger_bonus_lazy_refresh(
    service: CircleCompletionService,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """浏览路径必须是纯 DB 读：``build_circle_completion_view`` 不应再调用
    ``lazy_refresh_bonus_for_cached_rjcodes``——bonus 补刷已经移到
    ``index_circle_catalog`` / ``refresh_circle_works`` 写路径里。"""
    _seed_circle(
        db_session,
        circle_id="circle_browse_pure_read",
        canonical_rjcode="RJ01392203",
        is_bonus_work_in_circle_work=False,
    )

    captured: Dict[str, Any] = {"calls": 0}

    async def _spy_lazy_refresh(rjcodes: List[str], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        captured["calls"] += 1
        return {"RJ01392203": {"is_bonus_work": True, "has_bonus": False}}

    monkeypatch.setattr(
        service.metadata_service,
        "lazy_refresh_bonus_for_cached_rjcodes",
        _spy_lazy_refresh,
    )

    result = await service.build_circle_completion_view("circle_browse_pure_read")

    # 1) lazy_refresh 一次都没被调用——浏览路径已纯读化
    assert captured["calls"] == 0, "浏览路径不应触发 bonus lazy_refresh"

    # 2) circle_works.is_bonus_work 现状被原样输出（False），浏览路径不再回写
    works = result["works"]
    assert len(works) == 1
    assert works[0]["is_bonus_work"] is False

    row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ01392203")
        .one()
    )
    assert bool(row.is_bonus_work) is False


@pytest.mark.asyncio
async def test_build_view_cache_can_be_invalidated(
    service: CircleCompletionService,
    db_session,
) -> None:
    _seed_circle(
        db_session,
        circle_id="circle_view_cache",
        canonical_rjcode="RJ01392204",
        is_bonus_work_in_circle_work=False,
    )

    first = await service.build_circle_completion_view("circle_view_cache")
    row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ01392204")
        .one()
    )
    row.title = "缓存失效后的标题"
    db_session.commit()

    cached = await service.build_circle_completion_view("circle_view_cache")
    service.invalidate_completion_view_cache("circle_view_cache")
    refreshed = await service.build_circle_completion_view("circle_view_cache")

    assert first["works"][0]["title"] != "缓存失效后的标题"
    assert cached["works"][0]["title"] != "缓存失效后的标题"
    assert refreshed["works"][0]["title"] == "缓存失效后的标题"


@pytest.mark.asyncio
async def test_refresh_circle_bonus_fields_syncs_updates_to_circle_works(
    service: CircleCompletionService,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_refresh_circle_bonus_fields`` 在写路径里被调用时，必须把
    ``lazy_refresh_bonus_for_cached_rjcodes`` 返回的 ``is_bonus_work=True``
    同步到当前社团的 ``circle_works`` 行。"""
    _seed_circle(
        db_session,
        circle_id="circle_index_path",
        canonical_rjcode="RJ01392203",
        is_bonus_work_in_circle_work=False,
    )

    async def _fake_lazy_refresh(rjcodes: List[str], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        # 注意 helper 内部会先 normalize，传进来的应该都是大写 RJ
        assert "RJ01392203" in rjcodes
        return {
            "RJ01392203": {
                "is_bonus_work": True,
                "has_bonus": False,
                "bonus_info_checked_at": datetime(2025, 10, 1, 12, 0, 0).isoformat(),
            }
        }

    monkeypatch.setattr(
        service.metadata_service,
        "lazy_refresh_bonus_for_cached_rjcodes",
        _fake_lazy_refresh,
    )

    updates = await service._refresh_circle_bonus_fields(
        "circle_index_path",
        ["RJ01392203"],
    )

    assert updates == {
        "RJ01392203": {
            "is_bonus_work": True,
            "has_bonus": False,
            "bonus_info_checked_at": datetime(2025, 10, 1, 12, 0, 0).isoformat(),
        }
    }

    # circle_works 行已被回写
    row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ01392203")
        .one()
    )
    assert bool(row.is_bonus_work) is True


@pytest.mark.asyncio
async def test_refresh_circle_bonus_fields_respects_canonical_filter(
    service: CircleCompletionService,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``refresh_circle_works`` 路径只刷新选中的 canonical 时，
    ``canonical_filter`` 必须把回写范围收窄，不动其他未选中作品。"""
    _seed_circle(
        db_session,
        circle_id="circle_selected_only",
        canonical_rjcode="RJ01392203",
    )
    # 同社团多塞一个未被选中的行——它即使在 bonus_updates 里命中也不应被回写
    db_session.add(
        CircleWork(
            id=str(uuid.uuid4()),
            circle_id="circle_selected_only",
            canonical_rjcode="RJ09999999",
            display_rjcode="RJ09999999",
            title="未选中的另一作",
            maker_id="RG_X",
            maker_name="生ハメ堕ち部★LACK",
            source_mask="dlsite",
            linked_rjcodes=["RJ09999999"],
            has_kikoeru=False,
            kikoeru_found_rjcodes=[],
            kikoeru_subtitle_rjcodes=[],
            has_dlsite=True,
            has_asmr_one=False,
            asmr_available_rjcode=None,
            image_url="",
            price_text="",
            is_bonus_work=False,
            has_bonus=False,
        )
    )
    db_session.commit()

    async def _fake_lazy_refresh(rjcodes: List[str], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        return {
            "RJ01392203": {"is_bonus_work": True, "has_bonus": False},
            "RJ09999999": {"is_bonus_work": True, "has_bonus": False},
        }

    monkeypatch.setattr(
        service.metadata_service,
        "lazy_refresh_bonus_for_cached_rjcodes",
        _fake_lazy_refresh,
    )

    await service._refresh_circle_bonus_fields(
        "circle_selected_only",
        ["RJ01392203", "RJ09999999"],
        canonical_filter=["RJ01392203"],
    )

    selected_row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ01392203")
        .one()
    )
    assert bool(selected_row.is_bonus_work) is True

    other_row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ09999999")
        .one()
    )
    assert bool(other_row.is_bonus_work) is False, (
        "canonical_filter 之外的行不应被回写，refresh_circle_works "
        "只刷新选中作品时不能误伤同社团其他行"
    )


@pytest.mark.asyncio
async def test_refresh_circle_bonus_fields_handles_lazy_refresh_failure(
    service: CircleCompletionService,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``lazy_refresh_bonus_for_cached_rjcodes`` 异常时 helper 必须吞掉、
    保留 ``circle_works`` 现状，索引 / 刷新流程不能因为 bonus 失败而崩。"""
    _seed_circle(
        db_session,
        circle_id="circle_bonus_outage",
        canonical_rjcode="RJ02000999",
    )

    async def _exploding(rjcodes: List[str], **kwargs: Any) -> Dict[str, Dict[str, Any]]:
        raise RuntimeError("dlsite outage")

    monkeypatch.setattr(
        service.metadata_service,
        "lazy_refresh_bonus_for_cached_rjcodes",
        _exploding,
    )

    updates = await service._refresh_circle_bonus_fields(
        "circle_bonus_outage",
        ["RJ02000999"],
    )

    assert updates == {}

    row = (
        db_session.query(CircleWork)
        .filter(CircleWork.canonical_rjcode == "RJ02000999")
        .one()
    )
    assert bool(row.is_bonus_work) is False
