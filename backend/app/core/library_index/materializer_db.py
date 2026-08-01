"""库存索引物化器专用 PostgreSQL 连接池。"""

from __future__ import annotations

import threading
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from ...models.database import (
    _connect_args as _main_connect_args,
    _orjson_dumps,
    _orjson_loads,
    engine as main_engine,
)


_lock = threading.RLock()
_engine: Optional[Engine] = None
_session_factory = None


def _materializer_connect_args() -> dict:
    """继承主连接的 libpq 参数，只收紧物化器自己的连接行为。"""
    _args, kwargs = main_engine.dialect.create_connect_args(main_engine.url)
    connect_args = dict(_main_connect_args())
    kwargs.pop("context", None)
    connect_args.update(kwargs)
    connect_args["connect_timeout"] = 1
    connect_args["application_name"] = (
        "kikoerumanager-library-index-materializer"
    )
    return connect_args


def get_materializer_engine() -> Engine:
    """返回最多占用一个连接的索引物化专用 engine。"""
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            _engine = create_engine(
                main_engine.url,
                connect_args=_materializer_connect_args(),
                poolclass=QueuePool,
                pool_size=1,
                max_overflow=0,
                pool_timeout=1,
                pool_pre_ping=True,
                json_serializer=_orjson_dumps,
                json_deserializer=_orjson_loads,
                echo=False,
            )
    return _engine


def get_materializer_session_factory():
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    with _lock:
        if _session_factory is None:
            _session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=get_materializer_engine(),
            )
    return _session_factory


def materializer_pool_diagnostics() -> dict[str, int]:
    engine = _engine
    if engine is None:
        return {"pool_size": 1, "checked_out": 0, "overflow": 0}
    pool = engine.pool
    return {
        "pool_size": int(pool.size()),
        "checked_out": int(pool.checkedout()),
        "overflow": int(pool.overflow()),
    }


def dispose_materializer_engine() -> None:
    global _engine, _session_factory
    with _lock:
        engine = _engine
        _engine = None
        _session_factory = None
    if engine is not None:
        engine.dispose()
