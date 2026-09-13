"""T-5.15 — checkpointer **真的落库**（不是静默 no-op）。

背景（真实事故）：`create_pg_saver` 原本只 `psycopg.AsyncConnection.connect(dsn)`，
缺 `autocommit=True`。saver 内部 `get_connection()` 对裸连接只 yield、不 commit，
于是 `aput` 的写入全留在未提交事务里，连接关闭即回滚 —— **checkpoint 一行不落库**，
而图照常跑完、`setup()` 也"成功"，全程无异常。C6（每 superstep checkpoint）、崩溃续跑、
retry 因此全部形同虚设，且无法从日志察觉。

本测试就是那个能抓住它的判据：跑一次图 → 必须能在库里查到该 thread 的 checkpoint。
需要真实 PG（与 test_ingest_graph.py 同级依赖，docker 8 服务）。
"""
from __future__ import annotations

import uuid
from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.infrastructure.checkpoint.pg_saver import close_pg_saver, create_pg_saver
from app.infrastructure.settings import get_settings


class _S(TypedDict, total=False):
    seed: int
    a: int


async def _node_a(state):
    return {"a": 1}


def _tiny_graph(saver):
    g = StateGraph(_S)
    g.add_node("a", _node_a)
    g.add_edge(START, "a")
    g.add_edge("a", END)
    return g.compile(checkpointer=saver)


async def _count(dsn: str, tid: str) -> dict[str, int]:
    """用**独立连接**读（能看见才算真提交——同连接内自读会掩盖未提交写入）。"""
    import psycopg

    from app.infrastructure.checkpoint.pg_saver import normalize_dsn

    out: dict[str, int] = {}
    async with await psycopg.AsyncConnection.connect(normalize_dsn(dsn)) as conn:
        for tbl in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            cur = await conn.execute(
                f"select count(*) from {tbl} where thread_id = %s", (tid,)  # noqa: S608
            )
            out[tbl] = (await cur.fetchone())[0]
    return out


async def _cleanup(dsn: str, tid: str) -> None:
    import psycopg

    from app.infrastructure.checkpoint.pg_saver import normalize_dsn

    async with await psycopg.AsyncConnection.connect(
        normalize_dsn(dsn), autocommit=True
    ) as conn:
        for tbl in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            await conn.execute(f"delete from {tbl} where thread_id = %s", (tid,))  # noqa: S608


@pytest.mark.asyncio
async def test_pg_saver_actually_persists_checkpoints():
    """跑一次图 → 该 thread 必须查得到 checkpoint/writes（防 autocommit 回归）。"""
    dsn = get_settings().resolved_database_url
    saver = await create_pg_saver(dsn)
    tid = f"test:persist:{uuid.uuid4().hex[:10]}"
    try:
        out = await _tiny_graph(saver).ainvoke(
            {"seed": 1}, {"configurable": {"thread_id": tid, "recursion_limit": 100}}
        )
        assert out.get("a") == 1  # 图本身跑通

        c = await _count(dsn, tid)
        assert c["checkpoints"] >= 1, (
            f"checkpoint 未落库（counts={c}）—— 多半是 create_pg_saver 丢了 "
            "autocommit=True：写入留在未提交事务里，连接一关即回滚，且不报错"
        )
        assert c["checkpoint_writes"] >= 1, f"writes 未落库（counts={c}）"
    finally:
        await close_pg_saver(saver)
        await _cleanup(dsn, tid)


@pytest.mark.asyncio
async def test_pg_saver_survives_reconnect_and_resume():
    """落库可读：换一个 saver/连接后仍能按 thread_id 取回历史（续跑的物理前提）。"""
    dsn = get_settings().resolved_database_url
    tid = f"test:resume:{uuid.uuid4().hex[:10]}"
    cfg = {"configurable": {"thread_id": tid, "recursion_limit": 100}}

    saver1 = await create_pg_saver(dsn)
    try:
        await _tiny_graph(saver1).ainvoke({"seed": 7}, cfg)
    finally:
        await close_pg_saver(saver1)

    # 全新连接读回（模拟进程重启后续跑）
    saver2 = await create_pg_saver(dsn)
    try:
        st = await _tiny_graph(saver2).aget_state(cfg)
        assert st is not None and st.values.get("a") == 1, (
            f"重启后取不到历史状态（values={getattr(st, 'values', None)}）"
        )
    finally:
        await close_pg_saver(saver2)
        await _cleanup(dsn, tid)
