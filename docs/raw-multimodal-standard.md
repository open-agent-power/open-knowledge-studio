---
title: Raw 多模态协议入口
nav_order: 22
parent: 参考
---

# Raw 多模态协议入口

Studio 不再维护另一份多模态字段标准。仓库级机器可读事实源位于 `schemas/`，
运行时使用包内镜像 `knowledge_studio/schemas/` 做强制校验：

- `schemas/capture-envelope.schema.json`
- `schemas/capability-manifest.schema.json`
- `schemas/processing-run.schema.json`
- `schemas/raw-bundle-v0.2.schema.json`

当前 Bundle 版本是 `raw-multimodal/v0.2`。Studio 只负责 Capture 编排、Candidate、人工审核、Wiki 晋升与召回；来源获取后的机械解析、证据定位、质量状态和失败事实由 connector 负责。

设计边界与迁移历史见：

- [架构设计](architecture.md)

旧版 v0.1 长篇字段示例已移除，避免与 connector 的 Schema 和 Capability Manifest 发生双重事实源污染。

---

{% include comments.html %}
