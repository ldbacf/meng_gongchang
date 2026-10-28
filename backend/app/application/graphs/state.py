"""IngestionGraph 状态契约（contract 4.2.1 落地）。

- 批图（thread_id=batch:{batch_id}）处理整批；index_document 子图（thread_id=batch:{batch_id}:doc:{md5}）per-doc。
- `poll_started_ts`：轮询超时时钟基准（进程内墙钟崩溃重启会归零，故入 state）。
- `poll_pending`：poll_parsed 返回 pending 时置 True，条件边走 pause_wait（interrupt）。
- `error/fatal`：节点异常统一写入，finalize 以 DB 回读判定终态。

## 节点返回的每个 key 都必须在这里声明

LangGraph 只给 TypedDict 里声明过的字段建 channel；节点返回的**未声明 key
会被静默丢弃**（不是报错）。这条踩过一次真实事故：`poll_parsed` 的 resume
分支返回 `resume_dispatch=True`，但本文件里没声明它 → 值进不了 state →
条件边 `_route_poll` 永远读不到 → resume 批每次走到 poll_parsed 都判定
"继续等"，`pause_wait → poll_parsed` 无限自旋（实测一个 4 天前的旧批
spin 到 poll_count=577、每 5 秒一轮），把唯一 worker 独占，后面所有
新上传文件的队列消息永远轮不到处理 —— 界面表现就是"一直卡在 MinerU 解析中"。
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
    # resume 批跳过 MinerU 轮询、直接派发索引的信号（poll_parsed 置位）
    resume_dispatch: bool
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
