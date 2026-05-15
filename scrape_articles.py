"""
遍历 article_links.txt 中的文章链接，提取字段 + 下载 PDF
输出: articles/json/ (每篇文章一个独立 JSON) + articles/pdf/

反ban策略：
  - 随机延迟 2-5s（PDF下载后再加 1-3s）
  - 每次请求带 Referer 头
  - 使用 Session 保持 cookie
  - 遇到 429/503 自动指数退避
  - 支持断点续爬
"""
import requests
import json
import re
import time
import random
from lxml import html
from pathlib import Path
from tqdm import tqdm

HEADERS_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
]

BASE_URL = "https://www.chinagp.net"
OUT_DIR = Path("articles")
JSON_DIR = OUT_DIR / "json"
PDF_DIR = OUT_DIR / "pdf"
JSON_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)
PROGRESS_PATH = OUT_DIR / "_progress.txt"

session = requests.Session()


def set_headers(referer=None):
    h = {
        "User-Agent": random.choice(HEADERS_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        h["Referer"] = referer
    return h


def request_with_retry(method, url, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = session.request(method, url, timeout=kwargs.pop("timeout", 30), **kwargs)
            if resp.status_code in (429, 503):
                wait = (2 ** attempt) * 10 + random.uniform(0, 5)
                tqdm.write(f"  遇到 {resp.status_code}，等待 {wait:.0f}s 后重试...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise
            wait = (2 ** attempt) * 5 + random.uniform(0, 3)
            tqdm.write(f"  请求失败: {e}，等待 {wait:.0f}s 后重试...")
            time.sleep(wait)
    return None


def extract_text(el):
    if el is None:
        return ""
    try:
        return el.text_content().strip()
    except Exception:
        return ""


def clean_keywords(text):
    text = re.sub(r"\s+", " ", text)
    text = text.strip().strip("，,;；")
    return text


def get_article_id(resp_text):
    m = re.search(r"lsdy1\s*\(\s*'PDF'\s*,\s*'(\d+)'", resp_text)
    if m:
        return m.group(1)
    m = re.search(r"lsdy1\s*\(\s*'RICH_HTML'\s*,\s*'(\d+)'", resp_text)
    if m:
        return m.group(1)
    return ""


def sanitize_filename(name):
    name = re.sub(r'[\x00-\x1f\\/:*?"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name)
    name = name.strip().rstrip('.')
    return name[:100]


def download_pdf(article_id, title, referer):
    pdf_name = sanitize_filename(title) + ".pdf"
    pdf_path = PDF_DIR / pdf_name
    if pdf_path.exists():
        return True, pdf_name, ""
    try:
        resp = request_with_retry(
            "POST",
            f"{BASE_URL}/CN/article/showArticleFile.do",
            data={"attachType": "PDF", "id": article_id, "json": "true"},
            headers=set_headers(referer),
        )
        text = resp.text.strip()
        if text.startswith("[json]"):
            data = json.loads(text.replace("[json]", ""))
            if data.get("status") == 1:
                pdf_url = data.get("pdfUrl", "")
                if pdf_url and pdf_url.startswith("http"):
                    pr = request_with_retry(
                        "GET", pdf_url,
                        headers=set_headers(BASE_URL),
                        timeout=120,
                    )
                    if pr.status_code == 200 and pr.content[:4] == b"%PDF":
                        pdf_path.write_bytes(pr.content)
                        return True, pdf_name, ""
                    return False, pdf_name, f"PDF下载状态: {pr.status_code}"
        return False, pdf_name, f"API响应: {text[:100]}"
    except Exception as e:
        return False, pdf_name, str(e)


def extract_source(tree):
    p = tree.xpath("//div[@class='abs-con']//p[1]")
    if p:
        txt = p[0].text_content().strip()
        m = re.search(r"(\d{4}),\s*Vol\.?\s*(\d+).*?Issue\s*\(?(\d+)\)?", txt)
        if m:
            return f"{m.group(1)}, Vol.{m.group(2)}, No.{m.group(3)}"
    return ""


def scrape_article(url):
    result = {}
    resp = request_with_retry("GET", url, headers=set_headers())
    resp.encoding = "utf-8"
    tree = html.fromstring(resp.content)
    text = resp.text

    result["journal"] = "中国全科医学"
    result["source"] = extract_source(tree)

    doi_el = tree.xpath("//span[@class='doi-doi']")
    if doi_el:
        result["doi"] = doi_el[0].text_content().replace("DOI:", "").strip()
    else:
        m = re.search(r"DOI:\s*(10\.\d+\.[^\s<]+)", text)
        result["doi"] = m.group(1).rstrip(".") if m else ""

    sec_el = tree.xpath("//div[@class='abs-con']//p[a[contains(@href,'subject')]]/a")
    result["section"] = extract_text(sec_el[0]) if sec_el else ""

    type_el = tree.xpath("//p[@class='clearfix']/span[@class='pull-left']")
    result["article_type"] = extract_text(type_el[0]) if type_el else ""

    h3 = tree.xpath("//h3[@class='abs-tit']")
    result["title_cn"] = extract_text(h3[0]) if len(h3) > 0 else ""
    result["title_en"] = extract_text(h3[1]) if len(h3) > 1 else ""

    if h3:
        cn_auth = h3[0].xpath("following-sibling::p[1]/span")
        result["authors_cn"] = extract_text(cn_auth[0]) if cn_auth else ""
        if len(h3) > 1:
            en_auth = h3[1].xpath("following-sibling::p[1]/span")
            result["authors_en"] = extract_text(en_auth[0]) if en_auth else ""

    pb = tree.xpath("//div[contains(@class,'panel-body') and contains(@class,'line-height')]")
    if pb:
        abs_cn = tree.xpath(
            "//div[contains(@class,'panel-body')]//p[starts-with(normalize-space(),'摘要')]"
        )
        result["abstract_cn"] = extract_text(abs_cn[0]) if abs_cn else ""

        kw_el = tree.xpath(
            "//div[contains(@class,'panel-body')]//p[strong[contains(text(),'关键词')]]"
        )
        if kw_el:
            kw = re.sub(r"^关键词[：:]\s*", "", kw_el[0].text_content().strip())
            result["keywords_cn"] = clean_keywords(kw)

        kw_en_el = tree.xpath(
            "//div[contains(@class,'panel-body')]//p[strong[contains(text(),'Key words') or contains(text(),'KEY WORDS')]]"
        )
        if kw_en_el:
            kw_en = re.sub(
                r"^(Key words|KEY WORDS)[：:]\s*", "", kw_en_el[0].text_content().strip()
            )
            result["keywords_en"] = clean_keywords(kw_en)

        full_text = pb[0].text_content()
        m = re.search(
            r"Abstract[：:]\s*(.*?)(?:Key\s+[Ww]ords|KEY\s+WORDS)",
            full_text, re.DOTALL,
        )
        if m:
            result["abstract_en"] = m.group(1).strip()
        else:
            result["abstract_en"] = ""

    result["article_id"] = get_article_id(text)

    return result


def read_progress():
    if PROGRESS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            return int(f.read().strip())
    return 0


def write_progress(n):
    PROGRESS_PATH.write_text(str(n))


def main():
    with open("article_links.txt", encoding="utf-8") as f:
        article_urls = [line.strip() for line in f if line.strip()]

    total = len(article_urls)
    start_idx = read_progress()

    if start_idx >= total:
        print(f"全部完成！({total} 篇)")
        return

    pending = list(enumerate(article_urls[start_idx:total], start=start_idx))
    print(f"待爬取: {len(pending)} 篇 (已完成 {start_idx} 篇)")

    for idx, url in tqdm(pending, desc="爬取文章", unit="篇"):
        time.sleep(random.uniform(2, 5))

        try:
            data = scrape_article(url)
        except Exception as e:
            data = {"article_id": "", "title_cn": "", "error": str(e)}
            tqdm.write(f"  ! 错误: {e}")

        title = data.get("title_cn", "") or data.get("title_en", "") or f"article_{idx}"
        base_name = sanitize_filename(title)

        aid = data.get("article_id", "")
        if aid:
            ok, pdf_name, pdf_err = download_pdf(aid, title, url)
            if ok:
                tqdm.write(f"  PDF: {pdf_name}")
            elif pdf_err:
                tqdm.write(f"  ! PDF失败: {pdf_err}")
            time.sleep(random.uniform(1, 3))

        json_path = JSON_DIR / f"{base_name}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        write_progress(idx + 1)

    print(f"\n完成! 共 {total} 篇")
    print(f"JSON: {JSON_DIR}/")
    print(f"PDF:  {PDF_DIR}/")


if __name__ == "__main__":
    main()
