"""检索 / 生成适配器 — 把 infrastructure 的函数封装成 domain 端口。

**为什么要这层**：application 的图节点原先直接 `from app.infrastructure.search import
recall_dual`、`from app.infrastructure.adapters.llm_answer import answer_stream_async`
——编排层硬绑具体实现，换供应商要改节点。这里给出端口实现，节点改依赖本模块。

**为什么用 `_impl()` 延迟取函数而非模块顶层 import**：
既有测试用 `monkeypatch.setattr("app.infrastructure.search.recall_dual", fake)` 替换
**模块属性**。若在此处顶层 `from ... import recall_dual` 拿到的是函数对象的快照，
monkeypatch 之后本适配器仍指向旧对象 → 测试静默失效（假绿）。
故每次调用都经 `_impl()` 重新取模块属性。
"""
from __future__ import annotations

from typing import AsyncIterator

from app.domain.knowledge_base import KBKind
from app.domain.rag.intent import IntentResult
from app.domain.retrieval.search_hit import SearchHit


def _search_module():
    import app.infrastructure.search as m

    return m


def _intent_module():
    import app.infrastructure.adapters.query_intent as m

    return m


def _expansion_module():
    import app.infrastructure.adapters.query_expansion as m

    return m


def _answer_module():
    import app.infrastructure.adapters.llm_answer as m

    return m


class SearchAdapter:
    """`domain.ports.retrieval.RetrievalPort` 的实现（ES + Milvus + rerank）。"""

    def recall_dual(
        self,
        query: str,
        filters: dict | None = None,
        milvus_top_k: int = 200,
        es_top_k: int = 200,
        es_index: str | None = None,
        milvus_collection: str | None = None,
    ) -> tuple[list[SearchHit], list[SearchHit]]:
        return _search_module().recall_dual(
            query,
            filters=filters,
            milvus_top_k=milvus_top_k,
            es_top_k=es_top_k,
            es_index=es_index,
            milvus_collection=milvus_collection,
        )

    def rerank(
        self, query: str, docs: list[SearchHit], top_n: int | None = None
    ) -> list[SearchHit]:
        return _search_module().rerank(query, docs, top_n)

    def fetch_l0_meta(self, hits: list, es_index: str | None = None) -> dict[str, dict]:
        """批量查 ES L0 chunk 回填 title_cn / journal / md5（cite 节点用）。"""
        if not hits:
            return {}
        doc_ids = sorted({h.doc_id for h in hits if h.doc_id and not h.title_cn})
        if not doc_ids:
            return {}

        from app.infrastructure.settings import get_settings

        try:
            es = _search_module().get_es_client()
            resp = es.search(
                index=es_index or get_settings().es_index,
                body={
                    "size": len(doc_ids),
                    "query": {
                        "bool": {
                            "must": [
                                {"terms": {"doc_id": doc_ids}},
                                {"term": {"level": "L0"}},
                            ]
                        }
                    },
                    "_source": ["doc_id", "title_cn", "journal", "md5"],
                },
            )
            result: dict[str, dict] = {}
            for hit in resp.get("hits", {}).get("hits", []):
                src = hit["_source"]
                result[src.get("doc_id", "")] = {
                    "title_cn": src.get("title_cn", ""),
                    "journal": src.get("journal", ""),
                    "md5": src.get("md5", ""),
                }
            return result
        except Exception:
            return {}


class GenerationAdapter:
    """`domain.ports.generation` 的实现（意图 / 扩展 / 回答）。"""

    # ── IntentPort ──

    def analyze(
        self,
        query: str,
        last_context: str = "",
        kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
        timeout: float = 10.0,
    ) -> IntentResult:
        return _intent_module().analyze_intent(
            query, last_context, kb_kind, timeout=timeout
        )

    # ── QueryExpansionPort ──

    def expand(self, query: str, timeout: float = 8.0) -> str:
        return _expansion_module().expand_query(query, timeout=timeout)

    # ── AnswerPort ──

    def build_prompt(
        self,
        query: str,
        hits: list,
        history: list[dict] | None = None,
        top_n: int = 5,
    ) -> str:
        return _answer_module().build_answer_prompt(
            query, hits, history, top_n=top_n
        )

    def stream(
        self,
        user_prompt: str,
        kb_kind: KBKind = KBKind.MEDICAL_DEFAULT,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        mod = _answer_module()
        if system_prompt is None:
            # 不传时保持原有调用形状（测试里对 answer_stream_async 的 monkeypatch
            # 可能只接受两个位置参数）
            return mod.answer_stream_async(user_prompt, kb_kind)
        return mod.answer_stream_async(
            user_prompt, kb_kind, system_prompt=system_prompt
        )


class IndexWriteAdapter:
    """`domain.ports.indexing.IndexWritePort` 的实现。"""

    def es_bulk_write(self, es_index: str, chunks: list[dict]) -> int:
        import app.infrastructure.indexer as m

        return m.es_bulk_write(es_index, chunks)

    def milvus_insert(self, collection_name: str, chunks: list[dict]) -> int:
        import app.infrastructure.indexer as m

        return m.milvus_insert(collection_name, chunks)


class DocumentEventAdapter:
    """`domain.ports.indexing.DocumentEventPort` 的实现。"""

    async def broadcast_doc_update(self, task, kb_id=None) -> None:
        import app.infrastructure.ws_manager as m

        await m.broadcast_doc_update(task, kb_id)


# ── 单例（无状态，进程内复用）──────────────────────────────

_search = SearchAdapter()
_generation = GenerationAdapter()
_index_write = IndexWriteAdapter()
_doc_event = DocumentEventAdapter()


def get_search_adapter() -> SearchAdapter:
    return _search


def get_generation_adapter() -> GenerationAdapter:
    return _generation


def get_index_write_adapter() -> IndexWriteAdapter:
    return _index_write


def get_document_event_adapter() -> DocumentEventAdapter:
    return _doc_event
