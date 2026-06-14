import os
import sys
import logging

import uvicorn

from .api.routes import app


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
    configure_app_logging(log_dir=log_dir, use_console=True)


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

    init_database()

    reload_mode = os.environ.get("DEV_MODE", "false").lower() == "true"
    port = int(os.environ.get("PORT", "5555"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=reload_mode,
        limit_concurrency=128,
        timeout_keep_alive=15,
        backlog=512,
    )


if __name__ == "__main__":
    main()
