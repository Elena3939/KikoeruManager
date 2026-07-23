from types import SimpleNamespace

import pytest
import yaml

from app.core import library_manager as library_manager_module
from app.core.rj_subtitle_service import RJSubtitleService
from app.config import settings as settings_module


@pytest.mark.asyncio
async def test_process_folder_with_local_library_id_keeps_local_processing(monkeypatch, tmp_path):
    folder = tmp_path / "RJ01529215"
    folder.mkdir()
    manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="local"),
    )
    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: manager)

    service = RJSubtitleService()

    async def fail_remote_processing(**_kwargs):
        raise AssertionError("本地库存不应进入远程字幕处理")

    monkeypatch.setattr(service, "process_remote_folder", fail_remote_processing)
    monkeypatch.setattr(service, "_collect_audio_files", lambda _folder: [])

    with pytest.raises(ValueError, match="RJ 文件夹中没有找到音频文件"):
        await service.process_folder(str(folder), library_id="local-library")


@pytest.mark.asyncio
async def test_process_folder_with_synology_library_id_keeps_remote_processing(monkeypatch):
    manager = SimpleNamespace(
        get_library_definition=lambda _library_id: SimpleNamespace(type="synology_filestation"),
    )
    monkeypatch.setattr(library_manager_module, "get_library_manager", lambda: manager)

    service = RJSubtitleService()
    calls = []

    async def fake_remote_processing(**kwargs):
        calls.append(kwargs)
        return {"success": True, "rjcode": "RJ01529215"}

    monkeypatch.setattr(service, "process_remote_folder", fake_remote_processing)

    result = await service.process_folder(
        "/remote/RJ01529215",
        library_id="synology-library",
        overwrite=True,
    )

    assert result == {"success": True, "rjcode": "RJ01529215"}
    assert calls[0]["library_id"] == "synology-library"
    assert calls[0]["folder_path"] == "/remote/RJ01529215"
    assert calls[0]["overwrite"] is True


def test_runtime_subtitle_filter_keeps_normal_audio_tracks_and_excludes_explicit_variants():
    with open("../data/config/config.yaml", "r", encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    rules = config["rj_subtitle"]["subtitle_filter_rules"]
    service = RJSubtitleService()
    subtitles = [
        {"name": "第10章 【母乳喷射 站立后入 音轨】.wav.vtt"},
        {"name": "Track01_无效果音 【WAV】.wav.vtt"},
        {"name": "第10章 【母乳喷射 站立后入 音轨】.mp3.vtt"},
    ]

    filtered = service._apply_subtitle_filter_rules(subtitles, rules)

    assert [item["name"] for item in filtered] == [
        "第10章 【母乳喷射 站立后入 音轨】.wav.vtt",
    ]


@pytest.mark.asyncio
async def test_process_local_folder_reports_all_candidates_filtered_without_downloading(monkeypatch, tmp_path):
    folder = tmp_path / "RJ01529215"
    folder.mkdir()
    (folder / "track01.wav").write_bytes(b"audio")
    config = SimpleNamespace(
        storage=SimpleNamespace(temp_path=str(tmp_path / "temp")),
        rj_subtitle=SimpleNamespace(
            overwrite_existing=False,
            enable_metadata_match=True,
            naming_strategy="audio",
            use_filter_rules=True,
        ),
    )
    monkeypatch.setattr(settings_module, "get_config", lambda: config)

    service = RJSubtitleService()

    async def fake_source(*_args, **_kwargs):
        return ({
            "rjcode": "RJ01554928",
            "lang": "CHI_HANS",
            "title": "测试字幕来源",
            "subtitle_files": [{
                "name": "track01.wav.vtt",
                "relative_path": "track01.wav.vtt",
                "media_download_url": "https://example.invalid/track01.vtt",
            }],
        }, [])

    async def fail_download(*_args, **_kwargs):
        raise AssertionError("全部候选被过滤后不应调用下载接口")

    monkeypatch.setattr(service, "find_best_subtitle_source", fake_source)
    monkeypatch.setattr(service.asmr_service, "download_file", fail_download)

    result = await service.process_folder(
        str(folder),
        use_filter_rules=True,
        subtitle_filter_rules=[{"name": "全部排除", "pattern": ".*", "target": "name", "enabled": True}],
    )

    assert result["success"] is False
    assert result["error"] == "字幕过滤规则排除了全部 1 个候选，请调整或关闭过滤规则"
    assert result["failed_files"] == []


@pytest.mark.asyncio
async def test_process_local_folder_reports_actual_download_failure_count(monkeypatch, tmp_path):
    folder = tmp_path / "RJ01529215"
    folder.mkdir()
    (folder / "track01.wav").write_bytes(b"audio")
    config = SimpleNamespace(
        storage=SimpleNamespace(temp_path=str(tmp_path / "temp")),
        rj_subtitle=SimpleNamespace(
            overwrite_existing=False,
            enable_metadata_match=True,
            naming_strategy="audio",
            use_filter_rules=False,
        ),
    )
    monkeypatch.setattr(settings_module, "get_config", lambda: config)

    service = RJSubtitleService()

    async def fake_source(*_args, **_kwargs):
        return ({
            "rjcode": "RJ01554928",
            "lang": "CHI_HANS",
            "title": "测试字幕来源",
            "subtitle_files": [{
                "name": "track01.wav.vtt",
                "relative_path": "track01.wav.vtt",
                "media_download_url": "https://example.invalid/track01.vtt",
            }],
        }, [])

    async def fail_download(*_args, **_kwargs):
        return False

    monkeypatch.setattr(service, "find_best_subtitle_source", fake_source)
    monkeypatch.setattr(service.asmr_service, "download_file", fail_download)

    result = await service.process_folder(str(folder), use_filter_rules=False)

    assert result["success"] is False
    assert result["error"] == "1 个字幕文件全部下载失败"
    assert len(result["failed_files"]) == 1
