"""检查缺失 PDF 的条目，重新抓取"""
import json
import re
import time
import random
from pathlib import Path

from scrape_articles import (
    scrape_article,
    download_pdf,
    sanitize_filename,
    JSON_DIR,
    PDF_DIR,
    BASE_URL,
)

LINKS_PATH = Path("article_links.txt")

# 读取全部文章链接
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


def find_link(data, filename):
    if data.get("source_url"):
        return data["source_url"]
    doi = data.get("doi", "")
    if doi:
        if doi in doi_to_url:
            return doi_to_url[doi]
        doi_suffix = doi.split("/", 1)[-1] if "/" in doi else doi
        for k, v in doi_to_url.items():
            if doi_suffix in k or k in doi_suffix:
                return v
    m = re.match(r"^article_(\d+)$", filename)
    if m:
        idx = int(m.group(1))
        if 0 <= idx < len(all_links):
            return all_links[idx]
    return ""


def main():
    json_files = list(JSON_DIR.glob("*.json"))
    pdf_names = {p.stem for p in PDF_DIR.glob("*.pdf")}

    missing = []
    for jp in json_files:
        if jp.stem not in pdf_names:
            missing.append(jp)

    if not missing:
        print("没有缺失，全部对应上了。")
        return

    print(f"找到 {len(missing)} 个缺失 PDF 的条目\n")

    for i, jp in enumerate(missing, 1):
        try:
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        link = find_link(data, jp.stem)
        if not link:
            print(f"[{i}/{len(missing)}] {jp.name} — 未找到链接，跳过")
            continue

        print(f"[{i}/{len(missing)}] {link}")

        # 先删掉旧的残废 JSON（可能 title 为空或抓取失败）
        # 重新抓取
        time.sleep(random.uniform(2, 5))
        try:
            data = scrape_article(link)
        except Exception as e:
            data = {"article_id": "", "title_cn": "", "source_url": link, "error": str(e)}
            print(f"  ! 抓取失败: {e}")

        title = data.get("title_cn", "") or data.get("title_en", "") or jp.stem
        base_name = sanitize_filename(title)

        aid = data.get("article_id", "")
        if aid:
            ok, pdf_name, pdf_err = download_pdf(aid, title, link)
            if ok:
                print(f"  PDF 下载成功: {pdf_name}")
            elif pdf_err:
                print(f"  ! PDF 失败: {pdf_err}")
            time.sleep(random.uniform(1, 3))
        else:
            print(f"  ! 未提取到 article_id，跳过 PDF 下载")

        # 如果文件名变了（title 不再是 article_xxx），删掉旧文件
        new_path = JSON_DIR / f"{base_name}.json"
        if new_path != jp:
            jp.unlink(missing_ok=True)

        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"  JSON 已保存: {new_path.name}")

    print(f"\n完成！处理了 {len(missing)} 个条目")


if __name__ == "__main__":
    main()
