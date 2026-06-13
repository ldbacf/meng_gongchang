"""从 ES + MinIO 回填 document_tasks 表（预置文献用）

用法: uv run python scripts/backfill_document_tasks.py

流程:
1. 从 ES 的 chunks 索引取所有 L0 chunk（含 doc_id、md5、title_cn）
2. 用 real md5 去 MinIO raw-docs 桶找对应 PDF 文件
3. 创建 DocumentTask 行，raw_minio_path 指向 MinIO 中的真实路径
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elasticsearch import Elasticsearch
from sqlalchemy import select, func
from src.db import async_session
from src.config import ES_HOST, ES_PORT, MINIO_RAW_BUCKET
from src.models import DocumentTask, KnowledgeBase, TaskStatus, default_pipeline_steps
from src.minio_client import get_minio

es = Elasticsearch(f"http://{ES_HOST}:{ES_PORT}")
mc = get_minio()


async def backfill():
    async with async_session() as db:
        kb = (await db.execute(select(KnowledgeBase).where(KnowledgeBase.slug == "zhong_guo_quan_ke"))).scalar_one_or_none()
        if not kb:
            print("默认知识库不存在，请先启动后端")
            return

        # 已有 md5（避免重复创建）
        existing = set()
        for row in await db.execute(select(DocumentTask.md5)):
            existing.add(row[0])

        # ES 总 L0 数
        total = es.count(index="chunks", body={"query": {"term": {"level": "L0"}}})["count"]
        print(f"ES 中 L0 chunk: {total}  已有 DocumentTask: {len(existing)}")

        created = 0
        skipped = 0
        no_pdf = 0
        page_size = 200
        offset = 0

        while offset < total:
            resp = es.search(index="chunks", body={
                "size": page_size,
                "_source": ["doc_id", "md5", "title_cn", "journal"],
                "query": {"term": {"level": "L0"}},
                "sort": ["doc_id"],
                "from": offset,
            })
            for hit in resp["hits"]["hits"]:
                src = hit["_source"]
                doc_id = src.get("doc_id", "")
                real_md5 = src.get("md5", "")
                title = src.get("title_cn", "") or f"文献-{doc_id}"

                if not doc_id or not real_md5:
                    continue

                # 用 real_md5 查重（不是 doc_id）
                if real_md5 in existing:
                    skipped += 1
                    continue
                existing.add(real_md5)

                # 去 MinIO 找真实 PDF 路径
                pdf_path = None
                objects = list(mc.list_objects(MINIO_RAW_BUCKET, prefix=f"{real_md5}/", recursive=True))
                for obj in objects:
                    if obj.object_name.endswith(".pdf"):
                        pdf_path = obj.object_name
                        break

                if not pdf_path:
                    no_pdf += 1
                    print(f"  [!!] doc_id={doc_id} md5={real_md5}: MinIO 未找到 PDF")

                steps = default_pipeline_steps()
                for s in steps:
                    steps[s]["status"] = "done"

                task = DocumentTask(
                    kb_id=kb.id,
                    md5=real_md5,
                    batch_id=doc_id,  # 存 ES doc_id（如"7597"），删除时用
                    original_name=title,
                    raw_minio_path=f"{MINIO_RAW_BUCKET}/{pdf_path}" if pdf_path else f"preloaded/{doc_id}",
                    status=TaskStatus.READY,
                    pipeline_steps=steps,
                )
                db.add(task)
                created += 1

            offset += page_size
            print(f"  进度: {min(offset, total)}/{total}  新增: {created}  跳过: {skipped}  无PDF: {no_pdf}")

        await db.commit()
        print(f"\n完成: 新增 {created} 条, 跳过 {skipped} 条(已存在), {no_pdf} 条无原生PDF(仅可检索, 无法预览)")


if __name__ == "__main__":
    asyncio.run(backfill())
