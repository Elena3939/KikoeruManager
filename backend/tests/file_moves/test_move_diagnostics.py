"""设置页运行态、只读诊断与配置保护，不依赖数据库或 NAS。"""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import AppConfig
from app.core import file_move_diagnostics as diagnostics
from app.core.host_file_move_client import HostMoveError
from app.api import file_move_routes


@pytest.fixture
def config(tmp_path):
    return AppConfig(storage={"input_path": str(tmp_path), "temp_path": str(tmp_path),
                              "library_path": str(tmp_path), "processed_archives_path": str(tmp_path),
                              "existing_folders_path": str(tmp_path)},
                     http_downloader={"download_root": str(tmp_path)},
                     baidu_netdisk={"download_root": str(tmp_path)},
                     file_move={"journal_path": str(tmp_path / "journals")})


def online(monkeypatch, config):
    mappings = [{"path": path, "available": True, "filesystem": "btrfs:test"}
                for path in diagnostics.business_roots(config)]
    monkeypatch.setattr(diagnostics.os.path, "isdir", lambda _: True)

    class Client:
        def request(self, action):
            assert action == "health"
            return {"mapping_version": "test", "mappings": mappings}

        def probe(self, source, destination):
            return {"same_filesystem": True, "mapping_version": "test",
                    "source_filesystem": "btrfs:test", "target_filesystem": "btrfs:test"}

    monkeypatch.setattr(diagnostics, "_client", lambda _: Client())
    return mappings


def test_online_does_not_mean_enabled(monkeypatch, config):
    online(monkeypatch, config)
    result = diagnostics.runtime_status(config)
    assert result["online"] and result["ready"] and not result["enabled"]


def test_offline_can_be_diagnosed_when_disabled(monkeypatch, config):
    def offline(_):
        raise HostMoveError("执行器离线")
    monkeypatch.setattr(diagnostics, "_client", offline)
    result = diagnostics.runtime_status(config)
    assert not result["online"] and not result["ready"]
    assert "离线" in result["error"] and result["roots"]


def test_enabling_rejects_offline_and_keeps_original(monkeypatch, config):
    monkeypatch.setattr(diagnostics, "runtime_status", lambda _: {"ready": False, "error": "离线"})
    candidate = deepcopy(config)
    candidate.file_move.host_enabled = True
    with pytest.raises(ValueError, match="离线"):
        diagnostics.validate_configuration_update(config, candidate)
    assert not config.file_move.host_enabled


def test_online_missing_mapping_blocks_enable(monkeypatch, config):
    mappings = online(monkeypatch, config)
    mappings.pop()
    candidate = deepcopy(config)
    candidate.file_move.host_enabled = True
    with pytest.raises(ValueError, match="未映射"):
        diagnostics.validate_configuration_update(config, candidate)


def test_enable_with_verified_service(monkeypatch, config):
    online(monkeypatch, config)
    candidate = deepcopy(config)
    candidate.file_move.host_enabled = True
    diagnostics.validate_configuration_update(config, candidate)


def test_disabling_does_not_require_live_service(monkeypatch, config):
    config.file_move.host_enabled = True
    candidate = deepcopy(config)
    candidate.file_move.host_enabled = False
    monkeypatch.setattr(diagnostics, "_client", lambda _: pytest.fail("停用不应连接服务"))
    diagnostics.validate_configuration_update(config, candidate)


def test_unchanged_enabled_config_does_not_block_other_settings(monkeypatch, config):
    config.file_move.host_enabled = True
    monkeypatch.setattr(diagnostics, "_client", lambda _: pytest.fail("无关配置无需检查"))
    candidate = deepcopy(config)
    candidate.rename.template = "[{rjcode}]"
    diagnostics.validate_configuration_update(config, candidate)


def test_business_path_change_requires_mapping_refresh(monkeypatch, config, tmp_path):
    online(monkeypatch, config)
    config.file_move.host_enabled = True
    candidate = deepcopy(config)
    candidate.storage.temp_path = str(tmp_path / "other")
    # 原根仍覆盖 other，因此用完全不在映射中的目录。
    candidate.storage.temp_path = "/unmapped-new-temp"
    with pytest.raises(ValueError, match="未映射"):
        diagnostics.validate_configuration_update(config, candidate)


def test_status_includes_mounts_not_selected_in_settings(monkeypatch, config):
    mappings = online(monkeypatch, config)
    mappings.append({"path": "/anime_dowm", "available": True, "filesystem": "btrfs:anime"})
    result = diagnostics.runtime_status(config)
    row = next(row for row in result["roots"] if row["path"] == "/anime_dowm")
    assert row == {"path": "/anime_dowm", "configured": False, "mapped": True,
                   "available": True, "exists": True, "filesystem": "btrfs:anime"}
    assert result["ready"]


def test_switching_to_synced_mount_passes_save_validation(monkeypatch, config):
    mappings = online(monkeypatch, config)
    path = diagnostics.os.path.normpath("/anime_dowm")
    mappings.append({"path": path, "available": True, "filesystem": "btrfs:anime"})
    config.file_move.host_enabled = True
    candidate = deepcopy(config)
    candidate.storage.input_path = "/anime_dowm"
    diagnostics.validate_configuration_update(config, candidate)
    assert config.storage.input_path != candidate.storage.input_path


def test_unused_unavailable_mount_does_not_block_configured_paths(monkeypatch, config):
    mappings = online(monkeypatch, config)
    mappings.append({"path": "/unused", "available": False})
    result = diagnostics.runtime_status(config)
    assert result["ready"]
    assert not next(row for row in result["roots"] if row["path"] == "/unused")["available"]


