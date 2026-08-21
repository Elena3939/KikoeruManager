import os
import sys
import logging
from pathlib import Path

import uvicorn

from .api.routes import app


def get_uvicorn_limit_concurrency() -> int | None:
    """读取 uvicorn 并发硬限制；0/空值表示关闭，避免高并发读接口被直接 503。"""
    raw_value = os.environ.get("KIKOERUMANAGER_UVICORN_LIMIT_CONCURRENCY", "").strip()
    if not raw_value or raw_value in {"0", "none", "None", "false", "False"}:
        return None
    try:
        value = int(raw_value)
    except ValueError:
        logging.getLogger(__name__).warning(
            "忽略无效 KIKOERUMANAGER_UVICORN_LIMIT_CONCURRENCY=%r", raw_value
        )
        return None
    return value if value > 0 else None


def configure_stdio():
    """Force UTF-8 stdio on Windows so DLsite metadata logs render correctly."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def setup_logging():
    """Configure application logging (RotatingFileHandler, 20MB * 5)."""
    from .core.app_logging import configure_app_logging

    log_dir = os.environ.get("DATA_PATH", "./data")
    configure_app_logging(log_dir=log_dir, use_console=_console_logging_enabled())


def _console_logging_enabled() -> bool:
    """容器默认只写异步文件日志，避免未消费的 TTY 反压应用主线程。"""
    configured = os.environ.get("KIKOERUMANAGER_CONSOLE_LOGGING", "").strip().lower()
    if configured:
        return configured in {"1", "true", "yes", "on"}
    return not Path("/.dockerenv").exists()


def init_database():
    """Initialize PostgreSQL database tables and indexes."""
    from .models.database import init_db

    init_db()

    logger = logging.getLogger(__name__)
    logger.info("PostgreSQL 数据库初始化完成")


def main():
    """Backend entry point."""
    configure_stdio()
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("KikoeruManager 启动中...")
    logger.info("=" * 50)

    reload_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
    # reload 模式会再起一个子进程，数据库初始化交给 FastAPI startup，避免父子进程并发迁移。
    if not reload_mode:
        init_database()
    port = int(os.environ.get("PORT", "5555"))
    limit_concurrency = get_uvicorn_limit_concurrency()
    logger.info(
        "uvicorn 并发硬限制: %s",
        limit_concurrency if limit_concurrency is not None else "disabled",
    )

    # reload 模式必须传 import string，否则 Uvicorn 会提示无法启用 reload 后直接退出。
    uvicorn_app = "app.api.routes:app" if reload_mode else app
    uvicorn.run(
        uvicorn_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=reload_mode,
        limit_concurrency=limit_concurrency,
        timeout_keep_alive=15,
        backlog=512,
    )


if __name__ == "__main__":
    main()
