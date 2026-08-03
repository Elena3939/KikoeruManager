from types import SimpleNamespace

import pytest

from app.core import rename_service as rename_service_module
from app.core.metadata_service import MetadataService
from app.core.rename_service import RenameService


def _config(template: str, *, use_japanese_metadata: bool = False):
    return SimpleNamespace(
        rename=SimpleNamespace(
            template=template,
            use_japanese_metadata=use_japanese_metadata,
            date_format="%y%m%d",
            delimiter=" ",
            cv_list_left="(CV ",
            cv_list_right=")",
            tags_max_number=5,
            exclude_square_brackets=False,
        ),
    )


def test_compile_name_distinguishes_original_maker_and_translator(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        rename_service_module,
        "get_config",
        lambda: _config(
            "[{original_maker_name}][{translator_name}][{rjcode}]"
        ),
    )

    result = RenameService()._compile_name({
        "rjcode": "RJ01670873",
        "work_name": "怪異快楽",
        "maker_name": "生ハメ堕ち部★LACK",
        "original_maker_name": "生ハメ堕ち部★LACK",
        "translator_name": "みんなで翻訳",
    })

    assert result == "[生ハメ堕ち部★LACK][みんなで翻訳][RJ01670873]"


def test_compile_name_keeps_legacy_maker_name_as_original_maker(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        rename_service_module,
        "get_config",
        lambda: _config("[{maker_name}][{rjcode}]"),
    )

    result = RenameService()._compile_name({
        "rjcode": "RJ01670873",
        "maker_name": "错误旧值",
        "original_maker_name": "生ハメ堕ち部★LACK",
        "translator_name": "大家一起来翻译",
    })

    assert result == "[生ハメ堕ち部★LACK][RJ01670873]"


@pytest.mark.asyncio
async def test_original_maker_resolution_preserves_translator(
    monkeypatch,
) -> None:
    service = MetadataService()

    async def fake_product_info(*args, **kwargs):
        return {
            "metadata_verification_status": "verified",
            "product": {
                "maker_id": "RG64225",
                "maker_name": "生ハメ堕ち部★LACK",
            },
        }

    monkeypatch.setattr(
        service,
        "_get_product_info_for_metadata",
        fake_product_info,
    )

    fields = await service._resolve_original_maker_fields({
        "maker_id": "",
        "maker_name": "大家一起来翻译",
        "translator_name": "大家一起来翻译",
        "translation_info": {
            "is_original": False,
            "original_workno": "RJ01563471",
        },
    }, "RJ01670873")

    assert fields["maker_name"] == "生ハメ堕ち部★LACK"
    assert fields["original_maker_name"] == "生ハメ堕ち部★LACK"
    assert fields["translator_name"] == "大家一起来翻译"
