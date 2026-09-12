"""列出 MinIO 桶中的顶层文件夹数量（不递归）。

用法:
    python -m cli.list_bucket
    python -m cli.list_bucket --bucket parsed-data
    python -m cli.list_bucket --all
"""
from __future__ import annotations

from argparse import ArgumentParser

from src.config import MINIO_META_BUCKET, MINIO_PARSED_BUCKET, MINIO_RAW_BUCKET
from src.minio_client import get_minio


def list_folders(bucket: str) -> None:
    client = get_minio()
    folders = {o.object_name.split("/")[0] for o in client.list_objects(bucket, recursive=True)}
    flist = sorted(folders)
    print(f"  {bucket}: {len(flist)} 个文件夹")
    for f in flist:
        print(f"    {f}")


def main() -> None:
    ap = ArgumentParser(description="列出 MinIO 桶中的顶层文件夹")
    ap.add_argument("--bucket", "-b", type=str, default="parsed-data", help="桶名")
    ap.add_argument("--all", "-a", action="store_true", help="列出三个桶")
    args = ap.parse_args()

    if args.all:
        for b in (MINIO_RAW_BUCKET, MINIO_META_BUCKET, MINIO_PARSED_BUCKET):
            list_folders(b)
    else:
        list_folders(args.bucket)


if __name__ == "__main__":
    main()
