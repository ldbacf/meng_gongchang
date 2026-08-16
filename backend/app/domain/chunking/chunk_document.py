"""三粒度切分唯一入口（纯函数，零外部依赖）— 自 `src/chunker.py` 迁入。

`chunk_document(md5, full_md_text, content_list_v2, meta, title)`：
- 在线（indexer.process_document）与离线（scripts/run_chunker.py）共用此入口，产物同构。
- doc_id 统一口径：`meta.article_id` 兜底 `md5[:8]`（冻结契约，阶段 2 硬切点）。
- **L0 分流**：meta 有 article_id → 完整 L0（期刊元数据）；meta 空 → generic L0
  （`title` 入参保标题，通用 KB 引用展示不回归为"未知文档"）。
"""
from __future__ import annotations

import logging
import re

from app.domain.chunking.chunk_contract import (
    ChunkLevel,
    ChunkType,
    doc_id_from,
)
from app.domain.chunking.parser import (
    ElementType,
    FullMdParser,
    HeadingStack,
    _extract_table_refs,
    build_table_dict,
    scan_paragraphs,
    supplement_footnotes_from_v2,
)

_logger = logging.getLogger(__name__)


def _make_heading_stack_str(stack: list[str]) -> str:
    return " → ".join(stack)


def _parse_keywords(raw: str) -> list[str]:
    """将中英文关键词字符串拆成列表"""
    if not raw:
        return []
    # 中英文用分号或逗号分隔
    parts = re.split(r"[；;,，]+", raw)
    return [p.strip() for p in parts if p.strip()]


def _assemble_l0_chunk(doc_id: str, meta: dict) -> dict:
    """组装论文级 chunk（期刊元数据版）"""
    title_cn = meta.get("title_cn", "")
    abstract_cn = meta.get("abstract_cn", "")
    keywords_cn = meta.get("keywords_cn", "")

    parts = []
    if title_cn:
        parts.append(f"【标题】{title_cn}")
    if abstract_cn:
        parts.append(f"【摘要】{abstract_cn}")
    if keywords_cn:
        parts.append(f"【关键词】{keywords_cn}")

    content = "\n\n".join(parts)

    return {
        "chunk_id": f"{doc_id}__L0",
        "doc_id": doc_id,
        "level": ChunkLevel.L0,
        "chunk_type": ChunkType.PAPER,
        "journal": meta.get("journal", ""),
        "source": meta.get("source", ""),
        "doi": meta.get("doi", ""),
        "section": meta.get("section", ""),
        "article_type": meta.get("article_type", ""),
        "title_cn": title_cn,
        "title_en": meta.get("title_en", ""),
        "authors_cn": meta.get("authors_cn", ""),
        "keywords_cn": _parse_keywords(keywords_cn),
        "keywords_en": _parse_keywords(meta.get("keywords_en", "")),
        "content": content,
    }


def _assemble_l0_chunk_generic(doc_id: str, title: str, elements: list) -> dict:
    """通用文档级 chunk — 无期刊元数据，纯文件名 + 首个标题 + 前 3 段"""
    first_heading = ""
    paragraphs: list[str] = []
    for el in elements:
        if el.type is ElementType.HEADING and not first_heading:
            first_heading = el.text
        elif el.type is ElementType.PARAGRAPH and len(paragraphs) < 3:
            p = el.text.strip()
            if p:
                paragraphs.append(p)

    parts = [title] if title else []
    if first_heading and first_heading != title:
        parts.append(first_heading)
    if paragraphs:
        parts.append("\n\n".join(paragraphs))

    return {
        "chunk_id": f"{doc_id}__L0",
        "doc_id": doc_id,
        "level": ChunkLevel.L0,
        "chunk_type": ChunkType.PAPER,
        "title": title,
        "content": "\n\n".join(parts),
    }


