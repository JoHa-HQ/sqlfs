# sqlfs

fsspec adapter backed by SQL.

`sqlfs` exposes a single node table as an fsspec filesystem (`protocol = "sql"`).
Paths form a tree and file bodies are stored as JSON. Works over SQLite and
PostgreSQL via SQLAlchemy async drivers.

## Installation

```bash
pip install joha-sqlfs
```

Or with `uv`:

```bash
uv add joha-sqlfs
```

## Development setup

```bash
uv sync --group dev
prek install
```

## Current scope

- async filesystem operations via SQLAlchemy `AsyncEngine` (`AsyncFileSystem`)
- path CRUD via `_pipe_file` / `_cat_file`, `_ls`, `_glob`, `_rm`, `_info`, …
- SQLite (`aiosqlite`) and PostgreSQL (`asyncpg`) backends
- file payloads are stored as JSON with `content_type = "application/json"`
- table creation and migrations stay on the client side
- `open()` / file-like writers are not fully adapted yet (use pipe/cat)

## Schema contract

`sqlfs` does **not** create or own the table. The client creates the
`fs_node` table; after construct, call `await fs._load_table()` to reflect and
validate the schema.

Required columns:

- `path`
- `parent`
- `type` (`file` or `dir`)
- `content_type`
- `content`
- `size`
- `atime`
- `mtime`
- `ctime`

A minimal SQLite-compatible schema looks like this:

```sql
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
```

For PostgreSQL, `content` can be a JSON-capable type such as `JSONB`.

## Usage

Use an **async** SQLAlchemy URL (`sqlite+aiosqlite://…` or
`postgresql+asyncpg://…`). Construct is sync; schema load and I/O are async:

```python
import asyncio

import fsspec
from sqlfs import SQLFileSystem

fsspec.register_implementation("sql", SQLFileSystem)


async def main() -> None:
    fs = fsspec.filesystem(
        "sql",
        url="sqlite+aiosqlite:///app.db",
        # or "postgresql+asyncpg://user:pass@host/db"
        table="fs_node",
        asynchronous=True,
    )
    await fs._load_table()

    await fs._pipe_file("/cv/1/data", b'{"name": "John Doe"}')
    print(await fs._cat_file("/cv/1/data"))  # b'{"name": "John Doe"}'
    print(await fs._ls("/cv", detail=False))  # ["/cv/1"]
    print(await fs._glob("/cv/*/data"))  # ["/cv/1/data"]

    await fs.engine.dispose()


asyncio.run(main())
```

## Tests

```bash
uv run pytest
```

The PostgreSQL test cases use `testcontainers` and require Docker.
