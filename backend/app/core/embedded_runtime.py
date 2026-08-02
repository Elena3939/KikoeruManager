"""Windows 桌面版内置 PostgreSQL / Redis 引导。

exe 首次启动时如果本机没有可用的 PostgreSQL / Redis，会优先使用
发行包内携带的 runtime（exe 同级 tools 目录或 PyInstaller 解包目录），
缺失时再自动下载便携版并初始化到 data/postgresql 与 data/redis，
保证桌面版可以脱离源码环境和 Docker 独立运行。
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML 是后端固定依赖
    yaml = None


logger = logging.getLogger(__name__)

PG_VERSION = "18.4"
PG_PACKAGE = f"postgresql-{PG_VERSION}-1-windows-x64-binaries.zip"
PG_DOWNLOAD_URL = f"https://get.enterprisedb.com/postgresql/{PG_PACKAGE}"

REDIS_VERSION = "8.10.0"
REDIS_PACKAGE = f"Redis-{REDIS_VERSION}-Windows-x64-msys2.zip"
REDIS_DOWNLOAD_URL = (
    f"https://github.com/redis-windows/redis-windows/releases/download/"
    f"{REDIS_VERSION}/{REDIS_PACKAGE}"
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _is_local_host(value: str) -> bool:
    return str(value or "").strip().lower() in _LOCAL_HOSTS


def _tcp_connected(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _load_yaml(path: Path) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML 未安装，无法读写配置文件")
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    return payload if isinstance(payload, dict) else {}


def _write_yaml_atomically(path: Path, payload: dict) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML 未安装，无法写入配置文件")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".bootstrap.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)


def _run(
    args: Iterable[str],
    *,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 120,
    hide_window: bool = True,
    capture_output: bool = True,
    stdout: Any = None,
    stderr: Any = None,
) -> subprocess.CompletedProcess:
    creationflags = 0
    startupinfo = None
    if os.name == "nt" and hide_window:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    if capture_output:
        return subprocess.run(
            list(args),
            env=merged_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
            startupinfo=startupinfo,
            check=False,
        )
    return subprocess.run(
        list(args),
        env=merged_env,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=stderr if stderr is not None else subprocess.DEVNULL,
        timeout=timeout,
        creationflags=creationflags,
        startupinfo=startupinfo,
        check=False,
    )


def _download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("[内置运行环境] 下载 %s -> %s", url, dest)
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out, length=1024 * 1024)
    os.replace(tmp, dest)


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)


def _extract_pg_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract only PostgreSQL runtime directories (bin/lib/share)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    prefixes = ("pgsql/bin/", "pgsql/lib/", "pgsql/share/")
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if not name.startswith(prefixes):
                continue
            zf.extract(info, dest_dir)


def _find_pg_bin(roots: Iterable[Path]) -> Optional[Path]:
    for root in roots:
        for sub in ("pgsql\\bin", "bin"):
            candidate = Path(root) / sub
            if (
                (candidate / "psql.exe").exists()
                and (candidate / "pg_ctl.exe").exists()
                and (candidate / "initdb.exe").exists()
            ):
                return candidate
    return None


def _find_redis_server(roots: Iterable[Path]) -> Optional[Path]:
    for root in roots:
        candidate = Path(root) / "redis-server.exe"
        if candidate.exists():
            return candidate
    return None


def _search_roots(data_dir: Path, exe_dir: Path, bundle_dir: Path) -> List[Path]:
    roots = [
        data_dir / "postgresql",
        exe_dir / "tools" / "postgres",
        bundle_dir / "tools" / "postgres",
        data_dir / "redis",
        exe_dir / "tools" / "redis",
        bundle_dir / "tools" / "redis",
        Path("D:/softApp/PostgreSQL"),
        Path("D:/softApp/redis"),
        Path("C:/Program Files/PostgreSQL/18"),
        Path("C:/Program Files/PostgreSQL/17"),
        Path("C:/Program Files/PostgreSQL/16"),
        Path("C:/Program Files/Redis"),
    ]
    seen: set[str] = set()
    unique: List[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _redis_search_roots(data_dir: Path, exe_dir: Path, bundle_dir: Path) -> List[Path]:
    roots = [
        data_dir / "redis",
        exe_dir / "tools" / "redis",
        bundle_dir / "tools" / "redis",
        Path("D:/softApp/redis"),
        Path("C:/Program Files/Redis"),
    ]
    seen: set[str] = set()
    unique: List[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _write_database_config(
    config_path: Path,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    sslmode: str,
) -> None:
    cfg = _load_yaml(config_path)
    db_cfg = dict(cfg.get("database") or {})
    db_cfg.update(
        {
            "host": host,
            "port": int(port),
            "database": database,
            "username": username,
            "password": password,
            "sslmode": sslmode,
        }
    )
    cfg["database"] = db_cfg
    _write_yaml_atomically(config_path, cfg)


def _ensure_postgres(
    data_dir: Path,
    exe_dir: Path,
    bundle_dir: Path,
    database_cfg: dict,
    config_path: Path,
) -> Optional[str]:
    host = str(database_cfg.get("host") or "127.0.0.1").strip()
    if not _is_local_host(host):
        return None
    port = int(database_cfg.get("port") or 5432)
    db_name = str(database_cfg.get("database") or "kikoerumanager").strip()
    username = str(database_cfg.get("username") or "kikoerumanager").strip()
    password = str(database_cfg.get("password") or "")
    sslmode = str(database_cfg.get("sslmode") or "prefer").strip()

    if _tcp_connected(host, port, timeout=1.5):
        logger.info("[内置运行环境] 检测到 PostgreSQL 已监听 %s:%s，跳过初始化", host, port)
        return None

    pg_root = data_dir / "postgresql"
    pg_data = pg_root / "data"
    bin_dir = _find_pg_bin(_search_roots(data_dir, exe_dir, bundle_dir))
    if bin_dir is None:
        download_dir = data_dir / "downloads"
        zip_path = download_dir / PG_PACKAGE
        if not zip_path.exists():
            _download_file(PG_DOWNLOAD_URL, zip_path)
        logger.info("[内置运行环境] 解压 PostgreSQL 便携版到 %s", pg_root)
        _extract_pg_zip(zip_path, pg_root)
        bin_dir = _find_pg_bin([pg_root])
    if bin_dir is None:
        raise RuntimeError("未找到 PostgreSQL 可执行文件（psql/pg_ctl/initdb）")

    if not (pg_data / "PG_VERSION").exists():
        if not password:
            password = secrets.token_urlsafe(24)
        pg_data.mkdir(parents=True, exist_ok=True)
        pw_file = pg_root / "pg_init_password.txt"
        try:
            with open(pw_file, "w", encoding="ascii") as fh:
                fh.write(password)
            logger.info("[内置运行环境] 初始化 PostgreSQL 数据目录 %s", pg_data)
            result = _run(
                [
                    str(bin_dir / "initdb.exe"),
                    "-D", str(pg_data),
                    "-U", username,
                    "-A", "scram-sha-256",
                    "--pwfile=" + str(pw_file),
                    "--encoding=UTF8",
                    "--locale=C",
                ],
                timeout=300,
            )
            if result.returncode != 0:
                raise RuntimeError(f"initdb 失败: {result.stderr.strip()}")
        finally:
            pw_file.unlink(missing_ok=True)
        with open(pg_data / "postgresql.conf", "a", encoding="utf-8") as fh:
            fh.write(
                "\n"
                "listen_addresses = '127.0.0.1'\n"
                f"port = {port}\n"
                "shared_buffers = '128MB'\n"
                "effective_cache_size = '1GB'\n"
                "maintenance_work_mem = '128MB'\n"
                "work_mem = '8MB'\n"
                "checkpoint_completion_target = 0.9\n"
                "random_page_cost = 1.1\n"
                "default_statistics_target = 200\n"
                "log_min_duration_statement = 1000\n"
            )
        _write_database_config(
            config_path,
            host=host,
            port=port,
            database=db_name,
            username=username,
            password=password,
            sslmode=sslmode,
        )

    log_file = pg_root / "postgresql.log"
    if not _tcp_connected(host, port, timeout=1.5):
        logger.info("[内置运行环境] 启动 PostgreSQL (port=%s)", port)
        ctl_log = pg_root / "pg_ctl.start.log"
        with open(ctl_log, "ab") as ctl_handle:
            result = _run(
                [
                    str(bin_dir / "pg_ctl.exe"),
                    "-D", str(pg_data),
                    "-l", str(log_file),
                    "-w", "start",
                ],
                timeout=180,
                capture_output=False,
                stdout=ctl_handle,
                stderr=subprocess.STDOUT,
            )
        if result.returncode != 0:
            detail = ctl_log.read_text(encoding="utf-8", errors="replace").strip()
            raise RuntimeError(
                "PostgreSQL 启动失败: " + (detail or "pg_ctl 返回非零")
            )

    pg_env = {"PGPASSWORD": password or ""}
    psql = str(bin_dir / "psql.exe")
    # 初始密码为空且已有数据目录时，无法自动修复，交给后端给出明确错误。
    if not password:
        return None

    check = _run(
        [
            psql, "-h", host, "-p", str(port), "-U", username,
            "-d", "postgres", "-tAc",
            "SELECT 1 FROM pg_database WHERE datname='" + db_name.replace("'", "''") + "'",
        ],
        env=pg_env,
        timeout=60,
    )
    if check.returncode != 0:
        raise RuntimeError(f"PostgreSQL 连接校验失败: {check.stderr.strip()}")
    if check.stdout.strip() != "1":
        quoted_db = db_name.replace('"', '""')
        quoted_owner = username.replace('"', '""')
        create = _run(
            [
                psql, "-h", host, "-p", str(port), "-U", username,
                "-d", "postgres", "-v", "ON_ERROR_STOP=1",
                "-c", f'CREATE DATABASE "{quoted_db}" OWNER "{quoted_owner}"',
            ],
            env=pg_env,
            timeout=60,
        )
        if create.returncode != 0:
            raise RuntimeError(f"创建数据库失败: {create.stderr.strip()}")
    ext = _run(
        [
            psql, "-h", host, "-p", str(port), "-U", username,
            "-d", db_name, "-v", "ON_ERROR_STOP=1",
            "-c", "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        ],
        env=pg_env,
        timeout=60,
    )
    if ext.returncode != 0:
        logger.warning("[内置运行环境] pg_trgm 扩展创建失败: %s", ext.stderr.strip())

    from urllib.parse import quote_plus

    auth = quote_plus(username)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    query = f"?sslmode={quote_plus(sslmode)}" if sslmode else ""
    url = f"postgresql+psycopg://{auth}@{host}:{port}/{quote_plus(db_name)}{query}"
    os.environ["DATABASE_URL"] = url
    _write_database_config(
        config_path,
        host=host,
        port=port,
        database=db_name,
        username=username,
        password=password,
        sslmode=sslmode,
    )
    return url


def _ensure_redis(
    data_dir: Path,
    exe_dir: Path,
    bundle_dir: Path,
    redis_cfg: dict,
    config_path: Path,
) -> Optional[str]:
    if os.environ.get("KIKOERUMANAGER_REDIS_URL", "").strip():
        logger.info("[内置运行环境] 检测到 KIKOERUMANAGER_REDIS_URL，使用外部 Redis")
        return None
    if not bool(redis_cfg.get("enabled", True)):
        logger.info("[内置运行环境] Redis 已在配置中禁用，跳过启动")
        return None
    raw_url = str(redis_cfg.get("url") or "redis://localhost:6379/0")
    parsed = urllib.parse.urlsplit(raw_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    if not _is_local_host(host):
        return None
    if _tcp_connected(host, port, timeout=1.0):
        logger.info("[内置运行环境] 检测到 Redis 已监听 %s:%s，跳过启动", host, port)
        return None

    server = _find_redis_server(_redis_search_roots(data_dir, exe_dir, bundle_dir))
    if server is None:
        download_dir = data_dir / "downloads"
        zip_path = download_dir / REDIS_PACKAGE
        if not zip_path.exists():
            _download_file(REDIS_DOWNLOAD_URL, zip_path)
        redis_dir = data_dir / "redis"
        logger.info("[内置运行环境] 解压 Redis 便携版到 %s", redis_dir)
        _extract_zip(zip_path, redis_dir)
        server = next(redis_dir.rglob("redis-server.exe"), None)
        if server is not None:
            server = server.resolve()
    if server is None:
        raise RuntimeError("未找到 redis-server.exe")

    redis_data = data_dir / "redis"
    redis_data.mkdir(parents=True, exist_ok=True)
    args = [
        str(server),
        "--bind", "127.0.0.1",
        "--port", str(port),
        "--dir", str(redis_data),
        "--dbfilename", "dump.rdb",
        "--appendonly", "yes",
        "--logfile", str(redis_data / "redis.log"),
    ]
    if parsed.password:
        args += ["--requirepass", urllib.parse.unquote(parsed.password)]
    logger.info("[内置运行环境] 启动 Redis: %s", server)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    with open(redis_data / "redis.stdout.log", "ab") as log_handle:
        subprocess.Popen(
            args,
            creationflags=creationflags,
            close_fds=True,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

    deadline = time.time() + 30
    while time.time() < deadline:
        if _tcp_connected(host, port, timeout=1.0):
            canonical = f"redis://{host}:{port}/0"
            os.environ["KIKOERUMANAGER_REDIS_URL"] = canonical
            return canonical
        time.sleep(0.5)
    raise RuntimeError(f"Redis 启动后仍无法连接: {host}:{port}")


def bootstrap_embedded_runtime(
    data_dir: Optional[str] = None,
    config_path: Optional[str] = None,
) -> dict:
    """按需初始化桌面版本地 PostgreSQL / Redis，返回启动摘要。"""
    if os.name != "nt":
        return {"postgresql": None, "redis": None, "skipped": "non-windows"}

    if data_dir:
        data_path = Path(data_dir).resolve()
    else:
        data_path = Path(os.environ.get("DATA_PATH", "data")).resolve()
    if config_path:
        config_file = Path(config_path).resolve()
    else:
        config_file = data_path / "config" / "config.yaml"

    exe_dir = Path(os.path.dirname(sys.executable)).resolve()
    bundle_dir = Path(getattr(sys, "_MEIPASS", exe_dir)).resolve()
    cfg = _load_yaml(config_file)

    summary: Dict[str, Any] = {"postgresql": None, "redis": None}
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        database_url = _ensure_postgres(
            data_path, exe_dir, bundle_dir, cfg.get("database") or {}, config_file
        )
        summary["postgresql"] = database_url
        cfg = _load_yaml(config_file)

    redis_url = _ensure_redis(
        data_path, exe_dir, bundle_dir, cfg.get("redis") or {}, config_file
    )
    summary["redis"] = redis_url
    return summary


__all__ = ["bootstrap_embedded_runtime"]
