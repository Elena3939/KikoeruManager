r"""一次性把旧 SQLite 数据导入 PostgreSQL。

默认源库：
    D:\新建文件夹\新建文件夹 (2)\cache.db.fixed

执行示例：
    backend\venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py `
        --database-url "postgresql+psycopg://kikoerumanager:密码@127.0.0.1:5432/kikoerumanager?sslmode=prefer" `
        --replace-target --create-schema
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, Text, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.sqltypes import String

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SOURCE = Path(r"D:\新建文件夹\新建文件夹 (2)\cache.db.fixed")
DERIVED_SUFFIXES = (
    "_fts",
    "_fts_config",
    "_fts_content",
    "_fts_data",
    "_fts_docsize",
    "_fts_idx",
)
DERIVED_TABLES = {"lost_and_found"}


def _load_models():
    from backend.app.models.database import Base, _create_postgres_extensions_and_indexes

    return Base, _create_postgres_extensions_and_indexes


def _library_index_name_sort_key(value: Any) -> str:
    from backend.app.models.database import library_index_name_sort_key

    return library_index_name_sort_key(value)


def _sqlite_uri(path: Path) -> str:
    return f"file:{path.resolve().as_posix()}?mode=ro"


def _connect_sqlite_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(_sqlite_uri(path), uri=True)
    conn.text_factory = lambda raw: raw.decode("utf-8", "surrogateescape")
    conn.row_factory = sqlite3.Row
    return conn


def _quick_check(conn: sqlite3.Connection) -> str:
    try:
        return str(conn.execute("PRAGMA quick_check").fetchone()[0])
    except Exception as exc:
        raise RuntimeError(f"SQLite quick_check 执行失败，源库不可迁移: {exc}") from exc


def _sqlite_tables(conn: sqlite3.Connection) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT name, COALESCE(sql, '') AS sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {str(row["name"]): str(row["sql"] or "") for row in rows}


def _is_derived_table(name: str) -> bool:
    value = str(name or "")
    if value.startswith("sqlite_"):
        return True
    if value in DERIVED_TABLES:
        return True
    return any(value.endswith(suffix) for suffix in DERIVED_SUFFIXES)


def _business_source_tables(source_tables: Dict[str, str]) -> List[str]:
    return [name for name in sorted(source_tables) if not _is_derived_table(name)]


def _count_sqlite(conn: sqlite3.Connection, table_name: str) -> int:
    return int(conn.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()[0] or 0)


def _safe_text(value: Any) -> str:
    text_value = str(value)
    return text_value.encode("utf-8", "backslashreplace").decode("utf-8")


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, dict):
        return {
            _safe_text(key): _safe_json(current)
            for key, current in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(current) for current in value]
    return _safe_text(value)


def _loads_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="backslashreplace")
    text_value = str(value)
    if text_value == "":
        return None
    try:
        return _safe_json(json.loads(text_value))
    except Exception:
        return _safe_text(text_value)


def _parse_datetime(value: Any) -> Any:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except Exception:
            return None
    text_value = str(value or "").strip()
    if not text_value:
        return None
    normalized = text_value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text_value, fmt)
        except Exception:
            continue
    return None


def _convert_value(value: Any, column) -> Any:
    if value is None:
        return None
    col_type = column.type
    if isinstance(col_type, JSONB):
        return _loads_json(value)
    if isinstance(col_type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if isinstance(col_type, DateTime):
        return _parse_datetime(value)
    if isinstance(col_type, (Integer, BigInteger)):
        try:
            return int(value)
        except Exception:
            return None
    if isinstance(col_type, Float):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(col_type, (String, Text)):
        text_value = _safe_text(value)
        length = getattr(col_type, "length", None)
        if length:
            return text_value[: int(length)]
        return text_value
    return value


def _iter_sqlite_rows(conn: sqlite3.Connection, table_name: str, chunk_size: int) -> Iterable[List[sqlite3.Row]]:
    offset = 0
    while True:
        rows = conn.execute(
            f'SELECT * FROM "{table_name}" LIMIT ? OFFSET ?',
            (chunk_size, offset),
        ).fetchall()
        if not rows:
            break
        yield rows
        offset += len(rows)


def _convert_rows(rows: List[sqlite3.Row], table) -> List[Dict[str, Any]]:
    columns_by_name = {column.name: column for column in table.columns}
    payload: List[Dict[str, Any]] = []
    for row in rows:
        converted: Dict[str, Any] = {}
        for key in row.keys():
            column = columns_by_name.get(key)
            if column is None:
                continue
            converted[key] = _convert_value(row[key], column)
        if table.name == "library_index_entries" and "name_sort_key" in columns_by_name:
            converted["name_sort_key"] = _library_index_name_sort_key(converted.get("name") or "")
        payload.append(converted)
    return payload


def _quote_table_names(table_names: Iterable[str]) -> str:
    return ", ".join(f'"{name}"' for name in table_names)


def _truncate_target(conn, table_names: List[str]) -> None:
    if not table_names:
        return
    conn.execute(text(f"TRUNCATE TABLE {_quote_table_names(table_names)} RESTART IDENTITY CASCADE"))


def _target_count(conn, table_name: str) -> int:
    return int(conn.execute(text(f'SELECT count(*) FROM "{table_name}"')).scalar() or 0)


def _reset_sequences(conn, tables) -> List[Dict[str, Any]]:
    reset: List[Dict[str, Any]] = []
    for table in tables:
        for column in table.columns:
            if not column.primary_key or not isinstance(column.type, (Integer, BigInteger)):
                continue
            seq = conn.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column.name},
            ).scalar()
            if not seq:
                continue
            max_value = conn.execute(text(f'SELECT max("{column.name}") FROM "{table.name}"')).scalar()
            if max_value is None:
                conn.execute(text("SELECT setval(:seq, 1, false)"), {"seq": seq})
                reset.append({"table": table.name, "column": column.name, "sequence": seq, "value": 1})
            else:
                conn.execute(text("SELECT setval(:seq, :value, true)"), {"seq": seq, "value": int(max_value)})
                reset.append({"table": table.name, "column": column.name, "sequence": seq, "value": int(max_value)})
    return reset


def _analyze(conn, table_names: Iterable[str]) -> None:
    autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
    for table_name in table_names:
        autocommit.execute(text(f'ANALYZE "{table_name}"'))


def _ensure_not_dangerous_url(database_url: str) -> None:
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("目标 DATABASE_URL 必须使用 postgresql+psycopg:// 前缀")


def migrate(args: argparse.Namespace) -> Dict[str, Any]:
    source_path = Path(args.sqlite).resolve()
    if not source_path.is_file():
        raise RuntimeError(f"源库不存在: {source_path}")
    database_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("缺少目标 PostgreSQL DATABASE_URL；请传 --database-url 或设置环境变量")
    _ensure_not_dangerous_url(database_url)

    sqlite_conn = _connect_sqlite_readonly(source_path)
    started = time.monotonic()
    try:
        quick = _quick_check(sqlite_conn)
        if quick.lower() != "ok":
            raise RuntimeError(f"源库 quick_check={quick!r}，拒绝迁移")
        source_tables = _sqlite_tables(sqlite_conn)
        business_tables = _business_source_tables(source_tables)
        if not business_tables:
            raise RuntimeError("源库没有业务表，拒绝迁移")
        source_counts = {name: _count_sqlite(sqlite_conn, name) for name in business_tables}
        if sum(source_counts.values()) <= 0:
            raise RuntimeError("源库业务表总行数为 0，拒绝迁移")

        Base, create_pg_indexes = _load_models()
        metadata_tables = {table.name: table for table in Base.metadata.sorted_tables}
        target_names = [name for name in business_tables if name in metadata_tables]
        skipped = {
            "derived": [name for name in sorted(source_tables) if _is_derived_table(name)],
            "not_in_model": [name for name in business_tables if name not in metadata_tables],
            "missing_in_source": [name for name in metadata_tables if name not in source_tables],
        }
        if not target_names:
            raise RuntimeError("源库业务表与当前模型没有交集，拒绝迁移")

        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.begin() as pg:
            if args.create_schema:
                pg.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                Base.metadata.create_all(bind=pg)
                create_pg_indexes(pg)
            existing = set(inspect(pg).get_table_names())
            missing_target = [name for name in target_names if name not in existing]
            if missing_target:
                raise RuntimeError(f"目标库缺少表，请先执行 Alembic baseline 或加 --create-schema: {missing_target}")
            existing_counts = {name: _target_count(pg, name) for name in target_names}
            nonempty = {name: count for name, count in existing_counts.items() if count > 0}
            if nonempty and not args.replace_target:
                raise RuntimeError(f"目标库非空，拒绝覆盖；如确认离线迁移请加 --replace-target: {nonempty}")
            if args.replace_target:
                _truncate_target(pg, list(reversed([table.name for table in Base.metadata.sorted_tables if table.name in target_names])))

        imported_counts: Dict[str, int] = {}
        chunk_size = max(100, int(args.chunk_size or 1000))
        with engine.begin() as pg:
            for name in target_names:
                table = metadata_tables[name]
                imported = 0
                for rows in _iter_sqlite_rows(sqlite_conn, name, chunk_size):
                    payload = _convert_rows(rows, table)
                    if payload:
                        pg.execute(table.insert(), payload)
                        imported += len(payload)
                imported_counts[name] = imported
                print(f"[迁移] {name}: {imported}/{source_counts[name]}", flush=True)
            sequence_report = _reset_sequences(pg, [metadata_tables[name] for name in target_names])
            create_pg_indexes(pg)

        with engine.connect() as pg:
            _analyze(pg, target_names)
            target_counts = {name: _target_count(pg, name) for name in target_names}

        diffs = {
            name: {"source": source_counts[name], "target": target_counts.get(name, 0)}
            for name in target_names
            if int(source_counts[name]) != int(target_counts.get(name, 0))
        }
        report = {
            "ok": not diffs,
            "source": str(source_path),
            "quick_check": quick,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "source_table_count": len(source_tables),
            "business_table_count": len(business_tables),
            "migrated_table_count": len(target_names),
            "source_counts": source_counts,
            "target_counts": target_counts,
            "diffs": diffs,
            "skipped": skipped,
            "sequence_report": sequence_report,
            "derived_note": "FTS/shadow 派生表已跳过，PostgreSQL pg_trgm 索引已重建",
        }
        if args.report:
            report_path = Path(args.report)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if diffs:
            raise RuntimeError(f"迁移行数校验失败: {json.dumps(diffs, ensure_ascii=False)}")
        return report
    finally:
        sqlite_conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate KikoeruManager SQLite data to PostgreSQL")
    parser.add_argument("--sqlite", default=str(DEFAULT_SOURCE), help="源 SQLite 文件，默认使用 cache.db.fixed")
    parser.add_argument("--database-url", default="", help="目标 PostgreSQL URL；默认读取 DATABASE_URL")
    parser.add_argument("--replace-target", action="store_true", help="导入前清空目标业务表")
    parser.add_argument("--create-schema", action="store_true", help="导入前按当前模型创建表和 pg_trgm 索引")
    parser.add_argument("--chunk-size", type=int, default=1000, help="批量插入行数")
    parser.add_argument("--report", default="", help="可选 JSON 报告输出路径")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = migrate(args)
    except Exception as exc:
        print(f"[迁移] 失败: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
