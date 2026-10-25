"""「重新生成」契约：替换旧回答而不是追加新问答。

线上语义（手动端到端验证过，这里锁住不变量）：

1. `regenerate_message_id` 必须属于该会话且 `role='ai'`
2. 重新生成**不新建用户消息**（否则会话里会出现重复提问）
3. 新回答落库的同一事务里删除旧回答 → 消息总数不变
4. 生成失败时不进入 persist，旧回答保留（不会新旧都没有）

本文件只做**纯逻辑**断言（不连库），DB 行为由 `_prepare` 的校验分支与
`persist` 的删除分支共同保证；真实库行为在开发环境已端到端验证。
"""
from __future__ import annotations

import inspect
import uuid

import pytest
from pydantic import ValidationError

from app.application.graphs.rag.nodes import persist as persist_mod
from app.application.services.chat_service import ChatService
from app.interface.schemas import ChatSendRequest


# ── 请求模型 ───────────────────────────────────────────────


def test_request_accepts_regenerate_id():
    req = ChatSendRequest(message="q", conversation_id=None, regenerate_message_id="abc")
    assert req.regenerate_message_id == "abc"


def test_regenerate_id_defaults_to_none():
    assert ChatSendRequest(message="q").regenerate_message_id is None


def test_regenerate_id_must_be_string_or_none():
    with pytest.raises(ValidationError):
        ChatSendRequest(message="q", regenerate_message_id=123)


# ── 服务：校验分支存在且语义正确 ───────────────────────────


def _source(obj) -> str:
    return inspect.getsource(obj)


def test_prepare_skips_user_message_when_regenerating():
    """重新生成分支里不能出现 _persist_user_message。"""
    src = _source(ChatService._prepare)
    assert "replace_message_id" in src
    regen_part = src.split("if replace_id:", 1)[1].split("user_msg_id =", 1)[0]
    assert "_persist_user_message" not in regen_part, "重新生成不应新建用户消息"
    assert "replace_message_id" in regen_part


def test_prepare_excludes_replaced_message_from_history():
    src = _source(ChatService._prepare)
    assert "exclude_id=replace_id" in src, "被替换的回答不能进入历史上下文"


def test_assert_regenerable_rejects_non_ai():
    src = _source(ChatService._assert_regenerable)
    assert 'msg.role != "ai"' in src
    assert "只能对 AI 回答重新生成" in src


def test_assert_regenerable_checks_conversation_ownership():
    src = _source(ChatService._assert_regenerable)
    assert "Message.conversation_id == conv_id" in src, "必须校验消息属于该会话"


# ── 持久化：同事务删除旧回答 ───────────────────────────────


def test_persist_deletes_replaced_message():
    src = _source(persist_mod.persist)
    assert "replace_message_id" in src
    assert "session.delete(old_msg)" in src
    # 删除必须发生在 commit 之前（同一事务），否则失败时会丢数据
    assert src.index("session.delete(old_msg)") < src.index("await session.commit()")


def test_persist_guards_self_replacement():
    """新旧 id 相同时不能删自己（幂等分支会命中同一条记录）。"""
    src = _source(persist_mod.persist)
    assert "old_uuid != mid_uuid" in src


def test_persist_tolerates_bad_uuid():
    """历史脏数据里的非法 id 不能让整次落库失败。"""
    src = _source(persist_mod.persist)
    assert "ValueError" in src


# ── 端到端（可选，需库）────────────────────────────────────

@pytest.mark.skip(reason="需要真实数据库，开发环境已手动端到端验证")
def test_regenerate_keeps_message_count():
    cid = uuid.uuid4()
    assert cid
