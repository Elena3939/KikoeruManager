"""DLsite 列表摘要解析与音声类别判定回归，不依赖已移除的 Kikoeru 直连索引。"""

import pytest

from app.core.circle_completion_service import CircleCompletionService
from app.core.dlsite_service import DLsiteApiService


def _build_listing_html(items):
    """根据 (workno, type_code, title, maker_id, maker_name) tuple 列表生成 maker_profile 风格 HTML。"""
    rows = []
    for workno, type_code, title, maker_id, maker_name in items:
        rows.append(
            f'<li class="search_result_img_box_inner"><dl>'
            f'<dt class="work_thumb">'
            f'<a href="/maniax/work/=/product_id/{workno}.html" data-product_id="{workno}">'
            f'<img src="//img.dlsite.jp/modpub/images2/work/doujin/{workno}/{workno}_img_main.jpg" alt="{title}" />'
            f"</a></dt>"
            f'<dd class="work_name"><a href="/maniax/work/=/product_id/{workno}.html" title="{title}">{title}</a></dd>'
            f'<dd class="maker_name"><a href="/maniax/circle/profile/=/maker_id/{maker_id}.html">{maker_name}</a></dd>'
            f'<dd class="work_category type_{type_code}"><a class="work_category">{type_code}</a></dd>'
            f"</dl></li>"
        )
    return "<ul>" + "".join(rows) + "</ul>"


def test_extract_summaries_parses_workno_and_chip_fields():
    service = DLsiteApiService()
    html = _build_listing_html(
        [
            ("RJ01234567", "SOU", "Test Audio", "RG10001", "Audio Circle"),
            ("RJ02345678", "MNG", "Test Manga", "RG10001", "Audio Circle"),
        ]
    )
    summaries = service._extract_summaries_from_listing_html(html)
    assert len(summaries) == 2

    by_workno = {s.workno: s for s in summaries}

    sou = by_workno["RJ01234567"]
    assert sou.work_type_code == "SOU"
    assert "type_SOU" in sou.icon_classes
    assert sou.maker_id == "RG10001"
    assert sou.maker_name == "Audio Circle"
    assert sou.title == "Test Audio"
    assert sou.is_probably_audio is True
    assert "SOU" in sou.classification_reason

    mng = by_workno["RJ02345678"]
    assert mng.work_type_code == "MNG"
    assert "type_MNG" in mng.icon_classes
    assert mng.is_probably_audio is False
    assert "MNG" in mng.classification_reason


def test_classify_listing_summary_audio_falls_back_to_none_without_chip():
    service = DLsiteApiService()
    # 缺少 work_category / type chip / icon class → 列表信号不足
    html = (
        '<li class="search_result_img_box_inner"><dl>'
        '<dt><a href="/maniax/work/=/product_id/RJ03333333.html" data-product_id="RJ03333333"></a></dt>'
        '<dd class="work_name"><a href="/maniax/work/=/product_id/RJ03333333.html">Plain Work</a></dd>'
        '<dd class="maker_name"><a href="/maniax/circle/profile/=/maker_id/RG99999.html">Plain Circle</a></dd>'
        "</dl></li>"
    )
    summaries = service._extract_summaries_from_listing_html(html)
    assert len(summaries) == 1
    plain = summaries[0]
    # is_probably_audio = None 让下游走 metadata fallback（旧行为）
    assert plain.is_probably_audio is None


@pytest.mark.asyncio
async def test_profile_listing_fills_rj_codes_missing_from_summary_cards(monkeypatch):
    service = DLsiteApiService()
    html = (
        _build_listing_html([("RJ03333333", "SOU", "Recognized", "RG99999", "Plain Circle")])
        + '<a href="/maniax/work/=/product_id/RJ04444444.html">mixed card</a>'
        + '<a href="/maniax/work/=/product_id/RJ05555555.html">unrecognized card</a>'
    )

    class Response:
        status_code = 200
        text = html

    async def fake_get(url, **_kwargs):
        if "/announce/" in url or "/page/" in url:
            return type("NotFound", (), {"status_code": 404, "text": ""})()
        return Response()

    monkeypatch.setattr(service, "_guarded_get", fake_get)

    summaries, status = await service.list_circle_work_summaries_by_maker("RG99999")

    assert status == "ok"
    assert {item.workno for item in summaries} == {
        "RJ03333333",
        "RJ04444444",
        "RJ05555555",
    }
    assert next(item for item in summaries if item.workno == "RJ03333333").is_probably_audio is True
    assert next(item for item in summaries if item.workno == "RJ04444444").is_probably_audio is None
