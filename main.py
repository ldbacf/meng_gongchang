"""获取指定年份的所有卷期链接，支持多年份"""
import re
import requests
from lxml import html
from urllib.parse import urljoin
import sys

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def _extract_year(el):
    """从 <a> 元素或其附近提取年份。"""
    # 方式1: <a> 自身的文本，例如 "2025 Vol.28 No.36"
    m = re.search(r'(20[2-9]\d)', el.text_content())
    if m:
        return m.group(1)
    # 方式2: 父级 <li> 中的 <b> 标签，例如 "<b>2026 Vol.29 No.14</b>"
    parent_li = el.xpath('ancestor::li')
    if parent_li:
        for b in parent_li[0].xpath('.//b'):
            m = re.search(r'(20[2-9]\d)', b.text_content())
            if m:
                return m.group(1)
    return None


def get_volumn_links(year="2025"):
    url = f"https://www.chinagp.net/CN/article/showTenYearVolumnDetail.do?nian={year}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    tree = html.fromstring(resp.content)

    links = tree.xpath("//a[contains(@href, '/volumn/volumn_')]")
    if not links:
        links = tree.xpath("//a[contains(@href, 'volumn_')]")

    seen = set()
    unique = []
    for a in links:
        href = a.get('href')
        if href in seen:
            continue
        if _extract_year(a) == year:
            seen.add(href)
            unique.append(urljoin("https://www.chinagp.net/CN/article/", href))
    return unique


if __name__ == "__main__":
    years = sys.argv[1:] if len(sys.argv) > 1 else ["2025"]

    all_volumns = []
    for year in years:
        volumns = get_volumn_links(year)
        all_volumns.extend(volumns)
        print(f"{year}年 → {len(volumns)} 个卷期")

    # 写入 11.txt
    with open("11.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(all_volumns))

    print(f"\n共 {len(all_volumns)} 个卷期链接，已写入 11.txt")
