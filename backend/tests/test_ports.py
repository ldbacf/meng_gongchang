"""端口契约测试 — 适配器实现与 domain 端口一致，且不破坏 monkeypatch。

两个目的：
1. **契约绑定**：`SearchAdapter` / `GenerationAdapter` 必须满足 `domain.ports` 的
   方法签名（结构性 Protocol 靠静态检查易漂移，这里做运行时锚定）。
2. **monkeypatch 可达**：既有测试用 `monkeypatch.setattr("app.infrastructure.search.recall_dual", ...)`
   替换**模块属性**。若适配器在模块顶层 `from ... import recall_dual` 拿到函数快照，
   patch 后仍指向旧对象 → 测试静默假绿。适配器必须每次调用都重新取属性。
"""
from __future__ import annotations

import inspect

import pytest

from app.domain.ports.generation import AnswerPort, IntentPort, QueryExpansionPort
from app.domain.ports.indexing import DocumentEventPort, IndexWritePort
from app.domain.ports.retrieval import RetrievalPort
from app.infrastructure.adapters.ports_impl import (
    DocumentEventAdapter,
    GenerationAdapter,
    IndexWriteAdapter,
    SearchAdapter,
    get_document_event_adapter,
    get_generation_adapter,
    get_index_write_adapter,
    get_search_adapter,
)


# ── 契约锚定 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "impl,port",
    [
        (SearchAdapter, RetrievalPort),
        (GenerationAdapter, IntentPort),
        (GenerationAdapter, QueryExpansionPort),
        (GenerationAdapter, AnswerPort),
        (IndexWriteAdapter, IndexWritePort),
        (DocumentEventAdapter, DocumentEventPort),
    ],
)
def test_adapter_implements_port_methods(impl, port):
    """端口声明的每个方法，适配器都必须实现（同名、可调用）。"""
    for name in dir(port):
        if name.startswith("_"):
            continue
        attr = getattr(port, name, None)
        if not callable(attr):
            continue
        assert hasattr(impl, name), f"{impl.__name__} 缺端口方法 {name}"
        assert callable(getattr(impl, name))


def test_retrieval_port_signature_matches():
    """recall_dual 的关键参数名必须一致（节点按关键字传 es_index/milvus_collection）。"""
    port_sig = inspect.signature(RetrievalPort.recall_dual)
    impl_sig = inspect.signature(SearchAdapter.recall_dual)
    for p in ("query", "es_index", "milvus_collection"):
        assert p in port_sig.parameters
        assert p in impl_sig.parameters, f"实现缺参数 {p}"


def test_answer_port_signature_matches():
    port_sig = inspect.signature(AnswerPort.build_prompt)
    impl_sig = inspect.signature(GenerationAdapter.build_prompt)
    for p in ("query", "hits", "history", "top_n"):
        assert p in impl_sig.parameters, f"实现缺参数 {p}"
        assert p in port_sig.parameters


# ── monkeypatch 可达性（关键回归）─────────────────────────────


def test_search_adapter_sees_module_level_patch(monkeypatch):
    """patch `app.infrastructure.search.recall_dual` 必须对适配器生效。"""
    import app.infrastructure.search as search_mod

    calls = []

    def fake(query, **kw):
        calls.append(query)
        return [], []

    monkeypatch.setattr(search_mod, "recall_dual", fake)
    get_search_adapter().recall_dual("测试查询")
    assert calls == ["测试查询"]


def test_generation_adapter_sees_module_level_patch(monkeypatch):
    """patch `...adapters.llm_answer.build_answer_prompt` / `answer_stream_async` 必须生效。"""
    import app.infrastructure.adapters.llm_answer as ans_mod

    monkeypatch.setattr(ans_mod, "build_answer_prompt", lambda q, h, hist=None, top_n=5: f"P:{q}")
    assert get_generation_adapter().build_prompt("问", []) == "P:问"

    async def fake_stream(prompt, kb_kind):
        yield "tok"

    monkeypatch.setattr(ans_mod, "answer_stream_async", fake_stream)
    gen = get_generation_adapter().stream("P:问")
    assert inspect.isasyncgen(gen) or hasattr(gen, "__aiter__")


def test_intent_adapter_sees_module_level_patch(monkeypatch):
    import app.infrastructure.adapters.query_intent as intent_mod
    from app.domain.rag.intent import IntentResult

    monkeypatch.setattr(
        intent_mod, "analyze_intent",
        lambda q, ctx="", kb_kind=None, timeout=10.0: IntentResult(domain="心血管"),
    )
    assert get_generation_adapter().analyze("q").domain == "心血管"


def test_index_write_adapter_sees_module_level_patch(monkeypatch):
    import app.infrastructure.indexer as idx_mod

    monkeypatch.setattr(idx_mod, "es_bulk_write", lambda index, chunks: len(chunks))
    assert get_index_write_adapter().es_bulk_write("kb", [{"a": 1}, {"b": 2}]) == 2


# ── 异常继承链（应用层只依赖端口异常）──────────────────────────


def test_adapter_exceptions_inherit_port_contract():
    """适配器异常必须继承 domain 端口异常，应用层才能只按契约判断重试。"""
    from app.domain.ports.exceptions import FatalError, QuotaExhaustedError, TransientError
    from app.infrastructure.adapters.embedding_http import EmbeddingServiceError
    from app.infrastructure.adapters.mineru import MineruFatalError, MineruTransientError
    from app.infrastructure.key_manager import TokenExhausted

    assert issubclass(MineruTransientError, TransientError)
    assert issubclass(EmbeddingServiceError, TransientError)
    assert issubclass(MineruFatalError, FatalError)
    assert issubclass(TokenExhausted, QuotaExhaustedError)


def test_nodes_do_not_import_concrete_adapters():
    """图节点不得直接 import 具体适配器模块（必须经端口适配器）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "app" / "application" / "graphs"
    banned = (
        "from app.infrastructure.search import",
        "from app.infrastructure.indexer import",
        "from app.infrastructure.ws_manager import",
        "from app.infrastructure.adapters.llm_answer import",
        "from app.infrastructure.adapters.query_intent import",
        "from app.infrastructure.adapters.query_expansion import",
        "from app.infrastructure.adapters.mineru import",
        "from app.infrastructure.adapters.embedding_http import",
    )
    hits = []
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for b in banned:
            if b in text:
                hits.append(f"{path.name}: {b}")
    assert not hits, "节点仍直接依赖具体适配器:\n" + "\n".join(hits)
