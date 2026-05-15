# 中国全科医学爬虫

爬取[中国全科医学](https://www.chinagp.net)期刊的文章信息和PDF。

## 环境

- Python >= 3.12
- 使用 [uv](https://docs.astral.sh/uv/) 管理依赖

```bash
uv sync
```

## 使用

分三步走：

### 1. 获取某年的卷期链接

```bash
uv run main.py 2025
```

输出所有卷期链接。把需要的链接复制到 `11.txt`（每行一个链接）。

### 2. 提取每期的文章链接

```bash
uv run get_article_links.py
```

读取 `11.txt` 中的卷期链接，提取每期的文章链接，保存到 `article_links.txt`。

### 3. 爬取文章详情 + 下载PDF

```bash
uv run scrape_articles.py
```

读取 `article_links.txt`，逐篇爬取标题、作者、摘要、关键词、DOI 等字段，同时下载 PDF。结果保存到 `articles/` 目录：

- `articles/json/` — 每篇文章一个 JSON 文件
- `articles/pdf/` — 对应的 PDF 文件

支持断点续爬，中断后重新运行会自动跳过已完成的文章。
