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
from app.domain.ports.exceptions import FatalError

# 轮询轮次硬上限（兜底）。
#
# 墙钟超时 `max_poll_time` 只在 submit 路径生效；resume 路径提前 return，
# 一旦它的分支标志缺失（`resume_dispatch` 曾漏声明在 IngestState 里，
# 被 LangGraph 静默丢弃），图会走 `pause_wait → poll_parsed` 无限自旋，
# 而 `poll_started_ts` 在 resume 分支之前根本没被读取 —— 于是既超不了时、
# 也退不出去，把唯一 worker 永久独占。
#
# 所以这里再加一道**与路径无关**的轮次上限：正常 submit 批在 20 分钟内
# 最多 poll 240 次（poll_interval 5s），留一倍余量取 600。超过即判 fatal，
# 让 finalize 把任务标失败并在界面上显示原因，而不是无声地卡住。
_MAX_POLL_ROUNDS = 600


async def poll_parsed(state: IngestState) -> dict:
    """单次轮询 MinerU batch 结果。

    resume 模式（retry / 跨 KB 复制已解析文档）：产物已存 MinIO，跳过 poll 直接派发索引。
    """
    from app.infrastructure.container import get_container

    container = get_container()
    mineru = container.get_mineru()
    vault = container.get_token_vault()
    settings = container.get_settings()

    batch_id = state["batch_id"]
    token = vault.resolve(state["token_id"]) or ""
    count = state.get("poll_count", 0) + 1

    # 轮次硬上限：任何路径都不允许无限自旋（见 _MAX_POLL_ROUNDS 说明）
    if count > _MAX_POLL_ROUNDS:
        return {
            "poll_count": count,
            "fatal": True,
            "error": {
                "step": "poll",
                "type": "Fatal",
                "message": f"轮询次数超过 {_MAX_POLL_ROUNDS} 轮仍未结束（mode={state.get('mode')}）",
            },
        }

    # resume：已解析产物直接派发（不经 MinerU 轮询与下载）
    if state.get("mode") == "resume":
        return {"poll_count": count, "resume_dispatch": True}

    started = state.get("poll_started_ts") or time.time()
    elapsed = time.time() - started

    items = None
    try:
        items = await mineru.poll_batch(batch_id, token=token)
    except FatalError as e:
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
