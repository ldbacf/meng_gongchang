"""
验证 SentenceTransformer vs HuggingFaceEmbeddings 对同一 bge-m3 模型的编码一致性。

前提: 本地已有 models/bge-m3/ 目录
     需要 langchain-huggingface 和 sentence-transformers 均已安装

用法:
    uv run python test/test_embedding_compat.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

LOCAL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3"))

if not os.path.isdir(LOCAL_PATH):
    print(f"本地模型不存在: {LOCAL_PATH}")
    print("请先运行 scripts/download_model.py")
    sys.exit(1)

SAMPLE_TEXTS = [
    "高血压患者在冬季应如何调整降压药物剂量？",
    "The management of type 2 diabetes requires a multidisciplinary approach.",
    "基层医疗卫生机构的家庭医生签约服务覆盖率逐年提升。",
    "急性心肌梗死患者应在发病后2小时内进行急诊PCI治疗。",
    "Meta-analysis of randomized controlled trials on the efficacy of SGLT2 inhibitors.",
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_sentence_transformer() -> np.ndarray:
    """SentenceTransformer 编码（当前生产方式）"""
    print("  [1/3] 加载 SentenceTransformer...")
    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(LOCAL_PATH)
    embeddings = st.encode(SAMPLE_TEXTS, normalize_embeddings=True, show_progress_bar=False)
    dim = embeddings.shape[1]
    print(f"       维度: {dim}, 形状: {embeddings.shape}")
    assert dim == 1024, f"期望 1024, 实际 {dim}"
    norms = np.linalg.norm(embeddings, axis=1)
    print(f"       向量范数: min={norms.min():.4f} max={norms.max():.4f} (归一化后应为 1.0)")
    return embeddings


def test_huggingface_embeddings() -> np.ndarray:
    """HuggingFaceEmbeddings 编码（LangChain 方式）"""
    print("  [2/3] 加载 HuggingFaceEmbeddings...")
    from langchain_huggingface import HuggingFaceEmbeddings

    hf = HuggingFaceEmbeddings(
        model_name=LOCAL_PATH,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    embeddings_raw = hf.embed_documents(SAMPLE_TEXTS)
    embeddings = np.array(embeddings_raw)
    dim = embeddings.shape[1]
    print(f"       维度: {dim}, 形状: {embeddings.shape}")
    assert dim == 1024, f"期望 1024, 实际 {dim}"
    norms = np.linalg.norm(embeddings, axis=1)
    print(f"       向量范数: min={norms.min():.4f} max={norms.max():.4f} (归一化后应为 1.0)")
    return embeddings


def test_single_query():
    """HuggingFaceEmbeddings.embed_query() 单条编码"""
    print("  [单条] embed_query() 测试...")
    from langchain_huggingface import HuggingFaceEmbeddings

    hf = HuggingFaceEmbeddings(
        model_name=LOCAL_PATH,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
    vec = hf.embed_query(SAMPLE_TEXTS[0])
    dim = len(vec)
    norm = np.linalg.norm(vec)
    print(f"       维度: {dim}, 范数: {norm:.4f}")
    return np.array(vec)


def main():
    print("=" * 60)
    print("  验证: SentenceTransformer vs HuggingFaceEmbeddings")
    print("  Model: bge-m3 @ models/bge-m3/")
    print("  Texts: {} 条\n".format(len(SAMPLE_TEXTS)))

    # ─── 编码 ───
    try:
        st_emb = test_sentence_transformer()
    except Exception as e:
        print(f"  ❌ SentenceTransformer 加载失败: {e}")
        sys.exit(1)

    try:
        hf_emb = test_huggingface_embeddings()
    except Exception as e:
        print(f"  ❌ HuggingFaceEmbeddings 加载失败: {e}")
        print(f"     请先确保 langchain-huggingface 已安装: uv add langchain-huggingface")
        sys.exit(1)

    try:
        q_vec = test_single_query()
    except Exception as e:
        print(f"  ❌ embed_query 失败: {e}")
        sys.exit(1)

    # ─── 对比 ───
    print("\n  [3/3] 向量差异对比:")

    diffs = []
    for i in range(len(SAMPLE_TEXTS)):
        cos = cosine(st_emb[i], hf_emb[i])
        max_abs_diff = np.max(np.abs(st_emb[i] - hf_emb[i]))
        diffs.append(cos)
        print(f"    text[{i}]  cos_sim={cos:.6f}  max_abs_diff={max_abs_diff:.2e}")

    min_cos = min(diffs)
    avg_cos = sum(diffs) / len(diffs)

    print(f"\n    最小余弦相似度: {min_cos:.6f}")
    print(f"    平均余弦相似度: {avg_cos:.6f}")

    print("\n" + "=" * 60)
    if min_cos >= 0.99:
        print("  [PASS] Validation passed - cos_sim >= 0.99")
        print("  Safe to replace SentenceTransformer with HuggingFaceEmbeddings")
        sys.exit(0)
    elif min_cos >= 0.95:
        print(f"  [WARN] cos_sim={min_cos:.4f}, acceptable but minor differences")
        print("  May come from: tokenizer version / inference precision / normalization")
        sys.exit(0)
    else:
        print(f"  [FAIL] min cos_sim={min_cos:.4f} < 0.95")
        print("  Need to check: model_card params / normalize_embeddings")
        sys.exit(1)


if __name__ == "__main__":
    main()
