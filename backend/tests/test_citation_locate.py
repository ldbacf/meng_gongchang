"""引用定位：MinerU content_list 的 bbox 定位。

背景：原实现用 pdf.js findController 在文本层搜 snippet，两个硬伤
1. 必须先加载完整个 PDF（2.76MB @ 240KB/s ≈ 12s）才可能搜到
2. MinerU 抽取文本与 PDF 文本层在标点/空格/连字上不一致，稍长就 0 命中

MinerU 在 parsed-data/{md5}/*_content_list.json 里已给出每条文本的精确坐标
（`bbox` 0-1000 归一化 + `page_idx` 0-based），直接用它画框即可。

这里守住四件事：
1. 归一化能吃掉标点差异（全角/半角、引号、括号）
2. 跨块引用（条目 ⊂ snippet）也能命中
3. 排序把标题/参考文献/页眉页脚排到正文段落之后
4. 异常输入不抛错（空 snippet、脏数据、超长文本）
"""
from __future__ import annotations

from app.interface.routers.documents import (
    _locate_in_content_list,
    _longest_common,
    _norm_for_match,
)


def _item(text: str, page: int, bbox: list[float], typ: str = "text") -> dict:
    return {"text": text, "page_idx": page, "bbox": bbox, "type": typ}


# ── 归一化 ──


def test_norm_strips_punctuation_and_space():
    """全角标点/空格/引号都要归一掉 —— 这是文本层与 MinerU 文本最常见的差异。"""
    a = _norm_for_match("帕金森病，诊断　以临床症状为主。")
    b = _norm_for_match("帕金森病诊断以临床症状为主")
    assert a == b


def test_norm_keeps_cjk_and_alnum():
    assert _norm_for_match("ACEI 与 ARB 联用") == "ACEI与ARB联用"


def test_norm_empty():
    assert _norm_for_match("") == ""
    assert _norm_for_match("　，。！") == ""


# ── 匹配 ──


def test_exact_containment_hits():
    items = [_item("对合并糖尿病患者优先选择ACEI或ARB因其具有肾脏保护作用", 11, [100, 200, 900, 260])]
    boxes = _locate_in_content_list(items, "优先选择ACEI或ARB")
    assert len(boxes) == 1
    assert boxes[0].page == 12  # page_idx 11 → 1-based 12
    assert boxes[0].bbox == [100.0, 200.0, 900.0, 260.0]


def test_punctuation_difference_still_hits():
    """PDF 里是全角逗号，chunk 里是半角 —— 归一化后应命中。"""
    items = [_item("高血压患者，应定期随访。", 3, [10, 20, 300, 40])]
    boxes = _locate_in_content_list(items, "高血压患者,应定期随访")
    assert len(boxes) == 1


def test_cross_block_hits():
    """引用跨了多个条目：条目文本是 snippet 的一部分，也要命中。"""
    items = [
        _item("一线药物包括ACEI", 5, [10, 100, 400, 130]),
        _item("ARB与CCB", 5, [10, 140, 400, 170]),
    ]
    boxes = _locate_in_content_list(items, "一线药物包括ACEI，ARB与CCB均可作为初始选择")
    assert len(boxes) == 2
    assert all(b.page == 6 for b in boxes)


def test_no_match_returns_empty():
    items = [_item("完全无关的内容", 0, [10, 20, 30, 40])]
    assert _locate_in_content_list(items, "高血压怎么治疗") == []


# ── 排序 ──


def test_body_paragraph_ranks_above_title():
    """正文段落应排在标题之前 —— 标题短，正文长且常含完整句子。"""
    items = [
        _item("视网膜结构改变的机器学习", 0, [91, 142, 819, 193]),  # 标题，短
        _item(
            "本研究还发现，视网膜结构改变的机器学习模型在早期识别中表现良好，"
            "其敏感度与特异度均优于传统量表评估方式，具有临床推广价值。",
            4, [508, 768, 921, 933],
        ),  # 正文，长
    ]
    boxes = _locate_in_content_list(items, "视网膜结构改变的机器学习")
    assert boxes[0].page == 5, f"正文应排第一，实际 {boxes[0].text[:30]}"


def test_reference_entry_deprioritized():
    """「引用本文」与 ref_text 类型要降权，它们只是文末的重复出现。"""
    items = [
        _item("引用本文：梁可可，等. 视网膜结构改变的机器学习", 0, [83, 868, 904, 895]),
        _item("视网膜结构改变的机器学习可准确区分正常人与PD患者", 5, [510, 335, 919, 389]),
    ]
    boxes = _locate_in_content_list(items, "视网膜结构改变的机器学习")
    assert "引用本文" not in boxes[0].text


def test_header_footer_deprioritized():
    """页面最上/最下的重复（页眉页脚）降权。"""
    items = [
        _item("视网膜结构改变的机器学习相关研究进展综述", 2, [100, 30, 900, 50]),   # 页眉
        _item("视网膜结构改变的机器学习在诊断中的应用价值分析", 3, [100, 400, 900, 460]),  # 正文
    ]
    boxes = _locate_in_content_list(items, "视网膜结构改变的机器学习")
    assert boxes[0].page == 4


def test_page_number_type_skipped():
    items = [_item("视网膜结构改变的机器学习", 0, [10, 20, 30, 40], typ="page_number")]
    assert _locate_in_content_list(items, "视网膜结构改变的机器学习") == []


def test_result_capped():
    """同一句话重复很多次时不能返回几十个框。"""
    items = [
        _item(f"视网膜结构改变的机器学习第{i}次出现于正文描述之中", i, [10, 100, 900, 140])
        for i in range(30)
    ]
    boxes = _locate_in_content_list(items, "视网膜结构改变的机器学习")
    assert len(boxes) <= 4


# ── 健壮性 ──


def test_malformed_items_do_not_crash():
    items = [
        {},                                        # 空条目
        {"text": "有文本但无 bbox", "page_idx": 0},
        {"text": "有 bbox 无页码", "bbox": [0, 0, 1, 1]},
        {"text": "bbox 长度不对", "page_idx": 0, "bbox": [0, 0]},
        _item("正常条目：视网膜结构改变的机器学习", 1, [10, 20, 30, 40]),
    ]
    boxes = _locate_in_content_list(items, "视网膜结构改变的机器学习")
    assert len(boxes) == 1
    assert boxes[0].page == 2


def test_empty_snippet_returns_empty():
    assert _locate_in_content_list([_item("任意文本", 0, [0, 0, 1, 1])], "") == []


def test_longest_common_is_bounded():
    """超长输入必须被截断，否则 O(n²) 会卡住请求。"""
    a = "高血压" * 500
    b = "糖尿病" * 500
    # 不抛错即可；截断后规模是 120×120
    assert _longest_common(a, b) == 0
    assert _longest_common("高血压患者管理", "高血压") == 3
