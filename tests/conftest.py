from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import fsspec
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sqlfs import SQLFileSystem

FS_NODE_DDL_SQLITE = """
CREATE TABLE fs_node (
    path         TEXT PRIMARY KEY,
    parent       TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('file', 'dir')),
    content_type TEXT,
    content      TEXT,
    size         INTEGER NOT NULL DEFAULT 0,
    atime        REAL,
    mtime        REAL,
    ctime        REAL
);
CREATE INDEX ix_fs_node_parent ON fs_node(parent);
"""


@pytest.fixture(params=["sqlite"])
def backend(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def db_url(backend: str, tmp_path: Path) -> str:
    if backend == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    raise NotImplementedError(f"unsupported backend: {backend}")


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_engine(db_url)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def fs_node_table(engine: Engine, backend: str) -> Iterator[Engine]:
    """Create a clean fs_node table for each test."""
    if backend == "sqlite":
        ddl = FS_NODE_DDL_SQLITE
    else:
        raise NotImplementedError(f"unsupported backend: {backend}")

    statements = [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))
        for stmt in statements:
            conn.execute(text(stmt))

    yield engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))


@pytest.fixture
def sql_fs(fs_node_table: Engine, db_url: str) -> SQLFileSystem:
    fsspec.register_implementation("sql", SQLFileSystem, clobber=True)
    return fsspec.filesystem("sql", url=db_url, table="fs_node")
