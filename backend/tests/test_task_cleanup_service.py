from pathlib import Path

from app.core.task_cleanup_service import cleanup_task_download_artifacts
from app.core.task_engine import Task, TaskType


class DummyStorage:
    temp_path = ""


class DummyHttpDownloader:
    download_root = ""


class DummyConfig:
    def __init__(self, tmp_path: Path):
        self.storage = DummyStorage()
        self.storage.temp_path = str(tmp_path / "temp")
        self.http_downloader = DummyHttpDownloader()
        self.http_downloader.download_root = str(tmp_path / "downloads")


def bind_cleanup_config(monkeypatch, tmp_path: Path) -> DummyConfig:
    cfg = DummyConfig(tmp_path)
    monkeypatch.setattr("app.config.settings.get_config", lambda: cfg)
    return cfg


def test_http_download_cleanup_keeps_public_download_root(monkeypatch, tmp_path):
    cfg = bind_cleanup_config(monkeypatch, tmp_path)
    download_root = Path(cfg.http_downloader.download_root)
    target_dir = download_root / "gofile"
    old_file = download_root / "old.zip"
    current_file = target_dir / "current.zip"
    aria2_fragment = Path(str(current_file) + ".aria2")

    target_dir.mkdir(parents=True)
    old_file.write_bytes(b"keep")
    current_file.write_bytes(b"delete")
    aria2_fragment.write_bytes(b"partial")

    task = Task(
        task_type=TaskType.HTTP_DOWNLOAD,
        source_path="gofile.io",
        metadata={
            "download_root": str(download_root),
            "cleanup_mode": "files_only",
            "source_modes": ["gofile"],
            "download_files": [
                {
                    "source": "gofile",
                    "name": "current.zip",
                    "relative_path": "gofile/current.zip",
                    "local_path": str(current_file),
                    "status": "downloading",
                }
            ],
            "final_output_path": str(download_root),
        },
    )

    result = cleanup_task_download_artifacts(task)

    assert result["mode"] == "files_only"
    assert result["cleaned"] >= 2
    assert download_root.exists()
    assert old_file.read_bytes() == b"keep"
    assert not current_file.exists()
    assert not aria2_fragment.exists()
    assert not target_dir.exists()


def test_reimport_download_cleanup_keeps_user_directory(monkeypatch, tmp_path):
    bind_cleanup_config(monkeypatch, tmp_path)
    user_root = tmp_path / "manual-download"
    user_file = user_root / "voice.wav"
    user_root.mkdir()
    user_file.write_bytes(b"keep")

    task = Task(
        task_type=TaskType.ASMR_SYNC_DOWNLOAD,
        source_path=str(user_root),
        metadata={
            "download_mode": "enhanced",
            "download_root": str(user_root),
            "source_action": "reimport_local_download_root",
            "download_files": [{"local_path": str(user_file), "status": "completed"}],
        },
    )

    result = cleanup_task_download_artifacts(task)

    assert result["mode"] == "skipped"
    assert result["cleaned"] == 0
    assert user_file.read_bytes() == b"keep"
