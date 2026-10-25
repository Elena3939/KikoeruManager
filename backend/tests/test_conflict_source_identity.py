"""同 RJ 的不同来源必须独立进入问题作品，相同来源重复上报保持幂等。"""

import pytest

from app.core import classifier as classifier_module
from app.models.database import ConflictWork


@pytest.mark.parametrize("conflict_type", ["DUPLICATE", "LANGUAGE_CONFLICT", "PROCESS_FAILED"])
def test_same_rj_keeps_distinct_sources(db_session, monkeypatch, tmp_path, conflict_type):
    sources = [tmp_path / "RJ01406188.zip", tmp_path / "特典.zip"]
    for source in sources:
        source.write_bytes(b"archive")

    def get_db():
        yield db_session

    monkeypatch.setattr(classifier_module, "get_db", get_db)
    classifier = classifier_module.SmartClassifier()
    for index, source in enumerate(sources):
        classifier._add_to_conflict_works(
            f"task-{index}", "RJ01406188", conflict_type, "", str(source), {},
        )
    classifier._add_to_conflict_works(
        "task-0", "RJ01406188", conflict_type, "", str(sources[0]), {},
    )

    rows = db_session.query(ConflictWork).all()
    assert {(row.task_id, row.new_path) for row in rows} == {
        (f"task-{index}", str(source)) for index, source in enumerate(sources)
    }
