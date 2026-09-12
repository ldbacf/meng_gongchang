"""T-5.13 — `_handle_one_file` 新文件分支回归。

背景：「新文件」处理块曾被错放进 `_copy_across_kb()` 的两个 return 之后
（永远执行不到），而 `_handle_one_file` 缺该分支 → 上传**新** PDF 时隐式返回 None，
调用方 `resp, fi = await _handle_one_file(...)` 抛 TypeError（500）。

本测试用 fake session/file（不连真实 DB/MinIO）锁定：
- 新文件 → 返回 (TaskCreateResponse, fi)，fi 非 None，message 含"新文件"；
- 已存在同 md5（非 parsed）→ 走"重试"分支；
- 已存在且 parsed 且 MinIO 有产物 → 走"秒传"分支（fi 为 None）。
"""
from __future__ import annotations

import uuid

import pytest

import app.main as main_mod
from app.infrastructure.container import AppContainer
from app.infrastructure.settings import Settings
from app.interface.deps import set_container


class _FakeMinio:
    """容器注入的 MinIO fake（`_handle_one_file` 经 container.get_minio() 调用）。"""

    def __init__(self, parsed_exists: bool = False):
        self._parsed_exists = parsed_exists
        self.uploaded: list[tuple] = []

    def check_parsed_exists(self, md5: str) -> bool:
        return self._parsed_exists

    def upload_raw_pdf(self, md5: str, name: str, data: bytes) -> str:
        self.uploaded.append((md5, name))
        return f"{md5}/raw/{name}"


def _install_fake_minio(parsed_exists: bool = False) -> _FakeMinio:
    fake = _FakeMinio(parsed_exists=parsed_exists)
    set_container(AppContainer(
        settings=Settings(_env_file=None, jwt_secret_key="x"),
        fakes={"minio": fake},
    ))
    return fake


class _Res:
    def __init__(self, val):
        self._val = val

    def scalar_one_or_none(self):
        return self._val


class _Session:
    """最小 fake session：execute 固定返回 existing；记录 add。"""

    def __init__(self, existing=None):
        self._existing = existing
        self.added = []

    async def execute(self, *a, **k):
        return _Res(self._existing)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


class _Upload:
    def __init__(self, name: str, data: bytes):
        self.filename = name
        self._data = data

    async def read(self):
        return self._data


@pytest.fixture
def fake_minio():
    return _install_fake_minio()


async def test_new_file_returns_tuple(fake_minio):
    """新文件：返回 (resp, fi) 且 fi 非 None（修复前这里是 None → TypeError）。"""
    session = _Session(existing=None)
    resp, fi = await main_mod._handle_one_file(_Upload("新文档.pdf", b"%PDF-1.4 x"), session)

    assert resp is not None
    assert "新文件" in resp.message
    assert resp.status == "pending"
    assert fi is not None and fi["md5"] and fi["data"]
    assert len(session.added) == 1
    assert session.added[0].kb_id is None
    assert fake_minio.uploaded  # 经容器 MinIO 落 raw-docs


async def test_new_file_with_kb_id(fake_minio):
    kb_id = uuid.uuid4()
    session = _Session(existing=None)
    resp, fi = await main_mod._handle_one_file(_Upload("a.pdf", b"data"), session, kb_id=kb_id)

    assert fi is not None
    assert session.added[0].kb_id == kb_id


async def test_existing_unparsed_goes_retry(fake_minio):
    """已存在同 md5 且未 parsed → 重试分支（返回 fi 由调用方重提交）。"""
    from app.infrastructure.db.models import DocumentTask, TaskStatus

    task = DocumentTask(
        md5="a" * 32, original_name="x.pdf", raw_minio_path="raw-docs/x.pdf",
        status=TaskStatus.FAILED,
    )
    task.id = uuid.uuid4()
    session = _Session(existing=task)

    resp, fi = await main_mod._handle_one_file(_Upload("x.pdf", b"data"), session)
    assert "重试" in resp.message
    assert fi is not None


async def test_existing_parsed_is_instant_upload():
    """已存在且 parsed 且 MinIO 有产物 → 秒传（fi 为 None）。"""
    from app.infrastructure.db.models import DocumentTask, TaskStatus

    _install_fake_minio(parsed_exists=True)
    task = DocumentTask(
        md5="b" * 32, original_name="y.pdf", raw_minio_path="raw-docs/y.pdf",
        status=TaskStatus.PARSED,
    )
    task.id = uuid.uuid4()
    session = _Session(existing=task)

    resp, fi = await main_mod._handle_one_file(_Upload("y.pdf", b"data"), session)
    assert "秒传" in resp.message
    assert fi is None


def test_copy_across_kb_has_no_unreachable_tail():
    """`_copy_across_kb` 末尾不再有 return 之后的死代码（错位块已移回 _handle_one_file）。"""
    import inspect

    src = inspect.getsource(main_mod._copy_across_kb)
    assert "# 新文件" not in src
    assert "待提交解析" in src
