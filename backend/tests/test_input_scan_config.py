"""扫描配置在保存、加载与重载入口统一通知；不接触用户运行配置。"""

from app.config import settings


def test_save_load_reload_notify_once_outside_config_lock(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv("CONFIG_PATH", str(path))
    for key in (
        "_config", "_config_loaded_path", "_config_loaded_mtime", "_config_last_error",
        "_config_write_in_progress", "_config_reload_in_progress",
    ):
        monkeypatch.setattr(settings, key, getattr(settings, key))
    observed = []

    def callback(config):
        assert settings._config_lock.acquire(blocking=False)
        settings._config_lock.release()
        assert settings.get_config() is config
        observed.append((
            config.processing.max_workers, config.processing.file_stable_checks,
            config.processing.file_stable_interval, config.input_scan.active_candidate_limit,
        ))

    monkeypatch.setattr(settings, "_config_change_callbacks", [callback])
    settings.save_config({
        "processing": {"max_workers": 2, "file_stable_checks": 4, "file_stable_interval": 2},
        "input_scan": {"active_candidate_limit": 17},
    }, str(path))
    settings.load_config(str(path))
    settings.reload_config()
    assert observed == [(2, 4, 2, 17)] * 3
    settings.save_config({
        "processing": {"max_workers": 1}, "input_scan": {"active_candidate_limit": 8},
    }, str(path))
    assert observed[-1] == (1, 4, 2, 8)
