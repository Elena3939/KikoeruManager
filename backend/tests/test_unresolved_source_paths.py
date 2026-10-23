from contextlib import nullcontext

from app.core.file_processor import FileProcessor
from app.models import database


def test_unresolved_paths_survive_memory_loss_and_source_relocation(db_session, monkeypatch):
    """真实 PostgreSQL 查询保留原包、暂存路径及无任务的问题项，已解决后解除。"""
    source = 'input/RJ123456.zip'
    relocated = 'library/_conflicts/RJ123456'
    orphan = 'input/orphan.zip'
    db_session.add(database.Task(id='failed-import', source_path=source, status='failed'))
    problem = database.ConflictWork(
        id='unresolved-problem', task_id='failed-import', new_path=relocated,
        status='PENDING', conflict_type='DUPLICATE',
    )
    db_session.add(problem)
    db_session.add(database.ConflictWork(id='orphan', new_path=orphan, status='PROCESSING'))
    db_session.add(database.ConflictWork(id='resolved', new_path='input/resolved.zip', status='SKIP'))
    db_session.flush()
    monkeypatch.setattr(database, 'SessionLocal', lambda: nullcontext(db_session))

    processor = FileProcessor()
    paths = processor._load_unresolved_source_paths()
    assert paths == {processor._path_key(p) for p in (source, relocated, orphan)}
    # 新对象不依赖 watcher 或任务引擎内存，模拟重启后的第一次扫描。
    assert FileProcessor()._load_unresolved_source_paths() == paths
    problem.status = 'KEEP_NEW'
    db_session.flush()
    assert processor._load_unresolved_source_paths() == {processor._path_key(orphan)}
