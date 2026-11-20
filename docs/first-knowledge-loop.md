---
title: 第一次实践
nav_order: 2
parent: 开始使用
---

# 第一次实践：从 Source 到 Recall

这次实践用一段短文本走完 `Source → Raw → Candidate → 人工审核 → Wiki → Recall`。你会看到每一步产生了什么，以及怎样证明 Agent 实际完成了操作。

开始前，先完成[安装与创建知识库](installation.html)。让 Agent 报告当前个人知识库的实际路径，并运行 `oks status`。后面的所有步骤都应使用同一个知识库。

本页中的“示例项目”只是教程范围，不代表你的真实项目约定。第一次实践通过对话明确要求 Recall，不依赖 Hook。

## 1. 保存 Source，生成 Raw

输入是一段带有明确范围的 Source。把下面的内容交给 Agent：

```text
请把下面的教程 Source 收录到当前 OKS 知识库，保存原文和出处。
完成后打开生成的 Raw，报告保存位置和处理状态。
如果材料足以支持可复用结论，请另外生成一个 Candidate，
但不要执行 promote，也不要把它直接写成 Wiki。

标题：示例项目的问题说明约定
来源：本次 OKS 入门教程
适用范围：仅限示例项目

提交问题说明时，应包含复现步骤、预期结果和实际结果。
本材料没有规定问题优先级、负责人或修复时限。
```

Agent 应完成两类动作：调用 OKS 保存 Source 的原文、出处和处理状态；再根据实际材料编写 Candidate。生成 Candidate 是 Agent 的判断工作，不是 `raw-commit` 自动得出的知识结论。

这一阶段的产物应包括：

| 产物 | 状态 | 应包含什么 |
|---|---|---|
| Raw | 已保存的材料 | 原文、教程出处、适用范围和实际处理状态 |
| Candidate | 待人工决定 | 三项问题说明要求、示例项目范围、对应 Raw 证据 |

验收时，让 Agent 打开 Raw 和 Candidate 的实际文件。Raw 应保留完整原文；Candidate 不应增加“一天内修复”等 Source 没有支持的内容，也不应已经出现在 Wiki 中。某个采集或提取步骤如果标记为 `partial`、`failed` 或 `skipped`，不能改写成 `complete`；`failed` 或 `skipped` 时可能没有可用的 Raw，应先根据原始错误处理失败原因。

## 2. 审核 Candidate

人工审核的输入是 Candidate 及其 Raw 证据。先要求 Agent 展示当前版本：

```text
请展示刚才生成的 Candidate 和对应 Raw。
列出 Candidate 中的关键主张，分别标明证据位置、适用范围和仍未得到支持的内容。
先不要改变状态，等我决定。
```

确认 Candidate 只表达 Source 支持的内容后，你可以选择接受、要求修改、拒绝或暂缓。要继续完成教程，可以明确接受当前版本：

```text
我接受这个 Candidate 的当前版本，适用范围保持为“示例项目”。
请按 OKS 的审核流程 promote，并展示生成的 Wiki 和审核记录。
```

Agent 应通过审核流程保存决定，而不是只把文件移动到 `wiki/`。本教程中新生成的 Wiki 应能回查 Candidate、Raw 和本次人工决定。仅仅位于 `wiki/` 目录，不能单独证明某个旧文件具有有效审核记录。

在命令层，Agent 会先用 `oks drafts get <slug>` 读取待审核版本，接受后再执行 `oks drafts promote <slug>`。`promote` 会为该 Candidate 的当前版本保留审核证据，并创建带 `human_reviewed_at` 的 Wiki。

验收时检查：

- Wiki 正文仍只包含 Source 支持的三项要求和适用范围。
- 审核记录指向刚才查看的 Candidate 版本，并记录了接受决定。
- Wiki 包含 `human_reviewed_at` 以及可回查的 Candidate 信息。
- Raw 仍然保留，没有被 Wiki 摘要替换。

如果选择拒绝或暂缓，Candidate 不应成为本教程的新 Wiki。这也是有效的审核结果，但无法继续验证下一步的 Wiki Recall。

## 3. 在新会话中执行 Recall

开启一个新会话，让 Agent 先确认当前知识库，再查询一个需要这条知识的新问题：

```text
请先报告当前 OKS 个人知识库的实际路径，并确认它与上一步相同。
然后对下面的问题执行 Recall，打开命中的 Wiki 和必要的 Raw 来源：

示例项目中，有人只报告“导出失败”。提交问题说明前还要补充什么？

回答时说明实际使用了哪个 Wiki、为什么适用于示例项目，
并给出对应 Source。没有证据支持的内容不要补充。
```

Agent 应先运行 Recall，再读取命中的内容并判断适用范围。预期回答是补充复现步骤、预期结果和实际结果。它还应展示实际命中的 Wiki，以及 Wiki 关联的 Source。

命令层的查询可以写成：

```bash
oks recall "示例项目中，提交问题说明前还要补充什么" --knowledge-only --explain
```

验收时不要只看最终答案。即使 Agent 恰好知道这三项，也不能证明它使用了 OKS。需要同时确认：

- Recall 的查询和命中结果可以查看。
- 命中的是上一步接受的 Wiki，而不是未审核 Candidate。
- Agent 明确说明它在回答中使用了哪一条内容。
- 引用能回到本教程的 Source，适用范围仍是示例项目。

再问一句“示例项目承诺多久修好？”。Source 没有提供修复时限，Agent 应说明证据不足，而不是从常识补出答案。

## 完成标准

下面五项都能核对时，这次实践完成：

1. Source 的原文和出处保存在 Raw 中。
2. Candidate 与 Raw 分开保存，并保留证据和适用范围。
3. 人工决定通过审核流程记录，接受的版本形成 Wiki。
4. 新会话连接同一个知识库，并实际执行 Recall。
5. Agent 展示了命中的 Wiki、实际使用内容和对应 Source。

## 遇到问题

| 现象 | 先检查什么 |
|---|---|
| Raw 没有保存 | Agent 是否实际调用了收录流程；来源和处理状态是否完整 |
| Candidate 出现无依据内容 | 列出关键主张并对照 Raw，删除推断或补充证据 |
| 接受后找不到 Wiki | 是否执行了 promote；审核决定和目标知识库是否正确 |
| 新会话查不到内容 | 两次会话是否使用同一知识库；Wiki 是否进入当前 Recall 范围 |
| 回答正确但没有命中记录 | Agent 可能没有执行 Recall，要求展示查询和命中结果 |

详细排查见[故障排除](reference/troubleshooting.html)。完成练习后，可以用自己的材料继续[收录材料](usage/ingest.html)，或阅读[各部分怎样配合](concepts/architecture.html)。
