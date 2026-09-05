from __future__ import annotations

import pytest

import sqlfs.sql_filesystem as sql_filesystem_module
from sqlfs import SQLFileSystem

CREATED_AT = 100.0
UPDATED_AT = 200.0
READ_AT = 300.0


async def test_write_and_read(sql_fs: SQLFileSystem) -> None:
    data = b'{"company": "acme"}'
    await sql_fs._pipe_file("/cv/1/data", data)
    assert await sql_fs._cat_file("/cv/1/data") == data


async def test_exists_true_and_false(sql_fs: SQLFileSystem) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"ok": true}')
    assert await sql_fs._exists("/cv/1/data") is True
    assert await sql_fs._exists("/cv/missing") is False


async def test_overwrite_file(sql_fs: SQLFileSystem) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"v": 1}')
    await sql_fs._pipe_file("/cv/1/data", b'{"v": 2}')
    assert await sql_fs._cat_file("/cv/1/data") == b'{"v": 2}'


async def test_mkdir_and_ls(sql_fs: SQLFileSystem) -> None:
    await sql_fs._makedirs("/cv/1", exist_ok=True)
    await sql_fs._pipe_file("/cv/1/data", b'{"a": 1}')
    await sql_fs._pipe_file("/cv/2/data", b'{"b": 2}')

    names = await sql_fs._ls("/cv", detail=False)
    assert set(names) == {"/cv/1", "/cv/2"}


async def test_ls_nested_only_direct_children(sql_fs: SQLFileSystem) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"a": 1}')
    await sql_fs._pipe_file("/cv/1/meta", b'{"b": 2}')
    await sql_fs._pipe_file("/jd/1/data", b'{"c": 3}')

    assert set(await sql_fs._ls("/cv/1", detail=False)) == {"/cv/1/data", "/cv/1/meta"}
    assert set(await sql_fs._ls("/cv", detail=False)) == {"/cv/1"}
    assert set(await sql_fs._ls("/", detail=False)) == {"/cv", "/jd"}


async def test_ls_missing_raises(sql_fs: SQLFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        await sql_fs._ls("/nope")


async def test_ls_empty_dir(sql_fs: SQLFileSystem) -> None:
    await sql_fs._mkdir("/empty")
    assert await sql_fs._ls("/empty", detail=False) == []


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
async def test_glob_patterns(
    sql_fs: SQLFileSystem, pattern: str, expected: set[str]
) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"id": "1"}')
    await sql_fs._pipe_file("/cv/2/data", b'{"id": "2"}')
    await sql_fs._pipe_file("/cv/2/meta", b'{"tags": []}')
    await sql_fs._pipe_file("/cv/1/nested/x", b'{"x": 1}')

    assert set(await sql_fs._glob(pattern)) == expected


async def test_info_file_and_dir(sql_fs: SQLFileSystem) -> None:
    payload = b'{"name": "John"}'
    await sql_fs._pipe_file("/cv/1/data", payload)

    file_info = await sql_fs._info("/cv/1/data")
    assert file_info["type"] == "file"
    assert file_info["size"] == len(payload)

    dir_info = await sql_fs._info("/cv")
    assert dir_info["type"] == "directory"


async def test_info_missing_raises(sql_fs: SQLFileSystem) -> None:
    with pytest.raises(FileNotFoundError):
        await sql_fs._info("/missing")


@pytest.mark.skip(reason="open/_SQLFileWriter not yet adapted for async pipe/cat")
async def test_open_read_write_roundtrip(sql_fs: SQLFileSystem) -> None:
    payload = b'{"hello": "world"}'
    with sql_fs.open("/cv/1/data", "wb") as f:
        f.write(payload)
    with sql_fs.open("/cv/1/data", "rb") as f:
        assert f.read() == payload


async def test_rm_removes_file(sql_fs: SQLFileSystem) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"x": 1}')
    await sql_fs._rm("/cv/1/data")
    assert not await sql_fs._exists("/cv/1/data")


async def test_rm_directory_requires_recursive(sql_fs: SQLFileSystem) -> None:
    await sql_fs._pipe_file("/cv/1/data", b'{"x": 1}')
    with pytest.raises(OSError):
        await sql_fs._rm("/cv", recursive=False)
    await sql_fs._rm("/cv", recursive=True)
    assert not await sql_fs._exists("/cv/1/data")
    assert not await sql_fs._exists("/cv")


async def test_rm_empty_directory_without_recursive(sql_fs: SQLFileSystem) -> None:
    await sql_fs._mkdir("/empty")

    await sql_fs._rm("/empty")

    assert not await sql_fs._exists("/empty")


async def test_write_rejects_directory_path(sql_fs: SQLFileSystem) -> None:
    await sql_fs._makedirs("/cv/1")

    with pytest.raises(IsADirectoryError):
        await sql_fs._pipe_file("/cv", b'{"invalid": true}')

    assert (await sql_fs._info("/cv"))["type"] == "directory"
    assert await sql_fs._exists("/cv/1")


async def test_recursive_rm_treats_like_wildcards_literally(
    sql_fs: SQLFileSystem,
) -> None:
    await sql_fs._pipe_file("/team_1/data", b"{}")
    await sql_fs._pipe_file("/teamX1/data", b"{}")
    await sql_fs._pipe_file("/report%2024/data", b"{}")
    await sql_fs._pipe_file("/reportXYZ2024/data", b"{}")

    await sql_fs._rm("/team_1", recursive=True)
    await sql_fs._rm("/report%2024", recursive=True)

    assert not await sql_fs._exists("/team_1/data")
    assert not await sql_fs._exists("/report%2024/data")
    assert await sql_fs._exists("/teamX1/data")
    assert await sql_fs._exists("/reportXYZ2024/data")


async def test_file_metadata_and_timestamps(
    sql_fs: SQLFileSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: CREATED_AT)
    await sql_fs._pipe_file("/cv/1/data", b'{"v": 1}')

    created = await sql_fs._info("/cv/1/data")
    assert created["content_type"] == "application/json"
    assert created["size"] == len(b'{"v": 1}')
    assert created["atime"] == CREATED_AT
    assert created["mtime"] == CREATED_AT
    assert created["ctime"] == CREATED_AT

    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: UPDATED_AT)
    await sql_fs._pipe_file("/cv/1/data", b'{"version": 2}')

    overwritten = await sql_fs._info("/cv/1/data")
    assert overwritten["size"] == len(b'{"version": 2}')
    assert overwritten["atime"] == CREATED_AT
    assert overwritten["mtime"] == UPDATED_AT
    assert overwritten["ctime"] == UPDATED_AT

    monkeypatch.setattr(sql_filesystem_module.time, "time", lambda: READ_AT)
    assert await sql_fs._cat_file("/cv/1/data") == b'{"version": 2}'

    assert (await sql_fs._info("/cv/1/data"))["atime"] == READ_AT


async def test_content_type_is_required_by_schema(incomplete_async_url: str) -> None:
    fs = SQLFileSystem(
        incomplete_async_url,
        table="incomplete_node",
        asynchronous=True,
    )
    with pytest.raises(ValueError, match="content_type"):
        await fs._load_table()
    await fs.engine.dispose()
