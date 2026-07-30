from __future__ import annotations

import posixpath
import time
from io import BytesIO
from os import PathLike
from typing import Any

from fsspec.spec import AbstractFileSystem
from sqlalchemy import MetaData, Table, create_engine, delete, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import NoSuchTableError

REQUIRED_COLUMNS = frozenset(
    {
        "path",
        "parent",
        "type",
        "content_type",
        "content",
        "size",
        "atime",
        "mtime",
        "ctime",
    }
)


class _SQLFileWriter(BytesIO):
    def __init__(self, filesystem: SQLFileSystem, path: str) -> None:
        super().__init__()
        self._filesystem = filesystem
        self._path = path

    def close(self) -> None:
        if not self.closed:
            value = self.getvalue()
            try:
                self._filesystem.pipe_file(self._path, value)
            finally:
                super().close()


class SQLFileSystem(AbstractFileSystem):
    protocol = "sql"
    root_marker = "/"

    def __init__(self, url: str, table: str = "fs_node", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.table_name = table
        self.engine = create_engine(url)

        try:
            self._table = Table(table, MetaData(), autoload_with=self.engine)
        except NoSuchTableError as exc:
            self.engine.dispose()
            raise ValueError(f"SQL filesystem table does not exist: {table!r}") from exc

        missing_columns = REQUIRED_COLUMNS.difference(self._table.c.keys())
        if missing_columns:
            self.engine.dispose()
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(
                f"SQL filesystem table {table!r} is missing required columns: {missing}"
            )

    @classmethod
    def _strip_protocol(cls, path: str | PathLike[str]) -> str:
        stripped = super()._strip_protocol(path)
        normalized = posixpath.normpath(f"/{stripped.lstrip('/')}")
        return "/" if normalized == "/." else normalized

    @classmethod
    def _parent(cls, path: str) -> str:
        if path == "/":
            return ""
        parent = posixpath.dirname(path)
        return "" if parent == "/" else parent

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _row(self, path: str) -> RowMapping | None:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(self._table).where(self._table.c.path == path)
                )
                .mappings()
                .first()
            )

    @staticmethod
    def _info_from_row(row: RowMapping) -> dict[str, Any]:
        return {
            "name": row["path"],
            "type": "directory" if row["type"] == "dir" else "file",
            "size": row["size"] or 0,
            "content_type": row["content_type"],
            "atime": row["atime"],
            "mtime": row["mtime"],
            "ctime": row["ctime"],
            "created": row["ctime"],
        }

    def _ensure_dir(self, path: str) -> None:
        path = self._strip_protocol(path)
        if path == "/":
            return

        row = self._row(path)
        if row is not None:
            if row["type"] != "dir":
                raise FileExistsError(path)
            return

        parent = self._parent(path)
        self._ensure_dir(parent or "/")
        now = time.time()

        with self.engine.begin() as connection:
            connection.execute(
                self._table.insert().values(
                    path=path,
                    parent=parent,
                    type="dir",
                    content_type=None,
                    content=None,
                    size=0,
                    atime=now,
                    mtime=now,
                    ctime=now,
                )
            )

    def mkdir(self, path: str, create_parents: bool = True, **kwargs: Any) -> None:
        path = self._strip_protocol(path)
        if path == "/":
            return
        if create_parents:
            self._ensure_dir(path)
            return

        parent = self._parent(path)
        if parent:
            parent_row = self._row(parent)
            if parent_row is None:
                raise FileNotFoundError(parent)
            if parent_row["type"] != "dir":
                raise NotADirectoryError(parent)
        self._ensure_dir(path)

    def makedirs(self, path: str, exist_ok: bool = False) -> None:
        path = self._strip_protocol(path)
        row = None if path == "/" else self._row(path)
        if path == "/" or row is not None:
            if row is not None and row["type"] != "dir":
                raise FileExistsError(path)
            if not exist_ok:
                raise FileExistsError(path)
            return
        self._ensure_dir(path)

    def pipe_file(
        self,
        path: str,
        value: bytes,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> None:
        path = self._strip_protocol(path)
        if path == "/":
            raise IsADirectoryError(path)
        if mode not in {"create", "overwrite"}:
            raise ValueError(f"unsupported write mode: {mode!r}")
        if mode == "create" and self.exists(path):
            raise FileExistsError(path)

        payload = bytes(value)
        content = payload.decode("utf-8")
        parent = self._parent(path)
        self._ensure_dir(parent or "/")
        now = time.time()
        row = self._row(path)

        if row is not None:
            if row["type"] == "dir":
                raise IsADirectoryError(path)
            self._update_file(path, content, len(payload), now)
            return

        values = {
            "path": path,
            "parent": parent,
            "type": "file",
            "content_type": "application/json",
            "content": content,
            "size": len(payload),
            "atime": now,
            "mtime": now,
            "ctime": now,
        }
        with self.engine.begin() as connection:
            connection.execute(self._table.insert().values(**values))

    def _update_file(
        self, path: str, content: str, size: int, timestamp: float
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(self._table)
                .where(self._table.c.path == path)
                .values(
                    type="file",
                    content_type="application/json",
                    content=content,
                    size=size,
                    mtime=timestamp,
                    ctime=timestamp,
                )
            )

    def cat_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        **kwargs: Any,
    ) -> bytes:
        path = self._strip_protocol(path)
        row = self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        if row["type"] != "file":
            raise IsADirectoryError(path)

        content = row["content"] or ""
        data = content if isinstance(content, bytes) else content.encode("utf-8")
        with self.engine.begin() as connection:
            connection.execute(
                update(self._table)
                .where(self._table.c.path == path)
                .values(atime=time.time())
            )
        return data[start:end]

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        path = self._strip_protocol(path)
        if path == "/":
            return {"name": "/", "type": "directory", "size": 0}
        row = self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        return self._info_from_row(row)

    def exists(self, path: str, **kwargs: Any) -> bool:
        path = self._strip_protocol(path)
        return path == "/" or self._row(path) is not None

    def ls(
        self, path: str, detail: bool = True, **kwargs: Any
    ) -> list[str] | list[dict[str, Any]]:
        path = self._strip_protocol(path)
        if path != "/":
            row = self._row(path)
            if row is None:
                raise FileNotFoundError(path)
            if row["type"] == "file":
                info = self._info_from_row(row)
                return [info] if detail else [path]

        parent = "" if path == "/" else path
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(self._table)
                    .where(self._table.c.parent == parent)
                    .order_by(self._table.c.path)
                )
                .mappings()
                .all()
            )
        if detail:
            return [self._info_from_row(row) for row in rows]
        return [row["path"] for row in rows]

    def rm_file(self, path: str) -> None:
        path = self._strip_protocol(path)
        row = self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        if row["type"] == "dir":
            raise IsADirectoryError(path)
        with self.engine.begin() as connection:
            connection.execute(delete(self._table).where(self._table.c.path == path))

    def rmdir(self, path: str) -> None:
        self.rm(path, recursive=False)

    def rm(
        self,
        path: str | list[str],
        recursive: bool = False,
        maxdepth: int | None = None,
    ) -> None:
        if isinstance(path, list):
            for item in path:
                self.rm(item, recursive=recursive, maxdepth=maxdepth)
            return
        if maxdepth is not None:
            raise NotImplementedError("maxdepth is not supported")

        path = self._strip_protocol(path)
        if path == "/":
            raise ValueError("Cannot remove root")
        row = self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        if row["type"] == "file":
            self.rm_file(path)
            return

        with self.engine.begin() as connection:
            if not recursive:
                child = connection.execute(
                    select(self._table.c.path)
                    .where(self._table.c.parent == path)
                    .limit(1)
                ).first()
                if child is not None:
                    raise OSError(f"Directory not empty: {path}")
                connection.execute(
                    delete(self._table).where(self._table.c.path == path)
                )
                return

            escaped_path = self._escape_like(path)
            descendants = self._table.c.path.like(f"{escaped_path}/%", escape="\\")
            connection.execute(
                delete(self._table).where((self._table.c.path == path) | descendants)
            )

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BytesIO:
        path = self._strip_protocol(path)
        if mode == "rb":
            return BytesIO(self.cat_file(path))
        if mode == "wb":
            return _SQLFileWriter(self, path)
        raise NotImplementedError(f"mode {mode!r} is not supported")
