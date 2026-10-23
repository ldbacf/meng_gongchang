"""端口异常契约 — 应用层按语义决定重试/短路，不依赖具体适配器。

为什么放在 domain：`retry_policy` 的 `retry_on` 要判断"这是可重试的外部故障吗"，
这是**编排策略**而非实现细节。异常类型留在 infrastructure 会让 application 层
为了 isinstance 判断反向依赖具体适配器模块。

适配器抛出这些类型，应用层只依赖本模块。
"""
from __future__ import annotations


class PortError(Exception):
    """端口调用失败的基类。"""


class TransientError(PortError):
    """可重试的外部故障（网络抖动 / 5xx / 429 重试耗尽）。"""


class FatalError(PortError):
    """不可恢复（资源不存在 / 无权限 / 凭据失效）——重试无意义，直接短路。"""


class QuotaExhaustedError(PortError):
    """所有 key 的当日额度都用尽（业务约束，非故障）。"""
