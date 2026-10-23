"""索引与事件推送端口 — 让入库子图不直接 import 基础设施实现。

`index_document` 子图原先直接 `from app.infrastructure.indexer import es_bulk_write`、
`from app.infrastructure.ws_manager import broadcast_doc_update`——编排层绑死具体实现。
"""
from __future__ import annotations

from typing import Protocol


class IndexWritePort(Protocol):
    """ES / Milvus 写入。"""

    def es_bulk_write(self, es_index: str, chunks: list[dict]) -> int:
        """写 ES 指定索引（不存在自动建，同源 mapping）；返回成功条数。"""
        ...

    def milvus_insert(self, collection_name: str, chunks: list[dict]) -> int:
        """写 Milvus collection（按 chunk_id 幂等 upsert）；返回写入条数。"""
        ...


class DocumentEventPort(Protocol):
    """文档状态变更广播（WS / 事件总线）。"""

    async def broadcast_doc_update(self, task, kb_id=None) -> None:
        """序列化 DocumentTask 并发布 doc_update；失败静默（推送不该阻断入库）。"""
        ...
