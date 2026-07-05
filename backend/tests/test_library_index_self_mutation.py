"""库存索引 self_mutation upsert 子树回归测试。

聚焦本次修复：解压入库 / rename / 上传 / 字幕 / 冲突重绑这些 in-app 写路径
完成后，索引必须立即把新子树扫进去，避免 ready 状态下索引 stale 导致跨库
搜索 0 命中。

测试矩阵：
1. upsert_subtree_local：在 ready 索引上扫新子树，find_by_rjcode 立刻命中
2. rename 链路：先 upsert 旧名，delete 旧 + upsert 新后旧 RJ 找不到、新 RJ 命中
3. 越界保护：subtree 不在 library_root 下时抛 ValueError
4. 索引未就绪保护：is_ready=False 时 upsert_subtree_local 直接返回 0
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

# 让 pytest 直接运行 backend/tests 时也能 import app
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.database import Base, LibraryIndexStatus  # noqa: E402
from app.core.library_index.service import LibraryIndexService  # noqa: E402
from app.core.library_index.snapshot_store import SnapshotStore  # noqa: E402
from app.core.library_index.types import IndexEntry  # noqa: E402
from postgres_test_utils import create_postgres_test_engine, reset_postgres_schema  # noqa: E402


@pytest.fixture
def isolated_index(tmp_path):
    """每个测试一份 PostgreSQL 测试库 schema + 临时目录，互不污染。"""
    engine = create_postgres_test_engine()
    reset_postgres_schema(engine)
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    store = SnapshotStore(session_factory=SessionTesting)
    service = LibraryIndexService(store=store)
    library_root = tmp_path / "library"
    library_root.mkdir()
    yield {
        "engine": engine,
        "store": store,
        "service": service,
        "library_root": library_root,
    }
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _create_rj_dir(library_root: Path, rjcode: str, *, content: str = "audio") -> Path:
    rj_dir = library_root / "ぬまぬま" / f"[ぬまぬま][{rjcode}](CV 山田じぇみ子)"
    rj_dir.mkdir(parents=True)
    (rj_dir / f"{rjcode}_track1.mp3").write_text(content, encoding="utf-8")
    return rj_dir


def _mark_index_ready(store: SnapshotStore, library_id: str) -> None:
    """跳过 rebuild 直接置 ready，模拟"用户上次手动重建过、之后没再扫"的场景。"""
    store.upsert_status(library_id, status="ready", watcher_mode="disabled")


def _backdate_index_status(store: SnapshotStore, library_id: str, updated_at_ms: int) -> None:
    with store._write_session(invalidate_children_total_cache=False) as db:  # noqa: SLF001
        row = db.query(LibraryIndexStatus).filter(LibraryIndexStatus.library_id == library_id).first()
        assert row is not None
        row.updated_at = updated_at_ms
        db.flush()


def _manual_entry(
    relative_path: str,
    *,
    library_id: str,
    rjcode: str,
    entry_type: str = "dir",
    size: int = 123,
    file_count: int | None = None,
) -> IndexEntry:
    return IndexEntry(
        library_id=library_id,
        entry_type=entry_type,
        relative_path=relative_path,
        absolute_path=f"/library/{relative_path}",
        name=relative_path.rsplit("/", 1)[-1],
        rjcode=rjcode,
        parent_path=relative_path.rsplit("/", 1)[0] if "/" in relative_path else "",
        size=size if entry_type == "file" else max(0, int(size or 0)),
        file_count=0 if entry_type == "file" else max(0, int(file_count if file_count is not None else 0)),
        mtime=1000,
        depth=relative_path.count("/") + 1 if relative_path else 0,
        indexed_at=1000,
    )


# ---------- Case 1：upsert 后跨库搜索能命中 ----------

def test_upsert_subtree_local_lets_find_by_rjcode_hit_immediately(isolated_index):
    """复现用户截图的核心场景：

    库索引已 ready，但解压入库后没人通知索引；这次修复让 upsert_subtree_local
    立刻把新 RJ 扫进去，find_by_rjcode 必须命中。
    """
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_local_1"

    # 模拟：库存第一次手工重建过，之后没有任何变更
    _mark_index_ready(store, library_id)
    assert service.find_by_rjcode("RJ01392137", library_id) == []

    # 用户解压入库：磁盘上凭空多出一个 RJ 目录（索引此时是 stale）
    rj_dir = _create_rj_dir(library_root, "RJ01392137")

    # 修复点：classify_and_move 完成后会调到 upsert_subtree_local
    written = service.upsert_subtree_local(
        library_id, str(library_root), str(rj_dir),
    )
    assert written >= 2  # 目录自身 + 至少 1 个文件

    hits = service.find_by_rjcode("RJ01392137", library_id)
    assert len(hits) == 1
    assert hits[0].rjcode == "RJ01392137"
    assert hits[0].entry_type == "dir"
    # 用户搜索时拿到的 absolute_path 必须是真实落地路径，能直接打开
    assert os.path.normcase(hits[0].absolute_path) == os.path.normcase(str(rj_dir))


# ---------- Case 2：rename 不再留旧 RJ 残影 ----------

def test_rename_replaces_old_rj_with_new_rj_in_index(isolated_index):
    """rename 之后旧 RJ 应彻底从索引消失，新 RJ 立刻可搜。

    现有代码先 delete 旧子树，再 upsert 新子树（本次修复加上的第二步）。
    """
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_local_2"

    _mark_index_ready(store, library_id)

    # 初始：先 upsert RJ_OLD 让索引里有这条
    old_rj_dir = _create_rj_dir(library_root, "RJ00000001")
    service.upsert_subtree_local(library_id, str(library_root), str(old_rj_dir))
    assert len(service.find_by_rjcode("RJ00000001", library_id)) == 1

    # 模拟 rename：磁盘上把 RJ_OLD 改名成 RJ_NEW（os.rename 等价）
    new_rj_dir = old_rj_dir.parent / f"[ぬまぬま][RJ00000002](CV 山田じぇみ子)"
    old_rj_dir.rename(new_rj_dir)

    # 模拟 _local_rename：先 delete 旧子树
    relative_old = os.path.relpath(str(old_rj_dir), str(library_root)).replace("\\", "/")
    service.handle_self_mutation_delete(library_id, relative_old)
    # 再 upsert 新子树（本次修复点）
    service.upsert_subtree_local(library_id, str(library_root), str(new_rj_dir))

    assert service.find_by_rjcode("RJ00000001", library_id) == []
    new_hits = service.find_by_rjcode("RJ00000002", library_id)
    assert len(new_hits) == 1
    assert new_hits[0].rjcode == "RJ00000002"


# ---------- Case 3：越界保护 ----------

def test_upsert_subtree_outside_library_root_raises_value_error(isolated_index, tmp_path):
    """subtree 不在 library_root 下时立即抛 ValueError，避免污染索引（生成 ../ 形式 relative_path）。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_local_3"

    _mark_index_ready(store, library_id)

    # 在 library_root 外创建一个伪造的"子树"
    foreign_dir = tmp_path / "outside_library" / "[fake][RJ99999999]"
    foreign_dir.mkdir(parents=True)
    (foreign_dir / "track.mp3").write_text("x", encoding="utf-8")

    with pytest.raises(ValueError):
        service.upsert_subtree_local(library_id, str(library_root), str(foreign_dir))


