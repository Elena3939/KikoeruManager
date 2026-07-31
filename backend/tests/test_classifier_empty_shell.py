from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import classifier as classifier_module
from app.core import library_index as library_index_module
from app.core.classifier import InventoryEmptyShellChangedError, SmartClassifier
from app.core.task_engine import Task, TaskType


class _MutationService:
    def __init__(self):
        self.prepared = []
        self.started = []
        self.finalized = []
        self.reconcile_required = []

    def prepare(self, **kwargs):
        self.prepared.append(kwargs)
        return SimpleNamespace(operation_id="empty-shell-operation")

    def mark_filesystem_started(self, operation_id):
        self.started.append(operation_id)

    def finalize(self, operation_id, **kwargs):
        self.finalized.append((operation_id, kwargs))
        return kwargs

    def mark_reconcile_required(self, operation_id, error):
        self.reconcile_required.append((operation_id, str(error)))


class _LibraryManager:
    def __init__(self, library, hits):
        self.library = library
        self.hits = hits

    def get_library_definition(self, library_id):
        return self.library if library_id == self.library.id else None

    def find_rj_in_ready_index(self, rjcodes, **_kwargs):
        return {str(rjcodes[0]): list(self.hits)}

    def _index_relative_path(self, library, absolute_path):
        try:
            return Path(absolute_path).resolve().relative_to(
                Path(library.root_path).resolve()
            ).as_posix()
        except ValueError:
            return None


def _task(library_id):
    return Task(
        task_type=TaskType.AUTO_PROCESS,
        source_path="archive.7z",
        auto_classify=True,
        metadata={
            "target_library_id": library_id,
            "replace_inventory_empty_shell": True,
        },
    )


@pytest.mark.asyncio
async def test_replace_inventory_empty_shell_same_path_is_atomic(
    tmp_path,
    monkeypatch,
):
    library_root = tmp_path / "library"
    target_dir = library_root / "maker"
    old_path = target_dir / "[maker][RJ01582654]"
    old_path.mkdir(parents=True)
    source = tmp_path / "temp" / old_path.name
    source.mkdir(parents=True)
    (source / "track.mp3").write_bytes(b"audio")

    library = SimpleNamespace(
        id="local",
        type="local",
        root_path=str(library_root),
    )
    manager = _LibraryManager(library, [{
        "library_id": library.id,
        "library_type": "local",
        "path": str(old_path),
    }])
    mutation = _MutationService()
    monkeypatch.setattr(classifier_module, "get_library_manager", lambda: manager)
    monkeypatch.setattr(
        library_index_module,
        "get_library_index_mutation_service",
        lambda: mutation,
    )

    classifier = SmartClassifier()
    monkeypatch.setattr(
        classifier,
        "_apply_classification_rules",
        lambda *_args: str(target_dir),
    )
    monkeypatch.setattr(classifier, "_update_library_snapshot", lambda *_args: None)
    notify = []
    monkeypatch.setattr(
        classifier,
        "_notify_library_index_after_classify",
        lambda *_args, **_kwargs: notify.append(True),
    )

    task = _task(library.id)
    result = await classifier.classify_and_move(
        str(source),
        {"rjcode": "RJ01582654"},
        task,
    )

    assert Path(result) == old_path
    assert (old_path / "track.mp3").read_bytes() == b"audio"
    assert not source.exists()
    assert task.task_metadata["inventory_empty_shell_status"] == "replaced"
    assert mutation.started == ["empty-shell-operation"]
    effects = mutation.finalized[0][1]["actual_effects_by_library"][library.id]
    assert [effect["kind"] for effect in effects] == ["delete", "reconcile"]
    assert notify == []


@pytest.mark.asyncio
async def test_replace_inventory_empty_shell_keeps_old_when_import_fails(
    tmp_path,
    monkeypatch,
):
    library_root = tmp_path / "library"
    old_path = library_root / "old-maker" / "[old][RJ01582654]"
    old_path.mkdir(parents=True)
    target_dir = library_root / "new-maker"
    source = tmp_path / "temp" / "[new][RJ01582654]"
    source.mkdir(parents=True)
    (source / "track.mp3").write_bytes(b"audio")

    library = SimpleNamespace(
        id="local",
        type="local",
        root_path=str(library_root),
    )
    manager = _LibraryManager(library, [{
        "library_id": library.id,
        "library_type": "local",
        "path": str(old_path),
    }])
    mutation = _MutationService()
    monkeypatch.setattr(classifier_module, "get_library_manager", lambda: manager)
    monkeypatch.setattr(
        library_index_module,
        "get_library_index_mutation_service",
        lambda: mutation,
    )

    classifier = SmartClassifier()
    monkeypatch.setattr(
        classifier,
        "_apply_classification_rules",
        lambda *_args: str(target_dir),
    )
    monkeypatch.setattr(
        classifier,
        "_move_with_rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("move failed")),
    )

    with pytest.raises(RuntimeError, match="move failed"):
        await classifier.classify_and_move(
            str(source),
            {"rjcode": "RJ01582654"},
            _task(library.id),
        )

    assert old_path.is_dir()
    assert not any(old_path.iterdir())
    assert source.is_dir()
    assert mutation.finalized == []
    assert mutation.reconcile_required


