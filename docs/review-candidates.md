---
title: 审核 Candidate
nav_order: 2
parent: 使用 OKS
---
# 审核 Candidate

Candidate 是 Agent 的知识提案，不是已经确认的事实。

```bash
oks drafts list
oks drafts promote <slug>
oks drafts reject <slug>
```

审核时确认内容是否准确、来源是否支持结论、以后是否值得召回。晋升会写入
`human_reviewed_at`；只有 trace 证据或这个人工审核时间戳能够产生
`[verified]` 标签。Reject 会移出待审队列并保留不含正文的最小审阅回执。

需要逐条交互审阅时使用 `/promote` Skill。
