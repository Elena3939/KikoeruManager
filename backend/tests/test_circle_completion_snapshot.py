"""社团补全 - Phase 1 / Phase 2 重构后的 snapshot 数据流回归测试。

bug 现场（重构前）：
- ASMR.one 检查阶段把 9 个 bucket 串行 probe 各 3 个 RJ，semaphore=10 上限；
- Kikoeru 拥有态补查阶段同上；
- 总共 ~50-100 次零散 HTTP，4 分钟左右才能跑完中等规模社团。

重构后流程：
1. ``_collect_external_snapshot`` 一次性批量拉所有外部数据，写入 snapshot；
2. ``_find_public_downloadable_work(snapshot=...)`` 路径全本地查询，不再触网。

这套测试只覆盖**新加 dataclass + Phase 2 路径不打 HTTP** 这两个最核心
不变量，避免 ``_collect_external_snapshot`` 内部依赖太多服务（DLsite /
ASMR.one / Kikoeru）导致测试需要 mock 一大片网络调用。

只要 ``CircleCompletionSnapshot`` 的查询接口和 ``snapshot is not None``
分支稳定，重构就不会回退到老路径。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app.core.circle_completion_service import (
    CircleCompletionService,
    CircleCompletionSnapshot,
)


# ============ CircleCompletionSnapshot 查询接口 ============


def test_snapshot_default_values_are_empty() -> None:
    snapshot = CircleCompletionSnapshot()
    assert snapshot.candidate_rjcodes == []
    assert snapshot.all_rjcodes == []
    assert snapshot.asmr_work_info_by_rj == {}
    assert snapshot.asmr_tracks_by_rj == {}
    # 新增字段：作品链路去重信息
    assert snapshot.canonical_rj_by_rj == {}
    assert snapshot.chain_rjs_by_canonical == {}
    # P2 新增：canonical -> canonical_info（含 link_map），用于 wave 2a 按 link_map 选 preferred
    assert snapshot.canonical_info_by_canonical == {}
    assert snapshot.get_canonical_rj("RJ111") is None
    assert snapshot.get_chain_rjs("RJ111") == []


def test_snapshot_canonical_query_normalizes_case() -> None:
    """``get_canonical_rj`` / ``get_chain_rjs`` 也得做大小写 normalize。"""
    snapshot = CircleCompletionSnapshot()
    snapshot.canonical_rj_by_rj = {"RJ111": "RJ100", "RJ112": "RJ100", "RJ100": "RJ100"}
    snapshot.chain_rjs_by_canonical = {"RJ100": ["RJ100", "RJ111", "RJ112"]}

    assert snapshot.get_canonical_rj("rj111") == "RJ100"
    assert snapshot.get_canonical_rj("Rj112") == "RJ100"
    assert snapshot.get_canonical_rj("RJ_NOT_EXIST") is None

    assert snapshot.get_chain_rjs("rj100") == ["RJ100", "RJ111", "RJ112"]
    # 返回的是 copy，外部修改不应影响 snapshot 内部状态
    chain = snapshot.get_chain_rjs("RJ100")
    chain.append("RJ999")
    assert snapshot.chain_rjs_by_canonical["RJ100"] == ["RJ100", "RJ111", "RJ112"]


def test_snapshot_contains_asmr_requires_both_work_info_and_tracks() -> None:
    """``contains_asmr`` 必须 work_info + tracks 同时非空才算可下载。"""
    snapshot = CircleCompletionSnapshot()
    snapshot.asmr_work_info_by_rj = {
        "RJ111": {"id": 111, "title": "T1"},  # work_info OK
        "RJ222": {"id": 222, "title": "T2"},
        "RJ333": None,  # work_info 缺失
    }
    snapshot.asmr_tracks_by_rj = {
        "RJ111": [{"file": "a.mp3"}],  # tracks OK
        "RJ222": None,  # tracks 缺失
        "RJ333": [{"file": "b.mp3"}],  # 即便 tracks 有，work_info 缺也不算
    }
    assert snapshot.contains_asmr("RJ111") is True
    assert snapshot.contains_asmr("RJ222") is False
    assert snapshot.contains_asmr("RJ333") is False
    assert snapshot.contains_asmr("RJ_NOT_EXIST") is False


def test_snapshot_query_normalizes_rj_case() -> None:
    """传 rj111 / Rj111 / RJ111 都应该命中同一条数据，避免下游忘了 normalize。"""
    snapshot = CircleCompletionSnapshot()
    snapshot.asmr_work_info_by_rj["RJ111"] = {"id": 111}
    snapshot.asmr_tracks_by_rj["RJ111"] = [{"file": "a.mp3"}]

    assert snapshot.get_asmr_work_info("rj111") == {"id": 111}
    assert snapshot.get_asmr_work_info("Rj111") == {"id": 111}
    assert snapshot.get_asmr_work_info("RJ111") == {"id": 111}
    assert snapshot.contains_asmr("rj111") is True
    assert snapshot.get_asmr_tracks("rj111") == [{"file": "a.mp3"}]


def test_snapshot_query_handles_none_and_empty_input() -> None:
    snapshot = CircleCompletionSnapshot()
    assert snapshot.get_asmr_work_info("") is None
    assert snapshot.get_asmr_work_info(None) is None  # type: ignore[arg-type]
    assert snapshot.get_asmr_tracks("") is None
    assert snapshot.contains_asmr("") is False


# ============ _find_public_downloadable_work 走 snapshot 不打 HTTP ============


class _RecordingASMRService:
    """记录所有 fetch_* 调用次数；snapshot 路径不应该触发任何调用。"""

    def __init__(self) -> None:
        self.fetch_work_info_calls: List[str] = []
        self.fetch_track_list_calls: List[str] = []

    async def fetch_work_info(self, rj: str) -> Optional[Dict[str, Any]]:
        self.fetch_work_info_calls.append(rj)
        return None

    async def fetch_track_list(self, rj: str) -> Optional[List[Any]]:
        self.fetch_track_list_calls.append(rj)
        return None


@pytest.fixture
def service_with_recording_asmr(monkeypatch: pytest.MonkeyPatch) -> tuple[
    CircleCompletionService, _RecordingASMRService
]:
    """构造 service + 替换 asmr_service 为记录调用次数的 stub。"""
    service = CircleCompletionService()
    recording = _RecordingASMRService()
    service.asmr_service = recording  # type: ignore[assignment]

    # 让 _build_public_download_probe_candidates 不依赖 _is_public_catalog_variant
    # 真实判断（它会调 DLsite HTTP）；直接返回输入候选作为 probe 列表
    async def _stub_build_probe(
        canonical_info: Dict[str, Any],
        fallback_rjcode: str,
        metadata_map: Optional[Dict[str, Any]] = None,
        extra_candidates: Optional[List[Any]] = None,
    ) -> List[str]:
        candidates: List[str] = []
        for rj in canonical_info.get("linked_rjcodes") or []:
            normalized = service.normalize_rjcode(rj)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        return candidates

    monkeypatch.setattr(service, "_build_public_download_probe_candidates", _stub_build_probe)
    return service, recording


@pytest.mark.asyncio
async def test_find_public_downloadable_work_with_snapshot_does_not_call_asmr_service(
    service_with_recording_asmr: tuple[CircleCompletionService, _RecordingASMRService],
) -> None:
    """传 snapshot 时绝不能调 asmr_service.fetch_work_info / fetch_track_list。"""
    service, recording = service_with_recording_asmr

    # 清掉 _asmr_probe_cache 避免命中老缓存掩盖问题
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    snapshot = CircleCompletionSnapshot()
    snapshot.asmr_work_info_by_rj = {"RJ111": {"id": 111, "title": "T"}}
    snapshot.asmr_tracks_by_rj = {"RJ111": [{"file": "a.mp3"}]}

    canonical_info = {"canonical_rjcode": "RJ111", "linked_rjcodes": ["RJ111"]}
    actual_rj, work_info = await service._find_public_downloadable_work(
        canonical_info,
        "RJ111",
        snapshot=snapshot,
    )
    assert actual_rj == "RJ111"
    assert work_info == {"id": 111, "title": "T"}
    # ★ 关键不变量：snapshot 路径绝不应该触发 asmr_service 调用
    assert recording.fetch_work_info_calls == []
    assert recording.fetch_track_list_calls == []


@pytest.mark.asyncio
async def test_find_public_downloadable_work_without_snapshot_falls_back_to_http(
    service_with_recording_asmr: tuple[CircleCompletionService, _RecordingASMRService],
) -> None:
    """老调用点不传 snapshot 时，必须走原 HTTP 路径，保证向后兼容。"""
    service, recording = service_with_recording_asmr
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    canonical_info = {"canonical_rjcode": "RJ222", "linked_rjcodes": ["RJ222"]}
    actual_rj, work_info = await service._find_public_downloadable_work(
        canonical_info,
        "RJ222",
        # snapshot 缺省
    )
    assert actual_rj == ""  # _RecordingASMRService 始终返 None
    assert work_info is None
    # ★ 不传 snapshot 时必须真的调 HTTP（这里是 stub）
    assert recording.fetch_work_info_calls == ["RJ222"]


@pytest.mark.asyncio
async def test_find_public_downloadable_work_skips_rj_missing_from_snapshot(
    service_with_recording_asmr: tuple[CircleCompletionService, _RecordingASMRService],
) -> None:
    """snapshot 没收到的 RJ（fetch 失败 / 不存在），在 snapshot 路径下应跳过而不是回退到 HTTP。"""
    service, recording = service_with_recording_asmr
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    snapshot = CircleCompletionSnapshot()
    # snapshot 里只有 RJ111 有数据，RJ222 / RJ333 都没收到
    snapshot.asmr_work_info_by_rj = {"RJ111": None, "RJ222": None, "RJ333": {"id": 333}}
    snapshot.asmr_tracks_by_rj = {"RJ111": None, "RJ222": None, "RJ333": [{"file": "z.mp3"}]}

    canonical_info = {
        "canonical_rjcode": "RJ111",
        "linked_rjcodes": ["RJ111", "RJ222", "RJ333"],
    }
    actual_rj, work_info = await service._find_public_downloadable_work(
        canonical_info,
        "RJ111",
        snapshot=snapshot,
    )
    # 第三个 RJ333 才命中
    assert actual_rj == "RJ333"
    assert work_info == {"id": 333}
    # 仍然不应该调 asmr_service
    assert recording.fetch_work_info_calls == []
    assert recording.fetch_track_list_calls == []


# ============ _collect_external_snapshot 按 canonical 链路去重 Kikoeru ============


@pytest.mark.asyncio
async def test_collect_external_snapshot_dedupes_kikoeru_probes_by_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**性能 / 正确性双约束**：snapshot 收集阶段对 Kikoeru 必须按作品链路 canonical 去重。

    场景：4 个候选 RJ 分布在 2 条作品链路里：
      - 链路 A：canonical=RJ001，含 RJ001 / RJ002（原版 + 翻译版）
      - 链路 B：canonical=RJ100，含 RJ100 / RJ101 / RJ102（原版 + 2 个翻译版）

    旧实现会对全 ``all_rjcodes`` 共 5 个 RJ 各调一次 ``_probe_kikoeru_state``；
    新实现只对 2 个 canonical 调，结果回灌给链上所有 RJ 的 cache。
    """
    service = CircleCompletionService()
    service._kikoeru_state_cache.clear()
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    # 模拟 DLsite：每个候选 RJ 的 canonical 链路
    canonical_table: Dict[str, Dict[str, Any]] = {
        "RJ001": {"canonical_rjcode": "RJ001", "linked_rjcodes": ["RJ001", "RJ002"]},
        "RJ002": {"canonical_rjcode": "RJ001", "linked_rjcodes": ["RJ001", "RJ002"]},
        "RJ100": {"canonical_rjcode": "RJ100", "linked_rjcodes": ["RJ100", "RJ101", "RJ102"]},
        "RJ101": {"canonical_rjcode": "RJ100", "linked_rjcodes": ["RJ100", "RJ101", "RJ102"]},
    }

    async def fake_metadata(rj: str) -> Dict[str, Any]:
        return {"rjcode": rj}

    async def fake_resolve_canonical(rj: str, refresh: bool = False) -> Dict[str, Any]:
        return canonical_table.get(rj, {})

    monkeypatch.setattr(service, "_fetch_metadata_dict", fake_metadata)
    monkeypatch.setattr(service, "resolve_canonical_rj", fake_resolve_canonical)

    # 替换 asmr_service：测试焦点是 Kikoeru，ASMR 路径只保证不爆炸
    class _NoOpASMR:
        async def fetch_work_info(self, rj: str) -> None:
            return None

        async def fetch_track_list(self, rj: str) -> None:
            return None

    service.asmr_service = _NoOpASMR()  # type: ignore[assignment]

    # 关键 stub：记录 _probe_kikoeru_state 调用次数 + 调用的 RJ
    probe_calls: List[str] = []

    async def fake_probe_state(rj: str, *, use_cache: bool = True) -> Dict[str, Any]:
        probe_calls.append(rj)
        # 链路 A 在 Kikoeru 命中、链路 B 未命中——状态各异，方便核对回灌
        if rj == "RJ001":
            return {"has_kikoeru": True, "found_rjcodes": ["RJ001"], "subtitle_rjcodes": []}
        if rj == "RJ100":
            return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}
        # 其他 RJ 不应该被 probe（因为新流程按 canonical 去重）
        raise AssertionError(f"unexpected probe call: {rj}")

    monkeypatch.setattr(service, "_probe_kikoeru_state", fake_probe_state)

    snapshot = await service._collect_external_snapshot(
        ["RJ001", "RJ002", "RJ100", "RJ101"],
    )

    # ---- 性能不变量：probe 只跑了 2 次（canonical 数），不是 5 次（all_rjcodes 数）
    assert sorted(probe_calls) == ["RJ001", "RJ100"], (
        f"应只对 canonical 各 probe 一次,实际调用 RJ：{probe_calls}"
    )

    # ---- 链路映射正确
    assert snapshot.candidate_rjcodes == ["RJ001", "RJ002", "RJ100", "RJ101"]
    assert snapshot.canonical_rj_by_rj["RJ001"] == "RJ001"
    assert snapshot.canonical_rj_by_rj["RJ002"] == "RJ001"
    assert snapshot.canonical_rj_by_rj["RJ100"] == "RJ100"
    assert snapshot.canonical_rj_by_rj["RJ101"] == "RJ100"
    # 链上 RJ102 没出现在 candidates，但应该出现在链路全集 / canonical 映射里
    assert snapshot.canonical_rj_by_rj["RJ102"] == "RJ100"
    assert sorted(snapshot.chain_rjs_by_canonical["RJ001"]) == ["RJ001", "RJ002"]
    assert sorted(snapshot.chain_rjs_by_canonical["RJ100"]) == ["RJ100", "RJ101", "RJ102"]
    # all_rjcodes 是所有链路的并集
    assert sorted(snapshot.all_rjcodes) == ["RJ001", "RJ002", "RJ100", "RJ101", "RJ102"]

    # ---- 关键正确性：链上每个 RJ 都被回灌了同一份 state
    state_a = service._kikoeru_state_cache.get("RJ001")
    assert state_a is not None and state_a["has_kikoeru"] is True
    for rj in ("RJ001", "RJ002"):
        cached = service._kikoeru_state_cache.get(rj)
        assert cached is state_a, f"链路 A 上 {rj} 的 cache 必须复用同一份 state"

    state_b = service._kikoeru_state_cache.get("RJ100")
    assert state_b is not None and state_b["has_kikoeru"] is False
    for rj in ("RJ100", "RJ101", "RJ102"):
        cached = service._kikoeru_state_cache.get(rj)
        assert cached is state_b, f"链路 B 上 {rj} 的 cache 必须复用同一份 state"


