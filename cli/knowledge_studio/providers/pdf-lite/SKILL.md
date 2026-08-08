# PDF Lite Provider

轻量 PDF 文本层提取。33 页 / 82K 字符 / 6.3s / 成本 0 已验证。

## 前提

`pymupdf4llm` 必须可导入。若不可用，先运行：

```bash
oks capability install pdf-lite
```

## 调用方式

### 1. 提取文本到 JSON

```bash
python -c "
import pymupdf4llm, json, sys
pages = pymupdf4llm.to_markdown(sys.argv[1], page_chunks=True)
print(json.dumps(pages, ensure_ascii=False))
" <PDF文件路径> > .oks/runs/{run_id}/work/pdf-lite/output.json
```

输出是逐页 dict 的 JSON 数组，每个 dict 包含：
- `metadata`: `{page, title}` — 页码和文档标题
- `text`: 该页的 Markdown 文本

### 2. 构造 EvidenceFragment

Fragment schema：`oks schema show evidence-fragment`

关键字段：
- `producer`: `"pdf-lite"`
- `provenance.tool`: `"pymupdf4llm"`
- 每条 evidence：
  - `kind`: `"text"`
  - `method`: `"pdf_text_layer"`
  - `locator`: `{"kind": "page", "page": N, "total_pages": M}`
  - `agent_judgment`: `"mechanical"`
  - `confidence`: `1.0`（有文本）或 `null`（空页）
- 每页一个 `evidence_id`，格式 `ev-p{N}-{source_id前8位}`

artifact：
- `artifact_id`: `"content"`
- `kind`: `"primary_text"`
- `path`: `"content.md"`
- `locator_kind`: `"page"`

### 3. 合并为 content.md

将各页用 `\n\n` 拼接，每页前缀 `<!-- Page N -->`。

## 判断状态

- `text_chars > 0` → status: `succeeded` / `complete`
- `text_chars == 0`（纯扫描件）→ status: `partial`，`failure_disposition: "needs_user_action"`
  - warnings: `"PDF text layer is empty; use remote OCR fallback and keep this result partial."`

## 降级

扫描 PDF → rapidocr (OCR) 或 agent-runtime (视觉) 或 firecrawl (远程 OCR)。
