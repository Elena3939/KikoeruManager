"""投影计时覆盖惰性构建和数据库操作。"""
import time

from sqlalchemy.sql.dml import Insert

from app.core.circle_completion_projection import publish_projection
from app.core.request_performance import request_metrics


def test_projection_metrics_measure_lazy_rows_and_writes():
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, *args):
            if isinstance(statement, Insert):
                time.sleep(0.01)

        def get(self, *args):
            return None

        def add(self, value):
            pass

        def flush(self):
            pass

        def commit(self):
            time.sleep(0.01)

    def rows():
        for position in range(201):
            time.sleep(0.0001)
            yield {"position": position}

    metrics = {}
    token = request_metrics.set(metrics)
    try:
        assert publish_projection(
            "key", "circle", "v1", rows(), {"total_works": 201},
            lambda: True, session_factory=Session,
        )
    finally:
        request_metrics.reset(token)

    assert metrics["projection_row_count"] == 201
    assert metrics["projection_rows_build_ms"] >= 20
    assert metrics["projection_batch_write_ms"] >= 15
    assert metrics["projection_commit_ms"] >= 8
    assert "projection_advisory_lock_wait_ms" in metrics
