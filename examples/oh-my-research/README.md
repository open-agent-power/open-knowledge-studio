# 托管你的研究

*让论文、实验、讨论和失败经验围绕一个真实问题积累，而不是散落在 PDF、聊天记录和临时笔记里。*

研究案例遵循 OKS 的最短闭环：

```text
真实问题 → 收录资料 → Candidate → Human Review → Wiki → Recall
```

## 先确定问题

用一个能够被证据回答的问题作为 Goal，例如：

- 某个方法在目标场景下是否真的更好？
- 两种技术方案的边界分别是什么？
- 一次失败实验揭示了什么约束？

问题决定资料范围和停止条件。没有边界的“把所有论文都存进去”只会制造新的资料堆积。

## 收录真实资料

优先使用 Agent 路径：

```text
/ingest <你的论文、网页、实验记录或项目文档>
```

没有 Agent 时使用当前 CLI：

```bash
oks ingest prepare <source>
oks ingest run <source>
```

Raw 保留来源和机械提取结果；缺失、失败和部分完成必须按真实状态保存，不能为了生成报告
假装资料完整。

## 审核研究判断

研究 Candidate 至少区分三类内容：

- 可定位到来源的事实。
- 基于事实形成的推断。
- 人类最终接受、编辑或拒绝的判断。

```bash
oks drafts list
```

通过 `/promote` 完成人审。Wiki 保存值得复用的结论，Raw 和审核记录保留“为什么这样判断”。

## 精简真实案例：Kimi K3 研究

这次案例在 2026-07-30 以“评估 Kimi K3 在长程软件工程场景中的能力边界”为 Goal，
收录了官方博客、API Quickstart、模型列表和帮助页面等六份资料。运行产物进入独立 OKS
实例，没有把个人 Raw、Candidate 或 Wiki 提交到框架仓库。

研究过程产生了三类可审核判断：

- 架构与 API 描述能否定位到已摄入的文字证据。
- 官方能力声明与实际独立测试之间必须区分。
- 图片中的基准、架构图和案例截图没有被机械提取时，应保留证据缺口。

这次运行也明确记录了限制：没有发起 K3 API 调用，因此没有独立测量延迟、吞吐、输出质量
或规模化成本；机械提取保留了图片 URL，但没有读取图片中的完整基准数据。它是一份对官方
材料的可追溯整理，不是独立模型评测。

使用的主要来源：

- `https://www.kimi.com/blog/kimi-k3`
- `https://platform.kimi.ai/docs/guide/kimi-k3-quickstart`
- `https://platform.kimi.ai/docs/api/quickstart`
- `https://platform.kimi.ai/docs/models`
- `https://www.kimi.com/help/getting-started/agentic-chat`
- `https://www.moonshot.ai/`

这个案例保留的是研究方法和证据边界，而不是一张会快速过期的模型参数、价格或基准表。

## 可复制的示例 Goal

`goal.md` 是一个可复制的示例 Goal——用 OKS 审查 OKS 自己的 Core 与 Connector 职责边界；
`sample/research-question.md` 是研究问题模板（问题 → 证据范围 → 必须回答 → 输出要求）。
复制到你自己的实例后，先改研究问题、`owner` 和资料范围，再把 `status` 改为 `active`。

## Recall 验证

隔一段时间，在真实任务里重新提问：

```bash
oks recall "Kimi K3 研究中哪些结论没有独立测试"
oks recall "上次模型研究遗漏了哪些图片证据"
```

有用的 Recall 应当减少一次重复阅读、重复实验或重复争论。找不到、只找到一部分或找到
错误结论，都应作为真实失败样本保留。

## 接下来读哪里

- [收录资料](../../docs/reference/ingest.md)
- [审核 Candidate](../../docs/review-candidates.md)
- [Recall](../../docs/recall.md)
