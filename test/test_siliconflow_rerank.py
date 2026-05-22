"""
测试硅基流动 Rerank API — Qwen3-Reranker-4B

用法:
    uv run python test/test_siliconflow_rerank.py              # 全部测试
    uv run python test/test_siliconflow_rerank.py --api-only   # 仅 API 直连
    uv run python test/test_siliconflow_rerank.py --pipeline   # 仅 search+rerank 链路
"""

import os
import sys

# 加项目根目录到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = os.getenv("SILICONFLOW_RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")

if not API_KEY or API_KEY == "your-api-key-here":
    print("请先在 .env 中设置 SILICONFLOW_API_KEY=你的key")
    print("获取地址: https://cloud.siliconflow.cn/account/ak")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# 测试 1: API 直连
# ═══════════════════════════════════════════════════════════════

QUERY = "儿童发热的用药原则是什么？"

DOCUMENTS = [
    "儿童发热时，体温未超过38.5°C时首选物理降温，如温水擦浴、退热贴等。超过38.5°C可使用对乙酰氨基酚或布洛芬，按体重计算剂量，间隔4-6小时给药。",
    "成人高血压患者应控制盐摄入量在每日6克以下，并遵医嘱服用降压药物，定期监测血压变化。",
    "小儿发热常用退热药包括：对乙酰氨基酚（10-15mg/kg/次）和布洛芬（5-10mg/kg/次），两者均为安全有效的退热药物。",
    "今天天气晴朗，适合户外运动，但要注意防晒和补水。",
    "儿科退热药物的选择需要综合考虑患儿年龄、体重、发热程度及伴随症状，3个月以下婴儿发热应立即就医。",
]


def test_api_direct() -> bool:
    """直连硅基流动 Rerank API"""
    print("=" * 60)
    print("  测试 1: API 直连")
    print("=" * 60)
    print(f"  模型: {MODEL}")
    print(f"  Query: {QUERY}")
    print(f"  文档数: {len(DOCUMENTS)}\n")

    payload = {
        "model": MODEL,
        "query": QUERY,
        "documents": DOCUMENTS,
        "top_n": 3,
        "return_documents": True,
    }

    try:
        resp = httpx.post(
            f"{BASE_URL}/rerank",
            json=payload,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return False

    print(f"  Tokens: {data.get('tokens', {})}")
    print(f"  {'─' * 50}")
    for item in data["results"]:
        idx = item["index"]
        score = item["relevance_score"]
        text = DOCUMENTS[idx][:80]
        print(f"  index={idx}  score={score:.6f}  | {text}...")

    # 校验
    scores = [r["relevance_score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True), "分数未降序"
    relevant_idx = {0, 2, 4}
    top3_idx = {r["index"] for r in data["results"]}
    overlap = relevant_idx & top3_idx
    print(f"\n  ✅ API 直连通过 (top-3 命中 {len(overlap)}/3 篇相关文档)")
    return True


# ═══════════════════════════════════════════════════════════════
# 测试 2: search + rerank 完整链路
# ═══════════════════════════════════════════════════════════════


def test_pipeline() -> bool:
    """ES 召回 + Milvus 召回 + RRF 融合 + Rerank 精排"""
    from src.search import search, rerank

    print("\n" + "=" * 60)
    print("  测试 2: search → rerank 完整链路")
    print("=" * 60)
    print(f"  模型: {MODEL}")
    print(f"  Query: {QUERY}\n")

    # Step 1: 双路召回 + RRF
    print("  [1/3] 双路召回 (ES + Milvus) + RRF 融合...")
    try:
        hits = search(QUERY, filters={"level": "L1"}, top_k=50)
    except Exception as e:
        print(f"  ⚠️ 召回失败 (Milvus 可能无数据): {e}")
        print("  尝试仅 ES 召回...")
        from src.search import _es_search
        try:
            hits = _es_search(QUERY, filters={"level": "L1"}, top_k=50)
        except Exception as e2:
            print(f"  ❌ ES 召回也失败: {e2}")
            return False

    print(f"  RRF 融合后: {len(hits)} 条")
    if hits:
        print(f"  top-1 score_rrf={hits[0].score_rrf:.4f} | {hits[0].content[:80]}...")

    # Step 2: Rerank 精排
    print(f"\n  [2/3] Rerank 精排 (Qwen3-Reranker-4B)...")
    if not hits:
        print("  无候选文档，跳过")
        return False

    reranked = rerank(QUERY, hits, top_n=10)

    print(f"  精排后: {len(reranked)} 条")
    for i, h in enumerate(reranked[:5]):
        content_preview = h.content[:80].replace("\n", " ")
        print(f"  {i+1}. rerank={h.score_rerank:.6f} rrf={h.score_rrf:.4f} | {content_preview}...")

    # 校验
    if reranked and reranked[0].score_rerank > 0:
        rerank_scores = [h.score_rerank for h in reranked if h.score_rerank > 0]
        if rerank_scores:
            assert rerank_scores == sorted(rerank_scores, reverse=True), "rerank 分数未降序"
            print(f"\n  ✅ 完整链路通过 ({len(reranked)} 条结果，top-1 rerank={reranked[0].score_rerank:.4f})")
            return True

    print(f"\n  ⚠️ rerank 未返回分数，请检查 API Key 和网络")
    return False


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--pipeline", action="store_true")
    args = parser.parse_args()

    run_all = not args.api_only and not args.pipeline

    ok = True
    if run_all or args.api_only:
        ok &= test_api_direct()
    if run_all or args.pipeline:
        ok &= test_pipeline()

    print("\n" + "=" * 60)
    if ok:
        print("  全部测试通过 ✅")
    else:
        print("  部分测试失败 ⚠️")
    print("=" * 60)
    sys.exit(0 if ok else 1)
