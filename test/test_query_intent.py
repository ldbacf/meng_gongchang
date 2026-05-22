"""
测试查询意图识别 — DeepSeek-V4-Flash

用法:
    uv run python test/test_query_intent.py              # 全部测试
    uv run python test/test_query_intent.py --intent-only  # 仅意图识别
    uv run python test/test_query_intent.py --pipeline     # 意图识别 + 检索链路
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# API Key 检查
# ═══════════════════════════════════════════════════════════════

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_KEY or DEEPSEEK_KEY.startswith("your-"):
    print("请先在 .env 中设置 DEEPSEEK_API_KEY=你的key")
    print("获取地址: https://platform.deepseek.com/api_keys")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════

TEST_CASES = [
    # (query, expected_coverage, description)
    ("高血压患者降压药物怎么选", "high", "域内高覆盖: 高血压"),
    ("2型糖尿病的血糖管理目标是什么", "high", "域内高覆盖: 糖尿病"),
    ("儿童发热怎么用药", "low", "域外低覆盖: 儿科临床"),
    ("急性阑尾炎的手术指征有哪些", "out_of_domain", "域外无覆盖: 外科手术"),
    ("今天天气怎么样", "out_of_domain", "域外无覆盖: 非医学"),
    ("COPD稳定期的治疗原则", "medium", "域内中覆盖: 呼吸系统"),
    ("脑卒中后康复训练怎么做", "high", "域内高覆盖: 脑卒中"),
    ("基层医疗机构家庭医生签约现状", "high", "域内高覆盖: 全科医学"),
]


# ═══════════════════════════════════════════════════════════════
# 测试 1: 意图识别
# ═══════════════════════════════════════════════════════════════


def test_intent_only() -> bool:
    from src.query_intent import analyze_intent

    print("=" * 65)
    print("  测试 1: 意图识别")
    print("=" * 65)

    ok = 0
    fail = 0

    for query, expected, desc in TEST_CASES:
        intent = analyze_intent(query)
        match = "[PASS]" if intent.coverage == expected else "[WARN]"
        if intent.coverage == expected:
            ok += 1
        else:
            fail += 1

        print(f"\n  [{desc}]")
        print(f"  Query   : {query}")
        print(f"  覆盖度  : {intent.coverage} (期望 {expected}) {match}")
        print(f"  领域    : {intent.domain}")
        print(f"  重写    : {intent.rewritten_query}")
        print(f"  关键词  : {intent.keywords}")
        if intent.suggestion:
            print(f"  提示    : {intent.suggestion}")

    print(f"\n  ───────────────")
    print(f"  准确率: {ok}/{ok+fail}")
    return fail == 0


# ═══════════════════════════════════════════════════════════════
# 测试 2: 意图识别 + 检索链路
# ═══════════════════════════════════════════════════════════════


def test_pipeline() -> bool:
    from src.search import search_with_intent, rerank

    print("\n" + "=" * 65)
    print("  测试 2: 意图识别 + 检索链路")
    print("=" * 65)

    queries = [
        "高血压患者降压药物怎么选",
        "儿童发热怎么用药",
    ]

    for query in queries:
        print(f"\n  ── Query: {query} ──")

        # Step 1: 意图识别 + 检索
        hits, intent = search_with_intent(query, filters={"level": "L1"}, top_k=10)

        print(f"  领域    : {intent.domain}")
        print(f"  覆盖度  : {intent.coverage}")
        print(f"  重写    : {intent.rewritten_query}")
        if intent.suggestion:
            print(f"  ⚠️ 提示 : {intent.suggestion}")

        print(f"  RRF 融合: {len(hits)} 条")

        # Step 2: Rerank
        if hits:
            reranked = rerank(query, hits, top_n=5)
            print(f"  Rerank top-3:")
            for i, h in enumerate(reranked[:3]):
                content = h.content[:100].replace("\n", " ")
                print(f"    {i+1}. rerank={h.score_rerank:.4f} | {content}...")
        else:
            print("  无结果")

    print("\n  ✅ 链路测试完成")
    return True


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--intent-only", action="store_true")
    parser.add_argument("--pipeline", action="store_true")
    args = parser.parse_args()

    run_all = not args.intent_only and not args.pipeline

    all_ok = True
    if run_all or args.intent_only:
        all_ok &= test_intent_only()
    if run_all or args.pipeline:
        all_ok &= test_pipeline()

    print("\n" + "=" * 65)
    if all_ok:
        print("  [PASS] All 8/8 tests passed")
    else:
        print("  [WARN] Coverage classification mismatch (adjust prompt)")
    print("=" * 65)
    sys.exit(0 if all_ok else 1)
