import tempfile

from app.core import classifier as classifier_module
from app.core.classifier import SmartClassifier
from app.core.json_safety import safe_json_value
from app.models.database import ConflictWork


def test_safe_json_value_escapes_surrogates_recursively():
    payload = {
        "garbled_filename_sample": "RJ00000011_\udce4\udcb8\udcad.mp3",
        "garbled_filename_top_samples": [
            {"name": "track_\udce3.wav", "score": 100.0},
        ],
    }

    safe_payload = safe_json_value(payload)

    assert safe_payload["garbled_filename_sample"] == "RJ00000011_\\udce4\\udcb8\\udcad.mp3"
    assert safe_payload["garbled_filename_top_samples"][0]["name"] == "track_\\udce3.wav"


def test_add_extract_failed_conflict_escapes_garbled_metadata_before_db_write(db_session, monkeypatch):
    temp_dir = tempfile.TemporaryDirectory()
    source = f"{temp_dir.name}/RJ00000011.zip"
    with open(source, "wb") as fp:
        fp.write(b"zip")

    def fake_get_db():
        yield db_session

    monkeypatch.setattr(classifier_module, "get_db", fake_get_db)

    SmartClassifier()._add_to_conflict_works(
        "task-1",
        "RJ00000011",
        "EXTRACT_FAILED",
        "",
        source,
        {
            "failure_stage": "extract",
            "error_message": "解压失败：文件名乱码",
            "garbled_filename_sample": "bad_\udce4\udcb8.mp3",
            "garbled_filename_top_samples": [
                {"name": "bad_\udce4\udcb8.mp3", "score": 100.0, "garbled": True},
            ],
        },
    )

    row = db_session.query(ConflictWork).filter(ConflictWork.rjcode == "RJ00000011").one()
    assert row.new_metadata["garbled_filename_sample"] == "bad_\\udce4\\udcb8.mp3"
    assert row.new_metadata["garbled_filename_top_samples"][0]["name"] == "bad_\\udce4\\udcb8.mp3"
    temp_dir.cleanup()
