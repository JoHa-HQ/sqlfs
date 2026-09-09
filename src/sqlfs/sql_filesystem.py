from __future__ import annotations

import time
from io import BytesIO
from os import PathLike
from pathlib import PurePosixPath
from typing import Any

from fsspec.asyn import AsyncFileSystem
from sqlalchemy import (
    MetaData,
    Table,
    Text,
    cast,
    delete,
    select,
    type_coerce,
    update,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

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


class SQLFileSystem(AsyncFileSystem):
    protocol = "sql"
    root_marker = ""

    def __init__(self, url: str, table: str = "fs_node", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.table_name = table
        self._table: Table | None = None
        self.engine: AsyncEngine = create_async_engine(url)
        self._connection: AsyncConnection | None = None

    @property
    def table(self) -> Table:
        if self._table is None:
            raise RuntimeError(
                "SQL filesystem table is not loaded; call await fs._setup() first"
            )
        return self._table

    @property
    def connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError(
                "SQL filesystem connection is not open; call await fs._setup() first"
            )
        return self._connection

    async def _close_conn(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
        await self.engine.dispose()

    async def _setup(self) -> None:
        # Establish connection
        if self._connection is None:
            self._connection = await self.engine.connect()
        # Reflect fs_node schema
        try:
            async with self.connection.begin():
                self._table = await self.connection.run_sync(
                    lambda sync_conn: Table(
                        self.table_name, MetaData(), autoload_with=sync_conn
                    )
                )
        except NoSuchTableError as exc:
            await self._close_conn()
            raise ValueError(
                f"SQL filesystem table does not exist: {self.table_name!r}"
            ) from exc

        missing_columns = REQUIRED_COLUMNS.difference(self.table.c.keys())
        if missing_columns:
            await self._close_conn()
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(
                f"SQL filesystem table {self.table_name!r} "
                f"is missing required columns: {missing}"
            )

    def _node_columns(self) -> list[Any]:
        return [
            cast(column, Text).label("content") if column.name == "content" else column
            for column in self.table.c
        ]

    @staticmethod
    def _content_as_bytes(content: Any) -> bytes:
        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        return content.encode("utf-8")

    @classmethod
    def _strip_protocol(cls, path: str | PathLike[str]) -> str:
        stripped = super()._strip_protocol(path)
        if not stripped:
            return ""
        return str(PurePosixPath(stripped.lstrip("/")))

    @classmethod
    def _parent(cls, path: str) -> str:
        if not path:
            return ""
        parent = PurePosixPath(path).parent
        if parent in (PurePosixPath("."), PurePosixPath("/")):
            return ""
        return str(parent)

    async def _row(self, path: str) -> RowMapping | None:
        result = await self.connection.execute(
            select(*self._node_columns()).where(self.table.c.path == path)
        )
        return result.mappings().first()

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

    async def _mkdir(
        self,
        path: str,
        create_parents: bool = True,
        exist_ok: bool = False,
        **kwargs: Any,
    ) -> None:
        path = self._strip_protocol(path)
        if not path:
            if not exist_ok:
                raise FileExistsError(path)
            return

        row = await self._row(path)
        if row is not None:
            info = self._info_from_row(row)
            if info["type"] != "directory":
                raise FileExistsError(path)
            if not exist_ok:
                raise FileExistsError(path)
            return

        parent = self._parent(path)
        if create_parents:
            if parent:
                # Intermediate parents may already exist.
                await self._mkdir(parent, create_parents=True, exist_ok=True)
        elif parent:
            parent_row = await self._row(parent)
            if parent_row is None:
                raise FileNotFoundError(parent)
            parent_info = self._info_from_row(parent_row)
            if parent_info["type"] != "directory":
                raise NotADirectoryError(parent)

        now = time.time()
        await self.connection.execute(
            self.table.insert().values(
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
        await self.connection.commit()

    async def _makedirs(self, path: str, exist_ok: bool = False) -> None:
        await self._mkdir(path, create_parents=True, exist_ok=exist_ok)

    async def _pipe_file(
        self,
        path: str,
        value: bytes,
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> None:
        path = self._strip_protocol(path)
        if not path:
            raise IsADirectoryError(path)
        if mode not in {"create", "overwrite"}:
            raise ValueError(f"unsupported write mode: {mode!r}")
        if mode == "create" and await self._exists(path):
            raise FileExistsError(path)

        payload = bytes(value)
        # Bind as Text, then CAST to the reflected column type (TEXT / JSONB).
        content = cast(
            type_coerce(payload.decode("utf-8"), Text), self.table.c.content.type
        )
        parent = self._parent(path)
        if parent:
            await self._mkdir(parent, create_parents=True, exist_ok=True)
        now = time.time()
        row = await self._row(path)

        if row is not None:
            info = self._info_from_row(row)
            if info["type"] == "directory":
                raise IsADirectoryError(path)
            await self._update_file(path, content, len(payload), now)
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
        await self.connection.execute(self.table.insert().values(**values))
        await self.connection.commit()

    async def _update_file(
        self,
        path: str,
        content: Any,
        size: int,
        timestamp: float,
    ) -> None:
        await self.connection.execute(
            update(self.table)
            .where(self.table.c.path == path)
            .values(
                type="file",
                content_type="application/json",
                content=content,
                size=size,
                mtime=timestamp,
                ctime=timestamp,
            )
        )
        await self.connection.commit()

    async def _cat_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        **kwargs: Any,
    ) -> bytes:
        path = self._strip_protocol(path)
        row = await self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        info = self._info_from_row(row)
        if info["type"] != "file":
            raise IsADirectoryError(path)

        data = self._content_as_bytes(row.get("content"))
        await self.connection.execute(
            update(self.table)
            .where(self.table.c.path == path)
            .values(atime=time.time())
        )
        await self.connection.commit()
        return data[start:end]

    async def _info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        path = self._strip_protocol(path)
        if not path:
            return {"name": "", "type": "directory", "size": 0}
        row = await self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        return self._info_from_row(row)

    async def _exists(self, path: str, **kwargs: Any) -> bool:
        path = self._strip_protocol(path)
        return not path or await self._row(path) is not None

    async def _ls(
        self, path: str, detail: bool = True, **kwargs: Any
    ) -> list[str] | list[dict[str, Any]]:
        path = self._strip_protocol(path)
        if path:
            row = await self._row(path)
            if row is None:
                raise FileNotFoundError(path)
            info = self._info_from_row(row)
            if info["type"] == "file":
                return [info] if detail else [path]

        parent = path
        result = await self.connection.execute(
            select(*self._node_columns())
            .where(self.table.c.parent == parent)
            .order_by(self.table.c.path)
        )
        rows = result.mappings().all()
        if detail:
            return [self._info_from_row(row) for row in rows]
        return [row["path"] for row in rows]

    async def _rm_file(self, path: str, **kwargs: Any) -> None:
        path = self._strip_protocol(path)
        row = await self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        info = self._info_from_row(row)
        if info["type"] == "directory":
            raise IsADirectoryError(path)
        await self.connection.execute(
            delete(self.table).where(self.table.c.path == path)
        )
        await self.connection.commit()

    async def _rmdir(self, path: str) -> None:
        await self._rm(path, recursive=False)

    async def _rm(
        self,
        path: str | list[str],
        recursive: bool = False,
        batch_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("maxdepth") is not None:
            raise NotImplementedError("maxdepth is not supported")

        if isinstance(path, list):
            for item in path:
                await self._rm(
                    item, recursive=recursive, batch_size=batch_size, **kwargs
                )
            return

        path = self._strip_protocol(path)
        if not path:
            raise ValueError("Cannot remove root")
        row = await self._row(path)
        if row is None:
            raise FileNotFoundError(path)
        info = self._info_from_row(row)
        if info["type"] == "file":
            await self._rm_file(path)
            return

        if not recursive:
            result = await self.connection.execute(
                select(self.table.c.path).where(self.table.c.parent == path).limit(1)
            )
            if result.first() is not None:
                raise OSError(f"Directory not empty: {path}")
            await self.connection.execute(
                delete(self.table).where(self.table.c.path == path)
            )
            await self.connection.commit()
            return

        escaped_path = (
            path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        descendants = self.table.c.path.like(f"{escaped_path}/%", escape="\\")
        await self.connection.execute(
            delete(self.table).where((self.table.c.path == path) | descendants)
        )
        await self.connection.commit()

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BytesIO:
        """Return a file-like object backed by an in-memory buffer.

        We store each file as one JSON value in SQL, so opening a file means
        reading or writing that whole value at once. ``OpenFile`` is handled by
        fsspec above this method; here we only return the raw buffer.
        """
        path = self._strip_protocol(path)
        if mode == "rb":
            return BytesIO(self.cat_file(path))
        if mode == "wb":
            return _SQLFileWriter(self, path)
        raise NotImplementedError(f"mode {mode!r} is not supported")
