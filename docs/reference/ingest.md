---
title: 材料收录协议
nav_order: 2
parent: 参考手册
has_children: true
---

# 材料收录协议

收录协议负责把一个 Source 及其实际提取结果保存为 Raw Bundle。它记录来源、执行工具、产物、证据位置和处理状态，并由 CLI 检查文件与声明能否对应。

协议到 Raw Bundle 为止。它不会判断来源中的说法是否正确，也不会自动生成 Candidate、批准 Candidate 或创建带审核记录的 Wiki。

```text
Source
  → oks ingest prepare
  → Provider 或 Agent 取得内容
  → Evidence Fragment
  → Evidence Manifest
  → oks raw-commit
  → Raw Bundle

之后才由 Agent 判断是否提出 Candidate，并交给人审核。
```

## 四类对象各自记录什么

| 对象 | 作用 | 主要创建者 |
|---|---|---|
| Source Envelope | 标识来源、访问方式、采集时间、内容哈希和处理策略 | `oks ingest prepare` |
| Evidence Fragment | 记录一次 Provider、工具或人工处理取得的产物和证据 | CLI 生成骨架，Agent 按实际执行补充 |
| Evidence Manifest | 汇总本次收录实际采用的证据、步骤和总体完整性 | CLI 生成骨架，Agent 按实际结果完成 |
| Raw Bundle | 保存原始材料、派生产物、证据记录和处理报告 | `oks raw-commit` 校验后组装 |

对象字段和文件关系见[协议对象与状态](ingest/protocol-objects.html)。

Recipe 与 Connector 解决的问题不同。Recipe 是某类材料的处理要求，列出需要哪些证据、可以怎样降级，以及哪些 `complete_when` 条件算完成。Connector 是随 OKS 发布的采集与格式转换组件，`oks ingest run` 用它处理支持的来源。Recipe 规定验收条件，Connector 负责实际机械处理；两者都不会判断来源中的主张是否正确。

## 不要混用不同层的状态

| 所属层 | 状态 | 回答的问题 |
|---|---|---|
| Evidence Manifest | `complete`、`partial` | 这份材料是否达到 Recipe 规定的总体证据条件 |
| Fragment | `succeeded`、`partial`、`failed` | 某一次处理尝试取得了什么结果 |
| Manifest 中的步骤 | `succeeded`、`partial`、`degraded`、`failed`、`skipped` | 某项能力是否按计划执行，以及是否发生降级 |
| Raw Bundle | `complete`、`partial`、`failed` | 保存后的材料包记录了什么处理结果 |
| Candidate 审核 | pending、promoted、rejected 等工作流结果 | 人是否接受了某个 Candidate 版本 |

`complete` 只说明协议规定的证据条件已满足，不表示来源可信、提取无误或结论已经审核。一次步骤失败也不一定让 Manifest 变成 `partial`，例如平台字幕失败但 ASR 已取得可用转写，仍可能满足视频 Recipe 的完成条件。

## 两种命令路径

| 路径 | 适合什么情况 | 结果 |
|---|---|---|
| `oks ingest run <source>` | 使用内置 Connector 处理支持的来源 | 直接获取并转换材料；不会 Promote Wiki |
| `oks ingest prepare <source>` + `oks raw-commit <manifest-dir>` | Agent 需要选择 Provider、保留多步证据或排查协议问题 | 生成并校验标准协议对象，再组装 Raw Bundle |

普通用户从[收录材料](../usage/ingest.html)开始，让 Agent 选择路径。需要手工检查执行过程时，再阅读[收录操作手册](ingest/agent-native-ingest-walkthrough.html)。
