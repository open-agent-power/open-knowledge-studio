# Text Read Provider

零依赖文本文件读取。Agent 使用自身能力直接读取文件内容。

## 适用场景

- `.md`, `.txt`, `.csv` 文件
- 用户直接输入的文本
- 飞书表单提交的纯文本

## 调用方式

Agent 直接使用 Bash `cat` 或 `Read` 工具读取文件。

## 输出

文本原文即为 primary artifact。构造 EvidenceFragment 时标注 `agent_judgment: agent_observed`。

## 示例

```python
from providers.text_read.normalize import normalize
fragment = normalize(source_id, raw_text_bytes)
```
