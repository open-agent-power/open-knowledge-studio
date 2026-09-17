<div align="center">

<img src="images/oks-logo-readme.png" width="360" alt="Open Knowledge Studio">

### Open Knowledge Studio：面向编码 Agent 的文件化外部记忆

[English](README.md) / 中文

[![](https://img.shields.io/github/v/release/open-agent-power/open-knowledge-studio?color=369eff\&labelColor=black\&logo=github\&style=flat-square)](https://github.com/open-agent-power/open-knowledge-studio/releases)
[![](https://img.shields.io/github/stars/open-agent-power/open-knowledge-studio?labelColor\&style=flat-square\&color=ffcb47)](https://github.com/open-agent-power/open-knowledge-studio)
[![](https://img.shields.io/github/issues/open-agent-power/open-knowledge-studio?labelColor=black\&style=flat-square\&color=ff80eb)](https://github.com/open-agent-power/open-knowledge-studio/issues)
[![](https://img.shields.io/badge/license-MIT-white?labelColor=black\&style=flat-square)](./LICENSE)
[![](https://img.shields.io/github/last-commit/open-agent-power/open-knowledge-studio?color=c4f042\&labelColor=black\&style=flat-square)](https://github.com/open-agent-power/open-knowledge-studio/commits/main)

[文档站](https://open-agent-power.github.io/open-knowledge-studio/) · [实验数据](#实测效果) · [复现](#复现) · [更新日志](./CHANGELOG.md)

</div>

***

## 什么是 Open Knowledge Studio

Open Knowledge Studio（OKS）是一个开源的**文件化外部记忆**，面向编码 Agent。它不靠黑盒向量库，而是把知识存成一个可人工审计、git 版本化的文件系统——`profiles/`、`raw/`、`wiki/`、`drafts/`、`mail/`——Agent 用 `oks recall`、`oks wiki list`、`oks trace` 来浏览。内容经过一条可审计的流水线（来源 → 证据片段 → Manifest → Raw → Candidate → 人工审核 → Wiki），像真实记忆一样衰减，按需召回。完整介绍：[从这里开始](https://open-agent-power.github.io/open-knowledge-studio/)。

```
你的来源 → Candidate → 人工审核 → Wiki → 召回 → 注入 Agent 上下文
```

### OKS Mail 是协作侧车

Mail 只保留需要跨 Session、Agent、Host 或机器留下的协作事实：交接、结果、阻塞、批注，以及指向现有 Wiki/Candidate/Trace 的引用。它不是第二知识库、任务引擎、聊天替代品或唤醒服务。Agent 可以通过 Skill 写入、读取和回复；没有独立 Host Adapter 时，这不代表会启动进程、创建 Session 或完成任务。Thread 是这些记录的持久上下文，不是工作流状态。详见[产品边界](https://open-agent-power.github.io/open-knowledge-studio/concepts/product-boundary/)和 [Mail 协议](https://open-agent-power.github.io/open-knowledge-studio/reference/mail-protocol/)。

## 为什么选 Open Knowledge Studio

- **一套文件系统装下所有记忆。** profiles、raw、wiki、drafts、mail 各占一个目录，有不同的信任边界。Agent 确定性地定位和操作上下文，就像开发者操作文件一样。→ [架构总览](https://open-agent-power.github.io/open-knowledge-studio/concepts/architecture/) · [宪法](https://open-agent-power.github.io/open-knowledge-studio/concepts/constitution/)
- **人工审核是唯一入口。** 原始材料 ≠ 结论，Candidate ≠ 长期知识。任何东西都不会自动晋升到 Wiki——每条持久记忆都经过人审。→ [审核候选](https://open-agent-power.github.io/open-knowledge-studio/usage/review/)
- **三层召回压制幻觉。** Node-BM25 召回*什么*匹配，Soul Boost 重排*什么到达* Agent（反模式 ×1.5、review bonus、generic 降权），Memory Curve 评分*多新鲜*——所以置信度永远不会盖过事实。→ [召回引擎](https://open-agent-power.github.io/open-knowledge-studio/algorithms/recall-engine/)
- **知识像真实记忆一样衰减。** 不用的页面沿着 hot → warm → cold → evictable 降温；用过的页面会浮现。`importance × e^(-λ×days) + ln(1+access) + pin_bonus`。→ [衰减系统](https://open-agent-power.github.io/open-knowledge-studio/algorithms/decay-system/)
- **每次召回都可观测。** 每个查询都保留各因子分数和匹配路径（`oks recall "<q>" --explain`）；每次注入都记到 `records/inject.jsonl`。结果看着不对时，你能看到是哪个因子产生的。→ [评估](https://open-agent-power.github.io/open-knowledge-studio/algorithms/recall-evaluation/)

各部分怎么拼一起：[架构](https://open-agent-power.github.io/open-knowledge-studio/concepts/architecture/)。产品与协作边界见[产品边界](https://open-agent-power.github.io/open-knowledge-studio/concepts/product-boundary/)。设计背后的思考：[CONSTITUTION.md](./CONSTITUTION.md)。

```
open-knowledge-studio/
├── profiles/              # 团队、用户、项目、recipe、goal —— 稳定上下文
├── raw/                    # 人工收集的来源，按日期 {YYYY}/{MM}/{DD}/{source}/
├── wiki/                   # 人审过的记忆：concept、strategy、anti-pattern
├── drafts/                 # Candidate 提议，待审
├── mail/                   # agent 间通信：inbox/ + sent/ —— 不是长期知识
├── settings/               # recall.yaml（唯一参数源）、工具注册表
├── _meta/                  # schema 层：原始证据、召回 case、trace 事件
└── records/                # 版本验收证据 + 实验运行结果
```

三层召回：

- **Node-BM25（召回）**：SQLite FTS5 + BM25，按 markdown `##` 标题分 node，列权重 title 5× > tags 3× > body 1× > code 0.5×。召回过程零文件读（abstract 零读，v0.6.10）。
- **Soul Boost（注入）**：type_boost + review_bonus + generic_demotion 在 hit 到达 Agent 前重排——失败教训排得比通用 concept 高。
- **Memory Curve（衰减）**：类型差异 λ、access_count ln 增长、pin_bonus——不依附任何 backend，在 `store.py` 跑。

## 实测效果

OKS 在一个 50-case 语义改写数据集（严格精确 slug 匹配）和公开 LoCoMo 长对话评测上做过评估。完整结果和复现脚本在 [docs/algorithms/recall-evaluation.md](./docs/algorithms/recall-evaluation.md)；数据集和 run JSON 在 [./records/experiments](./records/experiments)。

### 三层消融 —— 50-case，严格精确 slug 匹配

查询是语义改写——query 不含 slug 的关键词，测试同义词/改写召回。匹配是严格的：期望 slug 必须出现在 top-k。

<img src="images/ablation-triple-layer.svg" alt="三层消融。fts5 R@1=0.825 R@3=0.925 MRR=0.907；fusion 0.805/0.905/0.900；native 0.525/0.647/0.630。">

- **Node-BM25 全面碾压 page-level 6+1**：R@1 +57%（0.525→0.825），MRR +44%（0.630→0.907）。多词同段 BM25 高分，语义改写召回精准。
- **Soul Boost 必须在注入层，不在召回层**：native 6+1 的 memory curve / goal boost / review bonus 放到召回层 re-rank *反而降精度*（R@1 0.825→0.805）——不相关 page 高分挤掉精确命中。
- **fts5 还更快**：93ms vs native 137ms vs fusion 226ms。SQLite 持久索引比实时遍历快。

### Embedding backend —— 语义召回对比（v0.6.2）

<img src="images/ablation-embedding.svg" alt="Embedding 对比。fts5 R@1=0.825 MRR=0.907 p50=93ms；embedding R@1=0.617 MRR=0.733 p50=18304ms（197x）。">

- 在中文术语重合度高的小库上，BM25 字面已能命中（术语和 wiki 重合）；embedding 的语义泛化反而引入噪声——而且慢 197 倍。
- **决策**：fts5 仍是默认。embedding 作 fts5 miss 时的 **fallback**，不替代。embedding 真正的价值在大库 + 跨语言 + 同义词重的场景。

### 逐层消融

<img src="images/ablation-layers.svg" alt="逐层消融。完整三层 R@1=0.825 MRR=0.907；去 Node-BM25 0.525/0.630（−36%）；去 Soul Boost 0.805/0.900。">

- **去 Node-BM25**（召回 fts5→native）：R@1 0.825→0.525（−36%）—— Node-BM25 是精度主力。
- **去 Soul Boost**（fusion 误用，灵魂搬到召回层 re-rank）：R@1 0.825→0.805 —— 灵魂在注入层才对，召回层 re-rank 是负优化。

### LoCoMo 长对话召回 —— vs OpenViking（1540 case）

我们适配了公开的 [LoCoMo](https://github.com/snap-research/locomo) 评测（ACL 2024，10 段长对话，1540 个 QA，4 个类别，排除 adversarial）：每段对话 → 一个 wiki 页，每个 QA question → 一个 eval case，期望命中是对话 slug。完整报告：[locomo-pk-report.md](./records/experiments/locomo-pk-report.md)。

<img src="images/locomo-pk.svg" alt="LoCoMo 1540 case。OKS recall@1=0.920 p50=31ms；OpenViking QA accuracy=0.8286。">

- **OKS recall@1 = 92.0%** —— 1540 个 LoCoMo question 里 92% 在 top-1 召回到正确对话。
- **指标诚实说明**：OKS 报*召回命中*（正确对话被召回到）；OpenViking 报*完整 QA accuracy*（召回 + LLM answer + LLM judge）。召回是 QA 的上界——召不到就答不对。OKS core 无 API（P4）评到召回为止；完整 QA accuracy 取决于宿主 Agent 的 LLM。
- **为什么 OKS 召回强**：Node-BM25 按 `##` 分 node，question 里的实体（人名/日期/事件）匹配到对话出现的那个 turn；SQLite 持久索引 + abstract 零读给到 31ms p50。
- **vs OKS 50-case**：LoCoMo R@1（0.920）> 50-case R@1（0.825）—— LoCoMo question 含对话里的实体；50-case 是语义改写（无关键词重合），更难。

复现：
```bash
git clone https://github.com/snap-research/locomo.git
python3 scripts/locomo_to_oks.py records/experiments/locomo-data/locomo10.json wiki/conversations/locomo records/locomo-eval.yaml
oks eval recall records/locomo-eval.yaml --output locomo-fts5.json --search-backend fts5
```

（数据集也 vendor 在 `records/experiments/locomo-data/locomo10.json` —— CC BY-NC 4.0，见其 LICENSE。）

### 为什么 OKS 召回更优 —— 架构分析

OKS recall@1 = 92.0% 在同一个 LoCoMo 数据集上超过 OpenViking 的完整 QA accuracy 82.86%。这个差距不是运气，而是五个架构选择的结果：

1. **Node-BM25 匹配对话结构，向量不匹配。** LoCoMo 对话几百个 turn。OKS 把每个 `##` 标题 turn 索引成独立的 FTS5 row（node-level），所以一个提到 "Caroline" + "October 13" 的问题只在两者都出现的那个 turn 上高分。OpenViking 把整段话 embed 成向量——实体特异性淹段在段嵌入里。
2. **实体查询上字面赢语义。** LoCoMo 问题实体重（人名、日期、事件）。BM25 字面命中精准；embedding 语义泛化引入噪声（"Caroline" → 附近的错误 speaker）。在 OKS 自己的 50-case（语义改写，无关键词重合）上 fts5 R@1 = 82.5%；在 LoCoMo（实体重合）上跳到 92.0% —— 正是字面赢的地方。
3. **零外部依赖。** OKS 用 SQLite FTS5（Python 自带）。无向量库、无 embedding model、无 GPU。OpenViking 要向量索引 + embedding model（Doubao-embedding-vision）+ 可选 VLM —— 更重的栈，更多失败点。
4. **31ms p50。** SQLite 持久索引 + abstract 零读（v0.6.10）意味着查询时零文件读。OpenViking 的目录递归向量搜索 + rerank + LLM answer 是更长的流水线。
5. **可观测、文件化、人可审。** `oks recall "<q>" --explain` 显示每个 node 的 BM25 分数和哪个 turn 命中。对话存为可读的 wiki markdown 你能编辑。OpenViking 的向量库是黑盒；它的 trajectory 有帮助，但索引本身不透明。

**诚实边界**：OKS 量的是*召回命中*（正确对话被召回到）；OpenViking 量的是*完整 QA accuracy*（召回 + LLM answer + judge）。召回是 QA 的天花板——召不到就答不对。OKS 的 92% 召回意味着一个带强 LLM 的宿主 Agent 可以接近 92% QA accuracy；OKS core 本身评到召回为止（无 API，P4）。优势在**召回层**，不在 answer 层。

### Abstract 零读 & tier 降级（v0.6.10 / v0.6.12）

- **Abstract 零读**：fts5 schema `node-v2` 加了 `abstract` 列；`body_preview` 从 SQLite 读——**召回过程零文件读**。R@1 持平（0.429），p50 121ms（略快）。
- **Tier 降级**：`_apply_budget()` 在 token budget 命中时按 tier 降级——L2（全文，200c）→ L1（概览，100c）→ L0（abstract，50c）→ title-only（0c，rel < `0.5`）→ 截断。验证：5×200c 在 300c budget 下 → 150c ≤ 300。

> 这些数字是某个时间点一个知识库的历史基准，不是通用 SLA。任何一个都能复现——见[复现](#复现)。

## 快速开始

> 💡 **第一次用 OKS？** 先读[从这里开始](https://open-agent-power.github.io/open-knowledge-studio/)——它讲清记忆生命周期和 OKS 在你 Agent 栈里的位置。

需要 Python 3.10+。

```bash
pipx install open-knowledge-studio && pipx ensurepath
oks init my-knowledge-base
cd my-knowledge-base
oks status          # wiki 数量、tier 分布、drafts、质量
oks recall "git branch"   # 三层召回 → 注入匹配的记忆
```

可选自动召回 hook（把召回接到你的 Agent 宿主）：

```bash
oks hook install --editor claude   # 或：qoder | codex | both
oks skills-install                # 打包 skills + agent-config 到 .claude/.qoder/.pi/.codex
```

接下来：

- CLI 参考、hook 配置、评估：[CLI 文档](https://open-agent-power.github.io/open-knowledge-studio/reference/cli/)
- 备份、导出、会话：[备份与导出](https://open-agent-power.github.io/open-knowledge-studio/connect/backup-export/)

## 跟你的 Agent 一起用

OKS 在每次 prompt 注入人审过的记忆（UserPromptSubmit），并在每次工具调用后检测冲突（PostToolUse → `mail/`）：

- **Claude Code** —— `.claude/hooks/` + `settings.json`
- **Codex** —— `.codex/hooks.json`
- **qoder** —— `.qoder/settings.json`（共享 `.claude/hooks/`）
- **pi** —— `.pi/extensions/*.ts`（TS extension，共享 `.claude/hooks/`）
- **其他 shell** —— 任何能跑 shell hook 的宿主

每个的设置：`oks hook install --editor <claude|qoder|codex|both>` 然后 `oks skills-install`。

## 产品边界

**开源版不阉割。** 这个仓库里的 OKS 在 MIT 下完全开源：没有功能门、不要账号、不要激活码。CLI 核心无 API（CONSTITUTION P4）——`oks` 只做文件操作；核心不调远程 AI API。AI 在你自接的可选 provider/skill 里。

- **OKS 不训练模型权重。** "知识模型"是文件系统。
- **OKS 不自动晋升 raw → Wiki。** 人审。
- **OKS 不替代你的 Agent。** 它提供召回原语；宿主 Agent 决定。
- **Git 就是迁移。** 没有数据库；schema 变更通过 `_meta/` 版本化。全程原子写。

<a id="复现"></a>
## 复现

50-case 数据集和所有 run JSON 都归档了：

```
records/experiments/
├── eval-50.yaml                 # 50 个语义改写 query + 期望 slug
└── runs/
    ├── eval-50-fts5.json        # R@1=0.825, MRR=0.907
    ├── eval-50-native.json      # R@1=0.525, MRR=0.630
    ├── eval-50-fusion.json      # R@1=0.805, MRR=0.900
    └── eval-50-embedding.json   # R@1=0.617, MRR=0.733
```

重跑任意 backend：

```bash
oks eval recall records/experiments/eval-50.yaml \
  --output my-run.json \
  --search-backend {fts5|native|fusion}

oks eval compare records/experiments/runs/eval-50-fts5.json my-run.json
```

逐 query 拆解：`oks recall "<query>" --explain` 显示每个因子分数。

**注意**：OKS 没有官方标注数据集——50-case 是一个知识库的历史。指标在那个数据集上跨 backend 可比；不是通用 SLA。建你自己的标注集再跑。

## 路线图

- **AI abstract 生成**（Dreaming 层）—— LLM 写 `abstract:` frontmatter，把 abstract 零读质量提到机械首段之上。
- **RecallLedger** —— 跨 turn 去重，同一个页面不会在 cooldown 内重复注入。
- **Query expansion** —— 同义词 / 中英互译，在召回层桥接同义词鸿沟，不走 embedding。
- **native→fts5 dispatch 统一** —— 现在两条路径（native 带灵魂层，fts5 不带）；统一让 fts5 也接灵魂层。

## 社区与贡献

- **文档**：[open-agent-power.github.io/open-knowledge-studio](https://open-agent-power.github.io/open-knowledge-studio/)
- **设计契约**：[CONSTITUTION.md](./CONSTITUTION.md) —— 记忆架构（A1–A5）
- **更新日志**：[CHANGELOG.md](./CHANGELOG.md) —— 完整发布历史
- **贡献**：bug 修复和新功能都欢迎——fork 一个分支，开 PR

## 安全与隐私

OKS 完全跑在你本地文件系统上。无遥测，核心不调远程（CONSTITUTION P4）。你的知识库留在你的 git remote（或不要 remote）下。

## License

[MIT](./LICENSE)
