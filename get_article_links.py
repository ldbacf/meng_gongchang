"""读取 11.txt 中的卷期链接，提取每期文章链接并保存"""
import requests
from lxml import html
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}


def get_article_links(volumn_url):
    try:
        resp = requests.get(volumn_url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
    except Exception as e:
        print(f"   请求失败: {e}")
        return []

    tree = html.fromstring(resp.content)
    links = tree.xpath("//form[@id='AbstractList']//dl/div[1]/a/@href")
    if not links:
        links = tree.xpath("//dl/div[1]/a/@href")
    return links


def main():
    with open("11.txt", "r", encoding="utf-8") as f:
        volumns = [line.strip() for line in f if line.strip()]

    print(f"共读取 {len(volumns)} 个卷期链接\n")

    all_articles = []
    for i, url in enumerate(volumns, 1):
        url = url.split()[-1]
        print(f"[{i:2d}/{len(volumns)}] {url}")
        links = get_article_links(url)
        print(f"       -> {len(links)} 篇文章")
        all_articles.extend(links)
        time.sleep(0.5)

    seen = set()
    unique = []
    for link in all_articles:
        if link not in seen:
            seen.add(link)
            unique.append(link)

    out_path = "article_links.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        for link in unique:
            f.write(link + "\n")

    print(f"\n完成！共收集 {len(unique)} 篇文章链接，已保存到 {out_path}")


if __name__ == "__main__":
    main()
