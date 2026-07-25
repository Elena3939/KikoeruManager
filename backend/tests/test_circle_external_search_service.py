import asyncio
from types import SimpleNamespace

import app.core.circle_external_search_service as external_search_module
from app.core.circle_external_search_service import (
    CircleExternalSearchService,
    _AnimeShareResultParser,
    _SouthPlusResultParser,
)


def test_anime_share_parser_keeps_real_rj_thread_only():
    parser = _AnimeShareResultParser()
    parser.feed(
        '<h3 class="contentRow-title"><a href="/threads/demo-rj01576821.1/">[Voice] RJ01576821</a></h3>'
        '<h3 class="contentRow-title"><a href="/threads/other.2/">Other work</a></h3>'
    )
    service = CircleExternalSearchService()
    async def fake_fetch(*args, **kwargs):
        return (
            '<h3 class="contentRow-title"><a href="/threads/demo-rj01576822.1/">'
            '[Voice] unrelated title</a></h3>'
            '<h3 class="contentRow-title"><a href="/threads/other.2/">Other work</a></h3>'
        )

    service._fetch_text = fake_fetch
    result = asyncio.run(service._search_anime_share("RJ01576821"))
    assert parser.results[0]["url"].endswith("rj01576821.1/")
    assert result["status"] == "hit"
    assert len(result["results"]) == 1


def test_south_plus_permission_page_has_no_results():
    parser = _SouthPlusResultParser()
    parser.feed('<title>用户组权限：你所属的用户组不能使用搜索功能 - 南+ South Plus</title>')
    assert parser.results == []


def test_disabled_or_unconfigured_source_keeps_search_url(monkeypatch):
    service = CircleExternalSearchService()
    monkeypatch.setattr(external_search_module, "get_config", lambda: SimpleNamespace(
        circle_external_search=SimpleNamespace(
            anime_share_enabled=False,
            south_plus_enabled=True,
            south_plus_cookie="",
        ),
    ))

    anime_share = asyncio.run(service._lookup_source("anime_share", "RJ01576821"))
    south_plus = asyncio.run(service._lookup_source("south_plus", "RJ01576821"))

    assert anime_share["status"] == "unavailable"
    assert anime_share["search_url"].startswith("https://www.anime-sharing.com/search/")
    assert south_plus["status"] == "unavailable"
    assert south_plus["search_url"].startswith("https://bbs.white-plus.net/search.php?")


def test_external_search_aggregates_variants(monkeypatch):
    service = CircleExternalSearchService()

    async def fake_lookup(source, rjcode):
        if source == "anime_share" and rjcode in {"RJ01576821", "RJ01596605"}:
            return {
                "status": "hit",
                "results": [{"url": f"https://www.anime-sharing.com/threads/{rjcode.lower()}/", "title": rjcode}],
                "search_url": f"https://www.anime-sharing.com/search/?q={rjcode}",
            }
        return {"status": "miss", "results": [], "search_url": f"https://example.test/search?q={rjcode}"}

    monkeypatch.setattr(service, "_lookup_source", fake_lookup)
    result = asyncio.run(service.search_variants({
        "RJ01576821": [
            {"rjcode": "RJ01576821", "title": "原作", "group_key": "original", "group_label": "原作"},
            {"rjcode": "RJ01596605", "title": "简中", "group_key": "simplified", "group_label": "简中"},
        ],
    }))
    entries = result["items"]["RJ01576821"]["anime_share"]["results"]
    assert len(entries) == 2
    assert {entry["variant_key"] for entry in entries} == {"original", "simplified"}


def test_external_search_keeps_miss_and_unavailable_search_actions(monkeypatch):
    service = CircleExternalSearchService()

    async def fake_lookup(source, rjcode):
        status = "miss" if source == "anime_share" else "unavailable"
        return {
            "status": status,
            "results": [],
            "search_url": service._source_search_url(source, rjcode),
        }

    monkeypatch.setattr(service, "_lookup_source", fake_lookup)
    result = asyncio.run(service.search_variants({
        "RJ01576821": [
            {"rjcode": "RJ01576821", "title": "原作", "group_key": "original", "group_label": "原作"},
            {"rjcode": "RJ01596605", "title": "简中", "group_key": "simplified", "group_label": "简中"},
        ],
    }))

    anime_share = result["items"]["RJ01576821"]["anime_share"]
    south_plus = result["items"]["RJ01576821"]["south_plus"]
    assert anime_share["status"] == "miss"
    assert south_plus["status"] == "unavailable"
    assert {entry["variant_key"] for entry in anime_share["search_results"]} == {"original", "simplified"}
    assert {entry["variant_key"] for entry in south_plus["search_results"]} == {"original", "simplified"}
    assert all(entry["url"].startswith("https://") for entry in anime_share["search_results"] + south_plus["search_results"])
