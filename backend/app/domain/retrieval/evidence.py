"""证据卡数据组装 — 从 chunk / 摘要原文提炼可读字段（纯函数，零外部依赖）。

## 为什么需要这一层

前端要展示的「证据卡」不是直接能拿到的东西：

- `abstract_cn` 是一整段字符串，但期刊结构式摘要有「背景/目的/方法/结果/结论」
  五个固定段键，读者要的是分段后的样子；
- `content` 里混着 MinerU 留下的 LaTeX 残留（`$\\mathrm{M}_{3}$`），
  检索无影响，但直接展示是乱码；
- chunk 首行有 `【章节】…` 前缀，而章节路径已经在 `heading_stack` 里单独给了；
- 引用片段本身只是长文本里的一段，读者需要前后文才读得懂。

这些都只依赖字符串，没有任何 I/O，所以放在 domain 层，由接口层调用。
放这里的另一个好处是**可以脱离 MinIO / ES 单测**：本机 MinIO 240 KB/s，
跑一次真实 locate 要十几秒，不适合做测试基线。

## 已知不可靠的地方（不要假装它可靠）

样本量抽取是**正则启发式**，全库 1248 篇实测覆盖 59.6%，且 744 篇里有 529 篇
会抽到多个候选数字（`纳入 18 篇文献，涉及 12 468 例患者` → 18 和 12468 都符合）。
`extract_sample_size` 取最大值并保留单位，这在「篇数 + 例数」共存时通常正确，
但**没有**逐条校验。前端应把它当作提示而非事实，且当单位是「篇/项」时明确标注
是「纳入文献数」而不是「样本量」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 结构式摘要的段键（顺序即期刊排版顺序）
SECTION_KEYS: tuple[str, ...] = ("背景", "目的", "方法", "结果", "结论")

# 段内容短于此长度视为误命中（PDF 里「方法。」这类残句会命中段键正则）
_MIN_SECTION_CHARS = 8

# 摘要开头的「摘要：」标记
_ABSTRACT_LABEL_RE = re.compile(r"^摘\s*要\s*[：:]\s*")

# 段键正则：允许字间有空格（MinerU 会输出「目 的」「结 论」）
_SECTION_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (k, re.compile(re.escape(k[0]) + r"\s*" + re.escape(k[1]))) for k in SECTION_KEYS
)

# chunk 首行前缀：`【章节】a → b → c`
_CHUNK_PREFIX_RE = re.compile(r"^【[^】]*】[^\n]*\n+")


@dataclass
class AbstractSection:
    """摘要的一段。`key` 为空表示整段没有分段键（指南/综述常见）。"""

    key: str
    text: str

    def to_dict(self) -> dict:
        return {"key": self.key, "text": self.text}


# ── 摘要分段 ──────────────────────────────────────────────────


def _strip_section_key(body: str, key: str) -> str:
    """去掉段落开头的段键本身（`结论 社区H型…` → `社区H型…`）。

    段键已经单独放在 `AbstractSection.key` 里，正文再带一遍会导致
    证据卡上出现「**结论** 结论 基于三级防控…」这样的重复。
    段键中间可能有空格（MinerU 会输出「目 的」），所以按字符放宽匹配。
    """
    if len(key) != 2:
        return body
    m = re.match(re.escape(key[0]) + r"\s*" + re.escape(key[1]) + r"\s*[：:]?\s*", body)
    return body[m.end():].strip() if m else body


def split_abstract_sections(raw: str | None) -> list[AbstractSection]:
    """把 `abstract_cn` 切成「背景/目的/方法/结果/结论」段。

    没有分段键（单段叙述式摘要）时返回**空列表**，调用方应回退到整段展示 ——
    不要伪造一个「结论」段，那会让用户以为文章真有结论句。

    实测 1248 篇中 911 篇（73.0%）能被正确切分，其余 337 篇多为指南与综述。

    段短于 `_MIN_SECTION_CHARS` 的会被丢弃：`abstract_cn` 里出现过
    「…进行综述，探索其发病机制及可能的治疗方法。方法。」这种残句，
    段键正则会在句尾命中一个孤立的「方法。」，切出来毫无意义。

    返回的 `text` **不含段键**：段键在 `key` 字段里，重复一遍会在界面上
    出现「结论 结论 …」。
    """
    text = _ABSTRACT_LABEL_RE.sub("", (raw or "").strip())
    if not text:
        return []

    found: list[tuple[int, str]] = []
    for key, pattern in _SECTION_RES:
        m = pattern.search(text)
        if m:
            found.append((m.start(), key))
    if not found:
        return []

    found.sort()
    sections: list[AbstractSection] = []
    for i, (start, key) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(text)
        body = _strip_section_key(text[start:end].strip(), key)
        if len(body) < _MIN_SECTION_CHARS:
            continue
        sections.append(AbstractSection(key=key, text=body))
    return sections


def has_conclusion(sections: list[AbstractSection]) -> bool:
    """是否切出了「结论」段 —— 证据卡据此决定「结论」区块是摘录还是降级提示。"""
    return any(s.key == "结论" for s in sections)


# ── 样本量 ────────────────────────────────────────────────────

_NUMBER = r"\d[\d\s,，]{0,8}\d|\d"
_UNIT = r"例|名|人|项|篇|份|个"

_SAMPLE_RE = re.compile(
    r"(?:共|累计)?\s*(?:纳入|选取|收集|调查|招募|检索|涉及|包含|观察|随机抽取|入组|有效问卷)"
    r"[^。；;，,]{0,25}?(" + _NUMBER + r")\s*(" + _UNIT + r")"
)


@dataclass
class SampleSize:
    """抽到的样本量。`unit` 是「例/名/人」时为受试者数，「篇/项」时为纳入文献数。"""

    value: int
    unit: str

    @property
    def is_subject_count(self) -> bool:
        """是否为受试者数（而非文献篇数）。

        「纳入 18 篇」说的是文献数量，不是样本量 —— 卡片上不能标成「样本量」。
        """
        return self.unit in ("例", "名", "人")

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "is_subject_count": self.is_subject_count,
        }


def extract_sample_size(*texts: str | None) -> SampleSize | None:
    """从方法/结果段抽样本量，取出现的最大值。

    取最大值的理由：「纳入 18 篇文献，涉及 12 468 例患者」里 18 是文献数、
    12468 是受试者数，最大值通常就是真正的样本量。代价是「纳入 34 项研究，
    包含 134 438 例」这类也存在时会把 134438 当样本量 —— 但那个数字确实
    就是样本量，所以不冲突。

    抽不到返回 `None`，**不猜**。前端应隐藏该指标而不是显示 0。
    """
    best: SampleSize | None = None
    for text in texts:
        if not text:
            continue
        for m in _SAMPLE_RE.finditer(text):
            try:
                value = int(re.sub(r"[\s,，]", "", m.group(1)))
            except ValueError:
                continue
            if not 1 <= value <= 5_000_000:
                continue
            if best is None or value > best.value:
                best = SampleSize(value=value, unit=m.group(2))
    return best


# ── LaTeX 残留清洗 ────────────────────────────────────────────
#
# MinerU 会把 PDF 里的公式/上下标输出成 `$...$` 包裹的 LaTeX。检索不受影响，
# 但用户看到 `$\\mathrm{M}_{3\\setminus\\mathrm{~}}\\mathrm{M}_{6}$` 只会以为坏了。
#
# 策略：**只处理 `$...$` 内部**，盒子外的正文一个字都不动。
# 这保证最坏情况也只是某段公式清洗得不好看，而不会破坏正常中文。

_MATH_SEGMENT_RE = re.compile(r"\$([^$]+)\$")

_LATEX_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\setminus", "、"),
    (r"\leqslant", "≤"),
    (r"\geqslant", "≥"),
    (r"\leq", "≤"),
    (r"\geq", "≥"),
    (r"\neq", "≠"),
    (r"\times", "×"),
    (r"\div", "÷"),
    (r"\pm", "±"),
    (r"\chi", "χ"),
    (r"\alpha", "α"),
    (r"\beta", "β"),
    (r"\gamma", "γ"),
    (r"\%", "%"),
    (r"\ ", " "),
    (r"\,", ""),
    (r"\;", ""),
    (r"\!", ""),
    (r"\~", "~"),
)

# 剩余的反斜杠命令（\mathrm / \mathbf / \left / \right / \sqrt …）整体删掉
_LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+")
# 数学排版符号：分组括号、上下标、对齐符
_LATEX_SYNTAX_RE = re.compile(r"[{}_^&]")

# ── 空格压紧 ──
#
# `\mathrm { M } _ { 3 }` 去掉命令和括号后剩「M 3」，直接展示是「M 3」——
# 能读但不像原文。这几条规则把数学片段内部的空隙合上：
#   M 3      → M3
#   H b A lc → HbAlc
#   χ 2      → χ2
#   7 . 0 %  → 7.0%
# **只匹配 ASCII 字母数字与 χ 这类单字符希腊字母**，中文之间的空格一律不动
# （「舒 张压 低 于」是 MinerU 的字间距噪声，但它属于正文，不在 `$...$` 内）。
_MATH_ALNUM = r"A-Za-z0-9\u03b1-\u03c9"
_SPACE_BETWEEN_ALNUM_RE = re.compile(rf"(?<=[{_MATH_ALNUM}]) (?=[{_MATH_ALNUM}])")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"(?<=[.,%<>=≤≥])\s+|\s+(?=[.,%<>=≤≥])")
_SPACE_COLLAPSE_RE = re.compile(r"[ \t]{2,}")
# 中文标点两侧不留空格
_CJK_PUNCT_SPACE_RE = re.compile(r"\s*([、，。；：（）])\s*")
# 数学片段里残留的英文句点紧挨中文标点时要丢掉（「M 0 . ，」→「M0，」）
_STRAY_PERIOD_RE = re.compile(r"\.\s*(?=[、，。；：])")
# 数学片段末尾的句读（PDF 把句号吸进公式里：`$\mathrm{M}_{0}.$`）—— 直接去掉
_TRAILING_PUNCT_RE = re.compile(r"[.,;:]+$")


def _compact_math_spaces(s: str) -> str:
    """把数学片段内部的空隙压紧（见上方规则说明）。"""
    prev = None
    # 反复压，直到稳定：`7 . 0 %` 要两轮才能从 `7 . 0 %` → `7.0%`
    while prev != s:
        prev = s
        s = _SPACE_BETWEEN_ALNUM_RE.sub("", s)
        s = _SPACE_BEFORE_PUNCT_RE.sub("", s)
    return s


def _clean_math(inner: str) -> str:
    s = inner
    for src, dst in _LATEX_REPLACEMENTS:
        s = s.replace(src, dst)
    s = _LATEX_COMMAND_RE.sub("", s)
    s = _LATEX_SYNTAX_RE.sub("", s)
    s = s.replace("~", "")
    s = _SPACE_COLLAPSE_RE.sub(" ", s)
    s = _compact_math_spaces(s)
    s = _STRAY_PERIOD_RE.sub("", s)
    s = s.rstrip()
    # 去掉公式末尾的句读，但**不能**连百分号/比较符一起砍（`7.5%` 要保留）
    if not s.endswith("%"):
        s = _TRAILING_PUNCT_RE.sub("", s)
    s = _CJK_PUNCT_SPACE_RE.sub(r"\1", s)
    return s.strip()


def clean_display_text(text: str | None) -> str:
    """清洗待展示文本里的 LaTeX 残留。

    只重写 `$...$` 内部，其余原样返回。

    **已知不完美的情形**：带嵌套上下标的长公式（如 `HbA1c` 被写成
    `$7.0\\% \\leqslant \\mathrm{HbA}_{\\mathrm{lc}} < 7.5\\%$`）清洗后
    会丢掉下标里的数字，得到 `7.0% ≤ HbA lc < 7.5%`。
    这类公式靠正则无法还原，属于已知损失 —— 但它至少不再是满屏反斜杠。
    """
    if not text or "$" not in text:
        return text or ""

    def repl(m: re.Match[str]) -> str:
        cleaned = _clean_math(m.group(1))
        # 清洗后若只剩标点/空白，整段公式丢弃（避免留下孤立的「、」）
        if not re.search(r"[0-9A-Za-z\u4e00-\u9fff]", cleaned):
            return ""
        return cleaned

    return _MATH_SEGMENT_RE.sub(repl, text)


# ── chunk 文本整理 ────────────────────────────────────────────


def strip_chunk_prefix(content: str | None) -> str:
    """去掉 chunk 首行的 `【章节】…` 前缀。

    章节路径已由 `heading_stack` 单独提供，正文里再带一遍会让证据卡出现
    「标题重复一次」的观感。
    """
    return _CHUNK_PREFIX_RE.sub("", (content or "").lstrip(), count=1).strip()


def split_paragraphs(text: str | None) -> list[str]:
    """按空行切段，丢弃空串。"""
    if not text:
        return []
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def prepare_hit_paragraphs(content: str | None) -> list[str]:
    """命中块 → 清洗后的段落列表（去前缀 + 洗 LaTeX + 切段）。"""
    return split_paragraphs(clean_display_text(strip_chunk_prefix(content)))


# ── 上下文摘录 ────────────────────────────────────────────────

_SENTENCE_END = "。！？；!?;"


def tail_excerpt(text: str | None, limit: int = 320) -> str:
    """取文本尾部，尽量从句子边界开始。

    上下文要「读得懂」，从半句话中间切开的尾巴比省略号更伤阅读 ——
    所以先在最后 `limit` 字符里找第一个句末标点，从它之后开始。
    找不到合适边界就保留原样截断（由前端加前置省略号表示）。
    """
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    tail = body[-limit:]
    # 在尾部窗口里找第一个句末标点，从其后面开始（跳过标点本身）
    for i, ch in enumerate(tail):
        if ch in _SENTENCE_END:
            rest = tail[i + 1:].strip()
            # 剩下太短说明切点不好，宁可多留
            if len(rest) >= limit // 3:
                return rest
            break
    return tail.strip()


def head_excerpt(text: str | None, limit: int = 320) -> str:
    """取文本头部，尽量在句子边界结束。

    与 `tail_excerpt` 对称：不把最后一句话切断。
    """
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    head = body[:limit]
    cut = max(head.rfind(ch) for ch in _SENTENCE_END)
    if cut >= limit // 3:
        return head[:cut + 1].strip()
    return head.strip()
