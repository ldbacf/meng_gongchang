"""QAGraph 节点共享 helper（非状态推进、纯应用逻辑）。

- `last_context_from_history`：取最近 4 条（2 turns）拼意图识别上下文（指代消解）。
- `fetch_l0_meta`：批量查 ES L0 chunk 回填 title_cn/journal/md5（自 chat.py `_fetch_l0_meta` 迁入）。
"""
from __future__ import annotations


def last_context_from_history(history: list[dict], turns: int = 2) -> str:
    """把最近 `turns*2` 条消息拼成意图识别的上轮对话上下文（指代消解用）。"""
    recent = history[-turns * 2:] if history else []
    lines = []
    for m in recent:
        role_label = "用户" if m.get("role") == "user" else "AI"
        lines.append(f"{role_label}：{str(m.get('content', ''))[:300]}")
    return "\n".join(lines)


def fetch_l0_meta(hits: list, es_index: str | None = None) -> dict[str, dict]:
    """批量查 ES L0 chunk 回填 title_cn / journal / md5（MEDICAL_DEFAULT 引用需要）。

    `es_index` 取自 KB 目标的 es_index（QaState.kb.es_index），后端到点检索，非硬编码缺省。
    """
    if not hits:
        return {}
    from app.infrastructure.search import get_es_client

    doc_ids = sorted({h.doc_id for h in hits if h.doc_id and not h.title_cn})
    if not doc_ids:
        return {}

    try:
        es = get_es_client()
        resp = es.search(
            index=es_index or "chunks",
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
            did = src.get("doc_id", "")
            result[did] = {
                "title_cn": src.get("title_cn", ""),
                "journal": src.get("journal", ""),
                "md5": src.get("md5", ""),
            }
        return result
    except Exception:
        return {}