def test_probe_accepts_unselected_synced_mount(monkeypatch, config):
    mappings = online(monkeypatch, config)
    mappings.append({"path": "/anime_dowm", "available": True})
    result = diagnostics.probe_paths(config, "/anime_dowm", diagnostics.business_roots(config)[0])
    assert result["source"] == "/anime_dowm"


def test_missing_mapping_error_names_the_directory(monkeypatch, config):
    online(monkeypatch, config)
    candidate = deepcopy(config)
    candidate.storage.input_path = "/anime_dowm"
    result = diagnostics.runtime_status(candidate)
    assert not result["ready"] and diagnostics.os.path.normpath("/anime_dowm") in result["error"]


def test_pending_journal_cannot_be_hidden_by_path_change(config, tmp_path):
    root = tmp_path / "journals"
    root.mkdir()
    (root / "pending.json").write_text('{"state":"published"}')
    candidate = deepcopy(config)
    candidate.file_move.journal_path = str(tmp_path / "other")
    with pytest.raises(ValueError, match="未完成"):
        diagnostics.validate_configuration_update(config, candidate)
    assert diagnostics.journal_summary(config)["states"] == {"published": 1}


@pytest.mark.parametrize("path", ["/etc", "/app/config", "/unmapped", "/../etc"])
def test_probe_rejects_arbitrary_paths(monkeypatch, config, path):
    online(monkeypatch, config)
    client = diagnostics._client(config)
    monkeypatch.setattr(client, "probe",
                        lambda *_: pytest.fail("越界不应请求宿主探测"))
    monkeypatch.setattr(diagnostics, "_client", lambda _: client)
    with pytest.raises(ValueError, match="业务根目录"):
        diagnostics.probe_paths(config, path, diagnostics.business_roots(config)[0])


def test_probe_explains_identity_check_is_not_clone_test(monkeypatch, config):
    online(monkeypatch, config)
    root = diagnostics.business_roots(config)[0]
    result = diagnostics.probe_paths(config, root, root)
    assert result["method"] == "快速克隆" and "需独立克隆验收" in result["note"]


def test_routes_return_actionable_failure_without_database(monkeypatch, config):
    monkeypatch.setattr(file_move_routes, "get_config", lambda: config)
    monkeypatch.setattr(file_move_routes, "runtime_status", lambda _: {"enabled": False, "online": False})
    app = FastAPI()
    app.include_router(file_move_routes.router)
    with TestClient(app) as client:
        result = client.get("/api/system/file-move/status")
        assert result.status_code == 200 and not result.json()["online"]
        result = client.post("/api/system/file-move/probe", json={"source": "/etc", "destination": "/etc"})
        assert result.status_code == 400


def test_general_config_response_preserves_move_settings(config):
    """读取真实响应构造代码，防止面板打开后被响应模型丢弃成默认值。"""
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    from typing import Optional
    from pydantic import BaseModel

    source = Path(__file__).resolve().parents[2] / "app/api/routes.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef))
             and node.name in {"ConfigResponse", "get_configuration"}]
    for node in nodes:
        node.decorator_list = []
    scope = {"BaseModel": BaseModel, "Optional": Optional, "get_config": lambda: config,
             "get_library_manager": lambda: SimpleNamespace(load_config=lambda: {
                 "default_library_id": "", "default_extract_library_id": "",
                 "health_warning_free_gb": 10, "stats_cache_ttl_seconds": 30}),
             "get_security_gate_service": lambda: SimpleNamespace(sanitize_config=lambda: {})}
    scope.update({node.func.id: lambda _: {} for node in ast.walk(nodes[-1])
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id.startswith("_mask_")})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
    config.file_move.host_enabled = True
    config.file_move.socket_path = "/custom/control.sock"
    result = scope["get_configuration"]().model_dump()
    assert result["file_move"] == config.file_move.model_dump()


def test_journal_summary_reports_corrupt_records(config, tmp_path):
    root = tmp_path / "journals"
    root.mkdir()
    (root / "bad.json").write_text("not-json")
    (root / "good.json").write_text('{"state":"cleaning"}')
    result = diagnostics.journal_summary(config)
    assert result["invalid"] == 1 and result["states"] == {"cleaning": 1}


def test_config_save_returns_400_and_never_saves_when_host_is_offline(monkeypatch, config):
    """执行真实配置保存处理器，避免外层异常捕获把参数错误改成 500。"""
    import ast
    import asyncio
    import logging
    from pathlib import Path
    from fastapi import HTTPException, Request
    from app.config import settings

    source = Path(__file__).resolve().parents[2] / "app/api/routes.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "update_configuration")
    node.decorator_list = []
    scope = {"__package__": "app.api", "Request": Request, "HTTPException": HTTPException,
             "asyncio": asyncio, "logger": logging.getLogger(__name__),
             "get_config": lambda: config}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), scope)
    monkeypatch.setattr(settings, "save_config", lambda _: pytest.fail("无效配置不能保存"))
    monkeypatch.setattr(diagnostics, "runtime_status",
                        lambda _: {"ready": False, "error": "执行器离线"})

    class ConfigRequest:
        async def json(self):
            return {"file_move": {"host_enabled": True}}

    with pytest.raises(HTTPException) as error:
        asyncio.run(scope["update_configuration"](ConfigRequest()))
    assert error.value.status_code == 400
    assert "执行器离线" in error.value.detail
    assert not config.file_move.host_enabled
