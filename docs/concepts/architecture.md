---
title: 架构总览
nav_order: 2
parent: 工作原理
---

# 架构总览

OKS 的主线是：保存材料、提出候选、由人审核，再把已确认的知识带回后续任务。Agent 负责组织工作，`oks` CLI 负责文件操作与查询。

## 知识怎样流转

{% include knowledge-cycle.html %}

审核是材料与长期知识之间的分界。拒绝或暂不决定的候选不会进入 Wiki；来源中的主张也不会因为保存成功就变成事实。

## 谁负责什么

<div class="oks-architecture" role="group" aria-label="人、Agent 与 OKS 的职责">
  <div><h3>你</h3><p>确定目标与边界<br>审核知识，决定是否保留</p></div>
  <div><h3>Agent</h3><p>读取 Skill、处理材料<br>提出候选，查询并引用知识</p></div>
  <div><h3>OKS</h3><p>提供 CLI 与文件协议<br>保存来源、知识和审核记录</p></div>
</div>

`oks` 核心不调用模型 API。网页、PDF、音视频等处理能力由 Agent 按实际环境选择；所需工具可以使用自己的 API。CLI 不会代替人批准候选，也不保证 Agent 已执行某个任务。

## 文件保存在哪里

| 目录 | 保存什么 | 后续怎样使用 |
|---|---|---|
| `raw/` | 原始材料、出处和机械提取结果 | 回到来源核对证据 |
| `drafts/` | Agent 提出的待审核知识 | 接受、修改、拒绝或暂不决定 |
| `wiki/` | 人工审核后的知识 | 供后续任务查询与引用 |
| `profiles/` | 用户、项目背景与当前目标 | 帮助限定任务范围 |
| `mail/` | 交接、回复和阻塞等协作记录 | 跨会话或 Agent 继续工作 |

实例配置放在 `settings/`；Schema由OKS工具统一维护，不要求实例复制`_meta/`。Trace 保存执行证据；这些记录与 Mail 都不能自动升级为长期知识。

## 知识如何回到任务

Agent 查询时，OKS 根据实例配置检索相关知识，并结合范围、目标与召回规则返回结果。Agent 再把结果用于当前任务，说明引用来源和适用范围。相关性影响排序，不代表内容必然正确。

显式查询可以直接使用；自动注入需要安装并验证对应宿主的 Hook。新实例模板使用 FTS5，具体后端与参数以当前实例的 `settings/recall.yaml` 为准。算法细节见[召回引擎](../algorithms/recall-engine.html)。

## 扩展放在主线之外

Mail 保存跨执行边界的协作事实；是否唤醒 Agent、创建会话或运行任务，由独立的 Host Adapter 负责。飞书等集成可以提供采集或移动审核入口，不改变人工审核规则。

下一步可阅读[收录材料](../usage/ingest.html)、[审核知识](../usage/review.html)或[查询与引用](../usage/recall.html)。需要接入协作时，再查看[协作边界](product-boundary.html)与 [Mail 协议](../reference/mail-protocol.html)。
