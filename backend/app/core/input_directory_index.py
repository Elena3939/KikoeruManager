"""目录成员索引：小目录内存处理，大目录分块落账本并按游标读取。"""

from sqlalchemy import insert

from ..models.database import InputScanDirectoryEntry as Entry
from .input_scan_repository import path_key


class InputDirectoryIndex:
    def __init__(self, repository, scan_id, directory, memory_limit=4096):
        self.factory = repository.session_factory
        self.scan_id = scan_id
        self.directory_key = path_key(directory)
        self.memory_limit = memory_limit
        self.rows = {}
        self.spilled = False
        self._page_names = set()
        self._page_marks = set()
        self.clear()

    def _query(self, db):
        return db.query(Entry).filter_by(scan_id=self.scan_id, directory_key=self.directory_key)

    def clear(self):
        with self.factory.begin() as db:
            self._query(db).delete(synchronize_session=False)

    def add(self, name, processed=False):
        self.rows[name] = processed
        if len(self.rows) >= (256 if self.spilled else self.memory_limit):
            self.flush()

    def flush(self):
        if not self.rows:
            return
        rows, self.rows = self.rows, {}
        with self.factory.begin() as db:
            names = list(rows)
            for offset in range(0, len(names), 256):
                db.execute(insert(Entry), [{
                    "scan_id": self.scan_id, "directory_key": self.directory_key,
                    "name": name, "lower_name": name.lower(), "processed": rows[name],
                } for name in names[offset:offset + 256]])
        self.spilled = True

    def members(self, prefix=None):
        if not self.spilled:
            return [name for name in self.rows if prefix is None or name.lower().startswith(prefix.lower())]
        self.flush()
        with self.factory() as db:
            query = self._query(db)
            if prefix is not None:
                query = query.filter(Entry.lower_name.startswith(prefix.lower(), autoescape=True))
            return [row.name for row in query]

    def remaining(self):
        if not self.spilled:
            yield from ((name, processed) for name, processed in self.rows.items())
            return
        self.flush()
        cursor = 0
        while True:
            with self.factory() as db:
                rows = self._query(db).filter(Entry.id > cursor).order_by(Entry.id).limit(128).all()
                page = [(row.id, row.name, row.processed) for row in rows]
            if not page:
                return
            self._page_names = {name for _, name, _ in page}
            self._page_marks = set()
            for cursor, name, processed in page:
                yield name, processed or name in self._page_marks

    def mark(self, names):
        names = list(names)
        self._page_marks.update(self._page_names.intersection(names))
        if not self.spilled:
            for name in names:
                if name in self.rows:
                    self.rows[name] = True
            return
        with self.factory.begin() as db:
            self._query(db).filter(Entry.name.in_(names)).update(
                {Entry.processed: True}, synchronize_session=False,
            )

    def is_processed(self, name):
        if not self.spilled:
            return self.rows.get(name, False)
        with self.factory() as db:
            return bool(self._query(db).filter_by(name=name, processed=True).first())
