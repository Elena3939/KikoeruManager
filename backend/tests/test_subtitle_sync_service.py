# -*- coding: utf-8 -*-
"""字幕同步轨道号提取与匹配逻辑测试。"""

import os

from app.core.subtitle_sync_service import SubtitleSyncService


def _subtitle(num, title):
    base = f"{num} {title}"
    return {
        "name": base + ".lrc",
        "path": os.path.join("subs", base + ".lrc"),
        "ext": ".lrc",
        "base_name": base,
    }


def test_extract_track_number_supported_formats():
    service = SubtitleSyncService()
    assert service._extract_track_number("01 开场") == 1
    assert service._extract_track_number("Track01") == 1
    assert service._extract_track_number("track_02") == 2
    assert service._extract_track_number("Tr3") == 3
    assert service._extract_track_number("トラック11") == 11
    assert service._extract_track_number("s114_55_おまけトラック11／标题") == 55
    assert service._extract_track_number("s114_01_トラック1／标题") == 1
    assert service._extract_track_number("RJ01626948 标题") is None


def test_match_audio_subtitle_uses_dlsite_global_track_number():
    """s114_NN 全局轨道号应优先于 トラックN 与字幕全局编号配对。"""
    service = SubtitleSyncService()
    audio_names = [
        "s114_55_おまけトラック11／千友希のオナサポ用亀頭れろれろフェラチオ.wav",
        "s114_49_おまけトラック5／円架の安眠用好き好きループ（左耳）.wav",
        "s114_62_おまけトラック18／藍のオナサポ用あざとさ全開の喘ぎ声ボイス（左耳）.wav",
        "s114_01_トラック1／オープニング〜お久しぶりです、お兄さん♪.wav",
    ]
    subtitles = [
        _subtitle(55, "辅助自慰用 千友希的舔弄龟头口交"),
        _subtitle(49, "助眠用 圆架的循环诉说喜欢"),
        _subtitle(62, "辅助自慰用 蓝的媚态全开娇喘声（左耳）"),
        _subtitle(1, "开场〜哥哥，好久不见♪"),
    ]

    matches = service.match_audio_subtitle(audio_names, subtitles)
    by_audio = {os.path.basename(m["audio_path"]): m["subtitle_name"] for m in matches}

    assert by_audio["s114_55_おまけトラック11／千友希のオナサポ用亀頭れろれろフェラチオ.wav"] == "55 辅助自慰用 千友希的舔弄龟头口交.lrc"
    assert by_audio["s114_49_おまけトラック5／円架の安眠用好き好きループ（左耳）.wav"] == "49 助眠用 圆架的循环诉说喜欢.lrc"
    assert by_audio["s114_62_おまけトラック18／藍のオナサポ用あざとさ全開の喘ぎ声ボイス（左耳）.wav"] == "62 辅助自慰用 蓝的媚态全开娇喘声（左耳）.lrc"
    assert by_audio["s114_01_トラック1／オープニング〜お久しぶりです、お兄さん♪.wav"] == "1 开场〜哥哥，好久不见♪.lrc"


def test_match_audio_subtitle_marks_low_confidence_when_only_one_side_has_number():
    """音频无法解析轨道号、字幕带序号且标题不相似时，标记低置信度。"""
    service = SubtitleSyncService()
    audio_names = [
        "s114_62_藍のオナサポ用あざとさ全開の喘ぎ声ボイス（左耳）.wav",
        "s114_49_円架の安眠用好き好きループ（左耳）.wav",
    ]
    subtitles = [
        _subtitle(1, "开场〜哥哥，好久不见♪"),
        _subtitle(2, "千友希的掏耳（左耳）"),
    ]

    matches = service.match_audio_subtitle(audio_names, subtitles)
    assert matches
    # 轨道号缺失时不得按文件顺序盲配，低置信度结果由调用方跳过自动重命名
    assert all(m.get("low_confidence") for m in matches)
    assert all(m["match_type"] == "低置信度匹配" for m in matches)


def test_rj_subtitle_match_uses_global_track_number():
    """RJ 字幕服务同样按 s114_NN 全局轨道号配对，不再按顺序盲配。"""
    from app.core.rj_subtitle_service import RJSubtitleService

    service = object.__new__(RJSubtitleService)
    service.subtitle_service = SubtitleSyncService()
    service.asmr_service = None

    audio_names = [
        "s114_55_おまけトラック11／千友希のオナサポ用亀頭れろれろフェラチオ.wav",
        "s114_01_トラック1／オープニング〜お久しぶりです、お兄さん♪.wav",
    ]
    subtitles = [
        _subtitle(55, "辅助自慰用 千友希的舔弄龟头口交"),
        _subtitle(1, "开场〜哥哥，好久不见♪"),
    ]
    result = service.match_subtitles_to_audio(audio_names, subtitles)
    by_audio = {m["audio_name"]: m["subtitle_name"] for m in result["matches"]}
    assert by_audio["s114_55_おまけトラック11／千友希のオナサポ用亀頭れろれろフェラチオ.wav"] == "55 辅助自慰用 千友希的舔弄龟头口交.lrc"
    assert by_audio["s114_01_トラック1／オープニング〜お久しぶりです、お兄さん♪.wav"] == "1 开场〜哥哥，好久不见♪.lrc"
    assert not result["unmatched_audio"]
    assert not result["unmatched_subtitles"]
