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
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 让 pytest 直接运行 backend/tests 时也能 import app
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.database import Base  # noqa: E402
from app.core.library_index.service import LibraryIndexService  # noqa: E402
from app.core.library_index.snapshot_store import SnapshotStore  # noqa: E402


@pytest.fixture
def isolated_index(tmp_path):
    """每个测试一份内存 SQLite + 临时目录，互不污染。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
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
