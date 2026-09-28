from app.core.email_watcher_service import _subject_matches_filter


def test_legacy_new_release_filter_accepts_dlsite_localized_subjects():
    assert _subject_matches_filter("【DLsite】「B-bishop」新作已開始販售！", "新着作品")
    assert _subject_matches_filter("【DLsite】「B-bishop」から新着作品が販売開始されました！", "新着作品")
    assert not _subject_matches_filter("【DLsite】優惠活動已開始！", "新着作品")
    assert not _subject_matches_filter("其他郵件新作已開始販售！", "新着作品")


def test_custom_subject_filter_remains_literal():
    assert not _subject_matches_filter("【DLsite】「B-bishop」新作已開始販售！", "特定社团")
