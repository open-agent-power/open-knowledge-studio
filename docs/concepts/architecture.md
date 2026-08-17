---
title: 架构总览
nav_order: 3
parent: 概念
---

# 架构总览

OKS 三层架构：**摄入流水线 → 知识桶 → 召回注入**。

```mermaid
flowchart TD
    subgraph L1["第 1 层 · 摄入流水线 Ingestion"]
        direction LR
        src["① Source<br/>文件 / URL / 媒体 / 平台"]
        mod["② 模态判定<br/>text · pdf · office · image · web · audio · video"]
        prov["③ 选 Provider（17 个）<br/>text-read · pdf-lite · rapidocr · http-fetch · yt-dlp …"]
        frag["④ EvidenceFragment × N"]
        man["⑤ EvidenceManifest<br/>steps + artifacts + SHA-256"]
        rc["⑥ oks raw-commit<br/>fail-closed：Schema + provenance + 哈希"]
        rb["⑦ Raw Bundle v0.2<br/>bundle.json · content.md · source/ · derived/"]
        cand["⑧ Candidate<br/>A / B / C 分级，A 级才写"]
        hr["⑨ Human Review<br/>promote / edit / reject"]
        wiki["⑩ Wiki"]
        src --> mod --> prov --> frag --> man --> rc --> rb --> cand --> hr --> wiki
    end

    subgraph L2["第 2 层 · 知识桶 + 基础设施（7 桶）"]
        direction LR
        prof["profiles/<br/>画像：users · projects · goals · recipes · registry"]
        raw["raw/<br/>原始材料，日期归档"]
        wiki2["wiki/<br/>语义知识，22 domain，带衰减曲线"]
        drafts["drafts/<br/>候选，人审门控"]
        mail["mail/<br/>协调：inbox / sent<br/>（协调桶，不是知识桶）"]
        settings["settings/<br/>配置：recall.yaml · input-sources.json"]
        meta["_meta/<br/>schema：协议形状契约"]
    end

    subgraph L3["第 3 层 · 召回 + 注入 Recall"]
        direction LR
        q["① query<br/>用户 prompt 或工具操作"]
        reg["② registry 查 scope / goal<br/>agent_id + cwd"]
        score["③ 6+1 因子评分<br/>token overlap + substring + topic trace + type boost + review bonus + memory curve + goal boost"]
        backend["④ search backend<br/>native 默认 · fts5 = SQLite + BM25 · fusion = native + fts5"]
        filt["⑤ floor 过滤 + cooldown 去重"]
        inj["⑥ 注入上下文<br/>recalled-memory"]
        q --> reg --> score --> backend --> filt --> inj
    end

    wiki -.->|晋升| wiki2
    raw -.->|episodic 召回| q
    wiki2 -.->|semantic 召回| q
    hr -.->|写 human_reviewed_at| wiki2
```

## 关键约束

- 摄入 **fail-closed**：Schema + provenance + SHA-256 校验，证据不足即拒绝，不把「Agent 自称存了」当证据。
- 信任语义：`[verified]` 只来自 trace 证据或 `human_reviewed_at`（人审时间戳），绝不来自使用次数。
- 两条 hook：`UserPromptSubmit`（用户说话 → recall 注入）与 `PostToolUse`（工具调用 → recall 补位 + 文件冲突检测，写 mail/）。