@pytest.mark.asyncio
async def test_replace_inventory_empty_shell_deletes_old_after_different_path_import(
    tmp_path,
    monkeypatch,
):
    library_root = tmp_path / "library"
    old_path = library_root / "old-maker" / "[old][RJ01582654]"
    old_path.mkdir(parents=True)
    target_dir = library_root / "new-maker"
    source = tmp_path / "temp" / "[new][RJ01582654]"
    source.mkdir(parents=True)
    (source / "track.mp3").write_bytes(b"audio")

    library = SimpleNamespace(
        id="local",
        type="local",
        root_path=str(library_root),
    )
    manager = _LibraryManager(library, [{
        "library_id": library.id,
        "library_type": "local",
        "path": str(old_path),
    }])
    mutation = _MutationService()
    monkeypatch.setattr(classifier_module, "get_library_manager", lambda: manager)
    monkeypatch.setattr(
        library_index_module,
        "get_library_index_mutation_service",
        lambda: mutation,
    )

    classifier = SmartClassifier()
    monkeypatch.setattr(
        classifier,
        "_apply_classification_rules",
        lambda *_args: str(target_dir),
    )
    monkeypatch.setattr(classifier, "_update_library_snapshot", lambda *_args: None)
    monkeypatch.setattr(
        classifier,
        "_notify_library_index_after_classify",
        lambda *_args, **_kwargs: pytest.fail("空壳替换不应重复通知索引"),
    )

    result = await classifier.classify_and_move(
        str(source),
        {"rjcode": "RJ01582654"},
        _task(library.id),
    )

    assert Path(result) == target_dir / source.name
    assert Path(result, "track.mp3").exists()
    assert not old_path.exists()
    effects = mutation.finalized[0][1]["actual_effects_by_library"][library.id]
    assert [effect["kind"] for effect in effects] == ["delete", "reconcile"]


@pytest.mark.asyncio
async def test_replace_inventory_empty_shell_stops_when_old_dir_gains_file(
    tmp_path,
    monkeypatch,
):
    library_root = tmp_path / "library"
    old_path = library_root / "old-maker" / "[old][RJ01582654]"
    old_path.mkdir(parents=True)
    target_dir = library_root / "new-maker"
    source = tmp_path / "temp" / "[new][RJ01582654]"
    source.mkdir(parents=True)
    (source / "track.mp3").write_bytes(b"audio")

    library = SimpleNamespace(
        id="local",
        type="local",
        root_path=str(library_root),
    )
    manager = _LibraryManager(library, [{
        "library_id": library.id,
        "library_type": "local",
        "path": str(old_path),
    }])
    mutation = _MutationService()
    monkeypatch.setattr(classifier_module, "get_library_manager", lambda: manager)
    monkeypatch.setattr(
        library_index_module,
        "get_library_index_mutation_service",
        lambda: mutation,
    )

    classifier = SmartClassifier()
    monkeypatch.setattr(
        classifier,
        "_apply_classification_rules",
        lambda *_args: str(target_dir),
    )
    original_move = classifier._move_with_rename

    def move_then_fill_old(*args, **kwargs):
        result = original_move(*args, **kwargs)
        (old_path / "appeared.txt").write_text("late", encoding="utf-8")
        return result

    monkeypatch.setattr(classifier, "_move_with_rename", move_then_fill_old)

    with pytest.raises(InventoryEmptyShellChangedError) as exc_info:
        await classifier.classify_and_move(
            str(source),
            {"rjcode": "RJ01582654"},
            _task(library.id),
        )

    assert old_path.is_dir()
    assert (old_path / "appeared.txt").exists()
    assert Path(exc_info.value.preserved_path).is_dir()
    actual = mutation.finalized[0][1]["actual_effects_by_library"][library.id]
    assert [effect["kind"] for effect in actual] == ["reconcile"]
