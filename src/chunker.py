"""
PDF 切分模块 — 三粒度分层切分（L0 论文级 / L1 章节级 / L2 图表级）

主源: full.md（正文、标题、表格 HTML、表注、图表引用）
补源: content_list_v2.json（回填 table_footnote 术语缩写解释）
元源: doc-meta JSON（刊名、DOI、摘要、关键词等）
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 类型定义
# ═══════════════════════════════════════════════════════════════


class ElementType(Enum):
    HEADING = auto()
    PARAGRAPH = auto()
    TABLE_CAPTION = auto()
    TABLE_CAPTION_EN = auto()
    HTML_TABLE = auto()
    TABLE_FOOTNOTE = auto()
    EQUATION = auto()
    IMAGE = auto()
    SKIP = auto()  # 页眉页脚 / <details> / 空行


class ChunkLevel:
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class ChunkType:
    PAPER = "paper"
    PARAGRAPH = "paragraph"
    TABLE = "table"


@dataclass
class Element:
    type: ElementType
    text: str = ""
    number: int | None = None  # 表号 / 图号 / 编号中的数字
    number_str: str = ""  # 编号字符串，如 "1.1"
    depth: int = 0  # 标题深度
    html: str = ""  # 仅 HTML_TABLE
    raw: str = ""  # 原始行文本


@dataclass
class TableInfo:
    """一张表的完整信息"""
    table_number: int
    caption_cn: str = ""
    caption_en: str = ""
    html: str = ""
    html_size: int = 0
    footnote: str = ""
    heading_stack: list[str] = field(default_factory=list)
    referring_paragraphs: list[str] = field(default_factory=list)


@dataclass
class ParsedDocument:
    """解析后的文档中间产物"""
    md5: str
    elements: list[Element] = field(default_factory=list)
    tables: dict[int, TableInfo] = field(default_factory=dict)
    heading_stack: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 步骤 1：full.md 逐行解析（状态机）
# ═══════════════════════════════════════════════════════════════

# 标题行模式：可选的 #  + 数字编号 + 空格 + 中文/英文
_HEADING_PATTERN = re.compile(
    r"^(#{1,4})\s*(\d+(?:\.\d+)*)\s+(.+)$"
)
# 无 # 但有数字编号的小标题（如 "3.2.1 优秀级政策分析："）
_SUBHEADING_PATTERN = re.compile(
    r"^(\d{1,2}(?:\.\d{1,2}){1,})\s+([一-鿿][一-鿿\w\s]*)[：:。]?$"
)
# 表标题：表+数字
_TABLE_CAPTION_PATTERN = re.compile(
    r"^表\s*(\d+)\s*(.*?)$"
)
# 英文表标题
_TABLE_CAPTION_EN_PATTERN = re.compile(
    r"^Table\s*(\d+)\s*(.*?)$", re.IGNORECASE
)
# 表注
_FOOTNOTE_PATTERN = re.compile(r"^注[：:]\s*(.*)")
# 图片
_IMAGE_PATTERN = re.compile(r"^!\[.*\]\(.+\)")
# 公式块边界
_EQUATION_BOUNDARY = re.compile(r"^\$\$")
# HTML table 边界
_TABLE_OPEN = re.compile(r"^<table[>\s]")
_TABLE_CLOSE = re.compile(r"^</table>")
# details 块
_DETAILS_OPEN = re.compile(r"^<details>")
_DETAILS_CLOSE = re.compile(r"^</details>")
# 跳过行
_SKIP_PATTERNS = [
    re.compile(r"^扫描二维码"),
    re.compile(r"^©\s"),
    re.compile(r"^基金项目"),
    re.compile(r"^引用本文"),
    re.compile(r"^\["),  # 参考文献条目
]


def _is_skip_line(line: str) -> bool:
    """判断是否可跳过的行（页眉页脚、参考文献条目等）"""
    for pat in _SKIP_PATTERNS:
        if pat.match(line.strip()):
            return True
    return False


class FullMdParser:
    """full.md 状态机解析器"""

    def __init__(self, text: str):
        self.lines = text.split("\n")
        self.elements: list[Element] = []
        self._buf: list[str] = []
        self._state = "NORMAL"
        self._para_buf: list[str] = []
        self._last_element_type: ElementType | None = None

    def parse(self) -> list[Element]:
        for line in self.lines:
            stripped = line.strip()

            # 状态：正在收集 HTML table
            if self._state == "IN_HTML_TABLE":
                self._buf.append(line)
                if "</table>" in stripped.lower():
                    self._flush_html_table()
                continue

            # 状态：正在收集公式块
            if self._state == "IN_EQUATION":
                self._buf.append(line)
                if _EQUATION_BOUNDARY.match(stripped):
                    self._flush_equation()
                continue

            # 状态：正在收集 <details>
            if self._state == "IN_DETAILS":
                self._buf.append(line)
                if _DETAILS_CLOSE.match(stripped):
                    self._flush_skip()
                continue

            # 空行 → 分割段落
            if not stripped:
                self._flush_paragraph()
                continue

            # 跳过行
            if _is_skip_line(stripped):
                continue

            # 公式块开始
            if _EQUATION_BOUNDARY.match(stripped):
                self._flush_paragraph()
                self._state = "IN_EQUATION"
                self._buf = [line]
                continue

            # <details> 块开始
            if _DETAILS_OPEN.match(stripped):
                self._flush_paragraph()
                self._state = "IN_DETAILS"
                self._buf = [line]
                continue

            # <table> 开始
            if _TABLE_OPEN.match(stripped):
                self._flush_paragraph()
                # 单行表格：<table> 和 </table> 在同一行
                if "</table>" in stripped.lower():
                    el = Element(
                        type=ElementType.HTML_TABLE, html=line, text=line,
                    )
                    self.elements.append(el)
                    self._last_element_type = ElementType.HTML_TABLE
                else:
                    self._state = "IN_HTML_TABLE"
                    self._buf = [line]
                continue

            # 图片
            if _IMAGE_PATTERN.match(stripped):
                continue

            # 标题（带 #）
            heading_match = _HEADING_PATTERN.match(stripped)
            if heading_match:
                self._flush_paragraph()
                hashes, num, title = heading_match.groups()
                depth = num.count(".") + 1
                el = Element(
                    type=ElementType.HEADING,
                    number_str=num,
                    text=f"{num} {title.strip()}",
                    depth=min(depth, 4),
                    raw=stripped,
                )
                self.elements.append(el)
                self._last_element_type = ElementType.HEADING
                continue

            # 表标题（中文）
            table_match = _TABLE_CAPTION_PATTERN.match(stripped)
            if table_match:
                self._flush_paragraph()
                num = int(table_match.group(1))
                rest = table_match.group(2).strip()
                caption = f"表{num} {rest}" if rest else f"表{num}"
                el = Element(
                    type=ElementType.TABLE_CAPTION,
                    number=num,
                    text=caption,
                    raw=stripped,
                )
                self.elements.append(el)
                self._last_element_type = ElementType.TABLE_CAPTION
                continue

            # 表标题（英文）
            table_en_match = _TABLE_CAPTION_EN_PATTERN.match(stripped)
            if table_en_match:
                num = int(table_en_match.group(1))
                rest = table_en_match.group(2).strip()
                caption = f"Table {num} {rest}" if rest else f"Table {num}"
                el = Element(
                    type=ElementType.TABLE_CAPTION_EN,
                    number=num,
                    text=caption,
                    raw=stripped,
                )
                self.elements.append(el)
                self._last_element_type = ElementType.TABLE_CAPTION_EN
                continue

            # 无 # 但有小标题格式的行（如 "3.2.1 研究工具："）
            sub_match = _SUBHEADING_PATTERN.match(stripped)
            if sub_match and not stripped.startswith("#"):
                self._flush_paragraph()
                num, title = sub_match.groups()
                depth = num.count(".") + 1
                el = Element(
                    type=ElementType.HEADING,
                    number_str=num,
                    text=f"{num} {title.strip()}",
                    depth=min(depth, 4),
                    raw=stripped,
                )
                self.elements.append(el)
                self._last_element_type = ElementType.HEADING
                continue

            # 表注（仅在表/HTML table/英表标题之后）
            fn_match = _FOOTNOTE_PATTERN.match(stripped)
            if fn_match and self._last_element_type in (
                ElementType.TABLE_CAPTION,
                ElementType.TABLE_CAPTION_EN,
                ElementType.HTML_TABLE,
            ):
                self._flush_paragraph()
                el = Element(
                    type=ElementType.TABLE_FOOTNOTE,
                    text=f"注：{fn_match.group(1).strip()}",
                    raw=stripped,
                )
                self.elements.append(el)
                self._last_element_type = ElementType.TABLE_FOOTNOTE
                continue

            # 普通正文行 → 累积到段落缓冲区
            self._para_buf.append(stripped)
            self._last_element_type = ElementType.PARAGRAPH

        # 文件结束，flush 剩余内容
        self._flush_paragraph()
        if self._state == "IN_HTML_TABLE":
            self._flush_html_table()
        elif self._state == "IN_EQUATION":
            self._flush_equation()

        return self.elements

    def _flush_paragraph(self):
        if self._para_buf:
            text = " ".join(self._para_buf).strip()
            if text:
                el = Element(type=ElementType.PARAGRAPH, text=text)
                self.elements.append(el)
                self._last_element_type = ElementType.PARAGRAPH
            self._para_buf = []

    def _flush_html_table(self):
        html = "\n".join(self._buf).strip()
        el = Element(type=ElementType.HTML_TABLE, html=html, text=html)
        self.elements.append(el)
        self._last_element_type = ElementType.HTML_TABLE
        self._buf = []
        self._state = "NORMAL"

    def _flush_equation(self):
        el = Element(
            type=ElementType.EQUATION,
            text="\n".join(self._buf).strip(),
        )
        self.elements.append(el)
        self._last_element_type = ElementType.EQUATION
        self._buf = []
        self._state = "NORMAL"

    def _flush_skip(self):
        self._buf = []
        self._state = "NORMAL"


# ═══════════════════════════════════════════════════════════════
# 步骤 2：标题栈管理
# ═══════════════════════════════════════════════════════════════


class HeadingStack:
    """维护当前章节坐标"""

    def __init__(self):
        self._stack: list[str] = ["", "", "", ""]  # L1, L2, L3, L4

    def push(self, heading_text: str, depth: int) -> list[str]:
        """
        depth=1 → 清空栈，设 [0]
        depth=2 → 保留 [0]，设 [1]，清 [2][3]
        depth=3 → 保留 [0][1]，设 [2]，清 [3]
        depth=4 → 保留 [0][1][2]，设 [3]
        返回当前栈快照（非空项列表）
        """
        idx = depth - 1
        self._stack[idx] = heading_text
        for i in range(idx + 1, 4):
            self._stack[i] = ""
        return self.snapshot()

    def snapshot(self) -> list[str]:
        return [h for h in self._stack if h]

    def clear(self):
        self._stack = ["", "", "", ""]


# ═══════════════════════════════════════════════════════════════
# 步骤 3：表格字典 & 图表字典构建
# ═══════════════════════════════════════════════════════════════


def build_table_dict(elements: list[Element]) -> dict[int, TableInfo]:
    """
    遍历元素序列，按相邻关系配对：
    TABLE_CAPTION → TABLE_CAPTION_EN → HTML_TABLE → TABLE_FOOTNOTE
    """
    tables: dict[int, TableInfo] = {}
    i = 0
    while i < len(elements):
        el = elements[i]
        if el.type != ElementType.TABLE_CAPTION:
            i += 1
            continue

        num = el.number
        if num is None:
            i += 1
            continue

        info = TableInfo(table_number=num, caption_cn=el.text)
        i += 1

        # 看后续元素是否属于同一张表
        while i < len(elements):
            nxt = elements[i]
            if nxt.type == ElementType.TABLE_CAPTION_EN and nxt.number == num:
                info.caption_en = nxt.text
                i += 1
            elif nxt.type == ElementType.HTML_TABLE:
                info.html = nxt.html
                info.html_size = len(nxt.html)
                i += 1
            elif nxt.type == ElementType.TABLE_FOOTNOTE:
                info.footnote = nxt.text
                i += 1
            elif nxt.type in (ElementType.HEADING, ElementType.TABLE_CAPTION):
                # 新标题或新表格 = 当前表结束
                break
            else:
                # 段落/图片/公式/英文标题拼写错误等 — 跳过，继续找 HTML
                i += 1

        tables[num] = info

    return tables


# ═══════════════════════════════════════════════════════════════
# 步骤 4：段落扫描 — 图表引用检测
# ═══════════════════════════════════════════════════════════════

# 图表引用正则
_TABLE_REF_PATTERNS = [
    # "见表2、3、5" / "见表2和表3"
    re.compile(r"表\s*(\d+)\s*[、，,和&及与]\s*表?\s*(\d+)"),
    # "表2～5" / "表2-5"
    re.compile(r"表\s*(\d+)\s*[～~\-—]\s*表?\s*(\d+)"),
    # "见表1" / "(表 1)" / "如表1所示"
    re.compile(r"表\s*(\d+)"),
]
_TABLE_EN_REF = re.compile(r"Table\s*(\d+)", re.IGNORECASE)


def _extract_table_refs(text: str) -> set[int]:
    """从文本中提取所有引用的表号"""
    refs: set[int] = set()
    for pat in _TABLE_REF_PATTERNS:
        for match in pat.finditer(text):
            for g in match.groups():
                refs.add(int(g))
    for match in _TABLE_EN_REF.finditer(text):
        refs.add(int(match.group(1)))
    return refs


def scan_paragraphs(
    elements: list[Element],
    heading_stack: HeadingStack,
    tables: dict[int, TableInfo],
):
    """
    遍历元素，为每个段落记录：
    - 当时标题栈（章节坐标）
    - 引用的表号
    - 将段落文本追加到对应表格的灵魂池
    """
    hs = heading_stack
    hs.clear()

    for el in elements:
        if el.type == ElementType.HEADING:
            hs.push(el.text, el.depth)
            continue

        if el.type == ElementType.PARAGRAPH:
            refs_t = _extract_table_refs(el.text)

            for tn in refs_t:
                if tn in tables:
                    tables[tn].referring_paragraphs.append(el.text)
                    if not tables[tn].heading_stack:
                        tables[tn].heading_stack = hs.snapshot()

            continue

        if el.type == ElementType.TABLE_CAPTION and el.number and el.number in tables:
            if not tables[el.number].heading_stack:
                tables[el.number].heading_stack = hs.snapshot()


# ═══════════════════════════════════════════════════════════════
# content_list_v2.json — footnote 回填
# ═══════════════════════════════════════════════════════════════


def supplement_footnotes_from_v2(
    content_list_v2: list,
    tables: dict[int, TableInfo],
):
    """
    从 content_list_v2.json 中按表号匹配，回填更完整的 table_footnote。
    content_list_v2 结构: [page1_items, page2_items, ...]
    """
    for page in content_list_v2:
        for item in page:
            if item.get("type") != "table":
                continue
            content = item.get("content", {})
            captions = content.get("table_caption", [])
            footnote_list = content.get("table_footnote", [])
            if not footnote_list:
                continue

            v2_footnote = "".join(
                c.get("content", "") for c in footnote_list
            ).strip()

            if not v2_footnote:
                continue

            for cap in captions:
                cap_text = cap.get("content", "")
                m = _TABLE_CAPTION_PATTERN.match(cap_text)
                if m:
                    tn = int(m.group(1))
                    if tn in tables and not tables[tn].footnote:
                        tables[tn].footnote = v2_footnote


# ═══════════════════════════════════════════════════════════════
# 步骤 5：三层 Chunk 组装
# ═══════════════════════════════════════════════════════════════


def _make_heading_stack_str(stack: list[str]) -> str:
    return " → ".join(stack)


def _assemble_l0_chunk(doc_id: str, meta: dict) -> dict:
    """组装论文级 chunk"""
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


def _assemble_l1_chunks(
    doc_id: str,
    doi: str,
    elements: list[Element],
    heading_stack: HeadingStack,
) -> list[dict]:
    """
    将元素列表中的段落按标题边界组装为 L1 chunk。
    同一标题下的所有段落合并为一个 chunk，过长时分段。
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
            "heading_stack": list(stack),
            "heading_depth": depth,
            "refers_to_tables": sorted(refs_t),
            "content": content,
            })

    for el in elements:
        if el.type == ElementType.HEADING:
            flush(current_paragraphs, current_refs_t,
                  current_heading_snapshot, current_heading_number)
            hs.push(el.text, el.depth)
            current_heading_snapshot = hs.snapshot()
            current_heading_number = el.number_str
            current_paragraphs = []
            current_refs_t = set()
            continue

        if el.type == ElementType.PARAGRAPH:
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
    tables: dict[int, TableInfo],
) -> list[dict]:
    """组装 L2 表格 chunk"""
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


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def _parse_keywords(raw: str) -> list[str]:
    """将中英文关键词字符串拆成列表"""
    if not raw:
        return []
    # 中英文用分号或逗号分隔
    parts = re.split(r"[；;,，]+", raw)
    return [p.strip() for p in parts if p.strip()]


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════


