"""获取某年的所有卷期链接"""
import requests
from lxml import html
from urllib.parse import urljoin
import sys

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def get_volumn_links(year="2025"):
    url = f"https://www.chinagp.net/CN/article/showTenYearVolumnDetail.do?nian={year}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    tree = html.fromstring(resp.content)

    links = tree.xpath("//a[contains(@href, '/volumn/volumn_')]/@href")
    if not links:
        links = tree.xpath("//a[contains(@href, 'volumn_')]/@href")

    seen = set()
    unique = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique.append(urljoin("https://www.chinagp.net/CN/article/", link))
    return unique


if __name__ == "__main__":
    year = sys.argv[1] if len(sys.argv) > 1 else "2025"
    volumns = get_volumn_links(year)
    print(f"共找到 {len(volumns)} 个卷期链接（{year}年）\n")
    for i, url in enumerate(volumns, 1):
        print(f"[{i:3d}] {url}")
