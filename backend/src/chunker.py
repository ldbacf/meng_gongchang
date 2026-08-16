"""PDF 切分模块 — 转发到 `app.domain.chunking`（阶段 2 统一切分入口）。

`chunk_document` / `FullMdParser` 等纯函数资产迁入 domain 层（零外部依赖），
本模块保留公开名以兼容 `scripts/run_chunker.py` 等调用方。不暴露 `_assemble_*` 私有。
"""
from __future__ import annotations

from app.domain.chunking.chunk_contract import ChunkLevel, ChunkType  # noqa: F401
from app.domain.chunking.chunk_document import chunk_document  # noqa: F401
from app.domain.chunking.parser import (  # noqa: F401
    Element,
    ElementType,
    FullMdParser,
    HeadingStack,
    ParsedDocument,
    TableInfo,
    build_table_dict,
    scan_paragraphs,
    supplement_footnotes_from_v2,
)
