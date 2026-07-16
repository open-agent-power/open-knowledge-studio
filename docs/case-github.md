---
title: 托管你的 GitHub
nav_order: 2
parent: 案例
---
# 托管你的 GitHub

*让代码之外的东西——为什么这么做、试过什么、踩过什么坑——不再随提交记录一起被遗忘；再进一步，让沉淀下来的知识反过来驱动你的下一次贡献。*

Git 记得你**改了什么**，但记不住你**为什么这么改、当时纠结过什么、哪条路走不通**。这些才是最贵的知识。把 GitHub 当成一个 goal 驱动的知识库来托管，让每个项目的思考随代码一起沉淀——**而当策略和教训攒够了，知识库还能反过来自动化你的贡献**。本页后半段就是一次真跑通的演示。

## 设 goal

- **项目 goal**：把某项目做扎实（如"把 X 服务的可观测性补齐"），或把它讲清楚（如"能给别人 5 分钟讲明白架构"）。
- goal 决定哪些提交、issue、讨论值得沉淀，哪些只是日常噪音。

## 收集入 raw/

把持续产生的技术素材汇入 `raw/`：

- 一次有分量的技术决策 → 记下选项、权衡、最终选择。
- 一个难缠的 bug → 记下现象、根因、修法。
- PR review / issue 讨论里的高信号结论 → 存下来。
- 读别人仓库的收获 → 存成笔记。

## 审查沉淀 wiki/

在 goal 约束下 `/promote`：

- **concept**：项目里的核心架构、关键机制。
- **strategy**：验证有效的技术方案、调试套路、贡献策略。
- **anti-pattern**：那些"别再这么干了"的教训。

{: .tip }
失败和踩坑尤其值得沉淀。OKS 的召回引擎**给失败经验额外加权**（见 [召回引擎](recall-engine.md)）——"我们试过 X，没用"往往比又一个成功案例更能防止重蹈覆辙。

## 召回复用

```bash
oks search "为什么 选型 消息队列"
```

- 重构或接手老代码时，召回当初的决策上下文。
- 写 PR 描述、技术文档、复盘时，直接调用已沉淀的结论。
- 让连上 OKS 的 Agent 带着项目历史帮你改代码，而不是每次从零解释背景。

---

## 实战：自动化一次开源贡献

