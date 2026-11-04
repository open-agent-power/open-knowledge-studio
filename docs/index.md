---
title: 认识 OKS
nav_order: 1
---

<div class="oks-intro">
  <h1>让这次确认的经验，<br>用在下一次任务里。</h1>
  <p class="oks-lead">Open Knowledge Studio（OKS）是给 Agent 使用的文件化知识工作空间。它保存原始材料、待审核提议和你确认的知识，供后续任务查找与引用。</p>
  <div class="oks-actions">
    <a class="btn btn-primary" href="{{ '/start-here.html' | relative_url }}">开始使用</a>
    <a href="{{ '/first-knowledge-loop.html' | relative_url }}">已安装？完成第一次知识循环 →</a>
  </div>
</div>

## 从保存材料，到真正用上

你整理了一份项目约定，希望换一个会话后，Agent 仍能按这份约定工作。把材料交给 Agent，审核它整理的经验；下一次任务中，再要求它查询并说明引用了哪条知识。

{% include knowledge-cycle.html %}

来源保存在 `raw/`，待审核提议放在 `drafts/`，你明确接受的知识进入 `wiki/`。材料和候选都不会自动变成已确认知识。

## 适合用来做什么

- **整理学习材料**：保留来源，把值得复用的内容整理成待审核知识。
- **延续项目经验**：保存你确认的约定、做法和失败教训，供后续任务查询。
- **继续未完成的研究**：保留已有材料与判断范围，补充证据后再更新知识。

你提供材料、方向和审核决定；Agent 负责收录、整理与查询；OKS 保存这些文件和记录。它需要配合能读取文件、执行命令的 Agent 使用。

## 从一份短材料开始

先[安装并创建独立知识库](installation.html)，再跟着[第一次知识循环](first-knowledge-loop.html)保存一份样例、审核一条候选，并在新会话中检查实际引用。

已经在使用？按任务查阅[收录材料](usage/ingest.html)、[审核知识](usage/review.html)和[查询与引用](usage/recall.html)。想先看已有记录，可以阅读[学习研究案例](oh-my/study.html)；它明确保留了尚待审核的部分。

需要了解设计时，再阅读[工作原理](concepts/)；命令、配置与排错见[参考手册](reference/)。
