# sqlfs

fsspec adapter backed by SQL.

`sqlfs` exposes a single node table as an fsspec filesystem (`protocol = "sql"`).
Paths form a tree and file bodies are stored as JSON. Works over SQLite and
PostgreSQL via SQLAlchemy.

Scope is synchronous path CRUD: `pipe`/`cat`, `ls`, `glob`, `rm`, `info`.


## Setup

```bash
uv sync
prek install
```

## Schema ownership

sqlfs does **not** create or own the table. The client creates the
`fs_node` table; sqlfs connects and validates the contract on startup.

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
