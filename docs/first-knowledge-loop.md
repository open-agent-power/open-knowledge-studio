---
title: 第一个知识闭环
nav_order: 3
parent: 开始使用
---
# 第一个知识闭环

请选择一份你自己的真实资料。不要为了演示专门准备测试 PDF。

## 1. 交给 Agent

在知识库目录中，把文件或 URL 交给兼容 Agent：

> 收录这份资料。保留来源证据，生成 Candidate 后停下来让我审核。

如果要先显式创建工作区：

```bash
oks ingest prepare <文件或URL>
```

成功信号：命令输出 Run Workspace；Agent 最终报告 Raw Bundle 和 Candidate 的位置。

## 2. 审核 Candidate

```bash
oks drafts list
```

阅读 Candidate 正文和来源。决定：

- `promote`：内容准确、可复用，值得进入 Wiki；
- `edit`：方向正确，但需要改写或补充；
- `reject`：不值得长期保留。

通过后运行：

```bash
oks drafts promote <slug>
```

## 3. Recall

用你未来真的会问的问题召回：

```bash
oks recall "当时为什么这样决定？"
```

成功信号：结果中出现刚晋升的 Wiki 页面，并带路径和分数。

## 完成标准

- Raw 中保留了来源和证据；
- Candidate 经过你实际阅读；
- Wiki 页面带有 `human_reviewed_at`；
- `oks recall` 能用自然问题找回它。

如果某一步没有发生，前往[确认 OKS 正在工作](verify.md)。
