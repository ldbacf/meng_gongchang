#!/usr/bin/env python3
"""
中国全科医学 (Chinese General Practice) 爬虫脚本
爬取 2024-2025 年期刊文章元数据（JSON）及 PDF 文件

目录结构：
爬取数据/
├── 2024Vol.27/
│   ├── No.1/
│   │   ├── ~科学研究是我国全科医学发展的应有之义和当务之急.json
│   │   ├── 科学研究是我国全科医学发展的应有之义和当务之急.pdf
│   │   └── ...
│   ├── No.2/
│   └── ...
└── 2025Vol.28/
    ├── No.1/
    └── ...
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import sys
from datetime import datetime
from urllib.parse import urljoin

# Windows GBK 终端兼容 + 强制行缓冲
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    # 所有 print 强制刷新
    _orig_print = print
    def print(*args, **kwargs):
        kwargs.setdefault('flush', True)
        _orig_print(*args, **kwargs)

BASE_URL = "https://www.chinagp.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/CN/1007-9572/home.shtml",
}

# 卷期配置
YEAR_CONFIG = {
    "2024": {"vol": 27, "start_id": 1841, "end_id": 1876},
    "2025": {"vol": 28, "start_id": 1877, "end_id": 1912},
}

ROOT_DIR = R"E:\梦工厂自建项目\爬取数据"
REQUEST_INTERVAL = 1.5  # 请求间隔（秒），避免被封
MAX_RETRIES = 3


def safe_filename(text, max_len=100):
    """将文本转为安全的文件名"""
    # 移除或替换不安全的文件名字符
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', '_', text.strip())
    if len(text) > max_len:
        text = text[:max_len]
    return text if text else "untitled"


def fetch_with_retry(url, session, params=None, retries=MAX_RETRIES):
    """带重试的 HTTP GET 请求"""
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, params=params, timeout=30)
            resp.encoding = 'utf-8'
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 404:
                print(f"  [404] 页面不存在: {url}")
                return None
            else:
                print(f"  [HTTP {resp.status_code}] {url}")
        except requests.RequestException as e:
            print(f"  [请求异常] {url}: {e}")
        if attempt < retries - 1:
            time.sleep(REQUEST_INTERVAL * 2)
    return None


def extract_issue_number(volumn_id, year_config):
    """根据 volumn_id 计算期号"""
    return volumn_id - year_config["start_id"] + 1


def parse_issue_page(volumn_id, session):
    """
    解析单期页面，提取文章列表
    返回: (issue_info, articles_list)
    """
    url = f"{BASE_URL}/CN/volumn/volumn_{volumn_id}.shtml"
    resp = fetch_with_retry(url, session)
    if not resp:
        return None, []

    soup = BeautifulSoup(resp.text, 'html.parser')

    # 提取期信息：2024年 第27卷 第01期 / 刊出日期：2024-01-05
    issue_info = {"volumn_id": volumn_id}
    njq_el = soup.find('div', class_='njq')
    if njq_el:
        njq_text = njq_el.get_text(strip=True)
        year_m = re.search(r'(\d{4})年', njq_text)
        vol_m = re.search(r'第(\d+)卷', njq_text)
        no_m = re.search(r'第(\d+)期', njq_text)
        date_m = re.search(r'刊出日期：(\d{4}-\d{2}-\d{2})', njq_text)
        if year_m:
            issue_info["year"] = year_m.group(1)
        if vol_m:
            issue_info["volume"] = int(vol_m.group(1))
        if no_m:
            issue_info["issue"] = int(no_m.group(1))
            issue_info["issue_label"] = f"No.{int(no_m.group(1))}"
        if date_m:
            issue_info["publish_date"] = date_m.group(1)

    articles = []
    # 查找所有文章区块
    article_divs = soup.find_all('div', id=lambda x: x and x.startswith('art'))
    current_section = "未分类"

    # 先扫描所有 section 标题，再映射到文章
    all_elements = soup.find_all(['div', 'a'], recursive=True)
    current_section = "未分类"
    section_articles = []  # list of (section, article_element)

    for el in soup.find_all(True):
        # 检测栏目名称
        if el.name == 'div' and 'wenzhanglanmu' in el.get('class', []):
            name_el = el.find('a')
            if name_el and name_el.get('name'):
                current_section = name_el.get('name').strip()
            else:
                current_section = el.get_text(strip=True)
            continue

        # 检测文章区块
        if el.name == 'div' and el.get('id', '').startswith('art'):
            article_id = el.get('id')[3:]
            section_articles.append((current_section, article_id, el))

    # 解析每篇文章
    seen_ids = set()
    for section, article_id, article_el in section_articles:
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)

        article_data = {
            "article_id": article_id,
            "section": section,
            "pdf_url": f"{BASE_URL}/CN/article/downloadArticleFile.do?attachType=PDF&id={article_id}",
        }

        # 标题
        biaoti_el = article_el.find('div', class_='biaoti')
        if biaoti_el:
            link_el = biaoti_el.find('a', class_='biaoti')
            if link_el:
                article_data["title_cn"] = link_el.get_text(strip=True)
                article_data["article_url"] = urljoin(BASE_URL, link_el.get('href', ''))

        # 作者
        zuozhe_el = article_el.find('div', class_='zuozhe')
        if zuozhe_el:
            article_data["authors_cn"] = zuozhe_el.get_text(strip=True)
            article_data["authors_list"] = [a.strip() for a in article_data["authors_cn"].split(',')]

        # DOI 和页码
        kmnjq_el = article_el.find('div', class_='kmnjq')
        if kmnjq_el:
            kmnjq_text = kmnjq_el.get_text(strip=True)
            doi_link = kmnjq_el.find('a')
            if doi_link:
                article_data["doi"] = doi_link.get_text(strip=True)
            pages_m = re.search(r':\s*(\d+(?:-\d+)?)\.', kmnjq_text)
            if pages_m:
                article_data["pages"] = pages_m.group(1)

        # 摘要（从issue页提取中文摘要，后续从文章详情页补充结构化信息）
        abstract_el = article_el.find('div', id=f'Abstract{article_id}')
        if abstract_el:
            p_el = abstract_el.find('p', class_='mag_zhaiyao_p')
            if p_el:
                abstract_text = p_el.get_text(strip=True)
                if abstract_text:
                    article_data["abstract_cn_text"] = abstract_text

        articles.append(article_data)

    return issue_info, articles


def parse_structured_abstract(html):
    """
    解析结构化摘要（含子标题: 背景/目的/方法/结果/结论 / Background/Objective/Methods/Results/Conclusion）
    返回: {"full_text": "...", "sections": {"标题": "内容", ...}}
    """
    result = {"full_text": "", "sections": {}}

    # 查找所有 mag_zhaiyao_sec 区块
    sec_blocks = re.findall(
        r'<div\s+class="mag_zhaiyao_sec">(.*?)</div>', html, re.DOTALL
    )
    if not sec_blocks:
        # 尝试直接找 <p> 中包含中文摘要强标签的段落
        sec_blocks = re.findall(
            r'<strong[^>]*>(?:摘要|Abstract)[：:]\s*</strong>\s*(.*?)(?=<strong|</div|<div)',
            html, re.DOTALL
        )
        if sec_blocks:
            full = re.sub(r'<[^>]+>', '', sec_blocks[0]).strip()
            result["full_text"] = full
        return result

    sections = {}
    all_text_parts = []

    for block in sec_blocks:
        title_m = re.search(
            r'<strong[^>]*class="mag_zhaiyao_title"[^>]*>(.*?)</strong>', block
        )
        p_m = re.search(
            r'<p[^>]*class="mag_zhaiyao_p"[^>]*>(.*?)</p>', block, re.DOTALL
        )
        if title_m and p_m:
            title = title_m.group(1).strip().rstrip('：:')
            text = re.sub(r'<[^>]+>', '', p_m.group(1)).strip()
            sections[title] = text
            all_text_parts.append(f"{title}: {text}")
        elif p_m:
            text = re.sub(r'<[^>]+>', '', p_m.group(1)).strip()
            all_text_parts.append(text)

    result["sections"] = sections
    main_text = re.sub(r'<[^>]+>', '', html)
    # 尝试另一模式：找所有紧挨内容的区块
    if not all_text_parts:
        # fallback: 直接取 p 标签文本
        ps = re.findall(r'<p[^>]*class="mag_zhaiyao_p"[^>]*>(.*?)</p>', html, re.DOTALL)
        all_text_parts = [re.sub(r'<[^>]+>', '', p).strip() for p in ps]

    result["full_text"] = "\n".join(all_text_parts)
    return result


def scrape_article_detail(article_url, session):
    """
    从文章详情页提取完整元数据、摘要（含子标题）、关键词等
    返回: dict (补充/更新的字段)
    """
    if not article_url:
        return {}

    resp = fetch_with_retry(article_url, session)
    if not resp:
        return {}

    soup = BeautifulSoup(resp.text, 'html.parser')
    page_text = resp.text
    detail = {}

    # ── 从 <meta> 标签提取结构化数据 ──
    meta_mappings = {
        "citation_title": "title_cn",
        "citation_doi": "doi",
        "citation_issn": "issn",
        "citation_volume": "volume",
        "citation_issue": "issue",
        "citation_firstpage": "first_page",
        "citation_lastpage": "last_page",
        "citation_publication_date": "publication_date",
        "citation_online_date": "online_date",
        "citation_pdf_url": "pdf_url",
    }
    for meta_name, key in meta_mappings.items():
        tag = soup.find('meta', {'name': meta_name})
        if tag and tag.get('content'):
            detail[key] = tag['content']

    # 英文标题
    for tag in soup.find_all('meta', {'name': 'citation_title', 'xml:lang': 'en'}):
        if tag.get('content'):
            detail["title_en"] = tag['content']
            break

    # ── 作者信息 ──
    cn_authors = []
    for tag in soup.find_all('meta', {'name': 'citation_authors', 'xml:lang': 'zh'}):
        if tag.get('content'):
            cn_authors.append(tag['content'])
    if cn_authors:
        detail["authors_cn"] = '; '.join(cn_authors)
        detail["authors_list"] = [
            a.strip() for a in '; '.join(cn_authors).replace(';', ',').split(',') if a.strip()
        ]

    en_authors = []
    for tag in soup.find_all('meta', {'name': 'citation_authors', 'xml:lang': 'en'}):
        if tag.get('content'):
            en_authors.append(tag['content'])
    if en_authors:
        detail["authors_en"] = '; '.join(en_authors)
        detail["authors_en_list"] = [
            a.strip() for a in '; '.join(en_authors).replace(';', ',').split(',') if a.strip()
        ]

    # ── 通讯作者 ──
    corr_m = re.search(r'通信作者[：:]\s*([^,，;；。]+)', page_text)
    if corr_m:
        detail["corresponding_author"] = corr_m.group(1).strip()

    # ── 作者单位 ──
    affiliations = []
    for m in re.finditer(r'(\d+[．.][^，,。]+(?:大学|医院|学院|研究所|中心|实验室)[^，,。]*)', page_text):
        aff = m.group(1).strip()
        if len(aff) > 5:
            affiliations.append(aff)
    if affiliations:
        detail["affiliations"] = list(dict.fromkeys(affiliations))  # 去重保留顺序

    # ── 关键词（从 meta 标签） ──
    cn_keywords = []
    for tag in soup.find_all('meta', {'name': 'citation_keywords', 'xml:lang': 'zh'}):
        if tag.get('content'):
            cn_keywords.append(tag['content'])
    if cn_keywords:
        detail["keywords_cn"] = cn_keywords
    else:
        # 备选: DC.Keywords
        dc_tag = soup.find('meta', {'name': 'DC.Keywords'})
        if dc_tag and dc_tag.get('content'):
            detail["keywords_cn"] = [
                k.strip() for k in dc_tag['content'].rstrip(',').split(',') if k.strip()
            ]

    en_keywords = []
    for tag in soup.find_all('meta', {'name': 'citation_keywords', 'xml:lang': 'en'}):
        if tag.get('content'):
            en_keywords.append(tag['content'])
    if en_keywords:
        detail["keywords_en"] = en_keywords

    # ── 结构化摘要 ──
    # 工具函数: 从纯文本中解析中文子标题（背景/目的/方法/结果/结论/Objective/Methods...）
    def parse_plain_abstract_sections(text, cn=True):
        """从纯文本摘要中解析子标题，返回 {"full_text":..., "sections":{...}}"""
        if cn:
            subtitles = ['背景', '目的', '方法', '结果', '结论', '基金', '局限性',
                         'Background', 'Objective', 'Methods', 'Results', 'Conclusion']
        else:
            subtitles = ['Background', 'Objective', 'Methods', 'Results', 'Conclusion',
                         '背景', '目的', '方法', '结果', '结论']

        # 尝试按子标题拆分
        pattern = r'(' + '|'.join(re.escape(s) for s in subtitles) + r')\s*'
        parts = re.split(pattern, text)
        if len(parts) >= 3:
            sections = {}
            for i in range(1, len(parts) - 1, 2):
                title = parts[i].strip()
                content = parts[i + 1].strip() if i + 1 < len(parts) else ''
                # 只取到下一个子标题之前
                sections[title] = content.strip()
            if sections:
                return {"full_text": text, "sections": sections}
        return {"full_text": text, "sections": {}}

    # 收集所有 mag_zhaiyao_sec 区块
    all_secs = re.findall(
        r'<div\s+class="mag_zhaiyao_sec">(.*?)</div>', page_text, re.DOTALL
    )

    cn_secs = []
    en_secs = []
    for sec in all_secs:
        if re.search(r'[一-鿿]', sec):
            cn_secs.append(sec)
        if re.search(r'[a-zA-Z]{4,}', sec):
            en_secs.append(sec)

    # ── 中文摘要 ──
    if cn_secs:
        cn_parsed = parse_structured_abstract(
            '<div class="mag_zhaiyao_sec">' + '</div><div class="mag_zhaiyao_sec">'.join(cn_secs) + '</div>'
        )
        detail["abstract_cn"] = cn_parsed
    else:
        # 从 Description meta 获取
        desc_tag = soup.find('meta', {'name': 'Description', 'xml:lang': 'zh'})
        if desc_tag and desc_tag.get('content', '').strip():
            cn_text = desc_tag['content']
            detail["abstract_cn"] = parse_plain_abstract_sections(cn_text, cn=True)
        else:
            # 从 <p><strong>摘要：</strong> 模式
            for p in soup.find_all('p'):
                strong = p.find('strong')
                if strong and '摘要' in strong.get_text(strip=True):
                    text = p.get_text(strip=True)
                    text = re.sub(r'^摘要[：:]\s*', '', text).strip()
                    if text:
                        detail["abstract_cn"] = parse_plain_abstract_sections(text, cn=True)
                        break

    # ── 英文摘要 ──
    if en_secs:
        en_parsed = parse_structured_abstract(
            '<div class="mag_zhaiyao_sec">' + '</div><div class="mag_zhaiyao_sec">'.join(en_secs) + '</div>'
        )
        detail["abstract_en"] = en_parsed
    else:
        desc_tag_en = soup.find('meta', {'name': 'Description', 'xml:lang': 'en'})
        if desc_tag_en and desc_tag_en.get('content', '').strip():
            en_text = desc_tag_en['content']
            detail["abstract_en"] = parse_plain_abstract_sections(en_text, cn=False)
        else:
            for p in soup.find_all('p'):
                strong = p.find('strong')
                if strong and 'Abstract' in strong.get_text(strip=True):
                    text = p.get_text(strip=True)
                    text = re.sub(r'^Abstract[：:]\s*', '', text).strip()
                    if text:
                        detail["abstract_en"] = parse_plain_abstract_sections(text, cn=False)
                        break

    # ── 所属专题（栏目/专辑） ──
    # 从面包屑导航提取栏目名: <p class="clearfix"><span class="pull-left">• 卷首语 •</span>
    bread_p = soup.find('p', class_='clearfix')
    if bread_p:
        span = bread_p.find('span', class_='pull-left')
        if span:
            section_text = span.get_text(strip=True).strip('• ')
            if section_text:
                detail["section"] = section_text

    # 从文章详情页的 category/collection 链接
    collect_links = re.findall(
        r'href=["\']([^"\']*(?:collection|subject)/[^"\']+)["\'][^>]*>([^<]{4,})<',
        page_text
    )
    for href, text in collect_links:
        if '专辑' in text or '合辑' in text or '专题' in text or len(text) > 5:
            detail["collection"] = text.strip()
            detail["collection_url"] = urljoin(BASE_URL, href)
            break

    # ── 中图分类号 ──
    cls_m = re.search(r'中图分类号[：:]\s*([^<]+)', page_text)
    if cls_m:
        code = cls_m.group(1).strip().replace(' ', '').replace('&nbsp;', '').strip()
        detail["classification_code"] = code

    # ── 基金项目 ──
    fund_patterns = [
        r'基金项目[：:]\s*([^<。]+(?:项目|基金)[^<。]*)',
        r'基金[：:]\s*([^<。]+(?:项目|基金)[^<。]*)',
        r'\[Fund(?:ing)?\].*?([^<。]+)',
    ]
    for pattern in fund_patterns:
        fund_m = re.search(pattern, page_text)
        if fund_m:
            detail["funding"] = fund_m.group(1).strip()
            break

    # ── DOI URL ──
    if detail.get("doi"):
        detail["doi_url"] = f"https://doi.org/{detail['doi']}"

    return detail


def get_sanitized_filename(title, article_id):
    """根据标题生成安全的文件名"""
    if title:
        name = safe_filename(title, 80)
    else:
        name = f"article_{article_id}"
    return name


def process_article(article, issue_dir, session):
    """
    处理单篇文章：获取详情、保存 JSON、下载 PDF
    返回 True 表示成功
    """
    article_id = article.get("article_id", "unknown")
    title = article.get("title_cn", f"article_{article_id}")

    # 生成文件名
    base_name = get_sanitized_filename(title, article_id)
    json_filename = f"~{base_name}.json"
    pdf_filename = f"{base_name}.pdf"
    json_path = os.path.join(issue_dir, json_filename)
    pdf_path = os.path.join(issue_dir, pdf_filename)

    # 如果 JSON 已存在且完整，跳过
    if os.path.exists(json_path) and os.path.exists(pdf_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            if existing.get("status") == "complete":
                print(f"  [跳过] {title}")
                return True
        except (json.JSONDecodeError, KeyError):
            pass

    print(f"  [处理] {title}")

    # 获取文章详情
    article_url = article.get("article_url", "")
    if article_url:
        detail = scrape_article_detail(article_url, session)
        article.update(detail)
        time.sleep(REQUEST_INTERVAL)

    # 二次处理：结构化数据增强
    article = post_process_article(article)

    # 保存 JSON
    article["status"] = "complete"
    article["crawl_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    article["pdf_filename"] = pdf_filename

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(article, f, ensure_ascii=False, indent=2)

    # 下载 PDF
    pdf_url = article.get("pdf_url", "")
    if pdf_url and not os.path.exists(pdf_path):
        download_pdf(pdf_url, pdf_path, session)
    elif os.path.exists(pdf_path):
        print(f"  [PDF已存在] {pdf_filename}")

    return True


def post_process_article(article):
    """
    二次处理：对提取的数据进行结构化增强
    - 作者列表清洗
    - 关键词数组化
    - 结构化摘要（含子标题: 背景/目的/方法/结果/结论）
    - 标准化引用格式
    - 提取年份、卷期数字
    """
    processed = dict(article)

    # 1. 确保作者列表是干净数组
    if "authors_list" in processed and isinstance(processed["authors_list"], list):
        processed["authors_list"] = [
            a.strip() for a in processed["authors_list"] if a.strip()
        ]
    elif "authors_cn" in processed:
        processed["authors_list"] = [
            a.strip() for a in processed["authors_cn"].replace(';', ',').split(',') if a.strip()
        ]
    else:
        processed["authors_list"] = []

    # 2. 处理结构化摘要（abstract 现在是 {"full_text": ..., "sections": {...}}）
    for lang in ["cn", "en"]:
        key = f"abstract_{lang}"
        raw = processed.get(key)
        if isinstance(raw, dict):
            full_text = raw.get("full_text", "")
            sections = raw.get("sections", {})
            processed[f"{key}_text"] = full_text
            processed[f"{key}_sections"] = sections
            processed[f"{key}_char_count"] = len(full_text)
            processed[f"{key}_short"] = (full_text[:80] + "...") if len(full_text) > 80 else full_text
        elif isinstance(raw, str) and raw:
            processed[f"{key}_text"] = raw
            processed[f"{key}_sections"] = {}
            processed[f"{key}_char_count"] = len(raw)
            processed[f"{key}_short"] = (raw[:80] + "...") if len(raw) > 80 else raw
        else:
            processed[f"{key}_text"] = ""
            processed[f"{key}_sections"] = {}
            processed[f"{key}_char_count"] = 0
            processed[f"{key}_short"] = ""

    # 3. 标准化引用信息
    citation_parts = []
    if processed.get("authors_cn"):
        citation_parts.append(processed["authors_cn"])
    if processed.get("title_cn"):
        citation_parts.append(f"{processed['title_cn']}[J]")
    citation_parts.append("中国全科医学")
    year = processed.get("year") or processed.get("publication_date", "")[:4]
    vol = processed.get("volume", "")
    issue = processed.get("issue", "")
    pages = processed.get("pages", "")
    if year or vol:
        citation_parts.append(f"{year},{vol}({issue}):{pages}")
    processed["citation_formatted"] = '. '.join(citation_parts)

    if processed.get("doi") and "doi_url" not in processed:
        processed["doi_url"] = f"https://doi.org/{processed['doi']}"

    # 4. 确保分类号字段存在
    if "classification_code" not in processed:
        processed["classification_code"] = ""

    # 5. 确保专题/栏目字段
    if "section" not in processed:
        processed["section"] = ""

    # 6. 确保关键词数组
    for kw_key in ["keywords_cn", "keywords_en"]:
        if kw_key not in processed:
            processed[kw_key] = []

    # 7. 确保基金字段
    if "funding" not in processed:
        processed["funding"] = ""

    # 8. 固定信息
    processed["source"] = "中国全科医学"
    processed["source_en"] = "Chinese General Practice"
    processed["issn"] = processed.get("issn", "1007-9572")

    return processed


def download_pdf(pdf_url, save_path, session):
    """下载PDF文件"""
    try:
        pdf_headers = dict(HEADERS)
        pdf_headers["Accept"] = "application/pdf,*/*"
        resp = session.get(pdf_url, headers=pdf_headers, timeout=60, stream=True)
        if resp.status_code == 200 and 'application/pdf' in resp.headers.get('Content-Type', ''):
            with open(save_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"  [PDF下载完成] {os.path.basename(save_path)} ({len(resp.content)} bytes)")
            return True
        elif resp.status_code == 200:
            # 可能 content-type 不标准，但仍可能是 PDF
            if resp.content[:4] == b'%PDF':
                with open(save_path, 'wb') as f:
                    f.write(resp.content)
                print(f"  [PDF下载完成] {os.path.basename(save_path)}")
                return True
            # 某些文章可能需要登录/付费下载
            print(f"  [PDF无法下载] HTTP 200 但非PDF格式, 可能需登录")
            return False
        else:
            print(f"  [PDF下载失败] HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [PDF下载异常] {e}")
        return False


def verify_issue_range(year, year_config, session):
    """
    验证卷期范围的完整性
    返回: (valid_start, valid_end, total_issues)
    """
    start_id = year_config["start_id"]
    end_id = year_config["end_id"]
    expected_count = end_id - start_id + 1

    print(f"\n验证 {year} 年卷期范围: volumn_{start_id} ~ volumn_{end_id} (共{expected_count}期)")
    valid_ids = []
    for vid in range(start_id, end_id + 1):
        url = f"{BASE_URL}/CN/volumn/volumn_{vid}.shtml"
        resp = fetch_with_retry(url, session)
        if resp:
            soup = BeautifulSoup(resp.text, 'html.parser')
            njq = soup.find('div', class_='njq')
            label = njq.get_text(strip=True) if njq else "未知"
            valid_ids.append((vid, label))
            print(f"  [OK] volumn_{vid}: {label}")
        else:
            print(f"  ✗ volumn_{vid}: 无法访问")
        time.sleep(REQUEST_INTERVAL * 0.5)

    return valid_ids


def build_directory(year_label, issue_label):
    """构建目录结构"""
    dir_path = os.path.join(ROOT_DIR, year_label, issue_label)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def main():
    print("=" * 60)
    print("中国全科医学 爬虫脚本")
    print(f"爬取范围: 2024 Vol.27, 2025 Vol.28")
    print(f"输出目录: {ROOT_DIR}")
    print("=" * 60)

    session = requests.Session()

    # 第一步：验证卷期范围
    print("\n>>> 第一步：验证卷期完整性")
    all_valid = {}
    for year, yc in YEAR_CONFIG.items():
        valid = verify_issue_range(year, yc, session)
        all_valid[year] = valid

    # 第二步：逐期爬取
    print("\n>>> 第二步：开始爬取文章数据")
    total_articles = 0
    total_issues = 0
    start_time = time.time()

    for year, yc in YEAR_CONFIG.items():
        vol_num = yc["vol"]
        year_label = f"{year}Vol.{vol_num}"
        print(f"\n{'=' * 40}")
        print(f"开始爬取: {year_label}")
        print(f"{'=' * 40}")

        for vid, issue_label in all_valid[year]:
            total_issues += 1
            # 从 issue_label 提取期号: "2024年 第27卷 第01期 刊出日期：2024-01-05"
            no_match = re.search(r'第(\d+)期', issue_label)
            issue_no = no_match.group(1) if no_match else f"{vid - yc['start_id'] + 1:02d}"
            issue_dir_label = f"No.{int(issue_no)}"

            print(f"\n  --- {issue_dir_label} ({issue_label}) ---")

            # 构建目录
            issue_dir = build_directory(year_label, issue_dir_label)

            # 解析期页面
            issue_info, articles = parse_issue_page(vid, session)
            if not articles:
                print(f"  [无文章] {issue_label}")
                continue

            print(f"  共 {len(articles)} 篇文章")

            # 处理每篇文章
            for article in articles:
                process_article(article, issue_dir, session)
                total_articles += 1
                time.sleep(REQUEST_INTERVAL)

    # 汇总
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"爬取完成!")
    print(f"  处理期数: {total_issues}")
    print(f"  处理文章: {total_articles}")
    print(f"  耗时: {elapsed:.0f} 秒 ({elapsed/60:.1f} 分钟)")
    print(f"  输出目录: {ROOT_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