def _assemble_l1_chunks(
    doc_id: str,
    doi: str,
    elements: list,
    heading_stack: HeadingStack,
    title_cn: str = "",
    keywords_cn: str = "",
) -> list[dict]:
    """
    将元素列表中的段落按标题边界组装为 L1 chunk。
    同一标题下的所有段落合并为一个 chunk，过长时分段。
    每个 chunk 的 content 前缀注入论文标题和关键词，提升 bge-m3 向量召回质量。
    """
    chunks: list[dict] = []
    hs = heading_stack
    hs.clear()

    current_heading_snapshot: list[str] = []
    current_heading_number: str = ""
    current_paragraphs: list[str] = []
    current_refs_t: set[int] = set()

    MAX_CHARS = 2000
    _flush_counter: dict[str, int] = {}  # 同 heading 下分段后缀计数

    def flush(paras: list[str], refs_t: set[int],
              stack: list[str], num: str):
        if not paras:
            return
        stack_str = _make_heading_stack_str(stack)
        depth = len(stack)

        parts = [f"【章节】{stack_str}"] if stack_str else []
        parts.extend(paras)
        content = "\n\n".join(parts)

        base_id = num if num else "body"
        idx = _flush_counter.get(base_id, 0)
        _flush_counter[base_id] = idx + 1
        suffix = f"_p{idx}" if idx > 0 else ""
        chunk_id = f"{doc_id}__L1__{base_id}{suffix}"

        chunks.append({
            "chunk_id": chunk_id,
            "doc_id": doc_id,
            "level": ChunkLevel.L1,
            "chunk_type": ChunkType.PARAGRAPH,
            "doi": doi,
            "metadata": {
                "title_cn": title_cn,
                "keywords_cn": keywords_cn,
            },
            "heading_stack": list(stack),
            "heading_depth": depth,
            "refers_to_tables": sorted(refs_t),
            "content": content,
            })

    for el in elements:
        if el.type is ElementType.HEADING:
            flush(current_paragraphs, current_refs_t,
                  current_heading_snapshot, current_heading_number)
            hs.push(el.text, el.depth)
            current_heading_snapshot = hs.snapshot()
            current_heading_number = el.number_str
            current_paragraphs = []
            current_refs_t = set()
            continue

        if el.type is ElementType.PARAGRAPH:
            refs_t = _extract_table_refs(el.text)
            current_refs_t |= refs_t

            # 检查是否需要分段（过长的段落自己成为一个 chunk）
            combined = "\n\n".join(current_paragraphs + [el.text])
            if len(combined) > MAX_CHARS:
                flush(current_paragraphs, current_refs_t,
                      current_heading_snapshot, current_heading_number)
                current_paragraphs = [el.text]
                current_refs_t = refs_t
            else:
                current_paragraphs.append(el.text)
            continue

        # 表格、公式——跳过（它们有独立的 L2 chunk）

    flush(current_paragraphs, current_refs_t,
          current_heading_snapshot, current_heading_number)

    return chunks


def _assemble_l2_table_chunks(
    doc_id: str,
    doi: str,
    md5: str,
    title_cn: str,
    tables: dict,
    keywords_cn: str = "",
) -> list[dict]:
    """组装 L2 表格 chunk — content 前缀注入标题+关键词以增强向量召回"""
    chunks: list[dict] = []
    title_short = title_cn[:40] if title_cn else ""
    for tn, info in tables.items():
        stack_str = _make_heading_stack_str(info.heading_stack)

        parts = [f"【章节】{stack_str}"] if stack_str else []

        for para in info.referring_paragraphs:
            parts.append(f"【作者结论】{para}")

        parts.append(f"【{info.caption_cn}】")
        if info.caption_en:
            parts.append(f"【{info.caption_en}】")
        if info.footnote:
            parts.append(f"【表注】{info.footnote}")

        content_for_emb = "\n\n".join(parts)

        if not info.html:
            _logger.warning(
                "Table %d of [%s | %s] 《%s》 has empty HTML — only caption+footnote available",
                tn, doc_id, md5[:12], title_short,
            )
        elif "<tr>" not in info.html and "<tr " not in info.html:
            _logger.warning(
                "Table %d of [%s | %s] 《%s》 HTML has no <tr> rows — may be corrupted",
                tn, doc_id, md5[:12], title_short,
            )

        chunks.append({
            "chunk_id": f"{doc_id}__L2__table_{tn}",
            "doc_id": doc_id,
            "level": ChunkLevel.L2,
            "chunk_type": ChunkType.TABLE,
            "doi": doi,
            "metadata": {
                "title_cn": title_cn,
                "keywords_cn": keywords_cn,
            },
            "heading_stack": list(info.heading_stack),
            "heading_depth": len(info.heading_stack),
            "table_number": tn,
            "table_caption": info.caption_cn,
            "table_caption_en": info.caption_en,
            "html_size": info.html_size,
            "refers_to_tables": [],
            "content": content_for_emb,
            "html_body": info.html,
        })

    return chunks


