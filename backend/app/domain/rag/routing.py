"""意图路由 — 决定这一问要不要走文献检索。

## 为什么需要
原来的图是直线：`intent → retrieval → fusion → cite → answer`。
意图识别明明产出了 `coverage`（high/medium/low/**out_of_domain**），却没有任何节点消费它。

后果：用户在对话里说「你好」，也会完整跑一遍向量+全文检索，最后拿到
"未找到相关文献信息，无法回答。" —— 既慢又答非所问。

本模块只做**纯函数判定**（零依赖，可单测），图里用它做条件边。

## 判定规则
| coverage | 是否检索 | 理由 |
|---|---|---|
| `out_of_domain` | **否** → 直答 | 寒暄/元问题/完全无关，检索必然空手 |
| `high` / `medium` / `low` | 是 | 覆盖度低也可能有片段，先捞再说 |
| 空 / `unknown` | 是 | 意图识别失败时**保守走检索**，不改变原有行为 |

注意：**降级（degraded）时一律走检索**。意图服务挂掉时 coverage 是空的，
此时无从判断是否属于文献范围，宁可多检一次也不能把医学问题误判成寒暄。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 判定为「不需要检索」的覆盖度取值
DIRECT_COVERAGES: frozenset[str] = frozenset({"out_of_domain"})

#: rerank top1 低于此分 → 视为「库内证据不足」，转直答。
#: 默认 0.25：实测高覆盖问题 top1≈0.90、低覆盖但仍相关的≈0.53；
#: 0.25 以下基本是"只有零星字面匹配"的噪声区。可由 Settings 覆盖。
MIN_EVIDENCE_SCORE: float = 0.25


@dataclass(frozen=True)
class RouteDecision:
    """路由结果。

    `on_true` / `on_false` 是条件边的目标节点名 —— intent 之后与 fusion 之后
    要去的节点不同（retrieval vs cite），所以由调用方指定。
    """

    use_retrieval: bool
    reason: str
    on_true: str = "retrieval"
    on_false: str = "direct_answer"

    @property
    def target(self) -> str:
        """条件边的目标节点名。"""
        return self.on_true if self.use_retrieval else self.on_false


def decide_route(*, coverage: str | None, degraded: bool = False) -> RouteDecision:
    """根据意图识别的 coverage 决定走检索还是直答。"""
    if degraded:
        return RouteDecision(True, "intent_degraded")

    cov = (coverage or "").strip().lower()
    if cov in DIRECT_COVERAGES:
        return RouteDecision(False, f"coverage={cov}")

    if not cov:
        return RouteDecision(True, "coverage_unknown")

    return RouteDecision(True, f"coverage={cov}")


def decide_after_fusion(
    *,
    top_score: float | None,
    has_content: bool,
    min_score: float = MIN_EVIDENCE_SCORE,
) -> RouteDecision:
    """fusion 之后：库内证据够不够用来回答。

    只在**已经走完检索**时调用。`low` 覆盖度本身不触发 —— 低覆盖也可能检索到
    真正相关的片段（实测 top1≈0.53），不能因为"领域冷门"就直接放弃文献。

    - 没有任何带正文的片段 → 直答（reason=`no_content`）
    - top1 低于阈值       → 直答（reason=`low_score:<分数>`）
    - 否则                → 继续 cite → answer
    """
    if not has_content:
        return RouteDecision(False, "no_content", on_true="cite")

    score = float(top_score or 0.0)
    if score < min_score:
        return RouteDecision(False, f"low_score:{score:.3f}", on_true="cite")

    return RouteDecision(True, f"score_ok:{score:.3f}", on_true="cite")