def chunk_document(
    md5: str,
    full_md_text: str,
    content_list_v2: list | None = None,
    meta: dict | None = None,
) -> dict:
    """
    对一篇 PDF 执行完整切分，返回包含所有 chunk 的 dict。

    参数:
        md5: 文件 MD5
        full_md_text: full.md 的文本内容
        content_list_v2: content_list_v2.json 解析后的 list（可选）
        meta: doc-meta JSON 解析后的 dict（可选）

    返回:
        {"doc_id": "...", "md5": "...", "total_chunks": N, "chunks": [...]}
    """
    if meta is None:
        meta = {}
    if content_list_v2 is None:
        content_list_v2 = []

    doc_id = meta.get("article_id") or md5[:8]
    if "article_id" not in meta:
        _logger.info("No article_id for %s, using md5[:8]=%s", md5, doc_id)

    doi = meta.get("doi", "")

    full_md_text = full_md_text.strip()
    if not full_md_text:
        _logger.warning("Empty full.md for %s — producing L0 only", md5)
        chunks = [_assemble_l0_chunk(doc_id, meta)]
        chunks[0]["md5"] = md5
        return {
            "doc_id": doc_id, "md5": md5,
            "total_chunks": 1, "chunks": chunks,
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

    # L0 — 论文级
    l0 = _assemble_l0_chunk(doc_id, meta)
    l0["md5"] = md5
    chunks.append(l0)

    # L1 — 章节级（需重新遍历，用新栈）
    hs2 = HeadingStack()
    l1_chunks = _assemble_l1_chunks(doc_id, doi, elements, hs2)
    chunks.extend(l1_chunks)

    # L2 — 表格级
    title_cn = meta.get("title_cn", "")
    l2_tables = _assemble_l2_table_chunks(doc_id, doi, md5, title_cn, tables)
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
