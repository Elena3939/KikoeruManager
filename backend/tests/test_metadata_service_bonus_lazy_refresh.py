"""metadata_service - bonus 字段懒迁移回归测试。

bug 现场：``work_metadata.is_bonus_work`` / ``has_bonus`` 字段是后期才加上的，
ALTER TABLE 给了 ``DEFAULT 0`` 让所有历史条目变成 False。再叠加 30 天 TTL
和 ``_should_refresh_cached_metadata`` 不看 bonus 字段，老条目就永远卡在
False，社团补全里看不到"特典" chip（用户反馈 RJ01392203）。

修复用 ``work_metadata.bonus_info_checked_at`` 做标记位 + 浏览路径 lazy
refresh。这里只覆盖 ``lazy_refresh_bonus_for_cached_rjcodes`` 自身行为：
存量补刷、跳过已 check、失败兜底。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import pytest

import app.core.metadata_service as metadata_service_module
from app.core.metadata_service import MetadataService
from app.models.database import WorkMetadata


@pytest.fixture
def service(db_session, monkeypatch: pytest.MonkeyPatch) -> MetadataService:
    """让 metadata_service 内部的 get_db 直接复用测试 session。"""

    def _fake_get_db():
        # metadata_service 用 ``next(get_db())`` 拿 db 然后 close；
        # 这里不真 close 测试 session，让 fixture 自己管理。
        try:
            yield db_session
        finally:
            pass

    monkeypatch.setattr(metadata_service_module, "get_db", _fake_get_db)
    return MetadataService()


class _StubDlsiteService:
    """记录调用，可注入返回值或异常。"""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.responses: Dict[str, Dict[str, bool]] = {}
        self.raise_for: set = set()

    async def get_product_bonus_info(self, rjcode: str, *, locale: str | None = None) -> Dict[str, bool]:
        self.calls.append(rjcode)
        if rjcode in self.raise_for:
            raise RuntimeError("stub failure")
        return self.responses.get(rjcode, {"is_bonus_work": False, "has_bonus": False})


@pytest.fixture
def stub_dlsite(monkeypatch: pytest.MonkeyPatch) -> _StubDlsiteService:
    stub = _StubDlsiteService()
    monkeypatch.setattr(
        metadata_service_module,
        "get_dlsite_service",
        lambda: stub,
    )
    return stub


def _add_metadata_row(
    db_session,
    rjcode: str,
    *,
    is_bonus_work: bool = False,
    has_bonus: bool = False,
    bonus_info_checked_at: datetime | None = None,
) -> None:
    db_session.add(
        WorkMetadata(
            rjcode=rjcode,
            work_name=f"{rjcode} 占位",
            maker_id="RG00000",
            maker_name="某社团",
            release_date="2025-01-01",
            tags=["音声・ASMR"],
            cvs=[],
            is_bonus_work=is_bonus_work,
            has_bonus=has_bonus,
            bonus_info_checked_at=bonus_info_checked_at,
            expires_at=datetime(2099, 1, 1),
        )
    )
    db_session.commit()


@pytest.mark.asyncio
async def test_lazy_refresh_backfills_old_entry_without_checked_at(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """老条目 bonus_info_checked_at IS NULL → 应触发 DLsite 拉一次并落库。"""
    _add_metadata_row(db_session, "RJ01392203")
    stub_dlsite.responses["RJ01392203"] = {"is_bonus_work": True, "has_bonus": False}

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(["RJ01392203"])

    assert stub_dlsite.calls == ["RJ01392203"]
    assert updated["RJ01392203"]["is_bonus_work"] is True
    assert updated["RJ01392203"]["has_bonus"] is False
    assert updated["RJ01392203"]["bonus_info_checked_at"]

    row = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01392203").one()
    assert bool(row.is_bonus_work) is True
    assert bool(row.has_bonus) is False
    assert row.bonus_info_checked_at is not None


@pytest.mark.asyncio
async def test_lazy_refresh_skips_already_checked_entry(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """已 check 过的条目（bonus_info_checked_at 有值）不重复触发 dlsite。"""
    fixed_time = datetime(2025, 10, 1, 12, 0, 0)
    _add_metadata_row(
        db_session,
        "RJ01577561",
        is_bonus_work=False,
        bonus_info_checked_at=fixed_time,
    )
    stub_dlsite.responses["RJ01577561"] = {"is_bonus_work": True, "has_bonus": True}

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(["RJ01577561"])

    assert stub_dlsite.calls == []
    assert updated == {}

    row = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01577561").one()
    # 不应该被 stub 的 True 覆盖
    assert bool(row.is_bonus_work) is False
    assert row.bonus_info_checked_at == fixed_time


@pytest.mark.asyncio
async def test_lazy_refresh_failure_keeps_checked_at_null(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """DLsite 抛异常的 RJ：bonus_info_checked_at 保持 NULL，下次还能再试。"""
    _add_metadata_row(db_session, "RJ09999999")
    stub_dlsite.raise_for.add("RJ09999999")

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(["RJ09999999"])

    assert stub_dlsite.calls == ["RJ09999999"]
    assert updated == {}

    row = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ09999999").one()
    assert row.bonus_info_checked_at is None
    assert bool(row.is_bonus_work) is False


@pytest.mark.asyncio
async def test_lazy_refresh_normalizes_rjcode_input(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """小写 / 带杂质前缀的 input 应该归一化后与 DB 主键对齐。"""
    _add_metadata_row(db_session, "RJ01392203")
    stub_dlsite.responses["RJ01392203"] = {"is_bonus_work": True, "has_bonus": False}

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(
        ["rj01392203", "39.RJ01392203", ""]
    )

    # 去重 + 归一化后只应该打一次
    assert stub_dlsite.calls == ["RJ01392203"]
    assert set(updated.keys()) == {"RJ01392203"}


@pytest.mark.asyncio
async def test_lazy_refresh_returns_empty_when_no_pending_rjcodes(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """没有 metadata 行 / 没有 NULL 条目时直接快返回，不调 DLsite。"""
    fixed_time = datetime(2025, 10, 1, 12, 0, 0)
    _add_metadata_row(
        db_session,
        "RJ01577561",
        bonus_info_checked_at=fixed_time,
    )

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(
        ["RJ01577561", "RJ09999999"]
    )

    assert stub_dlsite.calls == []
    assert updated == {}


@pytest.mark.asyncio
async def test_apply_dlsite_bonus_info_sets_checked_at(
    service: MetadataService,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """新建元数据走 _apply_dlsite_bonus_info 时也应该打上 bonus_info_checked_at。"""
    stub_dlsite.responses["RJ02000001"] = {"is_bonus_work": True, "has_bonus": True}
    metadata = metadata_service_module.WorkMetadata()
    metadata.rjcode = "RJ02000001"

    await service._apply_dlsite_bonus_info(metadata, "RJ02000001")

    assert metadata.is_bonus_work is True
    assert metadata.has_bonus is True
    assert metadata.bonus_info_checked_at is not None


@pytest.mark.asyncio
async def test_lazy_refresh_force_overrides_existing_checked_at(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """``force=True`` 必须忽略 bonus_info_checked_at 全量重刷。

    用户主动点"刷新选中作品"时走这条路径，专门修复历史 ``get_product_bonus_info``
    异常吞错（HTTP 失败被错误打了时间戳）导致 ``is_bonus_work=False`` 卡死的存量条目。
    """
    fixed_time = datetime(2025, 10, 1, 12, 0, 0)
    _add_metadata_row(
        db_session,
        "RJ01527756",
        is_bonus_work=False,  # 历史误写：明明是特典却被卡成 False
        bonus_info_checked_at=fixed_time,
    )
    stub_dlsite.responses["RJ01527756"] = {"is_bonus_work": True, "has_bonus": False}

    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(
        ["RJ01527756"], force=True
    )

    # ★ force=True 必须重新打 stub（不能因为时间戳已有就跳过）
    assert stub_dlsite.calls == ["RJ01527756"]
    assert updated["RJ01527756"]["is_bonus_work"] is True

    row = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01527756").one()
    assert bool(row.is_bonus_work) is True
    # 时间戳应该被刷成新的
    assert row.bonus_info_checked_at is not None
    assert row.bonus_info_checked_at != fixed_time


@pytest.mark.asyncio
async def test_lazy_refresh_force_default_false_keeps_legacy_behavior(
    service: MetadataService,
    db_session,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """``force`` 默认为 False，必须保持原有"只刷 NULL 时间戳"语义。

    避免某次粗心改动让浏览路径 / index_circle_catalog 也意外跑全量重刷。
    """
    fixed_time = datetime(2025, 10, 1, 12, 0, 0)
    _add_metadata_row(
        db_session,
        "RJ01577561",
        bonus_info_checked_at=fixed_time,
    )
    stub_dlsite.responses["RJ01577561"] = {"is_bonus_work": True, "has_bonus": True}

    # 不传 force / 默认 False
    updated = await service.lazy_refresh_bonus_for_cached_rjcodes(["RJ01577561"])

    assert stub_dlsite.calls == []
    assert updated == {}

    row = db_session.query(WorkMetadata).filter(WorkMetadata.rjcode == "RJ01577561").one()
    assert bool(row.is_bonus_work) is False
    assert row.bonus_info_checked_at == fixed_time


@pytest.mark.asyncio
async def test_apply_dlsite_bonus_info_skips_checked_at_when_dlsite_raises(
    service: MetadataService,
    stub_dlsite: _StubDlsiteService,
) -> None:
    """root cause 防御：DLsite 抛异常时 ``bonus_info_checked_at`` 必须保持 None。

    旧 ``get_product_bonus_info`` 拉空返 ``{False, False}`` 不抛异常，导致
    ``_apply_dlsite_bonus_info`` 错误打了时间戳。修复后 ``get_product_bonus_info``
    在拉空时 raise，这里测的是 except 分支不打时间戳的语义。
    """
    stub_dlsite.raise_for.add("RJ09999999")
    metadata = metadata_service_module.WorkMetadata()
    metadata.rjcode = "RJ09999999"

    await service._apply_dlsite_bonus_info(metadata, "RJ09999999")

    # 抛异常时不能打时间戳
    assert metadata.bonus_info_checked_at is None
    assert metadata.is_bonus_work is False
    assert metadata.has_bonus is False
