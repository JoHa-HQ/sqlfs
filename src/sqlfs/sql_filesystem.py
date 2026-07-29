from fsspec.spec import AbstractFileSystem


class SQLFileSystem(AbstractFileSystem):
    protocol = "sql"

    def __init__(self, url: str, table: str = "fs_node", **kwargs):
        raise NotImplementedError("SQLFileSystem not implemented yet")
