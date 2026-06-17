"""
测试配置文件
"""
import os
import shutil
from pathlib import Path

import pytest
import asyncio
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.models.database import Base, get_db
from app.api.routes import app
from tests.postgres_test_utils import create_postgres_test_engine, reset_postgres_schema, truncate_all_tables


# pytest 默认把 tmp_path / tmpdir 放在 ``%TEMP%/pytest-of-<user>``。
# Windows 上这个目录极易被杀软/系统锁定（PermissionError [WinError 5]
# 拒绝访问），导致整批 tmp_path 用例 setup 失败。把 basetemp 重定向到
# 仓库内的 ``backend/.pytest-tmp/``，开发机和 CI 都能稳定写入。
def pytest_configure(config: "pytest.Config") -> None:
    """在 pytest 启动时把 basetemp 重定向到工程目录内的可写位置。"""
    if config.getoption("basetemp", default=None):
        return  # 用户显式传了 --basetemp，尊重之
    repo_tmp = Path(__file__).resolve().parent.parent / ".pytest-tmp"
    try:
        repo_tmp.mkdir(parents=True, exist_ok=True)
    except OSError:
        return  # 创建失败就走 pytest 默认逻辑
    # 清理上一次跑剩的内容，避免残留目录/锁定影响新一次扫描
    for child in repo_tmp.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass
    # 通过 tmp_path_factory 的内部 option 注入 basetemp，让所有 tmp_path/tmpdir 走过来
    config.option.basetemp = str(repo_tmp)

engine = create_postgres_test_engine()
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    """覆盖数据库依赖"""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="session")
def db_engine():
    """创建 PostgreSQL 测试数据库引擎。"""
    reset_postgres_schema(engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

@pytest.fixture
def db_session(db_engine):
    """创建数据库会话"""
    truncate_all_tables(db_engine)
    connection = db_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db_session):
    """创建测试客户端"""
    yield TestClient(app)

@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def async_client():
    """创建异步测试客户端"""
    from httpx import AsyncClient
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
