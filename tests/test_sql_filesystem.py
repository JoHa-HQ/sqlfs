from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine

import sqlfs.sql_filesystem as sql_filesystem_module
from sqlfs import SQLFileSystem

CREATED_AT = 100.0
UPDATED_AT = 200.0
READ_AT = 300.0


def test_write_and_read(sql_fs: SQLFileSystem) -> None:
    data = b'{"company": "acme"}'
    sql_fs.pipe_file("/cv/1/data", data)
    assert sql_fs.cat("/cv/1/data") == data


def test_exists_true_and_false(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"ok": true}')
    assert sql_fs.exists("/cv/1/data") is True
    assert sql_fs.exists("/cv/missing") is False


def test_overwrite_file(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"v": 1}')
    sql_fs.pipe_file("/cv/1/data", b'{"v": 2}')
    assert sql_fs.cat("/cv/1/data") == b'{"v": 2}'


def test_mkdir_and_ls(sql_fs: SQLFileSystem) -> None:
    sql_fs.makedirs("/cv/1", exist_ok=True)
    sql_fs.pipe_file("/cv/1/data", b'{"a": 1}')
    sql_fs.pipe_file("/cv/2/data", b'{"b": 2}')

    names = sql_fs.ls("/cv", detail=False)
    assert set(names) == {"/cv/1", "/cv/2"}


def test_ls_nested_only_direct_children(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"a": 1}')
    sql_fs.pipe_file("/cv/1/meta", b'{"b": 2}')
    sql_fs.pipe_file("/jd/1/data", b'{"c": 3}')

    assert set(sql_fs.ls("/cv/1", detail=False)) == {"/cv/1/data", "/cv/1/meta"}
    assert set(sql_fs.ls("/cv", detail=False)) == {"/cv/1"}
    assert set(sql_fs.ls("/", detail=False)) == {"/cv", "/jd"}


def test_ls_missing_raises(sql_fs: SQLFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        sql_fs.ls("/nope")


def test_ls_empty_dir(sql_fs: SQLFileSystem) -> None:
    sql_fs.mkdir("/empty")
    assert sql_fs.ls("/empty", detail=False) == []


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("/cv/*/data", {"/cv/1/data", "/cv/2/data"}),
        ("/cv/*", {"/cv/1", "/cv/2"}),
        ("/cv/**/data", {"/cv/1/data", "/cv/2/data"}),
        ("/**/data", {"/cv/1/data", "/cv/2/data"}),
        ("/cv/2/m?ta", {"/cv/2/meta"}),
        ("/cv/*/m*", {"/cv/2/meta"}),
        ("/cv/1/data", {"/cv/1/data"}),
        ("/nope/*", set()),
    ],
)
def test_glob_patterns(sql_fs: SQLFileSystem, pattern: str, expected: set[str]) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"id": "1"}')
    sql_fs.pipe_file("/cv/2/data", b'{"id": "2"}')
    sql_fs.pipe_file("/cv/2/meta", b'{"tags": []}')
    sql_fs.pipe_file("/cv/1/nested/x", b'{"x": 1}')

    assert set(sql_fs.glob(pattern)) == expected


def test_info_file_and_dir(sql_fs: SQLFileSystem) -> None:
    payload = b'{"name": "John"}'
    sql_fs.pipe_file("/cv/1/data", payload)

    file_info = sql_fs.info("/cv/1/data")
    assert file_info["type"] == "file"
    assert file_info["size"] == len(payload)

    dir_info = sql_fs.info("/cv")
    assert dir_info["type"] == "directory"


def test_info_missing_raises(sql_fs: SQLFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        sql_fs.info("/missing")


def test_open_read_write_roundtrip(sql_fs: SQLFileSystem) -> None:
    payload = b'{"hello": "world"}'
    with sql_fs.open("/cv/1/data", "wb") as f:
        f.write(payload)
    with sql_fs.open("/cv/1/data", "rb") as f:
        assert f.read() == payload


def test_rm_removes_file(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"x": 1}')
    sql_fs.rm("/cv/1/data")
    assert not sql_fs.exists("/cv/1/data")


def test_rm_directory_requires_recursive(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"x": 1}')
    with pytest.raises(OSError):
        sql_fs.rm("/cv", recursive=False)
    sql_fs.rm("/cv", recursive=True)
    assert not sql_fs.exists("/cv/1/data")
    assert not sql_fs.exists("/cv")


def test_rm_empty_directory_without_recursive(sql_fs: SQLFileSystem) -> None:
    sql_fs.mkdir("/empty")

    sql_fs.rm("/empty")

    assert not sql_fs.exists("/empty")


def test_write_rejects_directory_path(sql_fs: SQLFileSystem) -> None:
    sql_fs.makedirs("/cv/1")

    with pytest.raises(IsADirectoryError):
        sql_fs.pipe_file("/cv", b'{"invalid": true}')

    assert sql_fs.info("/cv")["type"] == "directory"
    assert sql_fs.exists("/cv/1")


def test_recursive_rm_treats_like_wildcards_literally(
    sql_fs: SQLFileSystem,
) -> None:
    sql_fs.pipe_file("/team_1/data", b"{}")
    sql_fs.pipe_file("/teamX1/data", b"{}")
    sql_fs.pipe_file("/report%2024/data", b"{}")
    sql_fs.pipe_file("/reportXYZ2024/data", b"{}")

    sql_fs.rm("/team_1", recursive=True)
    sql_fs.rm("/report%2024", recursive=True)

    assert not sql_fs.exists("/team_1/data")
    assert not sql_fs.exists("/report%2024/data")
    assert sql_fs.exists("/teamX1/data")
    assert sql_fs.exists("/reportXYZ2024/data")


def test_file_metadata_and_timestamps(
    sql_fs: SQLFileSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: CREATED_AT)
    sql_fs.pipe_file("/cv/1/data", b'{"v": 1}')

    created = sql_fs.info("/cv/1/data")
    assert created["content_type"] == "application/json"
    assert created["size"] == len(b'{"v": 1}')
    assert created["atime"] == CREATED_AT
    assert created["mtime"] == CREATED_AT
    assert created["ctime"] == CREATED_AT

    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: UPDATED_AT)
    sql_fs.pipe_file("/cv/1/data", b'{"version": 2}')

    overwritten = sql_fs.info("/cv/1/data")
    assert overwritten["size"] == len(b'{"version": 2}')
    assert overwritten["atime"] == CREATED_AT
    assert overwritten["mtime"] == UPDATED_AT
    assert overwritten["ctime"] == UPDATED_AT

    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: READ_AT)
    assert sql_fs.cat_file("/cv/1/data") == b'{"version": 2}'

    assert sql_fs.info("/cv/1/data")["atime"] == READ_AT


def test_content_type_is_required_by_schema(
    db_url: str, incomplete_node_table: Engine
) -> None:
    with pytest.raises(ValueError, match="content_type"):
        SQLFileSystem(url=db_url, table="incomplete_node")
