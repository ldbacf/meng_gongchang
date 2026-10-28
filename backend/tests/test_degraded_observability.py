"""降级可观测性 —— 降级必须留日志、并把原因带进 metrics。

## 为什么需要这一组

真实事故：Milvus 因字段名写错（请求了 schema 里不存在的 `title`）每次向量检索
都抛 `MilvusException: field title not exist`。三个节点里都是裸

    except Exception:
        degraded = True

异常被彻底吞掉。后果是一条完整的伪装链：

    配置/代码错误  →  向量路恒 0 条  →  rerank 分数被拉低
                  →  「库内证据不足」→  直答

用户看到的是「知识库中未找到相关文献」，**和"这个库确实没有"完全一样**。
排查时日志里一个字都没有 —— `retrieval.py` 里那个
`logger = logging.getLogger(__name__)` 声明了却从未使用。

现在：降级时记 warning/error（含栈）+ `metrics["degraded_reason"]`。

## 契约细节

`degraded_reason` **只在降级时出现**。不降级时不写这个 key，保持
`test_sse_rag.py::test_metrics_single_source_fields` 对字段集的精确断言不变。
"""
from __future__ import annotations

import logging

import pytest

from app.application.rag.rag_metrics import build_rag_step, describe_exception


def _log_texts(caplog) -> str:
    """日志正文拼接。

    用 `record.getMessage()` 而不是 `record.message`：后者是**未格式化**的模板
    （`"...: %s"`），自己拼 `% r.args` 容易踩到参数个数不匹配。
    """
    return "\n".join(r.getMessage() for r in caplog.records)


def _hit(**over):
    """满足 `rrf_fusion` 所需属性的最小 SearchHit 替身。

    `rrf_fusion` 要读 `rank_milvus` / `rank_es` / `score_rrf` / `content` 等，
    缺一个就 AttributeError。用真实 SearchHit 更省事，也避免替身随契约漂移。
    """
    from app.domain.retrieval.search_hit import SearchHit

    base = dict(
        chunk_id="c1", doc_id="d1", level="L1", chunk_type="body",
        content="正文", score_milvus=0.9, rank_milvus=1,
    )
    base.update(over)
    return SearchHit(**base)


# ── describe_exception 纯函数 ─────────────────────────────────


def test_describe_exception_keeps_type_and_first_line():
    exc = ValueError("第一条消息\n第二条不该出现")
    text = describe_exception(exc)
    assert text.startswith("ValueError: ")
    assert "第一条消息" in text
    assert "第二条" not in text, "多行异常只取首行，避免撑大 SSE 帧"


def test_describe_exception_handles_none_and_empty_message():
    assert describe_exception(None) == ""
    # 无消息的异常只给类名，不留孤零零的冒号
    assert describe_exception(RuntimeError()) == "RuntimeError"


def test_describe_exception_truncates_long_message():
    text = describe_exception(ValueError("x" * 1000))
    assert len(text) <= 200, f"降级原因没截断（{len(text)} 字符），会撑大 SSE 帧与 DB JSONB"


def test_describe_exception_preserves_milvus_like_message():
    """复刻事故里的真实形态。"""
    text = describe_exception(
        RuntimeError('<MilvusException: (code=65535, message=field title not exist )>')
    )
    assert "field title not exist" in text


# ── build_rag_step 的 degraded_reason 契约 ────────────────────


def test_reason_absent_when_not_degraded():
    """不降级时不能凭空多出 degraded_reason 字段。

    这是与既有字段集断言的兼容点：四步 metrics 的键集是定稿契约，
    加字段会让 `test_metrics_single_source_fields` 之类的精确断言失效。
    """
    for key in ("intent", "retrieval", "fusion", "answer"):
        metrics = build_rag_step(key, degraded=False)["metrics"]
        assert "degraded_reason" not in metrics, f"{key} 未降级却带了 degraded_reason"


def test_reason_present_when_degraded_with_reason():
    metrics = build_rag_step(
        "retrieval", degraded=True,
        degraded_reason="MilvusException: field title not exist",
    )["metrics"]
    assert metrics["degraded"] is True
    assert metrics["degraded_reason"] == "MilvusException: field title not exist"


def test_degraded_without_reason_does_not_inject_empty_key():
    """降级但没给原因时也不塞空串（前端据此判断「有原因可展示」）。"""
    metrics = build_rag_step("fusion", degraded=True)["metrics"]
    assert metrics["degraded"] is True
    assert "degraded_reason" not in metrics


# ── 节点实际行为：降级要留日志 + 带原因 ───────────────────────


