"""下载 bge-m3 embedding 模型到 backend/models/bge-m3。

下载源优先级: ModelScope（国内） > HF 镜像 > HF 直连。
（无内部 import，standalone；仅放置模型权重。）

用法: python -m cli.download_model
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.pop("SSL_CERT_FILE", None)

REQUIRED_FILES = [
    "model.safetensors", "config.json", "tokenizer.json",
    "tokenizer_config.json", "modules.json", "sentence_bert_config.json",
]

MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
)


def verify() -> bool:
    missing = [f for f in REQUIRED_FILES if not os.path.isfile(os.path.join(MODEL_DIR, f))]
    if missing:
        print(f"缺少文件: {', '.join(missing)}")
        return False
    size = os.path.getsize(os.path.join(MODEL_DIR, "model.safetensors")) / 1024 / 1024
    print(f"model.safetensors: {size:.1f} MB")
    if size < 2000:
        print("模型文件异常小，可能未下载完整")
        return False
    print("模型完整性校验通过")
    return True


def download_hf(endpoint: str | None = None) -> bool:
    from huggingface_hub import snapshot_download

    if endpoint:
        os.environ["HF_ENDPOINT"] = endpoint
    else:
        os.environ.pop("HF_ENDPOINT", None)
        print("从 HuggingFace 直连下载…")
    try:
        snapshot_download(repo_id="BAAI/bge-m3", local_dir=MODEL_DIR)
        return verify()
    except Exception as e:
        print(f"HF 下载失败: {e}")
        return False


def download_modelscope() -> bool:
    print("从 ModelScope 下载…")
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        snapshot_download("BAAI/bge-m3", local_dir=MODEL_DIR)
        return verify()
    except Exception as e:
        print(f"ModelScope 下载失败: {e}")
        return False


def main() -> None:
    if os.path.exists(MODEL_DIR) and os.listdir(MODEL_DIR) and verify():
        print(f"模型已就绪: {MODEL_DIR}")
        return

    os.makedirs(MODEL_DIR, exist_ok=True)
    sources = [
        ("ModelScope", download_modelscope),
        ("HF 镜像", lambda: download_hf("https://hf-mirror.com")),
        ("HF 直连", lambda: download_hf(None)),
    ]
    for name, func in sources:
        print(f"\n尝试 {name}…")
        if func():
            print(f"下载成功: {name}")
            return

    print("\n所有下载方式均失败，请手动下载:")
    print("  https://modelscope.cn/models/BAAI/bge-m3")
    print(f"  放到 {MODEL_DIR}")
    sys.exit(1)


if __name__ == "__main__":
    main()
