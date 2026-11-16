---
title: 宪法
nav_order: 1
parent: 维护者
nav_exclude: true
search_exclude: true
---
# 设计约束（A1 至 A5 摘要）

仓库根目录的 `CONSTITUTION.md` 记录 OKS 的设计原则。本页概述其中的 A1 至 A5；完整文件还包含其他约束。下文的“已审核”表示有审核记录，不保证内容永远正确。

## A1：内容分类与配置分开

A1 区分 `profiles/`、`raw/`、`wiki/`、`drafts/`、`mail/` 五类目录，以及配置和格式规范。`settings/` 保存知识库配置；Schema（数据格式规范）随 OKS 程序维护，不要求每个知识库都复制 `_meta/`。`mail/` 保存 Agent 之间的协作消息，不参与知识查询或衰减，也不代替任务、审核和可信度状态。

内容从获取、整理、保存，到查询、送入 Agent 上下文，再到归档，各阶段应有明确记录。原始材料用于回查，后续解释另存；Wiki 页面可以经过审核修订。使用 FTS5 搜索时，索引根据知识文件建立，可以重新生成，不能代替原文件和 Git 历史。

## A2：六类内容与来源标签

六类记忆分别是用户背景（User）、项目背景（Project）、经历和原始记录（Episodic）、整理后的知识（Semantic）、执行方法（Procedural）以及待审核提议（Draft），对应背景、材料、知识、技能和提议等存储位置。

送入 Agent 上下文的内容必须标明来源与核验状态：`[verified]` 表示有执行证据或人工审核记录；`[inferred]` 表示尚未核验的模型提炼；`[stale]` 表示可能过时、需要复核。原始材料标为 `[untrusted-source]`，用户声明的背景标为 `[user-declared]`；无法识别的材料类型默认按不可信来源处理。

`[verified]` 记录的是证据或审核来源，不是“所有说法都正确”的保证。标签不能根据使用次数、排序分数或 `active` 状态推定；审核时间 `human_reviewed_at` 也不能单独证明审核人身份。

## A3：整理提议后，由人审核

Dreaming 是设计文档中对知识整理过程的名称：`raw/` → Agent 整理 → `drafts/` → 人工审核 → `wiki/`。Agent 提出 Candidate，是否接受、修改或拒绝由人决定；系统不得把 Raw 自动提升为带审核记录的 Wiki。`oks wiki create` 可以直接创建 `provisional` Wiki，但这不属于人工审核，也不能声称内容已经通过审核。

收录工作流按 A/B/C 分级，仅允许 A 级结果提交 Candidate。接受后的内容仍会经过衰减评分、关系更新和版本记录。`oks distill` 执行衰减与生成合并提议等维护工作，不代替 Agent 判断或人工审核。

`oks drafts promote` 按审核流程保存获准的提议，并记录 `human_reviewed_at` 等审核信息。记录说明哪份内容被接受，不构成独立的事实核验；发现新证据或错误后仍需修订。可以另外安排其他 Agent 复查，但这不能替代人的审核决定，也不是核心自动审核机制。

## A4：记录知识之间的关系

关系记录在 Markdown 开头的元数据（frontmatter）中，不同关系对旧页的影响不同：

| 关系 | 含义与对旧页的处理 |
|---|---|
| `supersedes`（取代） | 旧页标为 `superseded`，记录 `superseded_by`，从查询结果中排除，文件仍保留。 |
| `enriches`（补充） | 保留旧页，记录 `enriched_by`，不因补充关系自动归档旧页。 |
| `confirms`（印证） | 记录 `confirmed_by`，将 `confidence` 增加 0.1，最高为 1.0；这是字段评分，不是正确率保证。 |
| `challenges`（质疑） | 旧页标为 `stale`，记录 `challenged_by`；仍可被查到，但应附上 `[stale]` 提示。 |

新页通过 `relates_to` 和 `relationship` 指向旧页。更新不能静默抹去旧知识，应保留可追溯的关系。

## 执行记录与安全要求

`raw/executions/` 保存执行轨迹，`raw/.logs/` 保存工具或 Agent 生成的摘要。这些属于 provenance（来源和过程记录），不参与普通材料查询；可通过知识页的证据链接回查，不能因为 Agent 自己写过就当作有人工审核记录的知识。

调用远程 Provider（材料处理工具）时，凭据应来自环境变量、MCP token 或操作系统密钥存储，不能写死在代码里或提交到 Git。`policy.remote_processing` 的 `deny`、`allow`、`ask` 分别表示禁止、允许、先询问。输出应在进入 Raw Bundle（原始材料包）前经 `oks security sanitize` 脱敏；规则脱敏只能降低凭据泄露风险，不能保证发现所有敏感内容。

## A5：安全保存文件

文件快照先用 `mkstemp` 创建临时文件，写入并以 `fsync` 同步后，再通过 `os.replace` 整体替换目标文件。父目录同步也是设计要求；参考实现会尝试执行，但部分平台可能不支持。

追加式 JSONL 记录则在持有文件锁时追加，并执行 flush 和 `fsync`；读取后修改再写回的记录，锁要覆盖整个操作。不能用直接 `open(path, 'w')` 覆盖知识或配置。这些措施用于降低半文件和并发覆盖风险，不是对所有断电或磁盘故障的保证。
