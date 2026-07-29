from __future__ import annotations

import pytest

from sqlfs import SQLFileSystem

pytestmark = pytest.mark.skip(reason="SQLFileSystem core is not implemented yet")


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


def test_glob_data_files(sql_fs: SQLFileSystem) -> None:
    sql_fs.pipe_file("/cv/1/data", b'{"id": "1"}')
    sql_fs.pipe_file("/cv/2/data", b'{"id": "2"}')
    sql_fs.pipe_file("/cv/2/meta", b'{"tags": []}')

    assert set(sql_fs.glob("/cv/*/data")) == {"/cv/1/data", "/cv/2/data"}


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
