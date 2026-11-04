---
title: 视频研究与待审核知识
nav_order: 1
parent: 使用案例
---

# 视频研究与待审核知识

研究问题是：**Kimi 是否适合长文档分析？哪些结论来自视频，哪些还需要官方资料或 benchmark 验证？**

本案例的两个来源已形成 Raw Bundle，并生成待审核候选（Candidate）。正式实例尚未将候选晋升为 Wiki；下面保留这一进度，不给出产品能力结论。

## 收录来源

使用的材料：

- [B 站视频 BV1CDNd65EDc](https://www.bilibili.com/video/BV1CDNd65EDc/)
- [YouTube 视频 Q4LoxsIwriA](https://www.youtube.com/watch?v=Q4LoxsIwriA&t=45s)

B 站来源没有可直接使用的平台字幕，实际路径为本地媒体 → 音频 → 本地 ASR → 关键帧 → Raw Bundle。YouTube 来源使用用户提供的转写文本。ASR 的同音词和专有名词错误保留在 Raw，修正意见另写候选。

<figure class="oks-evidence oks-evidence-panel">
  <div class="oks-evidence-viewport">
    <img src="../assets/hosted-learning/02-evidence-raw.png" alt="宿主 DSH 的 OKS 面板展示两个来源形成的 Raw Bundle 列表">
  </div>
  <figcaption>来源与提取结果已保存。Raw Bundle 记录材料，不证明材料中的主张为真。<a href="../assets/hosted-learning/02-evidence-raw.png">查看原图</a></figcaption>
</figure>

## 提出候选

Agent 将视频作者主张、提取证据和自己的推断分开，列出还需核验的模型参数、上下文长度、价格、长文档分析效果及 ASR 内容。

<figure class="oks-evidence oks-evidence-panel">
  <div class="oks-evidence-viewport">
    <img src="../assets/hosted-learning/03-candidate-review.png" alt="宿主 DSH 的 OKS 面板显示待审核候选、证据范围和待核验主张">
  </div>
  <figcaption>候选保留来源与不确定项，等待人工审核。<a href="../assets/hosted-learning/03-candidate-review.png">查看原图</a></figcaption>
</figure>

审核者需要对照原视频修正转写，将产品参数与官方资料核对，并用固定数据集检验能力判断。只有明确接受的内容才能进入 Wiki；与旧知识的关系由审核结果决定。

## 检查召回边界

隔离验收副本曾测试 Promote 与 Recall 的界面流转，不能替代正式实例的人审。下图中已有 Kimi 页面仅覆盖视频中的模型介绍，不足以支持“智能文档分析系统”的设计结论，其余无关命中也被排除。

<figure class="oks-evidence">
  <div class="oks-evidence-viewport">
    <img src="../assets/hosted-learning/04-recall-boundary.png" alt="召回结果指出已审核知识不足以支持系统设计结论，并排除无关命中">
  </div>
  <figcaption>召回结果需要核对适用范围。证据不足时，Agent 应说明缺口。<a href="../assets/hosted-learning/04-recall-boundary.png">查看原图</a></figcaption>
</figure>

## 结果与限制

| 项目 | 状态 |
|---|---|
| 本地视频、ASR、关键帧进入 Raw Bundle | 已记录 |
| 用户提供的 YouTube 转写进入 Raw Bundle | 已记录 |
| 两个来源生成候选 | 已记录，待人审 |
| 候选自动进入 Wiki | 不允许，也未发生 |
| Kimi 参数、价格和能力主张 | 待官方资料复核 |
| 长文档分析效果 | 待固定数据集 benchmark |
| DSH Promote / Recall 界面流转 | 在隔离副本中验证，不代表正式实例完成审核 |

## 继续这项研究

下一步补充官方技术报告或 benchmark，围绕同一问题提出新候选，说明它如何补充、印证或质疑已有内容，再由人审核。

用自己的问题尝试时，从一份短材料开始，按[第一次知识循环](../first-knowledge-loop.html)完成收录、审核和后续引用。
