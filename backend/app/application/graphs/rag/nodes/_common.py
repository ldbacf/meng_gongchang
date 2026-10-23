"""QAGraph 节点共享 helper（非状态推进、纯应用逻辑）。

- `last_context_from_history`：取最近 4 条（2 turns）拼意图识别上下文（指代消解）。
- `fetch_l0_meta`：委托 `RetrievalPort.fetch_l0_meta`（ES L0 回填属检索能力，实现留在
  适配器层；本模块保留稳定调用入口供 cite 节点与既有测试使用）。
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
    实现见 `infrastructure.adapters.ports_impl.SearchAdapter.fetch_l0_meta`；此处延迟取，
    保证 `monkeypatch.setattr("app.infrastructure.search.get_es_client", ...)` 仍生效。
    """
    from app.infrastructure.adapters.ports_impl import get_search_adapter

    return get_search_adapter().fetch_l0_meta(hits, es_index=es_index)
