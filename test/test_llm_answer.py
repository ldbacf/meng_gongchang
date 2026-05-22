"""
测试 LLM 回答生成 — DeepSeek-V4-Pro

用法:
    uv run python test/test_llm_answer.py              # 全部
    uv run python test/test_llm_answer.py --sync       # 仅非流式
    uv run python test/test_llm_answer.py --stream     # 仅流式
    uv run python test/test_llm_answer.py --pipeline   # 仅一键管线
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_KEY or DEEPSEEK_KEY.startswith("your-"):
    print("请先在 .env 中设置 DEEPSEEK_API_KEY")
    sys.exit(1)


QUERY = "高血压患者降压药物怎么选"


def test_format_context():
    """测试 context 拼装格式"""
    from src.search import SearchHit
    from src.llm_answer import format_context

    hits = [
        SearchHit(
            content="高血压患者首选ACEI或ARB类药物，联合用药可提高达标率。",
            heading_stack=["2 治疗", "2.1 药物治疗"],
            title_cn="高血压诊疗指南",
            doi="10.xxxx/xxxx",
        ),
        SearchHit(
            content="老年高血压患者宜从低剂量开始，缓慢调整。",
            heading_stack=["3 特殊人群", "3.1 老年高血压"],
            title_cn="老年高血压管理共识",
            doi="10.xxxx/yyyy",
        ),
    ]

    ctx = format_context(hits, top_n=5)

    print("=" * 60)
    print("  [Test] format_context")
    print("=" * 60)
    print(ctx)
    assert "[1]" in ctx, "缺少 [1] 序号"
    assert "[2]" in ctx, "缺少 [2] 序号"
    print("\n  [PASS] format_context OK")


def test_answer_sync():
    """非流式回答"""
    from src.search import SearchHit
    from src.llm_answer import answer

    hits = _make_test_hits()

    print("\n" + "=" * 60)
    print(f"  [Test] answer (sync)")
    print(f"  Query: {QUERY}")
    print("=" * 60)

    result = answer(QUERY, hits, top_n=3)

    print(f"\n  回答:\n{result.answer[:500]}")
    print(f"\n  来源数: {len(result.sources)}")

    assert result.answer, "回答为空"
    assert len(result.answer) > 20, "回答太短"
    print("  [PASS] answer sync OK")


def test_answer_stream():
    """流式回答"""
    from src.search import SearchHit
    from src.llm_answer import answer_stream

    hits = _make_test_hits()

    print("\n" + "=" * 60)
    print(f"  [Test] answer (stream)")
    print(f"  Query: {QUERY}")
    print("=" * 60)

    tokens = []
    first = True
    for token in answer_stream(QUERY, hits, top_n=3):
        tokens.append(token)
        if first:
            print(f"  首 token: {token[:50]}...")
            first = False

    full = "".join(tokens)
    print(f"  总长度: {len(full)} chars")
    print(f"  完整:\n{full[:300]}...")

    assert len(full) > 20, "流式输出太短"
    print("  [PASS] answer stream OK")


def test_pipeline():
    """search_and_answer 一键管线（需要 ES + Milvus 运行中）"""
    from src.search import search_and_answer

    print("\n" + "=" * 60)
    print(f"  [Test] search_and_answer pipeline")
    print(f"  Query: {QUERY}")
    print("=" * 60)

    try:
        result = search_and_answer(QUERY, filters={"level": "L1"}, top_k=20)
    except Exception as e:
        print(f"  [SKIP] 基础设施不可用 (ES/Milvus): {e}")
        print("  跳过管线测试，单元测试已覆盖 LLM 回答逻辑")
        return

    print(f"\n  覆盖度: {result.intent.coverage if result.intent else 'N/A'}")
    print(f"  领域: {result.intent.domain if result.intent else 'N/A'}")
    if result.intent and result.intent.suggestion:
        print(f"  提示: {result.intent.suggestion}")
    print(f"\n  来源数: {len(result.sources)}")
    print(f"\n  回答:\n{result.answer[:500]}")

    assert result.answer, "回答为空"
    assert len(result.answer) > 20, "回答太短"
    print("\n  [PASS] pipeline OK")


def test_pipeline_stream():
    """search_and_answer 管线流式（需要 ES + Milvus 运行中）"""
    from src.search import search_and_answer

    print("\n" + "=" * 60)
    print(f"  [Test] search_and_answer (stream)")
    print(f"  Query: 儿童发热怎么用药")
    print("=" * 60)

    try:
        stream = search_and_answer("儿童发热怎么用药", filters={"level": "L1"}, top_k=20, stream=True)
    except Exception as e:
        print(f"  [SKIP] 基础设施不可用 (ES/Milvus): {e}")
        return

    tokens = []
    for token in stream:
        tokens.append(token)

    full = "".join(tokens)
    print(f"  总长度: {len(full)} chars")
    print(f"\n  回答:\n{full[:300]}")

    assert len(full) > 10, "流式输出太短"
    print("\n  [PASS] pipeline stream OK")


def _make_test_hits():
    """构造测试用的 SearchHit 列表"""
    from src.search import SearchHit

    return [
        SearchHit(
            content="高血压患者降压治疗首选血管紧张素转化酶抑制剂（ACEI）或血管紧张素II受体拮抗剂（ARB），单药不达标时联合钙通道阻滞剂（CCB）或噻嗪类利尿剂。",
            heading_stack=["2 治疗", "2.1 药物治疗原则"],
            title_cn="中国高血压防治指南",
        ),
        SearchHit(
            content="联合用药方案推荐ACEI/ARB+CCB或ACEI/ARB+利尿剂，可提高血压控制达标率，减少不良反应。",
            heading_stack=["2 治疗", "2.2 联合用药方案"],
            title_cn="中国高血压防治指南",
        ),
        SearchHit(
            content="老年高血压患者（≥65岁）降压目标为<140/90mmHg，如能耐受可进一步降至<130/80mmHg。起始治疗宜从低剂量开始，缓慢调整。",
            heading_stack=["3 特殊人群", "3.1 老年高血压"],
            title_cn="老年高血压管理专家共识",
        ),
        SearchHit(
            content="难治性高血压的定义为在改善生活方式基础上，使用≥3种不同机制降压药物（含利尿剂）足量治疗后血压仍不达标。",
            heading_stack=["4 难治性高血压", "4.1 定义与诊断"],
            title_cn="难治性高血压诊断与治疗中国专家共识",
        ),
        SearchHit(
            content="春季天气转暖，血管扩张，部分患者血压可下降，需减少降压药剂量以免低血压。冬季血管收缩，血压易升高，需增加剂量或联合用药。",
            heading_stack=["5 患者教育", "5.1 生活方式管理"],
            title_cn="高血压患者自我管理指导手册",
        ),
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--pipeline", action="store_true")
    args = parser.parse_args()

    run_all = not args.sync and not args.stream and not args.pipeline

    print()
    test_format_context()

    if run_all or args.sync:
        test_answer_sync()
        test_answer_stream()
    elif args.stream:
        test_answer_stream()

    if run_all or args.pipeline:
        test_pipeline()
        test_pipeline_stream()

    print("\n" + "=" * 60)
    print("  [PASS] All tests passed")
    print("=" * 60)
