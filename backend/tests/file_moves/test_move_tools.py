"""入口检查与安装包验证不依赖 PostgreSQL、Docker 或真实宿主。"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def tool(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inspected():
    return {"Id": "a" * 64, "HostConfig": {}, "Mounts": [
        {"Destination": "/library", "Source": "/volume4/ASMR", "Type": "bind", "RW": True},
        {"Destination": "/app/data", "Source": "/volume1/data", "Type": "bind", "RW": True},
    ]}


@pytest.mark.parametrize("path", ["/", "/app", "/app/config", "/app/data", "/app/data/redis",
                                      "/library/../etc", "/library-other"])
def test_mapping_rejects_non_business_paths(path):
    installer = tool("host-file-mover-install")
    with pytest.raises(ValueError):
        installer.build_config(inspected(), [path], 1000, 1000, "/var/lib/mover")


def test_mapping_uses_directory_boundary_and_longest_mount():
    installer = tool("host-file-mover-install")
    info = inspected()
    info["Mounts"].append({"Destination": "/library/nested", "Source": "/volume5/media",
                           "Type": "bind", "RW": True})
    with pytest.raises(ValueError, match="嵌套挂载"):
        installer.build_config(info, ["/library"], 1000, 1000, "/var/lib/mover")
    result = installer.build_config(info, ["/library", "/library/nested"], 1000, 1000, "/var/lib/mover")
    assert result["mappings"][1]["host"] == "/volume5/media"


@pytest.mark.parametrize("root", ["/var/lib/a b", "/var/lib/a%h", "/var/lib/a\nx", "/var/lib/../etc"])
def test_systemd_paths_cannot_inject_arguments(root):
    with pytest.raises(ValueError):
        tool("host-file-mover-install").installation_root(root)


def test_bundle_contains_only_executor_files_and_verified_manifest(tmp_path):
    installer = tool("host-file-mover-install")
    output = tmp_path / "bundle"
    installer.make_bundle(output, inspected(), ["/library"], 1000, 1000,
                          "/var/lib/mover", ROOT / "backend/app/core")
    manifest = json.loads((output / "manifest.json").read_text())
    assert set(manifest["sha256"]) == {*installer.FILES, installer.SERVICE, "config.json"}
    assert all(installer.sha(output / name) == digest for name, digest in manifest["sha256"].items())


@pytest.mark.parametrize("python", ["python3", "/bin/python3 -c", "/bin/python%h", "/bin/../python3"])
def test_host_python_path_rejects_systemd_injection(tmp_path, python):
    installer = tool("host-file-mover-install")
    with pytest.raises(ValueError):
        installer.make_bundle(tmp_path / "bundle", inspected(), ["/library"], 1000, 1000,
                              "/var/lib/mover", ROOT / "backend/app/core", python)


def test_bundle_uses_explicit_host_python(tmp_path):
    installer = tool("host-file-mover-install")
    installer.make_bundle(tmp_path / "bundle", inspected(), ["/library"], 1000, 1000,
                          "/var/lib/mover", ROOT / "backend/app/core", "/usr/local/bin/python3")
    assert "ExecStart=/usr/local/bin/python3 " in (tmp_path / "bundle" / installer.SERVICE).read_text(encoding="utf-8")


def test_extract_paths_excludes_remote_libraries_and_credentials():
    installer = tool("host-file-mover-install")
    result = installer.business_paths({"storage": {"input_path": "/down", "temp_path": "/temp",
        "libraries": [{"path": "/local"}, {"type": "synology_filestation", "path": "/remote"}]},
        "http_downloader": {"download_root": "/http", "pikpak_password": "secret"}})
    assert result == ["/app/data/browser-uploads", "/app/data/filter-recovery", "/down", "/http", "/local", "/temp"]


def test_ast_inventory_detects_aliases_and_copy_then_delete(tmp_path):
    checker = tool("check-file-move-coverage")
    directory = tmp_path / "backend/app"
    directory.mkdir(parents=True)
    (directory / "example.py").write_text(
        "from shutil import move as mv\nimport os as system\nimport shutil\n"
        "def work(a,b):\n mv(a,b)\n system.rename(a,b)\n"
        " shutil.copy2(a,b)\n system.unlink(a)\n"
        "def text(s):\n return s.replace('x','y')\n", encoding="utf-8")
    keys = [row["key"] for row in checker.inventory(tmp_path)]
    assert len(keys) == 4
    assert not any(":text:" in key for key in keys)


def test_host_sources_parse_with_python38_grammar():
    import ast
    for name in ("host_file_mover.py", "file_move_protocol.py"):
        ast.parse((ROOT / "backend/app/core" / name).read_text(encoding="utf-8"), feature_version=(3, 8))
    ast.parse((ROOT / "tools/host-file-mover-install.py").read_text(encoding="utf-8"), feature_version=(3, 8))


def test_ast_inventory_detects_thread_and_executor_callbacks(tmp_path):
    checker = tool("check-file-move-coverage")
    directory = tmp_path / "backend/app"
    directory.mkdir(parents=True)
    (directory / "example.py").write_text(
        "import asyncio\nimport shutil\nimport os\n"
        "async def work(a,b):\n await asyncio.to_thread(shutil.move,a,b)\n"
        " await asyncio.get_running_loop().run_in_executor(None,os.rename,a,b)\n",
        encoding="utf-8")
    keys = [row["key"] for row in checker.inventory(tmp_path)]
    assert len(keys) == 2
    assert any(key.endswith(":shutil.move") for key in keys)
    assert any(key.endswith(":os.rename") for key in keys)
