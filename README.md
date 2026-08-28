# sqlfs

fsspec adapter backed by SQL.

`sqlfs` exposes a single node table as an fsspec filesystem (`protocol = "sql"`).
Paths form a tree and file bodies are stored as JSON. Works over SQLite and
PostgreSQL via SQLAlchemy.

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

- synchronous filesystem operations only
- path CRUD via `pipe`/`cat`, `ls`, `glob`, `rm`, `info`, and `open`
- SQLite and PostgreSQL backends via SQLAlchemy
- file payloads are stored as JSON with `content_type = "application/json"`
- table creation and migrations stay on the client side

## Schema contract

`sqlfs` does **not** create or own the table. The client creates the
`fs_node` table; `sqlfs` connects and validates the contract on startup.

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

Register the `"sql"` protocol on the client side, then use it through fsspec:

```python
import fsspec
from sqlfs import SQLFileSystem

fsspec.register_implementation("sql", SQLFileSystem)

fs = fsspec.filesystem(
    "sql",
    url="sqlite:///app.db",   # or "postgresql+psycopg://user:pass@host/db"
    table="fs_node",
)

fs.pipe_file("/cv/1/data", b'{"name": "John Doe"}')
fs.cat("/cv/1/data")          # b'{"name": "John Doe"}'
fs.ls("/cv")                  # ["/cv/1"]
fs.glob("/cv/*/data")         # ["/cv/1/data"]
```

File-like access works too:

```python
with fs.open("/cv/1/data", "wb") as f:
    f.write(b'{"name": "John Doe"}')
```

## Tests

```bash
uv run pytest
```

The PostgreSQL test cases use `testcontainers` and require Docker.