def chunk_document(
    md5: str,
    full_md_text: str,
    content_list_v2: list | None = None,
    meta: dict | None = None,
    title: str = "",
) -> dict:
    """
    对一篇 PDF 执行完整切分，返回包含所有 chunk 的 dict（唯一入口）。

    参数:
        md5: 文件 MD5
        full_md_text: full.md 的文本内容
        content_list_v2: content_list_v2.json 解析后的 list（可选）
        meta: doc-meta JSON 解析后的 dict（可选）
        title: 通用文档（无 meta）时 L0 的标题（如文件名 stem）

    返回:
        {"doc_id": "...", "md5": "...", "total_chunks": N, "chunks": [...]}
    """
    if meta is None:
        meta = {}
    if content_list_v2 is None:
        content_list_v2 = []

    doc_id = doc_id_from(meta.get("article_id", ""), md5)
    if "article_id" not in meta:
        _logger.info("No article_id for %s, using md5[:8]=%s", md5, doc_id)

    doi = meta.get("doi", "")

    full_md_text = full_md_text.strip()
    if not full_md_text:
        _logger.warning("Empty full.md for %s — producing L0 only", md5)
        l0 = (_assemble_l0_chunk(doc_id, meta) if meta.get("article_id")
              else _assemble_l0_chunk_generic(doc_id, title, []))
        l0["md5"] = md5
        return {
            "doc_id": doc_id, "md5": md5,
            "total_chunks": 1, "chunks": [l0],
        }

    if len(full_md_text) > 5_000_000:
        _logger.warning("full.md for %s is large (%d chars), may be slow", md5, len(full_md_text))

    # 步骤 1：解析 full.md
    parser = FullMdParser(full_md_text)
    elements = parser.parse()

    # 步骤 2 + 3：构建表格字典 + 记录标题栈
    tables = build_table_dict(elements)

    # 步骤 4：扫描段落引用，填充灵魂池和标题栈
    hs = HeadingStack()
    scan_paragraphs(elements, hs, tables)

    # 补充 footnote（content_list_v2.json 回填）
    supplement_footnotes_from_v2(content_list_v2, tables)

    # 步骤 5：组装三层 chunk
    chunks: list[dict] = []

    # L0 — 论文级（有 article_id → 完整元数据版；无 → 通用版带 title）
    if meta.get("article_id"):
        l0 = _assemble_l0_chunk(doc_id, meta)
    else:
        l0 = _assemble_l0_chunk_generic(doc_id, title, elements)
    l0["md5"] = md5
    chunks.append(l0)

    # L1 — 章节级（需重新遍历，用新栈）
    hs2 = HeadingStack()
    title_cn = meta.get("title_cn", "")
    keywords_cn = meta.get("keywords_cn", "")
    l1_chunks = _assemble_l1_chunks(doc_id, doi, elements, hs2, title_cn=title_cn, keywords_cn=keywords_cn)
    chunks.extend(l1_chunks)

    # L2 — 表格级
    l2_tables = _assemble_l2_table_chunks(doc_id, doi, md5, title_cn, tables, keywords_cn=keywords_cn)
    chunks.extend(l2_tables)

    if len(chunks) > 500:
        _logger.warning(
            "Document %s produced %d chunks — consider adjusting L1 splitting threshold",
            doc_id, len(chunks),
        )

    return {
        "doc_id": doc_id,
        "md5": md5,
        "total_chunks": len(chunks),
        "chunks": chunks,
    }
