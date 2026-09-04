---
title: CLI
nav_order: 1
parent: 参考
---
# CLI 参考

`oks` 命令清单 + 关键契约。日常用前几个，后几个是改协议 / 写 Provider / 做评测时才查。

## 命令清单

| 命令 | 用途 |
|------|------|
| `oks init <path>` | 创建实例（物化认知桶、配置、Schema 与 Agent skills） |
| `oks status` | 知识库概览（wiki/raw 计数 + tier + 质量） |
| `oks metrics [--html]` | 知识指标；可生成基于注入与反馈记录的本地 HTML 报告和调参建议 |
| `oks recall "<q>"` | 召回（fts5 node-level，双路 wiki + raw） |
| `oks fs ls/tree/stat/read/overview/find` | 通过 canonical `oks://` URI 只读浏览当前实例 |
| `oks ingest run <src>` | 摄入材料 → Raw Bundle |
| `oks ingest prepare <src>` | 生成 ingest 协议骨架 |
| `oks wiki create/list/get/pin/archive/use/export` | wiki 页管理 + OKF 导出 |
| `oks workbuddy doctor [--kb-root PATH]` | 只读检查 WorkBuddy 本地 Agent 的 OKS 工作流是否就绪 |
| `oks drafts list/promote/reject` | draft 候选队列与状态变更；完整内容通过 `/promote` Skill 审阅，晋升与拒绝都必须保留人工决定 |
| `oks distill [--dry-run]` | 衰减 + 演化（dreaming 后半） |
| `oks capability list/install/status/guide` | 能力注册与选择指导 |
| `oks hook install/status` | opt-in 自动 recall + 文件冲突检测注入 |
| `oks team init [path] [--name NAME]` | 创建共享团队知识实例 |
| `oks schema show <name>` | 输出协议文档的校验示例 |
| `oks trace *` | 执行追踪（provenance） |
| `oks mail send/inbox/show/read/count` | Agent 间消息接口；不属于 `oks recall` 结果 |
| `oks registry list/bind/remove` | 终端注册表（agent+cwd → profile/goal） |
| `oks lint` | 扫 wiki/ 一致性 |
| `oks config init/show/set` | 配置 |
| `oks security sanitize <file>` | 凭据脱敏 |
| `oks eval recall <dataset>` | 召回离线评测 |

完整命令：`oks --help`。

## 只读虚拟文件系统

`oks fs` 为当前 OKS 实例提供统一的只读访问层。六个命令的准确形式是：

```bash
oks fs ls <uri> [--format table|json]
oks fs tree <uri> [--depth 0..10] [--max-entries 1..10000] [--format table|json]
oks fs stat <uri> [--format table|json]
oks fs read <uri> [--offset N] [--limit 1..1000000] [--format table|json]
oks fs overview <uri> [--format table|json]
oks fs find <literal-query> --under <uri> [--max-results 1..200] [--format table|json]
```

根 URI 是 `oks://`，公开 scope 固定为 `profiles`、`raw`、`wiki`、`drafts`、`mail`、`skills`、`traces`。其中 `traces` 是 `raw/executions/` 的唯一公开地址，`raw/.logs/` 不公开；`settings/`、`_meta/`、`.oks/` 和实例中的其他路径也不会经 VFS 暴露。URI 中的路径会规范化并拒绝目录穿越、编码分隔符和任意 symlink。

边界默认值如下：`tree` 默认深度 3、最多 1000 个节点；`read` 默认从字符 offset 0 返回最多 20,000 个 UTF-8 字符，单次最多 1,000,000 个字符；`find` 做大小写不敏感的字面搜索，默认最多 50 项、最多 200 项，正文 snippet 最多 200 个字符。达到结果上限时响应会显式设置 `truncated`；`find` 遇到二进制或不可读 UTF-8 文件时会累计 `skipped_count`。

`--format json` 的成功外壳固定为 `oks-fs-response/v1`，包含 `schema_version`、`operation`、canonical `uri` 和 `result`；失败外壳用相同 schema，并通过 `error.code` 与不含物理绝对路径的 `error.message` 报错。默认 `table` 格式供人直接阅读。

VFS 没有 `write`、`mkdir`、`mv`、`rm`、`cp` 或其他修改命令。Raw 写入、Draft 审核和 Wiki promotion 仍必须走各自领域命令，VFS 不能绕过治理门控。`overview` 只做机械目录统计，不生成摘要或 sidecar；`find` 不调用 LLM、embedding、reranker 或递归 Agent。

### hook 可调参数（env）

| env | 默认 | 用途 |
|-----|------|------|
| `OKS_RECALL_FLOOR` | 0.7 | 最小 relevance 才注入 |
| `OKS_RECALL_TOPN` | 3 | 最多注入条数 |
| `OKS_RECALL_COOLDOWN` | 10 | 同 slug 重注入间隔（轮）|
| `OKS_MAIL_TOPN` | 3 | 最多注入未读 mail |
| `OKS_CONFLICT_WINDOW` | 300 | 文件冲突检测窗口（秒）|
| `OKS_AGENT_ID` | cwd basename | Agent 身份（registry key）|
| `OKS_SEARCH_BACKEND` | native | search backend：`native` \| `fts5` \| `fusion` \| `<connector-name>`（见下） |
| `OKS_POSTTOOL_FLOOR` | 0.9 | PostToolUse recall 补位最小 relevance（比 UserPromptSubmit 高，避免噪声）|
| `OKS_POSTTOOL_TOPN` | 2 | PostToolUse 最多注入条数（比 UserPromptSubmit 少）|

