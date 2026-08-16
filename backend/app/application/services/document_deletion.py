"""DeleteDocumentService — 按统一 doc_id 删除 ES/Milvus + 残留对账（S-3.6）。

- 删除 key：三口径并集（task_batch_id=预置 article_id / md5[:8]=契约 / md5=存量旧口径），
  迁移完成后退化为单口径 doc_id。
- 顺序：先 ES（delete_by_query + **显式 refresh/wait_for**）后 Milvus（delete）。
- 对账：ES count=0；Milvus per-doc `count(*)`（**不用 num_entities**）。
- 竞态防护：非终态 task（处理中）拒绝删除（409）。
"""
from __future__ import annotations

from sqlalchemy import select

from src.models import DocumentTask, TaskStatus


class DocumentBusyError(Exception):
    """文档仍在处理中，不能删除。"""


class DeleteDocumentService:
    def __init__(self, container):
        self._container = container

    def _candidate_doc_ids(self, task: DocumentTask) -> list[str]:
        return list(dict.fromkeys(filter(None, [task.batch_id, task.md5[:8], task.md5])))

    async def delete(self, task: DocumentTask) -> dict:
        """删除文档的 ES/Milvus 数据（不动 MinIO 原始数据）。返回对账结果。"""
        if task.status not in (
            TaskStatus.READY.value,
            TaskStatus.FAILED.value,
            TaskStatus.PARSED.value,
        ):
            raise DocumentBusyError("文档仍在处理中，不能删除")

        steps = task.pipeline_steps or {}
        doc_ids = self._candidate_doc_ids(task)
        es_index = (steps.get("es_write") or {}).get("target_index")
        mv_collection = (steps.get("milvus") or {}).get("target_collection")

        es_remaining = None
        mv_remaining = None

        # ── ES：delete_by_query + 显式 refresh 后对账 ──
        if es_index and doc_ids:
            es = self._container.get_es().client
            try:
                es.delete_by_query(
                    index=es_index,
                    body={"query": {"terms": {"doc_id": doc_ids}}},
                    refresh=True,
                )
                es_remaining = es.count(index=es_index, body={
                    "query": {"terms": {"doc_id": doc_ids}},
                })["count"]
            except Exception:
                es_remaining = -1  # 不可确认

        # ── Milvus：delete + per-doc count 对账 ──
        if mv_collection and doc_ids:
            mv = self._container.get_milvus()
            try:
                mv.delete_by_doc_ids(mv_collection, doc_ids)
                mv_remaining = sum(
                    mv.count_by_doc_id(mv_collection, d) for d in doc_ids
                )
            except Exception:
                mv_remaining = -1

        return {"es_remaining": es_remaining, "milvus_remaining": mv_remaining}
