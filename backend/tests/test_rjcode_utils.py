from app.core.rjcode_utils import (
    extract_rjcode,
    extract_rjcode_from_path,
    scan_existing_folder_candidates,
)


def _mkdir(path):
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_extract_rjcode_supports_prefixed_and_numeric_names():
    assert extract_rjcode("RJ01234567 标题") == "RJ01234567"
    assert extract_rjcode("39.RJ01570159") == "RJ01570159"
    assert extract_rjcode("01503161") == "RJ01503161"
    assert extract_rjcode("社团名") is None


def test_extract_rjcode_from_path_searches_nested_folders(tmp_path):
    root = _mkdir(tmp_path / "existing" / "社团A")
    _mkdir(root / "RJ01234567 作品")

    assert extract_rjcode_from_path(str(root)) == "RJ01234567"


def test_scan_existing_folder_candidates_returns_top_level_rj_folder(tmp_path):
    existing_root = _mkdir(tmp_path / "existing")
    work_dir = _mkdir(existing_root / "RJ01234567 作品")
    (work_dir / "track01.wav").write_text("audio", encoding="utf-8")

    candidates = scan_existing_folder_candidates(str(existing_root))

    assert len(candidates) == 1
    assert candidates[0]["path"] == str(work_dir)
    assert candidates[0]["rjcode"] == "RJ01234567"
    assert candidates[0]["relative_path"] == "RJ01234567 作品"
    assert candidates[0]["is_nested"] is False


def test_scan_existing_folder_candidates_finds_circle_nested_rj_folder(tmp_path):
    existing_root = _mkdir(tmp_path / "existing")
    work_dir = _mkdir(existing_root / "社团A" / "RJ01234567 作品")
    (work_dir / "track01.wav").write_text("audio", encoding="utf-8")

    candidates = scan_existing_folder_candidates(str(existing_root))

    assert len(candidates) == 1
    assert candidates[0]["path"] == str(work_dir)
    assert candidates[0]["rjcode"] == "RJ01234567"
    assert candidates[0]["source_root_name"] == "社团A"
    assert candidates[0]["relative_path"] == "社团A/RJ01234567 作品"
    assert candidates[0]["is_nested"] is True
    assert candidates[0]["scan_depth"] == 2


def test_scan_existing_folder_candidates_keeps_multiple_nested_works_separate(tmp_path):
    existing_root = _mkdir(tmp_path / "existing")
    first = _mkdir(existing_root / "社团A" / "RJ01111111 作品1")
    second = _mkdir(existing_root / "社团A" / "RJ02222222 作品2")
    _mkdir(existing_root / "社团B" / "RJ03333333 作品3")

    candidates = scan_existing_folder_candidates(str(existing_root))
    by_rjcode = {item["rjcode"]: item for item in candidates}

    assert set(by_rjcode) == {"RJ01111111", "RJ02222222", "RJ03333333"}
    assert by_rjcode["RJ01111111"]["path"] == str(first)
    assert by_rjcode["RJ02222222"]["path"] == str(second)
    assert by_rjcode["RJ01111111"]["source_root_name"] == "社团A"
    assert by_rjcode["RJ02222222"]["source_root_name"] == "社团A"


def test_scan_existing_folder_candidates_skips_unrecognized_top_folder(tmp_path):
    existing_root = _mkdir(tmp_path / "existing")
    unknown = _mkdir(existing_root / "社团A" / "没有RJ")
    (unknown / "note.txt").write_text("no rj here", encoding="utf-8")

    candidates = scan_existing_folder_candidates(str(existing_root))

    assert candidates == []


def test_scan_existing_folder_candidates_does_not_return_circle_folder_when_nested_work_exists(tmp_path):
    existing_root = _mkdir(tmp_path / "existing")
    circle = _mkdir(existing_root / "Whisp")
    work_dir = _mkdir(circle / "[Whisp][RJ01234567] 作品")
    (work_dir / "track01.wav").write_text("audio", encoding="utf-8")

    candidates = scan_existing_folder_candidates(str(existing_root))

    assert len(candidates) == 1
    assert candidates[0]["path"] == str(work_dir)
    assert candidates[0]["rjcode"] == "RJ01234567"
    assert candidates[0]["source_root_name"] == "Whisp"