@pytest.mark.asyncio
async def test_collect_external_snapshot_fallbacks_when_canonical_resolution_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resolve_canonical_rj`` 抛错时必须 fallback 把 rj 自己当独立链路 canonical，
    不能漏掉任何候选作品。"""
    service = CircleCompletionService()
    service._kikoeru_state_cache.clear()
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    async def fake_metadata(rj: str) -> Dict[str, Any]:
        return {}

    async def failing_canonical(rj: str, refresh: bool = False) -> Dict[str, Any]:
        raise RuntimeError(f"network error for {rj}")

    monkeypatch.setattr(service, "_fetch_metadata_dict", fake_metadata)
    monkeypatch.setattr(service, "resolve_canonical_rj", failing_canonical)

    class _NoOpASMR:
        async def fetch_work_info(self, rj: str) -> None:
            return None

        async def fetch_track_list(self, rj: str) -> None:
            return None

    service.asmr_service = _NoOpASMR()  # type: ignore[assignment]

    probe_calls: List[str] = []

    async def fake_probe_state(rj: str, *, use_cache: bool = True) -> Dict[str, Any]:
        probe_calls.append(rj)
        return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

    monkeypatch.setattr(service, "_probe_kikoeru_state", fake_probe_state)

    snapshot = await service._collect_external_snapshot(["RJ001", "RJ002"])

    # canonical 失败时每个 rj 自成一条独立链路，仍然各 probe 一次（不会漏作品）
    assert sorted(probe_calls) == ["RJ001", "RJ002"]
    assert sorted(snapshot.all_rjcodes) == ["RJ001", "RJ002"]
    assert snapshot.canonical_rj_by_rj == {"RJ001": "RJ001", "RJ002": "RJ002"}
    assert sorted(snapshot.chain_rjs_by_canonical.keys()) == ["RJ001", "RJ002"]


@pytest.mark.asyncio
async def test_collect_external_snapshot_progress_uses_business_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """进度回调文案应使用业务化语言（"在 ASMR.one 上核对作品"等），
    避免出现旧的"收集 ASMR.one 数据"这类内部用语。"""
    service = CircleCompletionService()
    service._kikoeru_state_cache.clear()

    async def fake_metadata(rj: str) -> Dict[str, Any]:
        return {}

    async def fake_canonical(rj: str, refresh: bool = False) -> Dict[str, Any]:
        return {"canonical_rjcode": rj, "linked_rjcodes": [rj]}

    monkeypatch.setattr(service, "_fetch_metadata_dict", fake_metadata)
    monkeypatch.setattr(service, "resolve_canonical_rj", fake_canonical)

    class _NoOpASMR:
        async def fetch_work_info(self, rj: str) -> None:
            return None

        async def fetch_track_list(self, rj: str) -> None:
            return None

    service.asmr_service = _NoOpASMR()  # type: ignore[assignment]

    async def fake_probe_state(rj: str, *, use_cache: bool = True) -> Dict[str, Any]:
        return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

    monkeypatch.setattr(service, "_probe_kikoeru_state", fake_probe_state)

    progress_steps: List[str] = []

    def on_progress(pct: int, step: str) -> None:
        progress_steps.append(step)

    await service._collect_external_snapshot(
        ["RJ001"],
        progress_callback=on_progress,
    )

    joined = "\n".join(progress_steps)
    # 关键业务词
    assert "DLsite 作品关联链" in joined
    assert "ASMR.one" in joined
    assert "Kikoeru" in joined
    assert "作品链路" in joined
    # 不应再出现纯内部用语
    assert "收集 ASMR.one 数据" not in joined
    assert "收集 Kikoeru 数据" not in joined
    assert "展开 RJ 全集" not in joined


# ============ P2: Wave 2a 按 canonical 链路 + preferred 优先 + 命中即停 ============


@pytest.mark.asyncio
async def test_collect_external_snapshot_asmr_chain_probe_stops_on_first_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """链路上 preferred（简中翻译版）首次命中 ASMR.one 后必须立即停止，
    不再对原作 / 其他翻译版打 ``fetch_work_info``。

    这是 P2 优化的核心收益：把 wave 2a 的 ASMR.one HTTP 调用从"链上 N 条全量"
    压到"1 条命中即停"，单社团 70-80% 的 ASMR.one HTTP 调用直接消失。
    """
    service = CircleCompletionService()
    service._kikoeru_state_cache.clear()
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    # canonical=RJ100 (日文原作), 链上还有 RJ101 (简中)、RJ102 (繁中)
    # link_map 让 _sort_linked_variants 把 RJ101 (简中翻译) 排在最前面
    canonical_info = {
        "canonical_rjcode": "RJ100",
        "linked_rjcodes": ["RJ100", "RJ101", "RJ102"],
        "link_map": {
            "RJ100": {"link_type": "original", "lang": "JPN"},
            "RJ101": {"link_type": "translation", "lang": "CHI_HANS"},
            "RJ102": {"link_type": "translation", "lang": "CHI_HANT"},
        },
    }

    async def fake_canonical(rj: str, refresh: bool = False) -> Dict[str, Any]:
        return canonical_info

    monkeypatch.setattr(service, "resolve_canonical_rj", fake_canonical)

    # 模拟 ASMR.one：RJ101（简中 preferred）命中、其他 RJ 也都有数据
    asmr_calls: List[str] = []

    class _PreferredHitASMR:
        async def fetch_work_info(self, rj: str) -> Optional[Dict[str, Any]]:
            asmr_calls.append(f"work_info:{rj}")
            return {"id": int(rj[2:]), "title": f"T-{rj}"}

        async def fetch_track_list(self, rj: str) -> Optional[List[Any]]:
            asmr_calls.append(f"tracks:{rj}")
            return [{"file": f"{rj}.mp3"}]

    service.asmr_service = _PreferredHitASMR()  # type: ignore[assignment]

    # Kikoeru stub：保证 wave 2b 不爆
    async def fake_probe_state(rj: str, *, use_cache: bool = True) -> Dict[str, Any]:
        return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

    monkeypatch.setattr(service, "_probe_kikoeru_state", fake_probe_state)

    snapshot = await service._collect_external_snapshot(["RJ100"])

    # ★ 关键正确性：preferred=RJ101 优先探，命中即停，原作 / 繁中不再打 ASMR.one
    assert "work_info:RJ101" in asmr_calls
    assert "tracks:RJ101" in asmr_calls
    # 链上其他 RJ 应该没有 fetch_work_info 调用
    assert "work_info:RJ100" not in asmr_calls
    assert "work_info:RJ102" not in asmr_calls

    # snapshot 里 RJ101 有数据；其他链上 RJ 是 None 占位
    assert snapshot.asmr_work_info_by_rj["RJ101"] == {"id": 101, "title": "T-RJ101"}
    assert snapshot.asmr_tracks_by_rj["RJ101"] == [{"file": "RJ101.mp3"}]
    assert snapshot.asmr_work_info_by_rj.get("RJ100") is None
    assert snapshot.asmr_work_info_by_rj.get("RJ102") is None

    # snapshot.canonical_info_by_canonical 必须被填充
    assert snapshot.canonical_info_by_canonical["RJ100"]["link_map"]["RJ101"]["lang"] == "CHI_HANS"


@pytest.mark.asyncio
async def test_collect_external_snapshot_asmr_chain_probe_falls_back_to_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """preferred 在 ASMR.one miss 时按链上次序 fallback 探到原作 / 其他翻译版，
    全 miss 时链上每个 RJ 都标 None。"""
    service = CircleCompletionService()
    service._kikoeru_state_cache.clear()
    service._asmr_probe_cache.clear()  # type: ignore[attr-defined]

    canonical_info = {
        "canonical_rjcode": "RJ200",
        "linked_rjcodes": ["RJ200", "RJ201"],
        "link_map": {
            "RJ200": {"link_type": "original", "lang": "JPN"},
            "RJ201": {"link_type": "translation", "lang": "CHI_HANS"},
        },
    }

    async def fake_canonical(rj: str, refresh: bool = False) -> Dict[str, Any]:
        return canonical_info

    monkeypatch.setattr(service, "resolve_canonical_rj", fake_canonical)

    asmr_calls: List[str] = []

    class _OriginalHitASMR:
        """简中（preferred）miss、原作命中——典型场景：DLsite 上有简中翻译但
        ASMR.one 只收录原作。"""

        async def fetch_work_info(self, rj: str) -> Optional[Dict[str, Any]]:
            asmr_calls.append(f"work_info:{rj}")
            if rj == "RJ200":
                return {"id": 200, "title": "Original"}
            return None  # RJ201 简中 miss

        async def fetch_track_list(self, rj: str) -> Optional[List[Any]]:
            asmr_calls.append(f"tracks:{rj}")
            return [{"file": f"{rj}.mp3"}] if rj == "RJ200" else None

    service.asmr_service = _OriginalHitASMR()  # type: ignore[assignment]

    async def fake_probe_state(rj: str, *, use_cache: bool = True) -> Dict[str, Any]:
        return {"has_kikoeru": False, "found_rjcodes": [], "subtitle_rjcodes": []}

    monkeypatch.setattr(service, "_probe_kikoeru_state", fake_probe_state)

    snapshot = await service._collect_external_snapshot(["RJ200"])

    # 简中 RJ201 排第一被探，miss 后 fallback 到原作 RJ200，命中即停
    assert "work_info:RJ201" in asmr_calls
    assert "work_info:RJ200" in asmr_calls
    # tracks 只对 work_info 命中的 RJ 拉
    assert "tracks:RJ201" not in asmr_calls
    assert "tracks:RJ200" in asmr_calls

    # snapshot 写入：RJ200 有 work_info+tracks；RJ201 work_info 是 None
    assert snapshot.asmr_work_info_by_rj["RJ200"] == {"id": 200, "title": "Original"}
    assert snapshot.asmr_tracks_by_rj["RJ200"] == [{"file": "RJ200.mp3"}]
    assert snapshot.asmr_work_info_by_rj.get("RJ201") is None
    assert snapshot.contains_asmr("RJ200") is True
    assert snapshot.contains_asmr("RJ201") is False
