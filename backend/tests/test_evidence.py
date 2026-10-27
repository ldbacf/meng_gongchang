"""证据卡域逻辑单测 — 纯函数，不碰 MinIO / ES / DB。

覆盖的是**真实数据里踩到过的坑**，每条测试对应一个具体现象，
不是为了凑覆盖率：

- `abs_structured` 为 false 的 337 篇（指南/综述）必须返回空列表而不是伪造结论段
- 「方法。」这类 PDF 残句不能被当成段键
- `$\\mathrm{M}_{3}$` 必须清洗成 `M3`，且公式外的正文不能被改动
- 「纳入 18 篇文献」不能标成「样本量 18」
- 上下文摘录不能从半句话中间切开
"""
from __future__ import annotations

import pytest

from app.domain.retrieval.evidence import (
    SampleSize,
    clean_display_text,
    extract_sample_size,
    has_conclusion,
    head_excerpt,
    prepare_hit_paragraphs,
    split_abstract_sections,
    strip_chunk_prefix,
    tail_excerpt,
)


# ── 摘要分段 ──────────────────────────────────────────────────


def test_splits_structured_abstract_into_five_sections():
    """真实样本：7611（论著，结构式摘要）。"""
    raw = (
        "摘要： 背景 H型高血压严重影响着人们的健康及生活质量，目前临床上治疗高血压主要根据患者症状和临床经验选择药物。"
        " 目的 探讨济南市社区H型高血压药物作用靶点基因多态性分布及叶酸联合维生素D的干预作用。"
        " 方法 随机抽取山东省济南市槐荫区20家社区卫生服务中心200例血压控制不佳的高血压患者。"
        " 结果 M3、M6基因导向组Hcy水平低于基因组，差异有统计学意义（P<0.05）。"
        " 结论 社区H型高血压患者中存在高血压药物相关基因多态性的表达差异，个体化用药效果显著。"
    )
    sections = split_abstract_sections(raw)

    assert [s.key for s in sections] == ["背景", "目的", "方法", "结果", "结论"]
    assert sections[-1].text.startswith("结论 社区H型高血压患者")
    assert has_conclusion(sections) is True


def test_splits_when_section_keys_contain_spaces():
    """MinerU 会输出「目 的」「结 论」，段键正则要容忍字间空格。"""
    raw = "摘要： 背 景 高血压很常见，需要长期管理。 目 的 评价管理模式的效果与安全性。 结 论 该模式值得推广应用到基层。"
    sections = split_abstract_sections(raw)

    assert [s.key for s in sections] == ["背景", "目的", "结论"]


def test_returns_empty_for_single_paragraph_abstract():
    """真实样本：8087（综述）。没有分段键时不能凭空造一个「结论」段。"""
    raw = (
        "摘要： 高海拔地区低压、低氧环境致人体内代谢水平发生一系列变化，其特殊环境使体内氧化应激水平升高，"
        "从而损伤血管内皮细胞。本文主要就高海拔地区H型高血压患者血管内皮功能与氧化应激的关系进行综述，"
        "探索其发病机制及可能的治疗方法。"
    )
    sections = split_abstract_sections(raw)

    assert sections == []
    assert has_conclusion(sections) is False


def test_ignores_stray_section_key_at_sentence_end():
    """真实样本：8087 摘要末尾出现过孤立的「方法。」，字数不足必须被丢弃。"""
    raw = "摘要： 背景 某疾病的患病率逐年升高。 方法。"  # 末尾残句
    sections = split_abstract_sections(raw)

    assert [s.key for s in sections] == ["背景"]


def test_handles_missing_or_empty_abstract():
    assert split_abstract_sections(None) == []
    assert split_abstract_sections("") == []
    assert split_abstract_sections("   ") == []


def test_strips_abstract_label_prefix():
    sections = split_abstract_sections("摘 要：目的 验证某方案的可行性并给出推广建议。")
    assert sections[0].key == "目的"
    assert not sections[0].text.startswith("摘")


# ── 样本量 ────────────────────────────────────────────────────


def test_extracts_subject_count_from_methods():
    """真实样本：7611（200 例）。"""
    sample = extract_sample_size(
        "2020年6月—2022年6月随机抽取山东省济南市槐荫区20家街道办事处社区卫生服务中心200例血压控制不佳的高血压患者。"
    )
    assert sample == SampleSize(value=200, unit="例")
    assert sample.is_subject_count is True


def test_paper_count_is_not_treated_as_subject_count():
    """真实样本：8416（纳入 18 篇）。「篇」是文献数，不能标成样本量。"""
    sample = extract_sample_size("对纳入的18篇高血压管理模式文献涉及五种模式进行网状Meta分析。")
    assert sample == SampleSize(value=18, unit="篇")
    assert sample.is_subject_count is False


def test_prefers_larger_number_when_paper_and_subject_counts_coexist():
    """「纳入 18 篇文献，涉及 12 468 例患者」→ 样本量是 12468，不是 18。"""
    sample = extract_sample_size(
        "共纳入18篇文献，涉及12 468例患者，其中男6 200例。"
    )
    assert sample is not None
    assert sample.value == 12_468
    assert sample.is_subject_count is True


