"""安装版专属运行环境；不读取或修改系统数据库。"""

from __future__ import annotations

import json
import configparser
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import tempfile

import yaml


def contain_child_processes():
    """Windows 作业对象：桌面进程异常结束时，不留下数据库后台进程。"""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                    ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
                    ("max_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                    ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    # 句柄不继承、不主动关闭；当前进程退出后由 Windows 统一清理。
    return job


def available_port(preferred: int) -> int:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class DesktopRuntime:
    def __init__(self, install_dir: Path, data_dir: Path):
        self.root = install_dir / "runtime"
        self.data = data_dir
        self.pg_bin = self.root / "postgresql" / "bin"
        self.pg_data = data_dir / "postgresql"
        self.redis_process = None
        self.redis_log = None
        self.pg_started = False
        self.state = {}
        options = configparser.ConfigParser()
        options.read(install_dir / 'runtime-options.ini', encoding='utf-8-sig')
        self.embedded_pg = options.get('runtime', 'postgresql', fallback='embedded') == 'embedded'
        self.embedded_redis = options.get('runtime', 'redis', fallback='embedded') == 'embedded'
        for service in ('postgresql', 'redis'):
            if options.get('runtime', service, fallback='embedded') not in ('embedded', 'external'):
                raise RuntimeError(f'runtime-options.ini 中 {service} 必须为 embedded 或 external')

    def command(self, args, **kwargs):
        # pg_ctl 的后台子进程会继承句柄，PIPE 会令 communicate 永久等待 EOF。
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                [str(arg) for arg in args], stdout=output, stderr=subprocess.STDOUT,
                timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)
            if result.returncode:
                output.seek(0)
                detail = output.read().decode('utf-8', errors='replace')
                raise RuntimeError(f"{Path(args[0]).name} 执行失败：{detail[-3000:]}")
        return result

    def prepare(self):
        required = [self.root / "7zip" / "7z.exe",
                    self.root / "unar" / "unar.exe", self.root / "unar" / "lsar.exe",
                    self.root / "aria2" / "aria2c.exe", self.root / "baidupcs" / "BaiduPCS-Go.exe"]
        if self.embedded_pg:
            required += [self.pg_bin / 'initdb.exe', self.pg_bin / 'pg_ctl.exe']
        if self.embedded_redis:
            required.append(self.root / 'redis' / 'redis-server.exe')
        for path in required:
            if not path.is_file():
                raise RuntimeError(f"安装文件不完整，请重新安装：{path}")
        self.data.mkdir(parents=True, exist_ok=True)
        state_path = self.data / "desktop-runtime.json"
        if state_path.exists():
            self.state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            if self.embedded_pg and (self.pg_data / "PG_VERSION").exists():
                raise RuntimeError("数据库凭据文件缺失，不能覆盖已有数据库。请恢复 desktop-runtime.json。")
            self.state = {"pg_password": secrets.token_urlsafe(32),
                          "redis_password": secrets.token_urlsafe(32),
                          "pg_port": available_port(25432), "redis_port": available_port(26379)}
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state), encoding="utf-8")
            temporary.replace(state_path)
        for key, enabled in (('pg_port', self.embedded_pg), ('redis_port', self.embedded_redis)):
            if enabled:
                self.state[key] = available_port(self.state[key])
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state), encoding='utf-8')
        temporary.replace(state_path)
        # 系统环境中的外部连接不能覆盖安装版专属数据库。
        os.environ.pop('DATABASE_URL', None)
        os.environ.pop('KIKOERUMANAGER_REDIS_URL', None)
        directories = [path for path in self.root.iterdir() if path.is_dir()]
        os.environ["PATH"] = os.pathsep.join(map(str, directories)) + os.pathsep + os.environ.get("PATH", "")
        self.write_config()

    def write_config(self):
        path = self.data / "config" / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            # 只用模型默认值，禁止复制开发者的路径、凭据和服务器配置。
            config = {}
            storage = {}
            for key, folder in {"input_path": "input", "temp_path": "temp",
                                "library_path": "library", "processed_archives_path": "processed",
                                "existing_folders_path": "existing", "asmr_subtitle_path": "subtitles"}.items():
                target = self.data / folder
                target.mkdir(exist_ok=True)
                storage[key] = str(target)
            config["storage"] = storage
            config["watcher"] = {"enabled": False, "auto_start": False}
        from desktop_service_setup import configure_external_services
        configure_external_services(config, self.state, self.embedded_pg, self.embedded_redis)
        if self.embedded_pg:
            config.setdefault("database", {}).update(
                host="127.0.0.1", port=self.state["pg_port"], database="kikoerumanager",
                username="kikoerumanager", password=self.state["pg_password"], sslmode="disable")
        if self.embedded_redis:
            config.setdefault("redis", {}).update(
                enabled=True, required=True, environment="desktop",
                url=f"redis://:{self.state['redis_password']}@127.0.0.1:{self.state['redis_port']}/0")
        config.setdefault("extract", {})["seven_zip_path"] = str(self.root / "7zip" / "7z.exe")
        config.setdefault("http_downloader", {})["aria2_path"] = str(self.root / "aria2" / "aria2c.exe")
        config.setdefault("baidu_netdisk", {})["baidupcs_go_path"] = str(self.root / "baidupcs" / "BaiduPCS-Go.exe")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temporary.replace(path)

    def start(self):
        self.prepare()
        if self.embedded_pg:
            self.start_postgres()
        else:
            self.check_external_postgres()
        if self.embedded_redis:
            self.start_redis()
        else:
            self.check_external_redis()

    def check_external_postgres(self):
        import psycopg
        config = yaml.safe_load((self.data / 'config/config.yaml').read_text(encoding='utf-8'))['database']
        try:
            with psycopg.connect(host=config['host'], port=config.get('port', 5432),
                                 dbname=config['database'], user=config['username'],
                                 password=config.get('password', ''), sslmode=config.get('sslmode', 'prefer'),
                                 connect_timeout=5) as conn:
                conn.execute('SELECT 1')
        except psycopg.Error:
            raise RuntimeError('无法连接已有 PostgreSQL，请检查 config/config.yaml 中的 database 配置及服务状态。') from None

    def check_external_redis(self):
        import redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
        config = yaml.safe_load((self.data / 'config/config.yaml').read_text(encoding='utf-8'))['redis']
        client = redis.Redis.from_url(config['url'], socket_timeout=5, socket_connect_timeout=5,
                                      retry=Retry(NoBackoff(), 0))
        try:
            client.ping()
        except redis.RedisError:
            raise RuntimeError('无法连接已有 Redis，请检查 config/config.yaml 中的 redis.url 及服务状态。') from None
        finally:
            client.close()

    def start_postgres(self):
        if not (self.pg_data / "PG_VERSION").exists():
            password_file = self.data / ".initdb-password"
            password_file.write_text(self.state["pg_password"], encoding="utf-8")
            try:
                self.command([self.pg_bin / "initdb.exe", "-D", self.pg_data,
                              "-U", "kikoerumanager", "--encoding=UTF8",
                              "--auth=scram-sha-256", f"--pwfile={password_file}"])
            finally:
                password_file.unlink(missing_ok=True)
        self.command([self.pg_bin / "pg_ctl.exe", "-D", self.pg_data, "-l", self.data / "postgresql.log",
                      "-o", f"-h 127.0.0.1 -p {self.state['pg_port']}", "-w", "start"])
        self.pg_started = True
        import psycopg
        from psycopg import sql
        with psycopg.connect(host="127.0.0.1", port=self.state["pg_port"],
                             user="kikoerumanager", password=self.state["pg_password"],
                             dbname="postgres", autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("kikoerumanager",)).fetchone():
                conn.execute(sql.SQL("CREATE DATABASE {}" ).format(sql.Identifier("kikoerumanager")))
        with psycopg.connect(host="127.0.0.1", port=self.state["pg_port"],
                             user="kikoerumanager", password=self.state["pg_password"],
                             dbname="kikoerumanager", autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    def start_redis(self):
        redis_dir = self.data / "redis"
        redis_dir.mkdir(exist_ok=True)
        redis_config = redis_dir / "redis.conf"
        redis_config.write_text(
            f"bind 127.0.0.1\nport {self.state['redis_port']}\nprotected-mode yes\n"
            f"requirepass {self.state['redis_password']}\nappendonly yes\nsave \"\"\n", encoding="utf-8")
        self.redis_log = (redis_dir / "redis.log").open("ab")
        self.redis_process = subprocess.Popen(
            [str(self.root / "redis" / "redis-server.exe"), "redis.conf"], cwd=redis_dir,
            stdout=self.redis_log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        import redis
        client = redis.Redis(host="127.0.0.1", port=self.state["redis_port"],
                             password=self.state["redis_password"], socket_timeout=1)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.redis_process.poll() is not None:
                    raise RuntimeError(f"Redis 启动失败，请查看 {redis_dir / 'redis.log'}")
                try:
                    if client.ping():
                        return
                except redis.ConnectionError:
                    pass
                time.sleep(0.2)
            raise RuntimeError("Redis 启动超时")
        finally:
            client.close()

    def stop(self):
        if self.redis_process and self.redis_process.poll() is None:
            import redis
            from redis.backoff import NoBackoff
            from redis.retry import Retry
            client = redis.Redis(host="127.0.0.1", port=self.state["redis_port"],
                                 password=self.state["redis_password"], socket_timeout=5,
                                 socket_connect_timeout=2, retry=Retry(NoBackoff(), 0))
            try:
                client.shutdown(save=True)
                self.redis_process.wait(timeout=15)
            finally:
                client.close()
        if self.redis_log:
            self.redis_log.close()
        if self.pg_started:
            self.command([self.pg_bin / "pg_ctl.exe", "-D", self.pg_data, "-m", "fast", "-w", "stop"])
            self.pg_started = False

