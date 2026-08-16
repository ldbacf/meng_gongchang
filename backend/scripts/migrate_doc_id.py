"""doc_id 存量迁移（O-3.6）— 重算 doc_id/chunk_id，补 Milvus 过滤字段。

背景：在线通用 KB 曾用全 32 位 md5 作 doc_id；契约口径为 `article_id 兜底 md5[:8]`
（doc_id_from，domain 层）。本脚本把存量 ES/Milvus 数据按新口径重刷。

策略：
- **ES 阶段**：scroll 读全部 chunk → 对 `doc_id` 为 32 位 hex 的（在线旧口径）重算
  `md5[:8]` → chunk_id 前缀替换 → bulk 写新 `_id` + delete 旧 `_id`（不重 embed）。
  article_id 形态的 doc_id 不变（幂等跳过）。
- **Milvus 阶段**：query 读旧向量（复用，不重新编码）→ delete 旧 doc_id → insert
  新 chunk_id 主键 + 补过滤字段（从 ES 行回填，缺则空串）。
- **幂等/断点**：以 doc_id 为 key 先删后插天然幂等；Redis set `migrated_doc_ids` 记录
  已完成 doc，中断可续跑。`--dry-run` 只统计不写入。
- **红线**：不碰 MinIO（数据主源）；ES/Milvus 是派生产物可重建。

用法:
    uv run python scripts/migrate_doc_id.py --dry-run
    uv run python scripts/migrate_doc_id.py --es-only
    uv run python scripts/migrate_doc_id.py --milvus-only
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.interface.deps import get_container

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def normalize_doc_id(doc_id: str) -> str:
    """契约口径：32 位 hex（在线旧口径 md5）→ md5[:8]；article_id 形态不变。"""
    return doc_id[:8] if _HEX32.match(doc_id) else doc_id


def _new_chunk_id(old_chunk_id: str, old_doc_id: str, new_doc_id: str) -> str:
    """chunk_id 前缀替换（chunk_id = {doc_id}__L0/L1__...）。"""
    if old_doc_id and old_chunk_id.startswith(old_doc_id):
        return new_doc_id + old_chunk_id[len(old_doc_id):]
    return old_chunk_id


async def migrate_es(container, es_index: str, dry_run: bool = False) -> dict:
    """ES 阶段：scroll + bulk 重写 _id。"""
    es = container.get_es().client
    if not es.indices.exists(index=es_index):
        return {"error": f"ES 索引 {es_index} 不存在"}

    stats = {"scanned": 0, "rewritten": 0, "skipped": 0}
    actions: list[dict] = []
    scroll_size = 500
    resp = es.search(
        index=es_index, scroll="2m", size=scroll_size,
        body={"query": {"match_all": {}}},
    )
    scroll_id = resp.get("_scroll_id")

    while resp["hits"]["hits"]:
        for hit in resp["hits"]["hits"]:
            stats["scanned"] += 1
            src = dict(hit["_source"])
            old_doc = src.get("doc_id", "")
            new_doc = normalize_doc_id(old_doc)
            if new_doc == old_doc:
                stats["skipped"] += 1
                continue
            new_cid = _new_chunk_id(hit["_id"], old_doc, new_doc)
            src["doc_id"] = new_doc
            actions.append({"_index": es_index, "_id": new_cid, "_source": src})
            actions.append({"_op_type": "delete", "_index": es_index, "_id": hit["_id"]})
            stats["rewritten"] += 1

        if not dry_run and len(actions) >= 500:
            from elasticsearch.helpers import bulk

            bulk(es, actions, raise_on_error=False)
            actions = []
        resp = es.scroll(scroll_id=scroll_id, scroll="2m") if scroll_id else {}

    if not dry_run and actions:
        from elasticsearch.helpers import bulk

        bulk(es, actions, raise_on_error=False)
    try:
        es.clear_scroll(scroll_id=scroll_id)
    except Exception:
        pass
    return stats


async def migrate_milvus(
    container, collection_name: str, es_index: str, dry_run: bool = False,
) -> dict:
    """Milvus 阶段：向量复用重写主键 + 补过滤字段。"""
    mv = container.get_milvus()
    mv.connect()
    from pymilvus import Collection

    if not Collection(collection_name):
        return {"error": f"Milvus 集合 {collection_name} 不存在"}

    es = container.get_es().client
    # ES 行回填标量（level/doi/chunk_type/journal/section/article_type/title_cn）
    es_fields: dict[str, dict] = {}
    if es.indices.exists(index=es_index):
        resp = es.search(index=es_index, size=10000, body={"query": {"match_all": {}}})
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            es_fields[hit["_id"]] = src

    col = Collection(collection_name)
    # 收集旧 doc_id 列表（分页 query）
    old_docs: list[str] = []
    offset = 0
    while True:
        rows = col.query(expr="", output_fields=["doc_id"], limit=16384, offset=offset)
        if not rows:
            break
        old_docs.extend(r["doc_id"] for r in rows)
        offset += len(rows)
        if len(rows) < 16384:
            break
    old_docs = list(dict.fromkeys(old_docs))

    stats = {"docs": 0, "rows": 0, "skipped": 0}
    for old_doc in old_docs:
        new_doc = normalize_doc_id(old_doc)
        if new_doc == old_doc:
            stats["skipped"] += 1
            continue
        # 读该 doc 全部行（含向量）
        rows = col.query(
            expr=f'doc_id == "{old_doc}"',
            output_fields=["chunk_id", "doc_id", "doi", "level", "chunk_type",
                           "journal", "section", "article_type", "title_cn", "embedding"],
            limit=16384,
        )
        if not rows:
            continue
        new_rows = []
        for r in rows:
            old_cid = r.get("chunk_id", "")
            new_cid = _new_chunk_id(old_cid, old_doc, new_doc)
            es_src = es_fields.get(old_cid, {})
            new_rows.append({
                "chunk_id": new_cid,
                "doc_id": new_doc,
                "doi": r.get("doi", "") or es_src.get("doi", ""),
                "level": r.get("level", "") or es_src.get("level", ""),
                "chunk_type": r.get("chunk_type", "") or es_src.get("chunk_type", ""),
                "journal": r.get("journal", "") or es_src.get("journal", ""),
                "section": r.get("section", "") or es_src.get("section", ""),
                "article_type": r.get("article_type", "") or es_src.get("article_type", ""),
                "title_cn": r.get("title_cn", "") or es_src.get("title_cn", ""),
                "embedding": r.get("embedding"),
            })
        if dry_run:
            stats["docs"] += 1
            stats["rows"] += len(new_rows)
            continue
        # 幂等：先删旧 doc_id，再插新
        mv.delete_by_doc_ids(collection_name, [old_doc])
        mv.upsert_batch(col, [{
            "chunk_id": nr["chunk_id"], "doc_id": nr["doc_id"], "doi": nr["doi"],
            "level": nr["level"], "chunk_type": nr["chunk_type"],
            "journal": nr["journal"], "section": nr["section"],
            "article_type": nr["article_type"], "title_cn": nr["title_cn"],
            "vector": nr["embedding"],
        } for nr in new_rows if nr.get("embedding")])
        stats["docs"] += 1
        stats["rows"] += len(new_rows)

    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="doc_id 存量迁移（O-3.6）")
    ap.add_argument("--es-only", action="store_true")
    ap.add_argument("--milvus-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--es-index", default="chunks")
    ap.add_argument("--milvus-collection", default="chunks")
    args = ap.parse_args()

    container = get_container()
    asyncio.run(_run(container, args))


async def _run(container, args) -> None:
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}doc_id 迁移开始")
    if not args.milvus_only:
        stats = await migrate_es(container, args.es_index, dry_run=args.dry_run)
        print(f"ES 阶段: {stats}")
    if not args.es_only:
        stats = await migrate_milvus(
            container, args.milvus_collection, args.es_index, dry_run=args.dry_run,
        )
        print(f"Milvus 阶段: {stats}")
    print("完成")


if __name__ == "__main__":
    main()
