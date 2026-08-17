---
title: 架构总览
nav_order: 3
parent: 概念
---

# 架构总览

OKS 三层架构：**摄入 → 桶 → 召回**，两条 hook 是可选注入入口；飞书是可选集成，不随 `oks` CLI 分发。

```mermaid
flowchart TB

%% =========================================================
%% Open Knowledge Studio (OKS) 当前架构
%% Agent-native · 文件系统优先 · 可审核 · 可追溯
%% =========================================================

%% ---------- 颜色 ----------
classDef ingest fill:#EEF4FF,stroke:#4F7CFF,stroke-width:1.5px,color:#172033;
classDef ingestStrong fill:#E4EDFF,stroke:#2563EB,stroke-width:2px,color:#172033;

classDef knowledge fill:#EFFAF2,stroke:#55A86B,stroke-width:1.5px,color:#172033;
classDef mail fill:#F7EEFF,stroke:#9B51E0,stroke-width:2px,color:#5B2391;

classDef infra fill:#F4F5F7,stroke:#98A2B3,stroke-width:1.5px,color:#344054;

classDef recall fill:#FFF5EA,stroke:#F59E5B,stroke-width:1.5px,color:#172033;
classDef recallStrong fill:#FFECDB,stroke:#EA580C,stroke-width:2px,color:#172033;

classDef optional fill:#FCF7FF,stroke:#9B51E0,stroke-width:1.5px,stroke-dasharray:6 5,color:#5B2391;
classDef note fill:#FFF9E8,stroke:#D8B04C,stroke-width:1px,color:#594A1A;
classDef hook fill:#F7F8FA,stroke:#98A2B3,stroke-width:1px,stroke-dasharray:5 4,color:#475467;


%% =========================================================
%% 第 1 层：摄入流水线
%% =========================================================

subgraph L1["① 摄入流水线"]
direction LR

S["Source<br/><small>文件 / URL / 媒体 / 平台</small>"]:::ingest
M["模态判定<br/><small>text · pdf · office<br/>image · web · audio · video</small>"]:::ingest
P["选 Provider<br/><small>能力目录 · oks capability status</small>"]:::ingest

EF["EvidenceFragment ×N"]:::ingest
EM["EvidenceManifest<br/><small>steps · artifacts · SHA-256</small>"]:::ingest

RC["oks raw-commit<br/><small>fail-closed</small>"]:::ingestStrong

RB["Raw Bundle v0.2<br/><small>bundle · content · source · derived</small>"]:::ingest

C["Candidate<br/><small>A / B / C · A级才写</small>"]:::ingest

HR["Human Review<br/><small>promote · edit · reject</small>"]:::ingest

W0["Wiki"]:::knowledge

S --> M --> P --> EF --> EM --> RC --> RB --> C --> HR --> W0

end


%% =========================================================
%% 第 2 层：5 个主桶 + 2 个基础设施
%% =========================================================

subgraph L2["② 5 个主桶 + 2 个基础设施"]
direction TB

subgraph BUCKETS["知识工作区"]
direction LR

PRO["profiles/<br/><small>画像 · scope · goal · registry</small>"]:::knowledge

RAW["raw/<br/><small>原始材料 · episodic</small>"]:::knowledge

WIKI["wiki/<br/><small>人审知识 · 22 domain</small>"]:::knowledge

DRAFT["drafts/<br/><small>Candidate · 人审门控</small>"]:::knowledge

MAIL["mail/<br/><small>协调桶 · inbox / sent<br/><b>不是知识桶</b></small>"]:::mail

end

subgraph INFRA["基础设施"]
direction LR

SET["settings/<br/><small>recall.yaml</small>"]:::infra
META["_meta/<br/><small>schema · 协议形状契约</small>"]:::infra

end

RAW -. "raw ≠ memory<br/>材料 ≠ 正式知识" .-> WIKI

end


%% 摄入结果对应到文件系统
RB --> RAW
C --> DRAFT
HR --> WIKI
W0 --> WIKI


%% =========================================================
%% 第 3 层：召回 + 注入
%% =========================================================

subgraph L3["③ 召回 + 注入"]
direction LR

Q["query<br/><small>用户 prompt / 工具操作</small>"]:::recall

REG["registry<br/><small>scope / goal<br/>agent_id + cwd</small>"]:::recall

SCORE["6+1 因子评分<br/><small>overlap · substring · topic<br/>type · review · curve · goal</small>"]:::recall

SEARCH["search backend<br/><small>native · fts5 · fusion</small>"]:::recall

FILTER["过滤 + 去重<br/><small>floor · cooldown</small>"]:::recall

CTX["注入上下文<br/><small>&lt;recalled-memory&gt;</small>"]:::recallStrong

Q --> REG --> SCORE --> SEARCH --> FILTER --> CTX

end

PRO --> REG
WIKI --> SCORE
SET --> SCORE
SET --> SEARCH
META -. "协议约束" .-> SEARCH


%% =========================================================
%% Hooks
%% =========================================================

H1["UserPromptSubmit<br/><small>用户说话 → recall 注入</small>"]:::hook
H2["PostToolUse<br/><small>recall 补位 + 文件冲突检测</small>"]:::hook

H1 -.-> Q
H2 -.-> Q
H2 -. "冲突记录" .-> MAIL


%% =========================================================
%% 可选集成：飞书
%% =========================================================

subgraph FEISHU["可选集成 · 飞书"]
direction TB

F0["examples/oh-my-feishu/<br/><small>可选 · 不随 oks CLI 分发</small>"]:::optional
F1["手机表单采集"]:::optional
F2["IM 审核"]:::optional

F0 --> F1
F0 --> F2

end

F1 -. "替代采集入口" .-> S
F2 -. "审核表面" .-> HR


%% =========================================================
%% 信任语义
%% =========================================================

TRUST["[verified] 只来自 trace 证据或 human_reviewed_at<br/>绝不来自使用次数"]:::note

HR -.-> TRUST
WIKI -.-> TRUST
```

## 关键点

- **摄入 fail-closed**：Schema + provenance + SHA-256 校验，证据不足即拒；raw ≠ memory，材料≠正式知识。
- **7 桶**：profiles / raw / wiki / drafts / mail（5 认知）+ settings / _meta（2 基础设施）；`mail` 是协调桶，不是知识桶。
- **召回**：6+1 因子 + 可插拔 backend（native / fts5 / fusion），floor + cooldown 过滤去重后注入 `<recalled-memory>`。
- **Hooks（可选注入）**：UserPromptSubmit（用户 prompt → recall 注入）+ PostToolUse（recall 补位 + 文件冲突检测），`oks hook install` 显式安装。
- **信任语义**：`[verified]` 只来自 trace 证据或 `human_reviewed_at`，绝不来自使用次数。
- **飞书**：可选参考集成（`examples/oh-my-feishu/`），提供手机表单采集 + IM 审核的替代前端，不随 `oks` CLI 分发。
