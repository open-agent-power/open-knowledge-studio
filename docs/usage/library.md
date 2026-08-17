---
title: 资料库
nav_order: 3
parent: 使用 OKS
---
# 资料库

`raw/{YYYY}/{MM}/{DD}/{source}/` 存原始材料——论文、URL、视频、音频、代码仓库。工具做格式转换（video→text, URL→markdown），不做知识提炼。

## 摄入

```bash
oks ingest run <URL|file>
```

产出 Raw Bundle v0.2：`bundle.json`（清单）+ `content.md`（正文）+ `source-envelope.json` + `evidence-manifest.json` + `source/`（原始文件）+ `derived/`（fragments、补充产物）。每个 bundle 带 provenance（哪来的）+ fingerprint dedup（去重）。

## 分级

A / B / C 分级是 Agent 对材料的判断（值不值得起草）——`oks` 自己不判内容质量（P4）。A 级才写 `drafts/` Candidate，B/C 留 raw 待日后。

## 召回

keyword + freshness。`raw/` 是 episodic memory，无衰减。

ingest 的完整协议见 [ingest](../reference/ingest.md)。
