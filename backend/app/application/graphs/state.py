"""IngestionGraph 状态契约（contract 4.2.1 落地）。

- 批图（thread_id=batch:{batch_id}）处理整批；index_document 子图（thread_id=batch:{batch_id}:doc:{md5}）per-doc。
- `poll_started_ts`：轮询超时时钟基准（进程内墙钟崩溃重启会归零，故入 state）。
- `poll_pending`：poll_parsed 返回 pending 时置 True，条件边走 pause_wait（interrupt）。
- `error/fatal`：节点异常统一写入，finalize 以 DB 回读判定终态。
"""
from __future__ import annotations

from typing import TypedDict


class IngestState(TypedDict, total=False):
    # 批上下文（来自 BatchMessage + SubmissionService）
    batch_id: str
    md5_list: list[str]
    token_id: str
    mode: str  # "submit" | "resume"（retry 从 checkpoint 恢复用）
    # 轮询
    poll_count: int
    poll_started_ts: float
    poll_items: dict  # md5 → MinerU extract item（done 的）
    poll_pending: bool
    # 下载/解包
    parsed_md5s: list[str]  # 已下载解包存入 MinIO 的 md5
    # 派发/终态
    doc_results: dict  # md5 → "ready" | "failed"
    error: dict | None  # {step, type: Fatal|Transient, message}
    fatal: bool


class IndexDocState(TypedDict, total=False):
    """index_document 子图状态（per-doc，thread_id=batch:{batch_id}:doc:{md5}）。"""
    batch_id: str
    md5: str
    kb_kind: str
    es_index: str
    milvus_collection: str
    title: str
    parsed_full_md: str | None
    chunks: list | None
    vectors: list | None
    es_written: int | None
    milvus_written: int | None
    error: dict | None
    fatal: bool
