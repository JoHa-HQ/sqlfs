from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import fsspec
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer

from sqlfs import SQLFileSystem

FS_NODE_DDL = {
    "sqlite": """
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
""",
    "postgres": """
CREATE TABLE fs_node (
    path         TEXT PRIMARY KEY,
    parent       TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('file', 'dir')),
    content_type TEXT,
    content      JSONB,
    size         INTEGER NOT NULL DEFAULT 0,
    atime        DOUBLE PRECISION,
    mtime        DOUBLE PRECISION,
    ctime        DOUBLE PRECISION
);
CREATE INDEX ix_fs_node_parent ON fs_node(parent);
""",
}

INCOMPLETE_NODE_DDL = {
    "sqlite": """
CREATE TABLE incomplete_node (
    path TEXT PRIMARY KEY,
    parent TEXT NOT NULL,
    type TEXT NOT NULL,
    content TEXT,
    size INTEGER NOT NULL,
    atime REAL,
    mtime REAL,
    ctime REAL
)
""",
    "postgres": """
CREATE TABLE incomplete_node (
    path TEXT PRIMARY KEY,
    parent TEXT NOT NULL,
    type TEXT NOT NULL,
    content JSONB,
    size INTEGER NOT NULL,
    atime DOUBLE PRECISION,
    mtime DOUBLE PRECISION,
    ctime DOUBLE PRECISION
)
""",
}


def _ddl_statements(backend: str, ddl_by_backend: dict[str, str]) -> list[str]:
    ddl = ddl_by_backend[backend]
    return [stmt.strip() for stmt in ddl.split(";") if stmt.strip()]


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres.get_connection_url(driver="psycopg")


@pytest.fixture(params=["sqlite", "postgres"])
def backend(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def db_url(backend: str, postgres_url: str, tmp_path: Path) -> str:
    if backend == "sqlite":
        return f"sqlite:///{tmp_path / 'test.db'}"
    if backend == "postgres":
        return postgres_url
    raise ValueError(f"unsupported backend: {backend}")


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
    statements = _ddl_statements(backend, FS_NODE_DDL)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))
        for stmt in statements:
            conn.execute(text(stmt))

    yield engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))


@pytest.fixture
def incomplete_node_table(engine: Engine, backend: str) -> Iterator[Engine]:
    """Create a schema-invalid table missing content_type for contract tests."""
    statements = _ddl_statements(backend, INCOMPLETE_NODE_DDL)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS incomplete_node"))
        for stmt in statements:
            conn.execute(text(stmt))

    yield engine

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS incomplete_node"))


@pytest.fixture
def sql_fs(fs_node_table: Engine, db_url: str) -> SQLFileSystem:
    fsspec.register_implementation("sql", SQLFileSystem, clobber=True)
    return fsspec.filesystem("sql", url=db_url, table="fs_node")
