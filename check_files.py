"""检查 articles/json/ 和 articles/pdf/ 的文件名是否一一对应，缺失项匹配回 article_links"""
import json
import re
from pathlib import Path

JSON_DIR = Path("articles/json")
PDF_DIR = Path("articles/pdf")
LINKS_PATH = Path("article_links.txt")

json_names = {p.stem for p in JSON_DIR.glob("*.json")}
pdf_names = {p.stem for p in PDF_DIR.glob("*.pdf")}

only_json = sorted(json_names - pdf_names)
only_pdf = sorted(pdf_names - json_names)
matched = json_names & pdf_names

# 读取全部文章链接（按行索引，用于 article_{N} 这类文件名回查）
all_links = []
if LINKS_PATH.exists():
    with open(LINKS_PATH, encoding="utf-8") as f:
        all_links = [line.strip() for line in f if line.strip()]

# 建立 doi -> url 索引
doi_to_url = {}
for url in all_links:
    for part in url.split("/"):
        if part.startswith("10."):
            doi_to_url[part] = url
            break

print(f"JSON 文件: {len(json_names)}")
print(f"PDF  文件: {len(pdf_names)}")
print(f"匹配成功: {len(matched)}")
print()


def find_link(data, filename):
    # 优先用 JSON 里存的 source_url
    if data.get("source_url"):
        return data["source_url"]

    doi = data.get("doi", "")
    if doi:
        # 精确匹配
        if doi in doi_to_url:
            return doi_to_url[doi]
        # 部分匹配
        doi_suffix = doi.split("/", 1)[-1] if "/" in doi else doi
        for k, v in doi_to_url.items():
            if doi_suffix in k or k in doi_suffix:
                return v

    # article_{N} 类型：用索引直接查
    m = re.match(r"^article_(\d+)$", filename)
    if m:
        idx = int(m.group(1))
        if 0 <= idx < len(all_links):
            return all_links[idx]

    return ""


if only_json:
    print(f"有 JSON 但缺少对应 PDF ({len(only_json)} 个):")
    print("-" * 60)
    for name in only_json:
        json_path = JSON_DIR / f"{name}.json"
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        title_cn = data.get("title_cn", "") or name
        doi = data.get("doi", "")
        err = data.get("error", "")
        link = find_link(data, name)

        print(f"  文件: {name}.json")
        print(f"  标题: {title_cn[:60]}{'...' if len(title_cn) > 60 else ''}")
        if doi:
            print(f"  DOI:  {doi}")
        if err:
            print(f"  抓取错误: {err[:80]}")
        print(f"  链接: {link if link else '(未找到对应链接)'}")
        print()

if only_pdf:
    print(f"有 PDF 但缺少对应 JSON ({len(only_pdf)} 个):")
    print("-" * 60)
    for name in only_pdf:
        print(f"  - {name}.pdf")
    print()

if not only_json and not only_pdf:
    print("全部对应上了，没有缺失。")
