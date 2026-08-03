# -*- coding: utf-8 -*-
"""字幕同步轨道号提取与匹配逻辑测试。"""

import os

from app.core.subtitle_sync_service import SubtitleSyncService


def _subtitle(num, title):
    """构造字幕文件信息字典"""
    base = f"{num} {title}" if num else title
    return {
        "name": base + ".lrc",
        "path": os.path.join("subs", base + ".lrc"),
        "ext": ".lrc",
        "base_name": base,
    }


def test_extract_track_number_basic_formats():
    """测试基础轨道号格式识别"""
    service = SubtitleSyncService()
    assert service._extract_track_number("01 开场") == 1
    assert service._extract_track_number("Track01") == 1
    assert service._extract_track_number("track_02") == 2
    assert service._extract_track_number("Tr3") == 3
    assert service._extract_track_number("10 标题") == 10


def test_extract_track_number_dlsite_format():
    """测试 DLsite 全局轨道号格式"""
    service = SubtitleSyncService()
    # DLsite s114_NN_ 格式应提取全局轨道号，不被 トラックN 干扰
    assert service._extract_track_number("s114_55_おまけトラック11／千友希のオナサポ用亀頭れろれろフェラチオ.wav") == 55
    assert service._extract_track_number("s114_01_トラック1／オープニング〜お久しぶりです、お兄さん♪.wav") == 1
    assert service._extract_track_number("s114_49_おまけトラック5／円架の安眠用好き好きループ（左耳）.wav") == 49
    assert service._extract_track_number("s114_62_おまけトラック18／藍のオナサポ用あざとさ全開の喘ぎ声ボイス（左耳）.wav") == 62


def test_extract_track_number_japanese_track():
    """测试日文轨道标记"""
    service = SubtitleSyncService()
    assert service._extract_track_number("トラック1") == 1
    assert service._extract_track_number("トラック11") == 11
    assert service._extract_track_number("トラック01") == 1


def test_extract_track_number_skip_rj_code():
    """测试跳过纯 RJ 作品号"""
    service = SubtitleSyncService()
    assert service._extract_track_number("RJ01626948") is None
    assert service._extract_track_number("RJ123456") is None
    assert service._extract_track_number("[RJ01626948]") is None
    assert service._extract_track_number("VJ01234567") is None


def test_match_audio_subtitle_uses_dlsite_global_track_number():
    """s114_NN 全局轨道号应优先于 トラックN 与字幕全局编号配对"""
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


def test_match_audio_subtitle_marks_low_confidence_when_unrelated():
    """音频与字幕标题完全不相关时，标记低置信度"""
    service = SubtitleSyncService()
    audio_names = ["完全不相关的音频文件.wav"]
    subtitles = [_subtitle(None, "01 字幕标题")]

    matches = service.match_audio_subtitle(audio_names, subtitles)

    assert len(matches) == 1
    assert matches[0].get('low_confidence') is True
    assert matches[0]['match_type'] == '低置信度匹配'
    assert matches[0]['match_score'] < 30


def test_match_audio_subtitle_high_similarity_not_low_confidence():
    """相似度高的匹配不应标记为低置信度"""
    service = SubtitleSyncService()
    audio_names = ["千友希的掏耳服务.wav"]
    subtitles = [_subtitle(None, "千友希掏耳")]

    matches = service.match_audio_subtitle(audio_names, subtitles)

    assert len(matches) == 1
    assert matches[0].get('low_confidence') is not True
    assert matches[0]['match_score'] >= 30


def test_match_audio_subtitle_multiple_unrelated():
    """多个不相关文件应都标记低置信度"""
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

    # 轨道号缺失且标题不相似时，应标记为低置信度
    assert len(matches) == 2
    assert all(m.get("low_confidence") for m in matches)
    assert all(m["match_type"] == "低置信度匹配" for m in matches)
