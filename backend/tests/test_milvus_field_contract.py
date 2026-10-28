"""Milvus 召回**字段名**契约 —— 请求的 output_fields 必须真实存在于 schema。

## 为什么需要这一组

真实事故：用户在通用知识库（`kb_ai_smark`）里看到文档已「就绪」，提问命中
关键词也对得上，但回答始终是「知识库中未找到与该问题相关的可靠文献」。

根因在 `search.py::_milvus_search`：

    # 存量 4 字段通用集合无 level/chunk_type/doi/title_cn 字段，需精简 output_fields
    use_full_fields = not (milvus_collection and milvus_collection != default_collection)
    output_fields = None if use_full_fields else ["chunk_id", "doc_id", "title"]

但**所有集合都按共享 schema 建**（10 字段，其中标题字段叫 `title_cn`，没有
`title`）。于是非默认库每次向量检索都抛：

    MilvusException: field title not exist

这个异常被 `retrieval` 节点的 `except Exception: degraded = True` 吞掉 ——
向量召回恒为 0，只剩 ES 一路；rerank 分数被拉低后，条件边判定「库内证据不足」
走直答，输出那句「未找到」。

**静默降级比直接报错更难查**：界面上每一步都是绿色，只有答案不对。
本文件把「字段名以 schema 为唯一真相源」这条锁住。

依赖：纯静态检查（不连 Milvus），CI 无 Milvus 也能跑。
"""
from __future__ import annotations

import inspect

from app.infrastructure.milvus import schema as mv_schema


def test_search_passes_no_hardcoded_output_fields():
    """`_milvus_search` 不得自行拼 output_fields。

    一旦写死字段列表，就与 `milvus/schema.py` 形成两份真相；schema 改名后
    调用方不会跟着变，而错误又被上层 `except Exception` 吞掉。
    """
    from app.infrastructure import search as search_mod

    src = inspect.getsource(search_mod._milvus_search)
    assert "output_fields" not in src, (
        "_milvus_search 又自己传 output_fields 了。字段名必须由 milvus/schema.py 决定；"
        "历史上传过不存在的 'title' 导致向量检索静默失败。"
    )


def test_schema_has_no_field_named_title():
    """schema 里的标题字段是 `title_cn`，不存在 `title`。

    这条断言把事故里的那个具体字段名钉死：如果谁要请求 title，必须先确认
    schema 真的有它。
    """
    names = [f.name for f in mv_schema.build_milvus_fields(dim=1024)]
    assert "title" not in names
    assert "title_cn" in names


def test_default_output_fields_only_use_schema_names():
    """`MilvusAdapter.search` 的默认 output_fields 必须是 schema 里的真字段。"""
    from app.infrastructure.adapters.milvus import MilvusAdapter

    src = inspect.getsource(MilvusAdapter.search)
    schema_names = {f.name for f in mv_schema.build_milvus_fields(dim=1024)}

    # 取出默认字段列表那一行里的字符串字面量
    for line in src.splitlines():
        if "output_fields or [" in line:
            import re

            requested = set(re.findall(r'"([a-z_]+)"', line))
            unknown = requested - schema_names
            assert not unknown, (
                f"MilvusAdapter.search 默认请求了 schema 里不存在的字段: {unknown}"
            )
            break
    else:
        raise AssertionError("没找到默认 output_fields 定义，测试需要更新")


def test_milvus_adapter_search_emits_title_cn():
    """返回字典里 `title_cn` 与 `title` 都存在（下游 SearchHit 两个都读）。"""
    from app.infrastructure.adapters.milvus import MilvusAdapter

    src = inspect.getsource(MilvusAdapter.search)
    assert '"title_cn"' in src
    assert '"title"' in src
