---
title: 摄入协议
nav_order: 2
parent: 参考手册
has_children: true
---

# 摄入协议

Agent 收集来源与证据、填写 Manifest；CLI 校验引用、文件和 provenance，组装 Raw Bundle。协议保存机械处理结果，不替 Agent 判断材料，也不代替人工审核。

- [摄入操作手册](ingest/agent-native-ingest-walkthrough.html)：从来源到 Raw Bundle 的具体步骤与常见错误。
- [协议对象关系](ingest/protocol-objects.html)：SourceEnvelope、EvidenceFragment、EvidenceManifest 与 Raw Bundle 的字段和职责。

图片、音频和视频同时保留原始文件及 OCR、转写等文本结果。召回可通过文本找到相关材料，Agent 按需读取原文件。提取质量、来源主张与最终知识分别记录。

普通收录任务从[收录材料](../usage/ingest.html)开始，无需手工编写协议对象。
