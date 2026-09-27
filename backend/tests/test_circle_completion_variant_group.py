from app.core.circle_completion_service import CircleCompletionService


def test_composite_dlsite_language_keeps_japanese_original_group():
    service = CircleCompletionService()

    assert service._normalize_lang_code("CHI_HANS,JPN") == "JPN"
    assert service._variant_group("translation", "CHI_HANS,JPN")["key"] == "original"


def test_composite_dlsite_language_keeps_chinese_group_without_japanese():
    service = CircleCompletionService()

    assert service._normalize_lang_code("CHI_HANS,CHI_HANT") == "CHI_HANS"
    assert service._variant_group("translation", "CHI_HANS,CHI_HANT")["key"] == "simplified"
