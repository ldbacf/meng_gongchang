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

### 1. 获取卷期链接

```bash
uv run main.py              # 默认 2025 年
uv run main.py 2025         # 指定单年
uv run main.py 2024 2025    # 支持多个年份
```

自动抓取指定年份的所有卷期链接，写入 `11.txt`。

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

**断点续爬**：进度保存在 `articles/_progress.txt`（含文件指纹）。中断后重新运行会自动继续。若 `article_links.txt` 内容发生变化（例如重新跑了前两步），指纹不匹配，进度自动重置。

**PDF 去重**：已下载的 PDF 不会重复下载。

### 4. 检查 JSON 和 PDF 是否对应

```bash
uv run check_files.py
```

列出缺少 PDF 的条目，并匹配回原始文章链接。

### 5. 补抓缺失的 PDF

```bash
uv run rescrape_missing.py
```

对缺失 PDF 的条目重新抓取文章信息并下载 PDF。
