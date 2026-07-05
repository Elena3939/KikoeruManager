from __future__ import annotations

import os
import time
from pathlib import Path
from urllib.parse import quote_plus

import yaml
from sqlalchemy.exc import OperationalError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    raw = os.environ.get("CONFIG_PATH", "").strip()
    if raw:
        return Path(raw)
    return _repo_root() / "data" / "config" / "config.yaml"


def test_database_url() -> str:
    explicit = (
        os.environ.get("KIKOERUMANAGER_TEST_DATABASE_URL")
        or os.environ.get("TEST_DATABASE_URL")
        or ""
    ).strip()
    if explicit:
        if not explicit.startswith("postgresql+psycopg://"):
            raise RuntimeError("测试 DATABASE_URL 必须使用 postgresql+psycopg://")
        return explicit

    cfg = {}
    path = _config_path()
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            cfg = (yaml.safe_load(fh) or {}).get("database") or {}
    host = str(cfg.get("host") or "127.0.0.1")
    port = int(cfg.get("port") or 5432)
    database = str(cfg.get("database") or "kikoerumanager")
    username = str(cfg.get("username") or "kikoerumanager")
    password = str(cfg.get("password") or "kikoerumanager")
    sslmode = str(cfg.get("sslmode") or "prefer")
    if database.endswith("_test"):
        test_database = database
    else:
        test_database = f"{database}_test"
    auth = quote_plus(username)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    return f"postgresql+psycopg://{auth}@{host}:{port}/{quote_plus(test_database)}?sslmode={quote_plus(sslmode)}"


def assert_test_database_url(url: str) -> None:
    database = make_url(url).database or ""
    if database.endswith("_test"):
        return
    if os.environ.get("KIKOERUMANAGER_ALLOW_NON_TEST_DATABASE") == "1":
        return
    raise RuntimeError(f"拒绝在非测试库上运行测试: {database}")


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def ensure_test_database_exists(url: str) -> None:
    """测试启动前创建 *_test 数据库；生产库名已由 assert_test_database_url 拦住。"""
    parsed = make_url(url)
    database = parsed.database or ""
    assert_test_database_url(url)
    if not database:
        raise RuntimeError("测试 DATABASE_URL 缺少数据库名")

    admin_errors: list[Exception] = []
    for maintenance_db in ("postgres", "template1"):
        admin_url = parsed.set(database=maintenance_db)
        admin_engine = create_engine(admin_url, pool_pre_ping=True, isolation_level="AUTOCOMMIT")
        try:
            with admin_engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database"),
                    {"database": database},
                ).scalar()
                if not exists:
                    conn.execute(text(f"CREATE DATABASE {_quote_identifier(database)}"))
            return
        except Exception as exc:
            admin_errors.append(exc)
        finally:
            admin_engine.dispose()

    details = "; ".join(str(exc) for exc in admin_errors)
    raise RuntimeError(f"无法创建 PostgreSQL 测试库 {database}: {details}")


def create_postgres_test_engine() -> Engine:
    url = test_database_url()
    assert_test_database_url(url)
    ensure_test_database_exists(url)
    return create_engine(url, pool_pre_ping=True)


def reset_postgres_schema(engine: Engine) -> None:
    from app.models.database import (
        Base,
        _create_postgres_extensions_and_indexes,
        _migrate_compat_schema,
        ensure_library_index_postgres_indexes_concurrently,
    )

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _create_postgres_extensions_and_indexes(conn)
        _migrate_compat_schema(conn)
    ensure_library_index_postgres_indexes_concurrently(engine)


def truncate_all_tables(engine: Engine) -> None:
    from app.models.database import (
        Base,
        _create_postgres_extensions_and_indexes,
        _migrate_compat_schema,
        ensure_library_index_postgres_indexes_concurrently,
    )

    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _create_postgres_extensions_and_indexes(conn)
        _migrate_compat_schema(conn)
    ensure_library_index_postgres_indexes_concurrently(engine)
    existing = set(inspect(engine).get_table_names())
    table_names = [table.name for table in Base.metadata.sorted_tables if table.name in existing]
    if not table_names:
        return
    quoted = ", ".join(f'"{name}"' for name in table_names)
    last_error: OperationalError | None = None
    for attempt in range(5):
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
            return
        except OperationalError as exc:
            message = str(exc).lower()
            if "deadlock detected" not in message and "lock timeout" not in message:
                raise
            last_error = exc
            engine.dispose()
            time.sleep(0.15 * (attempt + 1))
    if last_error is not None:
        raise last_error
