"""桌面版内置运行环境引导的纯函数测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from app.core.embedded_runtime import (
    _extract_pg_zip,
    _find_pg_bin,
    _find_redis_server,
    _write_database_config,
    bootstrap_embedded_runtime,
)


class EmbeddedRuntimeTest(unittest.TestCase):
    def test_write_database_config_preserves_other_sections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="km_test_cfg_") as tmp:
            cfg = Path(tmp) / "config.yaml"
            cfg.write_text(
                "storage:\n"
                "  library_path: D:/asmr\n"
                "database:\n"
                "  host: 127.0.0.1\n"
                "  port: 5432\n"
                "  database: kikoerumanager\n"
                "  username: kikoerumanager\n"
                "  password: ''\n"
                "  sslmode: prefer\n",
                encoding="utf-8",
            )
            _write_database_config(
                cfg,
                host="127.0.0.1",
                port=5432,
                database="kikoerumanager",
                username="kikoerumanager",
                password="secret",
                sslmode="prefer",
            )
            data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
            self.assertEqual(data["database"]["password"], "secret")
            self.assertEqual(data["storage"]["library_path"], "D:/asmr")

    def test_bootstrap_skips_external_services(self) -> None:
        with tempfile.TemporaryDirectory(prefix="km_test_skip_") as tmp:
            cfg = Path(tmp) / "config.yaml"
            cfg.write_text(
                "database:\n"
                "  host: 10.0.0.1\n"
                "  port: 5432\n"
                "  database: kikoerumanager\n"
                "  username: kikoerumanager\n"
                "  password: ''\n"
                "  sslmode: prefer\n"
                "redis:\n"
                "  enabled: false\n"
                "  required: false\n"
                "  url: redis://localhost:6379/0\n",
                encoding="utf-8",
            )
            old_db = os.environ.pop("DATABASE_URL", None)
            old_redis = os.environ.pop("KIKOERUMANAGER_REDIS_URL", None)
            try:
                summary = bootstrap_embedded_runtime(
                    data_dir=tmp, config_path=str(cfg)
                )
            finally:
                if old_db is not None:
                    os.environ["DATABASE_URL"] = old_db
                if old_redis is not None:
                    os.environ["KIKOERUMANAGER_REDIS_URL"] = old_redis
            self.assertIsNone(summary["postgresql"])
            self.assertIsNone(summary["redis"])

    def test_find_binaries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="km_test_bin_") as tmp:
            root = Path(tmp)
            pg_bin = root / "postgres" / "pgsql" / "bin"
            pg_bin.mkdir(parents=True)
            for name in ("psql.exe", "pg_ctl.exe", "initdb.exe"):
                (pg_bin / name).write_bytes(b"fake")
            self.assertEqual(_find_pg_bin([root / "postgres"]), pg_bin)

            redis_bin = root / "redis"
            redis_bin.mkdir()
            (redis_bin / "redis-server.exe").write_bytes(b"fake")
            self.assertEqual(
                _find_redis_server([root / "redis"]), redis_bin / "redis-server.exe"
            )

    def test_extract_pg_zip_only_runtime_dirs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="km_test_pgzip_") as tmp:
            root = Path(tmp)
            zip_path = root / "fake-postgres.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("pgsql/bin/psql.exe", "x")
                zf.writestr("pgsql/lib/libpq.dll", "x")
                zf.writestr("pgsql/share/postgres.bki", "x")
                zf.writestr("pgsql/doc/readme.txt", "x")
                zf.writestr("pgsql/pgAdmin 4/web/app.py", "x")
            out = root / "out"
            _extract_pg_zip(zip_path, out)
            files = sorted(
                str(p.relative_to(out)).replace("\\", "/")
                for p in out.rglob("*")
                if p.is_file()
            )
            self.assertEqual(
                files,
                [
                    "pgsql/bin/psql.exe",
                    "pgsql/lib/libpq.dll",
                    "pgsql/share/postgres.bki",
                ],
            )


if __name__ == "__main__":
    unittest.main()