*这不是设想，是 2026-07-16 真跑通的一轮：从召回策略到提出 Apache RocketMQ [PR #10619](https://github.com/apache/rocketmq/pull/10619)，全程由知识库驱动。*

托管到位之后，知识库里攒下的贡献策略（选仓库、静默 merge、CI 排查）和项目教训，就能反过来驱动一次贡献。这条循环被固化在配方 `recipes/oss-contribution-scan.md`，边界由 `goals/oss-contribution.md` 划定：

```
召回策略 → repo 体检 → 拉 issue → Gate1 去重 → 判合法性
   → 打分 → 产出候选 → ⛔人类确认 → 提 PR → 监控 → 复盘回流
```

### 让知识库先开口

动手前先召回，而不是凭直觉：

```bash
oks recall "开源贡献 PR 选仓库 issue 筛选 merge"
```

召回一次性端出积累下来的策略：**选仓库标准**、**静默 merge 模式**（≤40 行 / 1 文件 / 1 issue，实测 75% 直接 merge）、**CI 假阳性排查**，还有项目画像 `rocketmq.md` 里两条血泪教训——

- #10531：没查竞争 PR，提了重复的，被关。
- #10532：提交后不监控，1 天被别人抢先 merge，17 天后才发现。

{: .important }
这两条教训不是背景故事，它们直接改写了这一轮的动作顺序——见下一步。

### Gate 1 去重前置——当场拦下 5 个 no-op

按静默 merge 策略，本该挑"漂亮的小 diff"。但 #10532 的教训要求：**先去重，再打分**。于是对最新一批 issue 逐个查竞争 PR：

| Issue | 查询结果 | 结论 |
|---|---|---|
| #10589 改拼写类名 | 已有 OPEN PR #10590 | 跳过 |
| #10511 Enum 优化 | 已 MERGED #10513 | 已修复 |
| #10464 减少分配 | 已有 OPEN PR #10468 | 跳过 |
| #10613 / #10609 / #10580 / #10575 / #10582 | 全都已有 OPEN PR | 跳过 |
| **#10617 明文 token 泄露** | **无任何 PR** | **唯一活候选** |

热门仓库里"漂亮"的小 diff 几小时内就被别人摘光——这本身是条**新知识**，当场沉淀成了 wiki 策略"热门仓库先去重再 triage"。

{: .tip }
如果先打分后去重，会在 5 个已经没戏的 issue 上白烧预算。教训回流成了流程，流程在下一轮自动生效——这就是"知识库即模型"的训练闭环。

### 合法性 + issue-as-spec

唯一活候选 #10617 恰好是最高 ROI 的一类：

- **维护者已确认**（评论 "Confirmed, verified against the current codebase"）——合法性 100%。
- **issue 即规范**：正文直接给出修法——`.github/workflows/coverage.yml` 里把明文 Codecov token 换成 `${{ secrets.CODECOV_TOKEN }}`，与仓库内其它凭据写法一致。
- **规模**：1 文件、1 行。完美命中静默 merge 模式。

### 人类确认闸门 ⛔

配方在这里**必须停下**。fork、提 PR、评论他人仓库都是不可逆的外部动作——AI 只做到"给出候选 + diff 预览"，是否提交由人拍板。这条边界写在 goal 里，不是可选项。

### 提 PR（确认后）

按 `apache-project-contribution.md` 约定执行：目标分支 `develop`（不是 main）、标题带 `[ISSUE #NNN]` 前缀、单行改动。最终 diff：

```diff
-          token: cf0cba0a-22f8-4580-89ab-4f1dec3bda6f
+          token: ${{ secrets.CODECOV_TOKEN }}
```

产出 → [apache/rocketmq#10619](https://github.com/apache/rocketmq/pull/10619)（OPEN / MERGEABLE / +1 -1）。

{: .warning }
安全类修复有边界感：真正 rotate 泄露的 token、添加 repo secret 是**维护者**的事，贡献者的 PR 只改工作流引用。PR 正文里把这点写清楚，避免越权。

### 监控 + 复盘回流

PR 不是终点。配方 `recipes/oss-pr-monitor.md` 每 2 天查一次状态，防止重蹈 #10532 被抢的覆辙。收敛后跑五维复盘，把新教训沉淀回 wiki，更新 `rocketmq.md` 的 PR 记录表。

### 这一轮沉淀了什么

| 产物 | 类型 | 作用 |
|---|---|---|
| `goals/oss-contribution.md` | goal | 划定循环边界（ODD） |
| `recipes/oss-contribution-scan.md` | 配方 | 11 步可复用扫描循环 |
| `recipes/oss-pr-monitor.md` | 配方 | 提交后监控环 |
| wiki: 热门仓库去重前置 | strategy | 把本轮教训固化 |
| rocketmq.md #10619 记录 | 项目记忆 | 下一轮召回可见 |

知识驱动了循环，循环产出了一个 PR **和**一批新知识，新知识又回到知识库——下一轮会跑得更准。这，就是把 GitHub 贡献"托管"给知识库的完整样子。

## 第一步该做什么

1. 给当前主力项目设一个 goal。
2. 把**最近一次**非显然的技术决策记进 `raw/`，提炼成一条 strategy 或 anti-pattern，搜一次试试。
3. 想体验自动化那半段：挑一个你熟的仓库，只跑到"产出候选清单"为止——先不提 PR，感受 Gate 1 去重帮你省掉了多少白工。

## 接下来读哪里

* **[自动驾驶](autonomous.md)**：上面这轮属于 L2——AI 触发、人类逐条确认；看看 L0-L5 各是什么。
* **[托管你的科研](case-research.md)**：论文与实验的沉淀方式。
* **[召回引擎](recall-engine.md)**：为什么失败经验会被优先召回。

---

{% include comments.html %}
