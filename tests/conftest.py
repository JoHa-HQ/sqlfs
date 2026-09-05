from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from testcontainers.community.postgres import PostgresContainer

from sqlfs import SQLFileSystem

_ASYNC_DRIVERS = {
    "sqlite": "sqlite+aiosqlite",
    "postgresql": "postgresql+asyncpg",
}


def _async_url(engine: Engine) -> str:
    """Rewrite a sync Engine URL to the matching async driver."""
    try:
        drivername = _ASYNC_DRIVERS[engine.dialect.name]
    except KeyError as exc:
        raise ValueError(f"unsupported dialect: {engine.dialect.name}") from exc
    return engine.url.set(drivername=drivername).render_as_string(hide_password=False)


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
    "postgresql": """
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
    "postgresql": """
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


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def postgres_engine(postgres_container: PostgresContainer) -> Iterator[Engine]:
    engine = create_engine(postgres_container.get_connection_url(driver="psycopg"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request: pytest.FixtureRequest) -> Engine:
    if request.param == "sqlite":
        return request.getfixturevalue("sqlite_engine")
    if request.param == "postgres":
        return request.getfixturevalue("postgres_engine")
    raise ValueError(f"unsupported backend type: {request.param}")


@pytest.fixture
def fs_node_table(engine: Engine) -> Iterator[Engine]:
    """Create a clean fs_node table for each test."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))
        for stmt in FS_NODE_DDL[engine.dialect.name].split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fs_node"))


@pytest.fixture
def incomplete_node_table(engine: Engine) -> Iterator[Engine]:
    """Create a schema-invalid table missing content_type for contract tests."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS incomplete_node"))
        for stmt in INCOMPLETE_NODE_DDL[engine.dialect.name].split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS incomplete_node"))


@pytest.fixture
def sql_fs_url(fs_node_table: Engine) -> str:
    return _async_url(fs_node_table)


@pytest.fixture
def incomplete_async_url(incomplete_node_table: Engine) -> str:
    return _async_url(incomplete_node_table)


@pytest.fixture
async def sql_fs(sql_fs_url: str) -> AsyncIterator[SQLFileSystem]:
    fs = SQLFileSystem(sql_fs_url, table="fs_node", asynchronous=True)
    await fs._load_table()
    try:
        yield fs
    finally:
        await fs.engine.dispose()
