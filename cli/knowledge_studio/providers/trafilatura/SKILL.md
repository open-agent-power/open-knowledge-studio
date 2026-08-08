# Trafilatura Provider

轻量 HTML 正文提取。适合普通英文网页和可公开访问的中文网页。不适合需要 JS 渲染的页面。

## 调用

```python
from trafilatura import extract
markdown = extract(html_bytes, output_format='markdown')
```

## 输出

Markdown 正文文本。不保留原始 HTML 或页面截图。

## 降级

trafilatura 空结果 → firecrawl (JS 渲染) → browser (登录态) → human