### 可插拔 search backend

`oks recall --search-backend <name>` 或 `OKS_SEARCH_BACKEND=<name>` 切换召回后端：

| backend | 说明 | 适用场景 |
|---------|------|----------|
| `native` | 6+1 因子 + jieba + IDF + title boost，page-level，实时遍历 | 小库 / 无 SQLite / 历史复现（v0.6.0 前默认，R@1=0.525） |
| `fts5` | SQLite FTS5 + BM25 + column weights + 持久化索引 + 增量 diff（CV from [TreeSearch](https://github.com/shibing624/TreeSearch) FTS5Index） | 大库（1000+ 页），持久化索引 |
| `fusion` | fts5 主召回 + native re-rank（0.7f+0.3n），R@1=0.805 | 实验位（低于纯 fts5 R@1=0.825，灵魂 re-rank 负优化） |
| `<connector-name>` | 第三方包经 `entry_points(group="oks_search_backend")` 注册 | embedding / 代码搜索（ast_parser）/ 其他开源 search 框架 |

**connector 扩展点**：第三方包写一个实现 `search()` + `index()` 的类，注册 entry_points，`oks recall --search-backend <name>` 即用，OKS 核心不改。这让 embedding 接入、代码检索等能力以 connector 方式自由扩展，而非硬塞进核心。

Registry、Mail 和 `records/*.jsonl` 使用独立的运行路径，不由 `oks recall` 返回。
`records/inject.jsonl` 记录哪些页面被注入，`oks wiki use` 可标记其是否被实际采用；
仅记录这些信号不会提升 `confidence`、改变审核状态或产生 `[verified]`。

## Frontmatter 字段

wiki 页 frontmatter（完整契约在仓库 `_meta/`）：

| 字段 | 说明 |
|------|------|
| `title` / `type` / `area` | 标题 / 类型（concept \| strategy \| anti-pattern）/ 知识域 |
| `status` | provisional \| active \| stale \| dropped \| superseded |
| `importance` / `confidence` | 0-1，人工设定重要性 / 可信度 |
| `created` / `human_reviewed_at` | 时间戳 |
| `pinned` / `archived` | 固定（不衰减）/ 归档（退出召回） |
| `tags` / `fingerprint` | 标签 / 内容指纹（dedup） |
| `traces` | evidence 链接（provenance） |
| `review` | `decision_correct` / `outcome` / `lesson` |
| `relates_to` / `relationship` | A4 关系（enriches / supersedes / confirms / challenges） |

draft frontmatter 用 `draft_type` / `draft_area`（不是 `type` / `area`），否则 promote 时 fallback 到 concept/computing。

## Trace 命令（provenance）

```bash
oks trace start <goal-id> --run-id <id>
oks trace append <id> --type retrieval --actor agent --payload '<json>'
oks trace judge <id> --outcome pass --comment "..."
oks trace feedback <id> --outcome accepted --comment "..."
oks trace blocker <id> --reason "..." --needed "..."
oks trace propose <id> --kind wiki --title "..." --summary "..."
oks trace finish <id> --result '{"outcome":"success"}'
oks trace validate <id> --completed
oks trace show <id>
```

轨迹存 `raw/executions/<id>/events.jsonl`，**排除召回**（provenance 非记忆）。`blocker` 需同时写 `reason` + `needed`，只有 `human_action` / `checkpoint` 能解除——agent 无法自解锁。`propose` 写 `drafts/proposals/`，不改正式 wiki。

## Raw Bundle 协议

机器可读事实源在仓库 `schemas/`（包内镜像 `knowledge_studio/schemas/` 做强制校验）：

- `capture-envelope.schema.json` — 来源信封
- `capability-manifest.schema.json` — 能力清单
- `processing-run.schema.json` — 处理运行
- `raw-bundle-v0.2.schema.json` — Raw Bundle v0.2

当前版本 `raw-multimodal/v0.2`。OKS 负责 Capture 编排 + Candidate + 人审 + wiki 晋升 + 召回；来源获取后的机械解析、证据定位、质量状态由独立发布的 `oks-connector` 负责。摄入流程见 [ingest](ingest.html)。

## Provider 凭证治理

远程 provider（Firecrawl 等）调外部 API：

- **凭据来源**：环境变量（`FIRECRAWL_API_KEY` 等）/ MCP session token / OS keychain（未来）。绝不硬编码、入 git、CLI 参数或 Recipe。
- **政策**：SourceEnvelope 的 `policy.remote_processing`（`deny` / `allow` / `ask`）控制是否调远程。`deny`=本地，`allow`=显式允许，`ask`=提示。Agent 必须遵守。
- **脱敏**：外部输出经 `oks security sanitize` 脱 API key / bearer / cookie / 内部 IP 后才入 Raw Bundle。键名规则（`*_token`、`*_secret` 等）+ 值扫描（AWS `AKIA...`、GitHub `ghp_...`、OpenAI `sk-...`、PEM 头）。best-effort，非完整防泄漏。
- **隔离**：每次 ingest 在 `.oks/runs/{run_id}/work/<provider>/` 隔离运行空间，raw output 落盘 + 校验大小后才做语义处理。
