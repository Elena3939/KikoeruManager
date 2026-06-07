import aiohttp
import pytest

from app.core.library_manager import SynologyConfig, SynologyError, SynologyFileStationClient


def test_synology_transport_error_opens_short_circuit():
    client = SynologyFileStationClient(SynologyConfig(base_url="http://nas.local"))

    client._record_remote_failure("SYNO.FileStation.List", aiohttp.ClientConnectionError("timeout"))

    assert client._remote_failures == 1
    snapshot = client.remote_health_snapshot()
    assert snapshot["status"] == "degraded"
    assert snapshot["failure_count"] == 1
    assert snapshot["circuit_remaining_seconds"] > 0
    with pytest.raises(SynologyError, match="远程库存暂时退化"):
        client._check_remote_circuit("SYNO.FileStation.List")


def test_synology_local_file_error_does_not_open_short_circuit():
    client = SynologyFileStationClient(SynologyConfig(base_url="http://nas.local"))

    client._record_remote_failure("SYNO.FileStation.Upload", FileNotFoundError("missing local file"))

    assert client._remote_failures == 0
    client._check_remote_circuit("SYNO.FileStation.Upload")


def test_synology_filestation_timeout_code_opens_short_circuit():
    client = SynologyFileStationClient(SynologyConfig(base_url="http://nas.local"))

    client._record_remote_failure(
        "SYNO.FileStation.List",
        SynologyError('Synology 文件站请求 failed (code 408): {"error":{"code":408}}'),
    )

    assert client._remote_failures == 1
    with pytest.raises(SynologyError, match="远程库存暂时退化"):
        client._check_remote_circuit("SYNO.FileStation.List")


def test_synology_business_error_code_does_not_open_short_circuit():
    client = SynologyFileStationClient(SynologyConfig(base_url="http://nas.local"))

    client._record_remote_failure(
        "SYNO.FileStation.Upload",
        SynologyError('Synology 文件站请求 failed (code 414): {"error":{"code":414}}'),
    )

    assert client._remote_failures == 0
    client._check_remote_circuit("SYNO.FileStation.Upload")


def test_synology_success_resets_remote_health():
    client = SynologyFileStationClient(SynologyConfig(base_url="http://nas.local"))
    client._record_remote_failure("SYNO.FileStation.List", aiohttp.ClientConnectionError("timeout"))

    client._record_remote_success()

    snapshot = client.remote_health_snapshot()
    assert snapshot["status"] == "healthy"
    assert snapshot["failure_count"] == 0
    assert snapshot["circuit_remaining_seconds"] == 0
