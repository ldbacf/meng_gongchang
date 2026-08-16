"""poll_parsed / pause_wait 节点 — MinerU 轮询状态机（C5：无节点内 while）。

- poll_parsed：**单次** poll。有 done/failed item → 条件边 download（poll_items 携带）；
  无终态且未超时 → `poll_pending=True` → 条件边 pause_wait（interrupt 暂停，外部 scheduler
  定时 `Command(resume=...)` 唤醒 resume）；超时（elapsed >= MAX_POLL_TIME，时钟基准
  `poll_started_ts` 在 state，崩溃重启不归零）→ fatal → 条件边 finalize FAILED。
- pause_wait：只调 `interrupt("POLL_PENDING")`，**零副作用**——resume 时整节点重跑
  也无重复计数（poll_count+1 已在上游 poll_parsed 返回值 checkpoint 化）。
"""
from __future__ import annotations

import time

from langgraph.types import interrupt

from app.application.graphs.state import IngestState
from app.infrastructure.adapters.mineru import MineruFatalError


async def poll_parsed(state: IngestState) -> dict:
    """单次轮询 MinerU batch 结果。

    resume 模式（retry / 跨 KB 复制已解析文档）：产物已存 MinIO，跳过 poll 直接派发索引。
    """
    from app.interface.deps import get_container

    container = get_container()
    mineru = container.get_mineru()
    vault = container.get_token_vault()
    settings = container.get_settings()

    batch_id = state["batch_id"]
    token = vault.resolve(state["token_id"]) or ""
    count = state.get("poll_count", 0) + 1

    # resume：已解析产物直接派发（不经 MinerU 轮询与下载）
    if state.get("mode") == "resume":
        return {"poll_count": count, "resume_dispatch": True}

    started = state.get("poll_started_ts") or time.time()
    elapsed = time.time() - started

    items = None
    try:
        items = await mineru.poll_batch(batch_id, token=token)
    except MineruFatalError as e:
        return {
            "poll_count": count,
            "fatal": True,
            "error": {"step": "poll", "type": "Fatal", "message": str(e)},
        }
    except Exception:
        pass  # 可重试（Transient / 网络抖动）：本次不计失败，继续轮询

    if items is None:
        if elapsed >= settings.max_poll_time:
            return {
                "poll_count": count,
                "fatal": True,
                "error": {"step": "poll", "type": "Fatal", "message": "轮询超时"},
            }
        return {"poll_count": count, "poll_pending": True}

    # 有终态（done / failed）→ 交给 download / finalize 处理
    poll_items = {}
    has_terminal = False
    for item in items:
        md5 = item.get("data_id") or item.get("file_name")
        if md5 and item.get("state") in ("done", "failed"):
            poll_items[md5] = item
            has_terminal = True

    if has_terminal:
        return {"poll_count": count, "poll_items": poll_items}

    if elapsed >= settings.max_poll_time:
        return {
            "poll_count": count,
            "fatal": True,
            "error": {"step": "poll", "type": "Fatal", "message": "轮询超时"},
        }
    return {"poll_count": count, "poll_pending": True}


def pause_wait(state: IngestState) -> dict:
    """interrupt 暂停点（零副作用；resume 后经条件边回 poll_parsed 继续轮询）。"""
    interrupt("POLL_PENDING")
    return {}
