"""卡片与列表共用的服务端特典展示契约。"""
from app.core.circle_completion_presentation import present_bonus_works, present_completion_rows
from app.core.circle_completion_service import CircleCompletionService


def bonus(code, title='共通特典', **kwargs):
    return dict(canonical_rjcode=code, display_rjcode=code, title=title, is_bonus_work=True, **kwargs)


def test_same_title_preserves_independent_members_and_business_labels():
    rows = [bonus('RJ01699067', owned=True), bonus('RJ01699068', has_downloadable_source=True)]
    parent = dict(bonus_works=rows)
    present_completion_rows(CircleCompletionService(), [parent])
    assert parent['bonus_works'] == rows
    displayed = parent['bonus_display_works']
    assert len(displayed) == 1
    assert [item['canonical_rjcode'] for item in displayed[0]['_bonus_members']] == ['RJ01699067', 'RJ01699068']
    assert displayed[0]['bonus_owned_label'] == '已收录'
    assert displayed[0]['bonus_download_label'] == '可下载'


def test_confirmed_cover_wins_and_numbered_noise_is_removed():
    rows = [bonus('RJ01699067', '特典'), bonus('RJ01699068', '特典_1', cover_confirmed_available=True),
            bonus('RJ01699069', '特典_2', cover_confirmed_missing=True)]
    displayed = present_bonus_works(CircleCompletionService(), rows)
    assert [item['canonical_rjcode'] for item in displayed] == ['RJ01699068']


def test_short_bonus_theme_removes_embedded_long_variants():
    rows = [bonus('RJ01699067', '415大特典'), bonus('RJ01699068', '【長い原作タイトル】415大特典'),
            bonus('RJ01699069', '別の特典')]
    displayed = present_bonus_works(CircleCompletionService(), rows)
    assert [item['canonical_rjcode'] for item in displayed] == ['RJ01699067', 'RJ01699069']


def test_title_plan_reused_but_resource_labels_and_members_are_current():
    from app.core.circle_completion_presentation import _bonus_title_groups
    _bonus_title_groups.cache_clear()
    service = CircleCompletionService()
    rows = [bonus('RJ01699067'), bonus('RJ01699068')]
    first = present_bonus_works(service, rows)
    hits = _bonus_title_groups.cache_info().hits
    updated = [dict(item, has_downloadable_source=True) for item in rows]
    second = present_bonus_works(service, updated)
    assert _bonus_title_groups.cache_info().hits == hits + 1
    assert first[0]['bonus_download_label'] == '无源'
    assert second[0]['bonus_download_label'] == '可下载'
    assert second[0]['_bonus_members'][0] is updated[0]
    renamed = [dict(updated[0], title='新的特典标题'), updated[1]]
    assert len(present_bonus_works(service, renamed)) == 2
