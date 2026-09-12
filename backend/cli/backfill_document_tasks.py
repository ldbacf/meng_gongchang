"""从 ES + MinIO 回填 document_tasks 表（预置文献用）。

流程:
1. 从 ES chunks 索引取所有 L0 chunk（含 doc_id、md5、title_cn）
2. 用 real md5 去 MinIO raw-docs 桶找对应 PDF
3. 创建 DocumentTask 行，raw_minio_path 指向 MinIO 中的真实路径

用法: python -m cli.backfill_document_tasks
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.domain.knowledge_base import KBKind
from app.infrastructure.settings import get_settings
from app.interface.deps import get_container
from src.models import DocumentTask, KnowledgeBase, TaskStatus, default_pipeline_steps


async def backfill() -> None:
    container = get_container()
    es = container.get_es().client
    mc = container.get_minio()
    sessionmaker = container.get_db_sessionmaker()

    async with sessionmaker() as db:
        kb = (
            await db.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.kb_kind == KBKind.MEDICAL_DEFAULT.value
                )
            )
        ).scalar_one_or_none()
        if not kb:
            print("默认知识库不存在，请先启动后端")
            return

        existing = {row[0] for row in await db.execute(select(DocumentTask.md5))}

        total = es.count(index="chunks", body={"query": {"term": {"level": "L0"}}})["count"]
        print(f"ES 中 L0 chunk: {total}  已有 DocumentTask: {len(existing)}")

        created = skipped = no_pdf = 0
        page_size, offset = 200, 0

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
                if not doc_id or not real_md5 or real_md5 in existing:
                    skipped += 1
                    continue
                existing.add(real_md5)

                pdf_path = None
                for obj in mc.list_objects(get_settings().minio_raw_bucket, prefix=f"{real_md5}/", recursive=True):
                    if obj.object_name.endswith(".pdf"):
                        pdf_path = obj.object_name
                        break
                if not pdf_path:
                    no_pdf += 1
                    print(f"  [!!] doc_id={doc_id} md5={real_md5}: MinIO 未找到 PDF")

                steps = default_pipeline_steps()
                for s in steps:
                    steps[s]["status"] = "done"

                db.add(DocumentTask(
                    kb_id=kb.id,
                    md5=real_md5,
                    batch_id=doc_id,  # 存 ES doc_id（如"7597"），删除时用
                    original_name=src.get("title_cn", "") or f"文献-{doc_id}",
                    raw_minio_path=f"{get_settings().minio_raw_bucket}/{pdf_path}" if pdf_path else f"preloaded/{doc_id}",
                    status=TaskStatus.READY,
                    pipeline_steps=steps,
                ))
                created += 1

            offset += page_size
            print(f"  进度: {min(offset, total)}/{total}  新增: {created}  跳过: {skipped}  无PDF: {no_pdf}")

        await db.commit()
        print(f"\n完成: 新增 {created} 条, 跳过 {skipped} 条(已存在), {no_pdf} 条无原生PDF(仅可检索, 无法预览)")


def main() -> None:
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