@pytest.mark.asyncio
async def test_retrieval_logs_and_reports_reason(monkeypatch, caplog):
    """检索异常 → ERROR 日志 + metrics.degraded_reason（事故的直接回归）。"""
    from app.application.graphs.rag.nodes import retrieval as mod

    class _BoomSearch:
        def recall_dual(self, query, **kwargs):
            raise RuntimeError("field title not exist")

    monkeypatch.setattr(
        "app.infrastructure.adapters.ports_impl.get_search_adapter",
        lambda: _BoomSearch(),
    )

    with caplog.at_level(logging.ERROR, logger=mod.__name__):
        out = await mod.retrieval({"query": "任意问题", "kb": {"es_index": "i", "milvus_collection": "c"}})

    step = out["rag_steps"]["retrieval"]
    assert step["metrics"]["degraded"] is True
    reason = step["metrics"]["degraded_reason"]
    assert "field title not exist" in reason

    assert "检索降级" in _log_texts(caplog), "检索降级没有留日志 —— 事故时就是这样静默的"


@pytest.mark.asyncio
async def test_fusion_logs_and_reports_reason(monkeypatch, caplog):
    """rerank 抛错 → WARNING + 保序返回 + 原因。

    刻意**不**做成"上抛由服务层兜底"：一次重排服务抖动不该让整个回答变成错误页，
    降级保序 + 显式标注是更好的取舍。
    """
    from app.application.graphs.rag.nodes import fusion as mod

    async def _boom(query, hits):
        raise RuntimeError("rerank 503")

    monkeypatch.setattr(mod, "_rerank", _boom)

    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        out = await mod.fusion({"query": "q", "hits": [_hit()], "es_hits": []})

    step = out["rag_steps"]["fusion"]
    assert step["metrics"]["degraded"] is True
    assert "rerank 503" in step["metrics"]["degraded_reason"]
    assert out["reranked"], "降级时必须保序返回，不能返回空列表"
    assert "重排降级" in _log_texts(caplog)


@pytest.mark.asyncio
async def test_fusion_reports_reason_on_all_zero_scores(monkeypatch):
    """非异常型降级（重排全 0 分）也要给原因，否则前端只能说「未知」。"""
    from app.application.graphs.rag.nodes import fusion as mod

    async def _all_zero(query, hits):
        return list(hits)

    monkeypatch.setattr(mod, "_rerank", _all_zero)

    out = await mod.fusion({"query": "q", "hits": [_hit()], "es_hits": []})

    step = out["rag_steps"]["fusion"]
    assert step["metrics"]["degraded"] is True
    assert "0 分" in step["metrics"]["degraded_reason"]


class _FakeSettings:
    use_query_expansion = False


def _patch_intent_deps(monkeypatch, gen):
    """`intent` 节点用模块级 import 的 `get_generation_adapter` / `get_container`。

    必须在**节点模块**上打补丁；打在 `ports_impl` 上无效，因为名字早已被
    绑进 `intent` 的模块命名空间。
    """
    from app.application.graphs.rag.nodes import intent as mod

    monkeypatch.setattr(mod, "get_generation_adapter", lambda: gen)
    monkeypatch.setattr(
        mod, "get_container",
        lambda: type("C", (), {"get_settings": staticmethod(lambda: _FakeSettings())})(),
    )


@pytest.mark.asyncio
async def test_intent_logs_and_reports_reason(monkeypatch, caplog):
    """意图识别异常 → WARNING + 原因，且仍按 coverage=unknown 继续检索。"""
    from app.application.graphs.rag.nodes import intent as mod

    class _BoomGen:
        def analyze(self, *a, **kw):
            raise RuntimeError("deepseek timeout")

        def expand(self, *a, **kw):
            return None

    _patch_intent_deps(monkeypatch, _BoomGen())

    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        out = await mod.intent({"query": "q", "kb": {"kb_kind": "generic"}})

    step = out["rag_steps"]["intent"]
    assert step["metrics"]["degraded"] is True
    assert "deepseek timeout" in step["metrics"]["degraded_reason"]
    # 降级后行为不变：coverage 归为 unknown，走保守检索
    assert out["intent"]["coverage"] == "unknown"
    assert out["rewritten_query"] == "q"
    assert "意图识别降级" in _log_texts(caplog)


@pytest.mark.asyncio
async def test_intent_reports_reason_on_empty_model_result(monkeypatch):
    """模型返回空 domain/coverage（非异常）也要有原因，不能只标 degraded。"""
    from app.application.graphs.rag.nodes import intent as mod
    from app.domain.rag.intent import IntentResult

    class _EmptyGen:
        def analyze(self, *a, **kw):
            return IntentResult()  # 全空

        def expand(self, *a, **kw):
            return None

    _patch_intent_deps(monkeypatch, _EmptyGen())

    out = await mod.intent({"query": "q", "kb": {}})

    step = out["rag_steps"]["intent"]
    assert step["metrics"]["degraded"] is True
    assert "空结果" in step["metrics"]["degraded_reason"]
