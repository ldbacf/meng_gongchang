"""
列出 MinIO 指定桶中的顶层文件夹数量（不递归，只看文件夹）

用法:
    uv run python scripts/list_bucket.py
    uv run python scripts/list_bucket.py --bucket parsed-data
    uv run python scripts/list_bucket.py --bucket raw-docs
    uv run python scripts/list_bucket.py --bucket doc-meta
    uv run python scripts/list_bucket.py --all      # 三个桶都看
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.minio_client import get_minio
from src.config import MINIO_RAW_BUCKET, MINIO_META_BUCKET, MINIO_PARSED_BUCKET


def list_folders(bucket: str):
    client = get_minio()
    objs = client.list_objects(bucket, recursive=True)
    folders = set()
    for o in objs:
        folder = o.object_name.split("/")[0]
        folders.add(folder)
    flist = sorted(folders)
    print(f"  {bucket}: {len(flist)} 个文件夹")
    for f in flist:
        print(f"    {f}")


def main():
    ap = ArgumentParser(description="列出 MinIO 桶中的顶层文件夹")
    ap.add_argument("--bucket", "-b", type=str, default="parsed-data", help="桶名")
    ap.add_argument("--all", "-a", action="store_true", help="列出三个桶")
    args = ap.parse_args()

    if args.all:
        for b in [MINIO_RAW_BUCKET, MINIO_META_BUCKET, MINIO_PARSED_BUCKET]:
            list_folders(b)
    else:
        list_folders(args.bucket)


if __name__ == "__main__":
    main()
