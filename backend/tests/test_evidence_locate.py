"""证据卡接口的定位正确性测试 —— 用真实 ES 片段，不需要 MinIO / DB。

## 为什么需要这一组

`/evidence` 返回的「命中章节」必须与引用片段真正所在的那一节一致。
第一版实现用 ES `match_phrase` 找块，结果**静默回退到该文档第一个正文块**：
用户点引用「2.4 结果」，右栏显示的却是「1.1 研究对象」。
这比不显示更糟 —— 它给出的是一个看起来合理但完全错误的答案。

根因：`citation.snippet` 是 `hit.content[:200]`，带 `【章节】…` 前缀且可能
截断在词中间；而证据卡展示用的是清洗后的文本。拿清洗后的句子去
match_phrase 原始 chunk 一条都命不中，于是走了兜底分支。

现在改为「拉全篇块 + Python 归一化匹配」，本文件锁住这个行为。

## 依赖策略

- ES 不可用 → 整个模块 skip（CI 无 ES 时不该红）
- 不打桩 ES：这里要验证的正是**真实索引里的内容**能否被匹配到，
  打桩就等于自己验证自己。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("elasticsearch")

ES_URL = os.getenv("TEST_ES_URL", "http://127.0.0.1:9200")

# (doc_id, 期望命中的章节关键字) —— 全部来自本机真实语料
REAL_DOCS: list[tuple[str, str]] = [
    ("7611", "2.4 基因组"),
    ("8285", "2.13"),
    ("8416", "2.3 结果分析"),
    ("8087", "4.1 降 Hcy"),
    ("8537", "1.2 中医三级防控"),
    ("8562", "2.1 PCI术后"),
]


@pytest.fixture(scope="module")
def es():
    from elasticsearch import Elasticsearch

    client = Elasticsearch(ES_URL, request_timeout=10)
    try:
        if not client.ping():
            pytest.skip("ES 不可用，跳过证据卡定位测试")
    except Exception:
        pytest.skip("ES 不可用，跳过证据卡定位测试")
    return client


@pytest.fixture(scope="module")
def index_name() -> str:
    from app.infrastructure.settings import get_settings

    return get_settings().es_index


@pytest.fixture(scope="module")
def l1_chunks(es, index_name):
    """{doc_id: [chunk, ...]}，只取有标题的正文块。"""

    def load(doc_id: str) -> list[dict]:
        resp = es.search(
            index=index_name,
            body={
                "size": 400,
                "query": {"bool": {"filter": [
                    {"term": {"level": "L1"}},
                    {"term": {"doc_id": doc_id}},
                ]}},
                "_source": ["chunk_id", "heading_stack", "content", "heading_depth"],
                "sort": ["_doc"],
            },
        )
        return [h["_source"] for h in resp["hits"]["hits"]]

    cache: dict[str, list[dict]] = {}

    def get(doc_id: str) -> list[dict]:
        if doc_id not in cache:
            cache[doc_id] = load(doc_id)
        return cache[doc_id]

    return get


def _real_snippet(chunks: list[dict], heading_kw: str) -> str:
    """取目标章节的真实 `content[:200]` —— 与 citation.snippet 同形。"""
    for c in chunks:
        if heading_kw in " → ".join(c.get("heading_stack") or []):
            return c["content"][:200]
    pytest.skip(f"语料里找不到章节 {heading_kw!r}（库可能已变更）")


# ── 命中定位 ──────────────────────────────────────────────────


@pytest.mark.parametrize("doc_id,heading_kw", REAL_DOCS)
def test_picks_the_section_the_snippet_came_from(doc_id, heading_kw, l1_chunks):
    """命中块必须是 snippet 真正所在的那一节，不能回退到第一个正文块。

    这是第一版的真实 bug：点「2.4 结果」显示「1.1 研究对象」。
    """
    from app.interface.routers.documents import _pick_hit_index

    chunks = l1_chunks(doc_id)
    snippet = _real_snippet(chunks, heading_kw)

    idx = _pick_hit_index(chunks, snippet)
    assert idx is not None, f"{doc_id} 未能匹配到任何块"

    heading = " → ".join(chunks[idx].get("heading_stack") or [])
    assert heading_kw in heading, (
        f"{doc_id} 命中错块：期望含 {heading_kw!r}，实际 {heading!r}"
    )


@pytest.mark.parametrize("doc_id,heading_kw", REAL_DOCS)
def test_never_returns_headline_block(doc_id, heading_kw, l1_chunks):
    """标题页/摘要页（heading_depth == 0）不能被选为命中块。

    它们不是引用要指的正文位置，选中等于答非所问。
    """
    from app.interface.routers.documents import _pick_hit_index

    chunks = l1_chunks(doc_id)
    snippet = _real_snippet(chunks, heading_kw)
    idx = _pick_hit_index(chunks, snippet)

    assert idx is not None
    assert (chunks[idx].get("heading_depth") or 0) >= 1


def test_returns_none_for_irrelevant_snippet(l1_chunks):
    """完全不相关的片段 → None。

    宁可没有命中块，也不能给一个错的（这正是第一版的教训）。
    """
    from app.interface.routers.documents import _pick_hit_index

    chunks = l1_chunks("7611")
    idx = _pick_hit_index(
        chunks,
        "量子色动力学中的渐近自由现象与夸克禁闭机制在格点规范理论中的数值模拟结果",
    )
    assert idx is None


def test_matches_snippet_with_section_prefix_stripped(l1_chunks):
    """snippet 去掉了 `【章节】` 前缀时也要能匹配。

    前端历史上传过 `cite.snippet`（`hit.content[:200]` 已去前缀）的情况，
    与原始 chunk 的形态不同 —— 归一化匹配必须两种情况都吃。
    """
    from app.domain.retrieval.evidence import strip_chunk_prefix
    from app.interface.routers.documents import _pick_hit_index

    chunks = l1_chunks("8416")
    raw = _real_snippet(chunks, "2.3 结果分析")
    stripped = strip_chunk_prefix(raw)

    assert "【章节】" not in stripped
    idx = _pick_hit_index(chunks, stripped)

    assert idx is not None
    assert "2.3 结果分析" in " → ".join(chunks[idx].get("heading_stack") or [])


def test_empty_snippet_yields_no_match(l1_chunks):
    from app.interface.routers.documents import _pick_hit_index

    chunks = l1_chunks("7611")
    assert _pick_hit_index(chunks, "") is None
    assert _pick_hit_index(chunks, "   ") is None
    assert _pick_hit_index([], "任意片段") is None
