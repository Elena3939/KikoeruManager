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
    """Configure application logging."""
    log_dir = os.environ.get("DATA_PATH", "./data")
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "app.log")
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


def init_database():
    """Initialize database tables and enforce UTF-8 encoding."""
    from sqlalchemy import text

    from .models.database import init_db, engine

    init_db()

    with engine.connect() as conn:
        conn.execute(text("PRAGMA encoding='UTF-8'"))
        conn.commit()

    logger = logging.getLogger(__name__)
    logger.info("数据库初始化完成，使用 UTF-8 编码")


def main():
    """Backend entry point."""
    configure_stdio()
    setup_logging()

    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("Prekikoeru 启动中...")
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
    )


if __name__ == "__main__":
    main()
