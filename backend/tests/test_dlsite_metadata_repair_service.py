from types import SimpleNamespace

import pytest

from app.core.dlsite_metadata_repair_service import (
    DLsiteMetadataRepairService,
    RepairCandidate,
)


class FakeDLsite:
    def __init__(self, payload):
        self.payload = payload
        self.invalidated = []

    def invalidate_rj_graph_cache(self, rjcode):
        self.invalidated.append(rjcode)

    async def get_product_info(self, rjcode, refresh=False):
        assert refresh is True
        return self.payload


class FakeDLsiteByRJ:
    def __init__(self, payloads):
        self.payloads = payloads
        self.invalidated = []

    def invalidate_rj_graph_cache(self, rjcode):
        self.invalidated.append(rjcode)

    async def get_product_info(self, rjcode, refresh=False):
        assert refresh is True
        return self.payloads.get(rjcode)


class FakeManager:
    def get_library_definition(self, library_id):
        return SimpleNamespace(id=library_id, root_path="D:\\library")


@pytest.mark.asyncio
async def test_repair_plan_rejects_unverified_placeholder_metadata():
    dlsite = FakeDLsite(
        {
            "product": {"workno": "RJ01619669", "maker_name": "みんなで翻訳"},
            "metadata_verification_status": "unverified",
            "metadata_verification_reason": "社团名是翻译占位名",
            "metadata_evidence_source": "page_metadata_unverified",
        }
    )
    service = DLsiteMetadataRepairService(dlsite=dlsite, manager=FakeManager())

    plan = await service.build_plan(RepairCandidate(rjcode="RJ01619669"))

    assert plan["status"] == "skipped"
    assert plan["evidence_status"] == "unverified"
    assert dlsite.invalidated == ["RJ01619669"]


@pytest.mark.asyncio
async def test_repair_plan_builds_verified_inventory_target(monkeypatch):
    dlsite = FakeDLsite(
        {
            "product": {
                "workno": "RJ01619669",
                "work_name": "作品名",
                "maker_name": "原作社团",
                "maker_id": "RG12345",
            },
            "metadata_verification_status": "verified",
            "metadata_evidence_source": "language_editions",
        }
    )
    service = DLsiteMetadataRepairService(dlsite=dlsite, manager=FakeManager())
    monkeypatch.setattr(service, "_build_api_rename_name", lambda *_args: "[原作社团][RJ01619669]")
    monkeypatch.setattr("os.path.exists", lambda _path: False)

    plan = await service.build_plan(
        RepairCandidate(
            rjcode="RJ01619669",
            library_id="default-local",
            old_path="/library/みんなで翻訳/[みんなで翻訳][RJ01619669]",
        )
    )

    assert plan["status"] == "ready"
    assert plan["new_maker_name"] == "原作社团"
    assert plan["new_path"].replace("\\", "/") == "D:/library/原作社团/[原作社团][RJ01619669]"
    assert plan["filesystem_action"] == "rename_and_move"


@pytest.mark.asyncio
async def test_metadata_only_plan_does_not_resolve_inventory_library():
    dlsite = FakeDLsite(
        {
            "product": {
                "workno": "RJ01619669",
                "work_name": "作品名",
                "maker_name": "原作社团",
            },
            "metadata_verification_status": "verified",
            "metadata_evidence_source": "language_editions",
        }
    )

    class RejectingManager:
        def get_library_definition(self, _library_id):
            raise AssertionError("metadata-only 不应读取库存配置")

    service = DLsiteMetadataRepairService(dlsite=dlsite, manager=RejectingManager())
    plan = await service.build_plan(
        RepairCandidate(
            rjcode="RJ01619669",
            library_id="default-local",
            old_path="/library/みんなで翻訳/[みんなで翻訳][RJ01619669]",
        ),
        include_filesystem=False,
    )

    assert plan["status"] == "ready"
    assert plan["filesystem_action"] == "metadata_only"
    assert plan["new_path"] == ""


@pytest.mark.asyncio
async def test_repair_plan_uses_verified_original_maker_for_translation():
    dlsite = FakeDLsiteByRJ(
        {
            "RJ01482856": {
                "product": {
                    "workno": "RJ01482856",
                    "work_name": "简体中文版",
                    "maker_id": "RG60289",
                    "maker_name": "みんなで翻訳",
                    "translation_info": {
                        "is_original": False,
                        "original_workno": "RJ01464840",
                    },
                },
                "metadata_verification_status": "unverified",
                "metadata_verification_reason": "社团名是翻译占位名: みんなで翻訳",
                "metadata_evidence_source": "dlsite_product",
            },
            "RJ01464840": {
                "product": {
                    "workno": "RJ01464840",
                    "maker_id": "RG12345",
                    "maker_name": "原作社团",
                },
                "metadata_verification_status": "verified",
                "metadata_evidence_source": "dlsite_product",
            },
        }
    )
    service = DLsiteMetadataRepairService(dlsite=dlsite, manager=FakeManager())

    plan = await service.build_plan(
        RepairCandidate(
            rjcode="RJ01482856",
            old_maker_name="みんなで翻訳",
        ),
        include_filesystem=False,
    )

    assert plan["status"] == "ready"
    assert plan["new_maker_name"] == "原作社团"
    assert plan["metadata"]["maker_id"] == "RG12345"
    assert plan["metadata"]["maker_name"] == "原作社团"
    assert plan["evidence_status"] == "verified"
