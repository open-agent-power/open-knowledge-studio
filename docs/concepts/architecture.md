---
title: 架构总览
nav_order: 3
parent: 概念
---

# 架构总览

OKS 三层架构：**摄入 → 桶 → 召回**。飞书是可选集成，不随 `oks` CLI 分发。

```mermaid
flowchart TD
    subgraph L1["① 摄入"]
        direction LR
        A[Source] --> B[模态判定] --> C[Provider ×17] --> D[Evidence<br/>Fragment · Manifest] --> E[raw-commit<br/>fail-closed] --> F[Bundle v0.2] --> G[Candidate] --> H[人审] --> I[Wiki]
    end

    subgraph L2["② 桶 · 5 认知 + 2 基础设施"]
        direction LR
        J[profiles] --- K[raw] --- L[wiki] --- M[drafts] --- N[mail 协调] --- O[settings] --- P[_meta]
    end

    subgraph L3["③ 召回"]
        direction LR
        Q[query] --> R[registry<br/>scope · goal] --> S[6+1 评分] --> T[backend<br/>native · fts5 · fusion] --> U[floor · cooldown] --> V[注入]
    end

    I -.->|晋升| L
    L -.->|semantic| Q
    K -.->|episodic| Q

    FSH[飞书 · 可选集成<br/>examples/oh-my-feishu] -.->|手机表单采集| B
    FSH -.->|IM 审核| H
```

## 关键点

- **摄入 fail-closed**：Schema + provenance + SHA-256 校验，证据不足即拒。
- **7 桶**：profiles / raw / wiki / drafts / mail（5 认知）+ settings / _meta（2 基础设施）；`mail` 是协调桶，不是知识桶。
- **召回**：6+1 因子 + 可插拔 backend（native / fts5 / fusion）。
- **飞书**：可选参考集成（`examples/oh-my-feishu/`），提供手机表单采集 + IM 审核的替代前端，不随 `oks` CLI 分发。
