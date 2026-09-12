"""chunk 结构契约定稿 — L0/L1/L2 三粒度。

`chunk_id` 命名、`doc_id` 统一口径、层级/类型枚举在此冻结（总需求文档 §7.4）。
在线与离线两条路径最终共用同一 `chunk_document` 入口，产物结构同构。
纯 stdlib，零外部依赖。
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ChunkLevel:
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class ChunkType:
    PAPER = "paper"
    PARAGRAPH = "paragraph"
    TABLE = "table"


def doc_id_from(article_id: str, md5: str) -> str:
    """doc_id 统一口径：meta.article_id 兜底 md5[:8]（全链路一致）。"""
    return (article_id or "").strip() or md5[:8]


def chunk_id_for_l0(doc_id: str) -> str:
    return f"{doc_id}__L0"


def chunk_id_for_l1(doc_id: str, number: str, idx: int = 0) -> str:
    base = number if number else "body"
    suffix = f"_p{idx}" if idx > 0 else ""
    return f"{doc_id}__L1__{base}{suffix}"


def chunk_id_for_l2_table(doc_id: str, table_number: int) -> str:
    return f"{doc_id}__L2__table_{table_number}"


@dataclass
class Chunk:
    """单条 chunk 的结构约定（dict 键名与此一致）。"""
    chunk_id: str
    doc_id: str
    level: str
    chunk_type: str
    content: str
    heading_stack: list[str] = field(default_factory=list)
    heading_depth: int = 0
    refers_to_tables: list[int] = field(default_factory=list)
    html_body: str = ""
    doi: str = ""
    journal: str = ""
    section: str = ""
    article_type: str = ""
    title_cn: str = ""
    # 向量（不落 ES _source，Milvus 专用）
    vector: list[float] | None = None

    def to_index_dict(self) -> dict:
        """输出为可写入 ES/Milvus 的 dict（vector 除外由调用方处理）。"""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "level": self.level,
            "chunk_type": self.chunk_type,
            "content": self.content,
            "heading_stack": list(self.heading_stack),
            "heading_depth": self.heading_depth,
            "refers_to_tables": list(self.refers_to_tables),
            "html_body": self.html_body,
            "doi": self.doi,
            "journal": self.journal,
            "section": self.section,
            "article_type": self.article_type,
            "title_cn": self.title_cn,
        }
