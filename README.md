# sqlfs

fsspec adapter backed by SQL.

## Setup

```bash
uv sync
prek install
```

## Usage

Bind the adapter to the `"sql"` protocol, then use it through fsspec:

```python
import fsspec
from sqlfs import SQLFileSystem

fsspec.register_implementation("sql", SQLFileSystem)

fs = fsspec.filesystem("sql", db_path="file.db")
fs.touch("/home/file.txt")
```

Or pass a full URL:

```python
fs = fsspec.filesystem("sql", db_path="file.db")
with fs.open("/path/to/file", "w") as f:
    f.write("hello")
```
