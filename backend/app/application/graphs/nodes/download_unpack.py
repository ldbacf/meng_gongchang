"""download_unpack 节点 — 下载 MinerU 产物 zip + 解包存 MinIO + 标记 task PARSED。

设计文档的 download_assets / unpack_store 两步合并为单节点：zip bytes 若进图 state
会被 checkpoint 序列化（每节点落 Postgres，大 zip 不可接受），故下载与解包在节点内
串联完成，state 只记录 `parsed_md5s`（轻量）。
"""
from __future__ import annotations

from app.application.graphs.nodes._task import ensure_parsed, mark_failed, update_steps
from app.application.graphs.state import IngestState


async def download_unpack(state: IngestState) -> dict:
    """下载 done 产物 → 解包存 MinIO → 标记 PARSED；failed 产物标记 FAILED。"""
    from app.interface.deps import get_container

    container = get_container()
    mineru = container.get_mineru()
    minio = container.get_minio()

    parsed_md5s = list(state.get("parsed_md5s") or [])
    for md5, item in (state.get("poll_items") or {}).items():
        if item.get("state") == "failed":
            await mark_failed(md5, item.get("err_msg") or "MinerU 解析失败")
            await update_steps(md5, "mineru", "failed", error=item.get("err_msg") or "MinerU 解析失败")
            continue
        try:
            zip_bytes = await mineru.download_result(item["full_zip_url"])
            md_url = minio.upload_parsed_assets(md5, zip_bytes)
            await ensure_parsed(md5)  # PENDING→PROCESSING→PARSED（含重跑补跳）
            await update_steps(md5, "mineru", "done")
            parsed_md5s.append(md5)
        except Exception as e:
            await mark_failed(md5, f"下载/解包失败: {e}")
            await update_steps(md5, "mineru", "failed", error=f"下载/解包失败: {e}")

    return {"parsed_md5s": parsed_md5s}
