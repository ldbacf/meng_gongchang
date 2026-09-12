"""Milvus 客户端适配器 — 连接 / collection 生命周期 + 幂等写入。

- `connect()` 幂等；`close()` 在容器 shutdown 时断开。
- `ensure_collection()`：不存在则按共享 schema（`app/infrastructure/milvus/schema.py`）
  自动创建 + 建索引；已存在则复用（仅当 embedding 维度与 Settings 不符时重建，保留旧行为）。
- `upsert_batch()`：按 chunk_id **先删后插**（幂等），供图重跑/文档重索引安全前提。
- pymilvus 的 connections 是库级全局，本适配器只负责 connect/disconnect 生命周期与调用封装。
"""
from __future__ import annotations

from pymilvus import Collection, connections, utility

from app.infrastructure.milvus.schema import (
    build_milvus_fields,
    build_milvus_index_params,
    build_milvus_schema,
    truncate_field,
)
from app.infrastructure.settings import Settings, get_settings

# Milvus in 表达式单条长度上限的保守分批阈值
_DELETE_BATCH = 200


class MilvusAdapter:
    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return
        s = self._settings
        connections.connect(host=s.milvus_host, port=s.milvus_port)
        self._connected = True

    def is_connected(self) -> bool:
        try:
            return connections.has_connection("default")
        except Exception:
            return False

    def ensure_collection(self, collection_name: str) -> Collection:
        """存在则复用（维度不符时重建），不存在则按共享 schema 创建。"""
        self.connect()
        s = self._settings

        if utility.has_collection(collection_name):
            existing = Collection(collection_name)
            for f in existing.schema.fields:
                if f.name == "embedding" and getattr(f, "params", None):
                    if f.params.get("dim") != s.embedding_dim:
                        existing.release()
                        utility.drop_collection(collection_name)
                    break

        if utility.has_collection(collection_name):
            return Collection(collection_name)

        schema = build_milvus_schema(dim=s.embedding_dim)
        col = Collection(name=collection_name, schema=schema)
        col.create_index(
            field_name="embedding",
            index_params=build_milvus_index_params(nlist=s.milvus_nlist),
        )
        col.load()
        return col

    def get_collection(self, collection_name: str) -> Collection:
        """直接取已有 collection（假定已初始化），调用方负责 load。"""
        self.connect()
        col = Collection(collection_name)
        col.load()
        return col

    def upsert_batch(self, collection: Collection, chunks: list[dict]) -> int:
        """按 chunk_id 先删后插（幂等）。缺失的标量字段填空串，向量缺失的跳过。

        返回实际写入行数。
        """
        self.connect()
        rows = [c for c in chunks if c.get("vector")]
        if not rows:
            return 0

        chunk_ids = [r["chunk_id"] for r in rows]
        # 先删：按 chunk_id 批量删除（幂等，重复索引不撞主键）
        for i in range(0, len(chunk_ids), _DELETE_BATCH):
            part = chunk_ids[i:i + _DELETE_BATCH]
            quoted = ", ".join(f'"{c}"' for c in part)
            collection.delete(f"chunk_id in [{quoted}]")

        # 后插：共享 schema 10 字段（doc_id 截断到 max_length=32）
        collection.insert(
            [
                [_trunc(r, "chunk_id") for r in rows],
                [_trunc(r, "doc_id") for r in rows],
                [_trunc(r, "doi") for r in rows],
                [_trunc(r, "level") for r in rows],
                [_trunc(r, "chunk_type") for r in rows],
                [_trunc(r, "journal") for r in rows],
                [_trunc(r, "section") for r in rows],
                [_trunc(r, "article_type") for r in rows],
                [_trunc(r, "title_cn") for r in rows],
                [r["vector"] for r in rows],
            ]
        )
        collection.flush()
        return len(rows)

    def search(
        self,
        collection_name: str,
        query_embedding: list[float],
        filters: dict | None = None,
        top_k: int = 200,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """向量召回。返回 [{chunk_id, doc_id, level, chunk_type, doi, title_cn, score, rank}]。

        `output_fields` 缺省用共享 schema 全字段；存量 4 字段通用集合传精简字段
        （chunk_id/doc_id/title），否则请求不存在字段会报错。
        """
        self.connect()
        col = self.get_collection(collection_name)

        expr_parts = []
        if filters:
            for key, val in filters.items():
                if key == "level":
                    if isinstance(val, list):
                        parts = [f'{key} == "{v}"' for v in val]
                        expr_parts.append(f"({' || '.join(parts)})")
                    else:
                        expr_parts.append(f'{key} == "{val}"')
                elif key in ("chunk_type", "journal", "section", "article_type", "doi"):
                    expr_parts.append(f'{key} == "{val}"')
        expr = " && ".join(expr_parts) if expr_parts else None

        fields = output_fields or ["chunk_id", "doc_id", "level", "chunk_type", "doi", "title_cn"]
        results = col.search(
            data=[query_embedding],
            anns_field="embedding",
            param={"metric_type": "COSINE", "nprobe": 16},
            limit=top_k,
            expr=expr,
            output_fields=fields,
        )

        hits = []
        for rank, hit in enumerate(results[0]):
            fields = hit.entity.fields
            hits.append({
                "chunk_id": fields.get("chunk_id", ""),
                "doc_id": fields.get("doc_id", ""),
                "level": fields.get("level", ""),
                "chunk_type": fields.get("chunk_type", ""),
                "doi": fields.get("doi", ""),
                "title": fields.get("title", ""),
                "title_cn": fields.get("title_cn", ""),
                "score": hit.score,
                "rank": rank + 1,
            })
        return hits

    def delete_by_doc_ids(self, collection_name: str, doc_ids: list[str]) -> None:
        """按 doc_id 批量删除（删除 key 统一 doc_id）。"""
        if not doc_ids:
            return
        self.connect()
        col = Collection(collection_name)
        quoted = ", ".join(f'"{d}"' for d in doc_ids)
        col.delete(f"doc_id in [{quoted}]")

    def count_by_doc_id(self, collection_name: str, doc_id: str) -> int:
        """per-doc 残留计数（对账用；**不能用 num_entities**——集合级总数）。"""
        self.connect()
        col = Collection(collection_name)
        try:
            rows = col.query(expr=f'doc_id == "{doc_id}"', output_fields=["count(*)"])
            return int(rows[0]["count(*)"]) if rows else 0
        except Exception:
            return -1  # 查询失败（如集合不存在）——对账时视为不可确认

    def close(self) -> None:
        try:
            connections.disconnect("default")
        except Exception:
            pass
        self._connected = False


def _trunc(chunk: dict, field: str) -> str:
    return truncate_field(str(chunk.get(field, "") or ""), field)
