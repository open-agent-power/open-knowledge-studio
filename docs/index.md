---
title: 认识 OKS
nav_order: 1
---

<div class="oks-intro">
  <h1>把这次任务的来源和结论，<br>留给下一次任务。</h1>
  <p class="oks-lead">Open Knowledge Studio（OKS）是一套供 Agent 使用的文件化知识系统。Agent 是当前理解任务、读取材料并调用工具执行工作的主体，例如 Claude Code 或 Codex。OKS 为 Agent 提供材料保存、候选审核、知识查询和过程记录能力。</p>
  <div class="oks-actions">
    <a class="btn btn-primary" href="{{ '/start-here.html' | relative_url }}">开始使用</a>
    <a href="{{ '/first-knowledge-loop.html' | relative_url }}">已经接入？完成第一次实践 →</a>
  </div>
</div>

## OKS 解决什么问题

一次任务结束后，结论往往只留在聊天记录里。换一个会话或换一个 Agent，同样的背景、判断和失败经验又要重新说明。OKS 把这些内容保存在独立知识库中，并保留它们从哪里来、是否经过人工决定，以及后来怎样被查到和使用。

OKS 不会把一份材料直接当成知识。产品和命令中的常用流程是 `Source → Raw → Candidate → 人工审核 → Wiki → Recall`：

- Source 是你交给 Agent 的文件、网页、文本或对话，Raw 保存原文、出处和实际提取结果。
- Candidate 是 Agent 根据材料提出的可复用内容，仍在等待人决定。
- 人工审核决定接受、修改、拒绝或暂缓哪一个版本。
- Wiki 保存准备供后续任务查找的知识。对于新产生的内容，应能回查对应来源和审核记录。
- Recall 根据当前问题查找可能相关的内容。命中结果还要由 Agent 判断是否适用于当前任务。

Raw 保存成功不表示材料中的说法正确；Candidate 写得完整不表示已经接受；Recall 命中也不表示内容已经在任务中采用。

## 谁负责什么

| 参与者或组件 | 职责 |
|---|---|
| 你 | 提供目标和材料，检查 Candidate，决定哪些内容可以保留 |
| Agent | 理解任务、读取来源、整理 Candidate、调用 OKS，并说明实际使用了哪些知识 |
| `oks` CLI | 创建和维护知识库，校验并保存文件，记录审核决定，执行 Recall |
| 知识库 | 用普通文件保存 Raw、Candidate、Wiki、Profile、Goal 和运行记录 |
| Skill | 告诉 Agent 怎样按 OKS 的规则完成某类操作，可包含脚本和配套资源 |
| Hook | 在宿主支持时自动触发 Recall 或检查，是可选设置 |
| Studio | 在本地网页中浏览和维护知识库，是可选界面 |

Agent 负责理解和执行，CLI 负责可校验的文件操作，知识库保存结果。OKS 本身不会理解当前任务，也不会自动把文件变成知识。Skill 是 Agent 的操作说明，不是后台服务；没有配置 Hook 或 Studio 时，仍然可以直接要求 Agent 查询知识。

## 可以用来做什么

- 保存研究材料，并区分来源原话、Agent 的判断和仍需核实的内容。
- 记录项目约定、解决办法和失败教训，在相似任务中重新查找。
- 维护个人和项目背景，让 Agent 知道当前问题的适用范围。
- 留下交接、执行和评测记录，方便之后核对任务进行到哪里。

第一次使用先阅读[开始使用](start-here.html)。完成安装和知识库选择后，跟着[第一次实践](first-knowledge-loop.html)保存一份材料、审核一个 Candidate，再在新会话中执行 Recall。

已经在使用时，可以直接按任务查看[收录材料](usage/ingest.html)、[审核 Candidate](usage/review.html)和[查询与引用](usage/recall.html)。系统组成和数据流见[工作原理](concepts/)，命令与协议见[参考手册](reference/)。
