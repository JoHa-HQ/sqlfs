from __future__ import annotations

import fsspec

from sqlfs._version import __version__
from sqlfs.sql_filesystem import SQLFileSystem

fsspec.register_implementation("sql", SQLFileSystem, clobber=True)

__all__ = ["SQLFileSystem", "__version__"]