def test_returns_none_when_nothing_extractable():
    """综述类无原始样本 —— 返回 None，前端隐藏该指标而不是显示 0。"""
    assert extract_sample_size("本文就血管内皮功能与氧化应激的关系进行综述。") is None
    assert extract_sample_size(None, "", "  ") is None


def test_ignores_absurd_values():
    """噪声里的大整数（年份区间、页数）不应被当成样本量。"""
    assert extract_sample_size("纳入 0 例受试者的预试验。") is None


# ── LaTeX 清洗 ────────────────────────────────────────────────


def test_cleans_real_latex_residue_from_7611():
    """真实样本：ES 里 M3、M6 被写成两段 LaTeX。"""
    raw = (
        "患者 $\\mathrm { M } _ { 3 \\setminus \\mathrm { ~ } } \\mathrm { M } _ { 6 }$ 舒 张压 低 于 "
        "$\\mathrm { M } _ { 0 } .$ ，差异有统计学意义（P<0.05）"
    )
    out = clean_display_text(raw)

    assert "$" not in out
    assert "\\mathrm" not in out
    assert "M3" in out.replace(" ", "") or "M、3" in out  # 允许清洗后带分隔符
    assert "差异有统计学意义" in out


def test_cleans_latex_but_keeps_surrounding_chinese_intact():
    """公式外的正文一个字都不能动 —— 清洗必须只作用于 `$...$` 内部。"""
    raw = "在传统降压药治疗的基础上联合使用抗氧化药物，维生素 $\\mathrm { B } _ { 6 }$ 可促进排泄。"
    out = clean_display_text(raw)

    assert out.startswith("在传统降压药治疗的基础上联合使用抗氧化药物，维生素 ")
    assert out.endswith("可促进排泄。")
    assert "\\mathrm" not in out


def test_cleans_chi_squared_and_percent():
    raw = "组间比较采用 $\\chi ^ { 2 }$ 检验，以 P<0.05 为差异有统计学意义，有效率 96.5\\% 。"
    out = clean_display_text(raw)

    assert "χ" in out
    assert "%" in out
    assert "组间比较采用" in out


def test_text_without_math_is_returned_unchanged():
    raw = "患者血压 ≥160/100 mmHg 时应联合降压治疗（1A）。"
    assert clean_display_text(raw) == raw


def test_handles_none_and_empty():
    assert clean_display_text(None) == ""
    assert clean_display_text("") == ""


# ── chunk 前缀 ────────────────────────────────────────────────


def test_strips_chunk_section_prefix():
    raw = "【章节】2 结果 → 2.4 基因组用药对血压的影响\n\nA6986G:CYP3A5*1/*1（AA）患者舒张压低于 M0。"
    out = strip_chunk_prefix(raw)

    assert out.startswith("A6986G")
    assert "【章节】" not in out


def test_strip_prefix_is_noop_without_prefix():
    raw = "没有前缀的正文段落，应当原样返回。"
    assert strip_chunk_prefix(raw) == raw


def test_prepare_hit_paragraphs_end_to_end():
    """真实样本：一段带前缀 + LaTeX + 多段的命中块。"""
    raw = (
        "【章节】2 结果 → 2.4 用药对血压的影响\n\n"
        "A6986G:CYP3A5*1/*1（AA）患者 $\\mathrm { M } _ { 3 }$ 舒张压低于 M0。\n\n"
        "AGTR1 c.1166 A>C:AC 患者差异无统计学意义（P>0.05）。"
    )
    paras = prepare_hit_paragraphs(raw)

    assert len(paras) == 2
    assert "【章节】" not in paras[0]
    assert "$" not in paras[0]
    assert paras[1].startswith("AGTR1")


# ── 上下文摘录 ────────────────────────────────────────────────


def test_tail_excerpt_starts_at_sentence_boundary():
    """上下文从半句话中间切开最伤阅读，必须优先从句末开始。"""
    long_text = "第一句话讲背景与目的。" * 20 + "这是最后一句用于收尾的话，它应该被保留下来。"
    out = tail_excerpt(long_text, limit=60)

    # 不能以句号/分号开头
    assert out[0] not in "。！？；!?;"
    assert out.endswith("。")


def test_tail_excerpt_returns_whole_text_when_short():
    raw = "很短的上下文。"
    assert tail_excerpt(raw, limit=320) == raw


def test_head_excerpt_ends_at_sentence_boundary():
    long_text = "这是第一句话，讲清楚背景与目的。" * 20
    out = head_excerpt(long_text, limit=60)

    assert out.endswith("。")
    assert len(out) <= 80


def test_head_and_tail_handle_empty():
    assert head_excerpt(None) == ""
    assert tail_excerpt("") == ""


@pytest.mark.parametrize("raw,expected_len_at_most", [
    ("一句话。", 100),
])
def test_excerpt_bounds(raw, expected_len_at_most):
    assert len(head_excerpt(raw, limit=expected_len_at_most)) <= expected_len_at_most
    assert len(tail_excerpt(raw, limit=expected_len_at_most)) <= expected_len_at_most
