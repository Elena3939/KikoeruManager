"""DLsite 列表层 summary + known_kikoeru_index 回归测试。

覆盖：

- ``_extract_summaries_from_listing_html``：能从 maker_profile 风格 HTML 解析 workno /
  maker_id / maker_name / title / work_type_code / icon_classes / category_label。
- ``_classify_listing_summary_audio``：SOU 类目正确判 True；MNG/GAM/VOC 类目正确判 False；
  缺少 chip 时回退 ``None`` 走 metadata 链路。
- ``_build_known_kikoeru_index``：把 kikoeru 直连 works 列表展开成 ``{RJ → state}`` 字典，
  state 结构（``has_kikoeru`` / ``found_rjcodes`` / ``subtitle_rjcodes`` / ``found_titles``）
  与 ``_probe_kikoeru_state`` 兼容，让 ``_collect_external_snapshot`` 的 Wave 2b 短路逻辑稳定。

这些用例之前没有覆盖，但都是 P1 / P3 优化路径的关键契约。任何破坏 chip 分类或
known index 字段名 / 类型的回归都会让"列表 chip 短路 metadata"和"直连命中跳过 probe"
两条性能路径静默退化，**没有这些测试很难发现**——因此必须保留。
"""

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


def test_build_known_kikoeru_index_returns_compatible_state_payload():
    service = CircleCompletionService()
    works = [
        {"id": 101, "title": "直连作品 A", "rjcode": "RJ01234567"},
        {"id": 202, "title": "直连作品 B", "rjcode": "RJ02222222"},
        {"id": 303, "title": "未提供 RJ 的作品"},
    ]
    index = service._build_known_kikoeru_index(works)
    # 至少包含两条显式 RJ 的命中
    assert "RJ01234567" in index
    assert "RJ02222222" in index

    a = index["RJ01234567"]
    assert a["has_kikoeru"] is True
    assert "RJ01234567" in a["found_rjcodes"]
    # ``subtitle_rjcodes`` 必须存在且为 list（即使为空），保证下游 dict.get 不抛
    assert isinstance(a.get("subtitle_rjcodes"), list)
    assert a["found_titles"].get("RJ01234567") == "直连作品 A"
    assert a["work_id"] == 101
    assert a["source"] == "kikoeru_circle_works"
