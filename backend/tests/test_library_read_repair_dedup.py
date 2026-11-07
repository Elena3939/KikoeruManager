"""读修复按库与路径隔离，30 秒后允许重新入队。"""
from app.core.library_manager import LibraryDefinition, LibraryManager


def test_read_repair_deduplicates_for_30_seconds(monkeypatch):
    manager = LibraryManager.__new__(LibraryManager)
    clock = [1.0]
    monkeypatch.setattr('app.core.library_manager.time.monotonic', lambda: clock[0])
    queued = []
    monkeypatch.setattr(manager, '_enqueue_index_upsert_subtree_many',
        lambda library, paths: queued.append((library.id, paths)))
    a = LibraryDefinition(id='a', name='A', path='D:/library')
    b = LibraryDefinition(id='b', name='B', path='D:/library')
    manager._enqueue_index_read_repair_upserts(a, ['D:/library/empty'])
    manager._enqueue_index_read_repair_upserts(a, ['D:/library/empty'])
    manager._enqueue_index_read_repair_upserts(b, ['D:/library/empty'])
    assert [item[0] for item in queued] == ['a', 'b']
    clock[0] = 30.9
    manager._enqueue_index_read_repair_upserts(a, ['D:/library/empty'])
    assert len(queued) == 2
    clock[0] = 31.0
    manager._enqueue_index_read_repair_upserts(a, ['D:/library/empty'])
    assert len(queued) == 3