# ---------- Case 4：索引未就绪时不应触发任何写操作 ----------

def test_upsert_subtree_skips_when_index_not_ready(isolated_index):
    """索引在 idle / syncing / error 状态时，upsert_subtree_local 直接返回 0。

    避免把"半完成"的子树写进去给后续 ready 切换造成数据竞态。
    """
    service: LibraryIndexService = isolated_index["service"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_local_4"

    # 不调 _mark_index_ready：状态是 idle（默认）
    rj_dir = _create_rj_dir(library_root, "RJ00000003")

    written = service.upsert_subtree_local(
        library_id, str(library_root), str(rj_dir),
    )
    assert written == 0
    assert service.find_by_rjcode("RJ00000003", library_id) == []


def test_syncing_with_existing_snapshot_is_still_readable(isolated_index):
    """远程库重建期间旧快照仍可读，浏览 / 搜索不能退回群晖 walk。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_remote_snapshot"

    _mark_index_ready(store, library_id)
    rj_dir = _create_rj_dir(library_root, "RJ00000004")
    service.upsert_subtree_local(library_id, str(library_root), str(rj_dir))
    store.upsert_status(library_id, status="syncing", watcher_mode="disabled")

    assert service.is_ready(library_id) is False
    assert service.has_usable_snapshot(library_id) is True
    assert len(service.find_by_rjcode("RJ00000004", library_id)) == 1


def test_syncing_without_snapshot_is_not_readable_until_manual_rebuild(isolated_index):
    """没有任何旧快照时，读路径不可用，但不会自动触发重建。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_remote_empty"

    store.upsert_status(library_id, status="syncing", watcher_mode="disabled")

    assert service.has_usable_snapshot(library_id) is False


# ---------- Case 5：跨库存移动场景 ----------

def test_cross_library_move_synchronizes_both_indexes(isolated_index, tmp_path):
    """模拟前端「把 RJ 移到其他库存」：源库 delete 旧子树、目标库 upsert 新子树。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    src_root: Path = isolated_index["library_root"]
    dest_root = tmp_path / "library_dest"
    dest_root.mkdir()
    src_id = "lib_src"
    dest_id = "lib_dest"
    _mark_index_ready(store, src_id)
    _mark_index_ready(store, dest_id)

    # 初始：源库里有 RJ
    rj_dir = _create_rj_dir(src_root, "RJ00000010")
    service.upsert_subtree_local(src_id, str(src_root), str(rj_dir))
    assert len(service.find_by_rjcode("RJ00000010", src_id)) == 1

    # 模拟移动：物理上把目录移过去
    new_parent = dest_root / "ぬまぬま"
    new_parent.mkdir()
    new_dir = new_parent / rj_dir.name
    rj_dir.rename(new_dir)

    # 模拟 _move_local_items_sync 的索引同步两步
    rel_old = os.path.relpath(str(rj_dir), str(src_root)).replace("\\", "/")
    service.handle_self_mutation_batch(src_id, deletes=[rel_old])
    service.upsert_subtree_local(dest_id, str(dest_root), str(new_dir))

    assert service.find_by_rjcode("RJ00000010", src_id) == []
    dest_hits = service.find_by_rjcode("RJ00000010", dest_id)
    assert len(dest_hits) == 1
    assert os.path.normcase(dest_hits[0].absolute_path) == os.path.normcase(str(new_dir))


def test_same_library_move_rewrites_index_without_rescan(isolated_index):
    """同库目录移动只改索引路径前缀，不重新扫上万文件。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_move_same"

    _mark_index_ready(store, library_id)
    old_dir = _create_rj_dir(library_root, "RJ00000020")
    source_parent_rel = os.path.relpath(str(old_dir.parent), str(library_root)).replace("\\", "/")
    store.bulk_upsert([
        _manual_entry(source_parent_rel, library_id=library_id, rjcode="", size=0, file_count=0),
    ])
    service.upsert_subtree_local(library_id, str(library_root), str(old_dir))
    source_parent_before = store.get_entry(library_id, source_parent_rel)
    assert source_parent_before is not None
    assert source_parent_before.size == len("audio")
    assert source_parent_before.file_count == 1
    old_status = service.get_status(library_id)

    new_parent = library_root / "移動先"
    new_parent.mkdir()
    store.bulk_upsert([
        _manual_entry("移動先", library_id=library_id, rjcode="", size=0, file_count=0),
    ])
    old_status = service.get_status(library_id)
    new_dir = new_parent / old_dir.name
    old_dir.rename(new_dir)
    old_rel = os.path.relpath(str(old_dir), str(library_root)).replace("\\", "/")
    new_rel = os.path.relpath(str(new_dir), str(library_root)).replace("\\", "/")

    moved = service.handle_self_mutation_move(
        source_library_id=library_id,
        target_library_id=library_id,
        old_relative_path=old_rel,
        new_relative_path=new_rel,
        old_absolute_path=str(old_dir),
        new_absolute_path=str(new_dir),
    )

    assert moved >= 2
    assert service.find_by_rjcode("RJ00000020", library_id)[0].relative_path == new_rel
    assert store.get_entry(library_id, old_rel) is None
    source_parent_after = store.get_entry(library_id, source_parent_rel)
    target_parent_after = store.get_entry(library_id, "移動先")
    assert source_parent_after is not None
    assert source_parent_after.size == 0
    assert source_parent_after.file_count == 0
    assert target_parent_after is not None
    assert target_parent_after.size == len("audio")
    assert target_parent_after.file_count == 1
    moved_file = store.get_entry(library_id, f"{new_rel}/RJ00000020_track1.mp3")
    assert moved_file is not None
    assert os.path.normcase(moved_file.absolute_path) == os.path.normcase(str(new_dir / "RJ00000020_track1.mp3"))
    new_status = service.get_status(library_id)
    assert new_status is not None and old_status is not None
    assert new_status.total_entries == old_status.total_entries
    assert new_status.total_size_bytes == old_status.total_size_bytes


def test_cross_library_move_copies_index_snapshot_without_rescan(isolated_index, tmp_path):
    """跨库移动用 INSERT...SELECT 复制旧索引快照，不依赖目标文件系统扫描。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    src_root: Path = isolated_index["library_root"]
    dest_root = tmp_path / "library_dest_fast"
    dest_root.mkdir()
    src_id = "lib_move_src"
    dest_id = "lib_move_dest"
    _mark_index_ready(store, src_id)
    _mark_index_ready(store, dest_id)

    old_dir = _create_rj_dir(src_root, "RJ00000021")
    source_parent_rel = os.path.relpath(str(old_dir.parent), str(src_root)).replace("\\", "/")
    store.bulk_upsert([
        _manual_entry(source_parent_rel, library_id=src_id, rjcode="", size=0, file_count=0),
    ])
    service.upsert_subtree_local(src_id, str(src_root), str(old_dir))
    source_parent_before = store.get_entry(src_id, source_parent_rel)
    assert source_parent_before is not None
    assert source_parent_before.size == len("audio")
    assert source_parent_before.file_count == 1
    dest_parent = dest_root / "移動先"
    dest_parent.mkdir()
    store.bulk_upsert([
        _manual_entry("移動先", library_id=dest_id, rjcode="", size=0, file_count=0),
    ])
    new_dir = dest_parent / old_dir.name
    old_dir.rename(new_dir)
    old_rel = os.path.relpath(str(old_dir), str(src_root)).replace("\\", "/")
    new_rel = os.path.relpath(str(new_dir), str(dest_root)).replace("\\", "/")

    moved = service.handle_self_mutation_move(
        source_library_id=src_id,
        target_library_id=dest_id,
        old_relative_path=old_rel,
        new_relative_path=new_rel,
        old_absolute_path=str(old_dir),
        new_absolute_path=str(new_dir),
    )

    assert moved >= 2
    assert service.find_by_rjcode("RJ00000021", src_id) == []
    dest_hits = service.find_by_rjcode("RJ00000021", dest_id)
    assert len(dest_hits) == 1
    assert dest_hits[0].relative_path == new_rel
    source_parent_after = store.get_entry(src_id, source_parent_rel)
    target_parent_after = store.get_entry(dest_id, "移動先")
    assert source_parent_after is not None
    assert source_parent_after.size == 0
    assert source_parent_after.file_count == 0
    assert target_parent_after is not None
    assert target_parent_after.size == len("audio")
    assert target_parent_after.file_count == 1
    moved_file = store.get_entry(dest_id, f"{new_rel}/RJ00000021_track1.mp3")
    assert moved_file is not None
    assert os.path.normcase(moved_file.absolute_path) == os.path.normcase(str(new_dir / "RJ00000021_track1.mp3"))


def test_move_many_rewrites_multiple_same_library_subtrees_in_one_call(isolated_index):
    """批量 rename/move 入口要一次提交多个同库前缀改写。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_move_many_same"

    _mark_index_ready(store, library_id)
    old_a = _create_rj_dir(library_root, "RJ00000022")
    old_b = _create_rj_dir(library_root, "RJ00000023")
    service.upsert_subtree_local(library_id, str(library_root), str(old_a))
    service.upsert_subtree_local(library_id, str(library_root), str(old_b))
    target_parent = library_root / "批量移动"
    target_parent.mkdir()
    new_a = target_parent / old_a.name
    new_b = target_parent / old_b.name
    old_a.rename(new_a)
    old_b.rename(new_b)

    old_rel_a = os.path.relpath(str(old_a), str(library_root)).replace("\\", "/")
    old_rel_b = os.path.relpath(str(old_b), str(library_root)).replace("\\", "/")
    new_rel_a = os.path.relpath(str(new_a), str(library_root)).replace("\\", "/")
    new_rel_b = os.path.relpath(str(new_b), str(library_root)).replace("\\", "/")

    moved = service.handle_self_mutation_move_many([
        {
            "source_library_id": library_id,
            "target_library_id": library_id,
            "old_relative_path": old_rel_a,
            "new_relative_path": new_rel_a,
            "old_absolute_path": str(old_a),
            "new_absolute_path": str(new_a),
        },
        {
            "source_library_id": library_id,
            "target_library_id": library_id,
            "old_relative_path": old_rel_b,
            "new_relative_path": new_rel_b,
            "old_absolute_path": str(old_b),
            "new_absolute_path": str(new_b),
        },
    ])

    assert moved[0] >= 2
    assert moved[1] >= 2
    assert store.get_entry(library_id, old_rel_a) is None
    assert store.get_entry(library_id, old_rel_b) is None
    assert store.get_entry(library_id, new_rel_a) is not None
    assert store.get_entry(library_id, new_rel_b) is not None


def test_move_many_copies_multiple_cross_library_subtrees(isolated_index, tmp_path):
    """跨库批量移动应按库对分组，并返回每个 move 的命中数。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    src_root: Path = isolated_index["library_root"]
    dest_root = tmp_path / "library_dest_many"
    dest_root.mkdir()
    src_id = "lib_move_many_src"
    dest_id = "lib_move_many_dest"
    _mark_index_ready(store, src_id)
    _mark_index_ready(store, dest_id)

    old_a = _create_rj_dir(src_root, "RJ00000024")
    old_b = _create_rj_dir(src_root, "RJ00000025")
    service.upsert_subtree_local(src_id, str(src_root), str(old_a))
    service.upsert_subtree_local(src_id, str(src_root), str(old_b))

    target_parent = dest_root / "跨库"
    target_parent.mkdir()
    new_a = target_parent / old_a.name
    new_b = target_parent / old_b.name
    old_a.rename(new_a)
    old_b.rename(new_b)

    old_rel_a = os.path.relpath(str(old_a), str(src_root)).replace("\\", "/")
    old_rel_b = os.path.relpath(str(old_b), str(src_root)).replace("\\", "/")
    new_rel_a = os.path.relpath(str(new_a), str(dest_root)).replace("\\", "/")
    new_rel_b = os.path.relpath(str(new_b), str(dest_root)).replace("\\", "/")

    moved = service.handle_self_mutation_move_many([
        {
            "source_library_id": src_id,
            "target_library_id": dest_id,
            "old_relative_path": old_rel_a,
            "new_relative_path": new_rel_a,
            "old_absolute_path": str(old_a),
            "new_absolute_path": str(new_a),
        },
        {
            "source_library_id": src_id,
            "target_library_id": dest_id,
            "old_relative_path": old_rel_b,
            "new_relative_path": new_rel_b,
            "old_absolute_path": str(old_b),
            "new_absolute_path": str(new_b),
        },
    ])

    assert moved[0] >= 2
    assert moved[1] >= 2
    assert service.find_by_rjcode("RJ00000024", src_id) == []
    assert service.find_by_rjcode("RJ00000025", src_id) == []
    assert store.get_entry(dest_id, new_rel_a) is not None
    assert store.get_entry(dest_id, new_rel_b) is not None


# ---------- Case 6：非法 UTF-8 文件名不能拖垮索引 ----------

def test_snapshot_store_escapes_surrogate_paths_before_sqlite_write(isolated_index):
    """Docker/Linux 上坏文件名字节会变成 surrogate，SQLite 绑定参数前必须转义。"""
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_bad_utf8"

    store.bulk_upsert([
        IndexEntry(
            library_id=library_id,
            entry_type="file",
            relative_path="社团/RJ00000011_\udce4\udcb8\udcad.mp3",
            absolute_path="/library/社团/RJ00000011_\udce4\udcb8\udcad.mp3",
            name="RJ00000011_\udce4\udcb8\udcad.mp3",
            rjcode="RJ00000011",
            parent_path="社团",
            size=1,
            file_count=0,
            mtime=1,
            depth=2,
        )
    ])

    hit = store.get_entry(library_id, "社团/RJ00000011_\\udce4\\udcb8\\udcad.mp3")
    assert hit is not None
    assert hit.name == "RJ00000011_\\udce4\\udcb8\\udcad.mp3"


def test_upsert_subtree_local_accepts_single_file_path(isolated_index):
    """flatten/单文件落盘会传文件路径，索引增量 upsert 不能按目录硬扫。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_single_file"

    _mark_index_ready(store, library_id)
    audio_dir = library_root / "RJ00000012"
    audio_dir.mkdir()
    audio_file = audio_dir / "RJ00000012_track.wav"
    audio_file.write_bytes(b"RIFF")

    written = service.upsert_subtree_local(
        library_id, str(library_root), str(audio_file),
    )

    assert written == 1
    hit = store.get_entry(library_id, "RJ00000012/RJ00000012_track.wav")
    assert hit is not None
    assert hit.entry_type == "file"
    assert hit.size == 4


def test_file_upsert_updates_ancestor_directory_size_and_count(isolated_index):
    """文件级 self_mutation upsert 后，父目录聚合必须立刻变化。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_file_parent_delta"

    store.bulk_upsert([
        _manual_entry("社团", library_id=library_id, rjcode="", size=0, file_count=0),
        _manual_entry("社团/RJ00000030", library_id=library_id, rjcode="RJ00000030", size=0, file_count=0),
    ])

    service.handle_self_mutation_upsert(_manual_entry(
        "社团/RJ00000030/track.wav",
        library_id=library_id,
        rjcode="RJ00000030",
        entry_type="file",
    ))

    parent = store.get_entry(library_id, "社团/RJ00000030")
    top = store.get_entry(library_id, "社团")
    assert parent is not None
    assert parent.size == 123
    assert parent.file_count == 1
    assert top is not None
    assert top.size == 123
    assert top.file_count == 1


def test_delete_file_updates_ancestor_directory_size_and_count(isolated_index):
    """删除子文件后，祖先目录 size/file_count 不能停在旧值。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_delete_parent_delta"

    store.bulk_upsert([
        _manual_entry("社团", library_id=library_id, rjcode="", size=123, file_count=1),
        _manual_entry("社团/RJ00000031", library_id=library_id, rjcode="RJ00000031", size=123, file_count=1),
        _manual_entry("社团/RJ00000031/track.wav", library_id=library_id, rjcode="RJ00000031", entry_type="file", size=123),
    ])

    deleted = service.handle_self_mutation_delete(library_id, "社团/RJ00000031/track.wav")

    assert deleted == 1
    parent = store.get_entry(library_id, "社团/RJ00000031")
    top = store.get_entry(library_id, "社团")
    assert parent is not None
    assert parent.size == 0
    assert parent.file_count == 0
    assert top is not None
    assert top.size == 0
    assert top.file_count == 0


def test_batch_delete_file_paths_skips_subtree_stats_sql(isolated_index):
    """批量删字幕文件时，文件路径不能走目录子树递归统计。"""
    engine = isolated_index["engine"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_batch_delete_file_fast_path"
    statements: list[str] = []

    def _capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(" ".join(str(statement).lower().split()))

    files = [
        _manual_entry(
            f"RJ00000033/subtitles/unused-{index:02d}.srt",
            library_id=library_id,
            rjcode="RJ00000033",
            entry_type="file",
            size=index + 1,
        )
        for index in range(35)
    ]

    store.upsert_status(library_id, status="ready", watcher_mode="disabled")
    store.bulk_upsert([
        _manual_entry("RJ00000033", library_id=library_id, rjcode="RJ00000033", size=0, file_count=0),
        _manual_entry("RJ00000033/subtitles", library_id=library_id, rjcode="RJ00000033", size=0, file_count=0),
        *files,
    ])

    event.listen(engine, "before_cursor_execute", _capture_statement)
    try:
        deleted = store.delete_subtrees(library_id, [item.relative_path for item in files], chunk_size=100)
    finally:
        event.remove(engine, "before_cursor_execute", _capture_statement)

    parent = store.get_entry(library_id, "RJ00000033")
    subtitles_dir = store.get_entry(library_id, "RJ00000033/subtitles")
    status = store.get_status(library_id)

    assert deleted == 35
    assert parent is not None
    assert parent.size == 0
    assert parent.file_count == 0
    assert subtitles_dir is not None
    assert subtitles_dir.size == 0
    assert subtitles_dir.file_count == 0
    assert status is not None
    assert status.total_entries == 2
    assert status.total_size_bytes == 0
    assert status.folder_count == 1
    assert store.get_entry(library_id, files[0].relative_path) is None
    assert not [
        item for item in statements
        if "left join library_index_entries" in item
        and "jsonb_to_recordset" in item
    ]
    assert not any(" like " in item for item in statements)


def test_subtree_upsert_updates_outer_parent_directory_delta(isolated_index):
    """子树 replace/upsert 后，只按子树根目录新旧差值更新外层父目录。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_subtree_parent_delta"

    _mark_index_ready(store, library_id)
    circle = library_root / "Circle"
    work_dir = circle / "RJ00000032"
    work_dir.mkdir(parents=True)
    track = work_dir / "track.wav"
    track.write_bytes(b"abcd")

    store.bulk_upsert([
        _manual_entry("Circle", library_id=library_id, rjcode="", size=0, file_count=0),
    ])

    service.upsert_subtree_local(library_id, str(library_root), str(work_dir))
    circle_entry = store.get_entry(library_id, "Circle")
    assert circle_entry is not None
    assert circle_entry.size == 4
    assert circle_entry.file_count == 1

    track.write_bytes(b"abcdefghij")
    service.upsert_subtree_local(library_id, str(library_root), str(work_dir))
    circle_entry = store.get_entry(library_id, "Circle")
    assert circle_entry is not None
    assert circle_entry.size == 10
    assert circle_entry.file_count == 1


def test_index_status_keeps_persisted_size_snapshot_with_deltas(isolated_index):
    """统计卡片读 status 聚合快照；业务变更只做差量加减。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_root: Path = isolated_index["library_root"]
    library_id = "lib_stats_snapshot"

    _mark_index_ready(store, library_id)
    top_dir = library_root / "RJ00000013"
    top_dir.mkdir()
    audio_file = top_dir / "track.wav"
    audio_file.write_bytes(b"abcd")

    service.upsert_subtree_local(library_id, str(library_root), str(top_dir))
    status = service.get_status(library_id)
    assert status is not None
    assert status.total_size_bytes == 4
    assert status.folder_count == 1
    assert service.get_library_size(library_id) == 4

    audio_file.write_bytes(b"abcdefghij")
    service.upsert_subtree_local(library_id, str(library_root), str(top_dir))
    status = service.get_status(library_id)
    assert status is not None
    assert status.total_size_bytes == 10
    assert status.folder_count == 1
    assert service.get_library_size(library_id) == 10

    service.handle_self_mutation_delete(library_id, "RJ00000013")
    status = service.get_status(library_id)
    assert status is not None
    assert status.total_size_bytes == 0
    assert status.folder_count == 0
    assert service.get_library_size(library_id) == 0


def test_delete_subtree_treats_percent_and_underscore_as_literal_path_chars(isolated_index):
    """子树删除不能把 relative_path 里的 %/_ 当 LIKE 通配符误删兄弟目录。"""
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_literal_subtree"

    store.bulk_upsert([
        _manual_entry("社团/a%_b", library_id=library_id, rjcode="RJ00000014"),
        _manual_entry("社团/a%_b/track.mp3", library_id=library_id, rjcode="RJ00000014", entry_type="file"),
        _manual_entry("社团/aXyb", library_id=library_id, rjcode="RJ00000015"),
        _manual_entry("社团/aXyb/track.mp3", library_id=library_id, rjcode="RJ00000015", entry_type="file"),
    ])

    deleted = store.delete_subtree(library_id, "社团/a%_b")

    assert deleted == 2
    assert store.get_entry(library_id, "社团/a%_b") is None
    assert store.get_entry(library_id, "社团/a%_b/track.mp3") is None
    assert store.get_entry(library_id, "社团/aXyb") is not None
    assert store.get_entry(library_id, "社团/aXyb/track.mp3") is not None


def test_snapshot_store_reads_do_not_wait_for_index_write_budget(monkeypatch, isolated_index):
    """库存 stats/search/list 读路径不能排在 library_index.write 队列后面。"""
    import app.core.library_index.snapshot_store as snapshot_store_module

    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_read_budget"
    calls = []

    class Budget:
        @contextmanager
        def acquire_sync(self, resource, *, weight=1, reason=""):
            calls.append((resource, weight, reason))
            yield

    monkeypatch.setattr(snapshot_store_module, "get_resource_budget_service", lambda: Budget())

    store.bulk_upsert([
        _manual_entry("社团/RJ00000016", library_id=library_id, rjcode="RJ00000016"),
    ])
    store.upsert_status(
        library_id,
        status="ready",
        watcher_mode="disabled",
        total_entries=1,
        total_size_bytes=123,
        folder_count=1,
    )
    calls.clear()

    assert store.get_status(library_id) is not None
    assert store.get_library_stats(library_id) == {"folder_count": 1, "total_size_bytes": 123}
    assert store.find_by_rjcode(library_id, "RJ00000016")
    assert store.get_entry(library_id, "社团/RJ00000016") is not None
    assert store.count_library_entries(library_id) == 1

    assert calls == []


def test_interrupted_initial_syncing_status_becomes_error(isolated_index):
    """首建中断不能在下次启动后继续显示同步中。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_interrupted_initial_sync"

    store.bulk_upsert([
        _manual_entry("社团/RJ00000017", library_id=library_id, rjcode="RJ00000017"),
        _manual_entry(
            "社团/RJ00000017/track.wav",
            library_id=library_id,
            rjcode="RJ00000017",
            entry_type="file",
            size=10,
        ),
    ])
    store.upsert_status(
        library_id,
        status="syncing",
        watcher_mode="disabled",
        total_entries=5000,
        total_size_bytes=999,
        folder_count=9,
    )
    _backdate_index_status(store, library_id, 1)
    service._pending_tasks.clear()
    service._pending_tasks_by_library.clear()

    status = service.get_status(library_id)

    assert status is not None
    assert status.status == "error"
    assert status.total_entries == 0
    assert "同步中断" in (status.error or "")


def test_interrupted_resyncing_status_restores_completed_snapshot_stats(isolated_index):
    """已有完整快照的重建中断后，恢复为可读 ready，并重算真实统计。"""
    service: LibraryIndexService = isolated_index["service"]
    store: SnapshotStore = isolated_index["store"]
    library_id = "lib_interrupted_resync"

    store.bulk_upsert([
        _manual_entry("社团/RJ00000018", library_id=library_id, rjcode="RJ00000018", size=0, file_count=1),
        _manual_entry(
            "社团/RJ00000018/track.wav",
            library_id=library_id,
            rjcode="RJ00000018",
            entry_type="file",
            size=10,
        ),
    ])
    store.upsert_status(
        library_id,
        status="syncing",
        watcher_mode="disabled",
        last_full_scan_at=123456,
        total_entries=5000,
        total_size_bytes=999,
        folder_count=9,
    )
    _backdate_index_status(store, library_id, 1)
    service._pending_tasks.clear()
    service._pending_tasks_by_library.clear()

    status = service.get_status(library_id)

    assert status is not None
    assert status.status == "ready"
    assert status.total_entries == 2
    assert status.total_size_bytes == 10
    assert status.folder_count == 0
    assert "同步中断" in (status.error or "")
