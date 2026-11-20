---
title: CLI
nav_order: 1
parent: 参考手册
---
# CLI 参考

本页按用途概括主要命令，并补充几组经常需要核对的参数。日常使用可以直接向 Agent 描述意图，见[日常任务](../usage/)；不需要先记住命令。当前安装版本的完整入口和参数以 `oks --help`、`oks <命令> --help` 为准。

## 手工安装

先准备 Python 3.12 或更新版本、Git 和 `pipx`。新安装使用：

```bash
pipx install open-knowledge-studio
pipx ensurepath
```

重新打开终端，在准备保存知识的上级目录创建独立实例：

```bash
oks init my-knowledge-base
cd my-knowledge-base
oks status
oks capability status
```

初始化会同时提供 Agent Skill。已有实例的更新与资产覆盖按[安装 Skill](https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md)操作，不重复初始化或覆盖本地修改。

## Mail 接入

Studio 与 Agent 的只读查看入口：

```bash
oks mail serve --path /path/to/knowledge-base --port 3182
oks mail snapshot
oks mail thread THREAD_ID
```

仅当宿主在知识库之外、无法直接发现随库 Skill 时，创建本机绑定：

```bash
oks mail setup --agent reviewer --path /path/to/knowledge-base --skills-dir .agents/skills
```

选择实际宿主的 Skill 发现目录，重新加载后使用。绑定不会覆盖已有不同内容，也不应进入团队 Git。发送、回复必须使用当前 Session；读取与回执不代表任务已执行。用户入口见 [Mail 接入](mail-portable.html)。

## 命令概览

先用 `oks --help` 查看顶层入口，再用 `oks <命令> --help` 查看当前版本的参数和子命令。下表用于定位命令组，不承诺列出每个子命令和参数。

### 知识库与配置

| 命令 | 用途 |
|---|---|
| `oks init <path>` | 创建独立知识库、默认配置和 Agent 操作入口 |
| `oks status` | 查看当前知识库路径、内容数量、状态分布和质量概览 |
| `oks config init/show/set` | 管理用户级默认知识库和其他全局配置 |
| `oks layout-migrate` | 把旧版 Goal、讨论和 Skill 路径迁移到当前目录结构，并保存迁移记录 |
| `oks skills-install` | 把随 OKS 发布的 Agent Skill 写入当前知识库或指定 Host 的全局目录 |
| `oks capability list/install/status/guide` | 查看、安装和选择材料处理能力 |

### 材料、Candidate 与知识页

| 命令 | 用途 |
|---|---|
| `oks ingest prepare/run/validate/finalize` | 准备或执行材料收录，并检查保存后的工作流事实；不会自动 Promote Wiki |
| `oks raw-commit <manifest-dir>` | 校验协议对象和文件引用，组装 Raw Bundle |
| `oks drafts list/get/promote/reject` | 查看 Candidate 的具体版本，并保存接受或拒绝决定 |
| `oks wiki list/get/domains/create/pin/archive/unarchive/use/export` | 管理 Wiki、记录显式使用和导出知识；`unarchive` 恢复为 `provisional` |
| `oks recall "<query>"` | 查询 `episodic`、个人 `knowledge` 和关联库 `team_knowledge` 三条通道 |
| `oks use <slug>` | `oks wiki use` 的顶层别名，记录页面被明确采用 |
| `oks skills import/list/versions/diff/search/load/unload/derive/merge-*` | 管理经过版本记录和审核的 Skill；搜索与加载不会执行 Skill |
| `oks sources link/inspect/list/unlink` | 关联或解除只读团队知识库，并检查其已提交版本 |
| `oks fs ls/tree/stat/read/read-many/overview/find/inspect` | 通过 `oks://` URI 只读浏览允许公开的知识库范围 |

普通 `oks recall` 不返回 Skill 卡片或加载命令。需要查找能力时使用 `oks skills search`；选定版本后使用 `oks skills load` 读取，只有显式提供目标目录时才会写入 Host 副本。

### 任务、协作与自动调用

| 命令 | 用途 |
|---|---|
| `oks capture connect/status/sync/extract/retry` | 把实际对话和阅读批次接入 Raw 与待审核提议，并保留失败批次 |
| `oks task start/begin/select/...` | 选择任务、保存进度、检查来源变化和生成本地交接；完成任务不会批准产物或 Wiki |
| `oks mail send/delegate/inbox/sent/thread/reply/read/count/ack/archive/...` | 保存 Agent 间消息、Thread、投递状态和读取回执；详见[Mail 协议](mail-protocol.html) |
| `oks handoff` | 冻结并检查已有 Mail 交接的任务上下文 |
| `oks registry list/bind/remove` | 记录某个 Agent 与工作目录对应的 Profile 和 Goal |
| `oks onboarding status/complete/skip/reset` | 保存 Studio 入门步骤的明确状态，不根据页面或文件自动推断完成 |
| `oks feedback record/propose/review/withdraw/list/context/export/forget` | 记录私有反馈和候选审核；导出后仍需走普通 Candidate 审核 |
| `oks trace start/append/judge/feedback/blocker/propose/finish/validate/show` | 保存执行事件、判断、阻塞和外部反馈 |
| `oks hook recall/history/install/status` | 安装、检查或直接运行 Host Hook，并读取保留的自动查询摘要 |
| `oks team init/sync` | 创建团队库；`sync` 提交共享目录、变基远端，并可在显式指定时推送 |
| `oks mail serve/setup/view/snapshot/wait` | 启动本地 Studio 或 Mail 入口，并为知识库外的 Host 建立绑定 |
| `oks workbuddy doctor` | 只读检查 WorkBuddy 的本地 OKS 接入是否完整 |

### 维护、评测与安全

| 命令 | 用途 |
|---|---|
| `oks lint` | 检查 Wiki 元数据、关系和文件一致性 |
| `oks metrics [--html]` | 查看知识指标，并可生成本地使用报告 |
| `oks decay` | 按当前分数规则更新达到退出条件的 Wiki 状态 |
| `oks distill [--dry-run]` | 执行衰减并提出维护 Candidate；`--dry-run` 只报告，不写入提议 |
| `oks eval candidates/capture/review/export/recall/compare` | 收集人工标签、导出数据集、运行离线评测并比较可比结果 |
| `oks schema show <name>` | 输出协议对象的有效示例 |
| `oks security sanitize <file>` | 就地清理 Provider 原始输出中的常见凭据格式 |

`oks recall` 的结果分为三条通道：`episodic` 查询 Raw 与符合身份范围的 Profile，`knowledge`
查询当前个人库的 Wiki，`team_knowledge` 查询已关联的团队库。`--knowledge-only` 只关闭
`episodic`，仍会查询团队库。默认 Prompt Hook 当前只注入个人 `knowledge`，不会把
`team_knowledge` 自动加入提示词。

完整命令：`oks --help`。

## 只读虚拟文件系统

`oks fs` 为当前 OKS 实例提供统一的只读访问层。常用命令的准确形式是：

```bash
oks fs ls <uri> [--format table|json]
oks fs tree <uri> [--depth 0..10] [--max-entries 1..10000] [--format table|json]
oks fs stat <uri> [--format table|json]
oks fs read <uri> [--offset N] [--limit 1..1000000] [--format table|json]
oks fs read-many <uri>... [--limit 1..1000000] [--max-total-chars 1..8388608] [--format table|json]
oks fs overview <uri> [--format table|json]
oks fs find <literal-query> --under <uri> [--max-results 1..200] [--format table|json]
oks fs inspect <uri> [--operation ls|stat|read|overview|find|compare] [--query TEXT] [--offset N] [--limit N]
```

根 URI 是 `oks://`。固定 scope 包括 `profiles`、`raw`、`wiki`、`drafts`、`mail`、`skills` 和 `traces`；关联团队库后还会出现只读的 `team` scope。其中 `traces` 是 `raw/executions/` 的公开地址，`raw/.logs/` 不公开；`settings/`、`_meta/`、`.oks/` 和实例中的其他路径也不会经 VFS 暴露。URI 中的路径会规范化并拒绝目录穿越、编码分隔符和任意 symlink。

边界默认值如下：`tree` 默认深度 3、最多 1000 个节点；`read` 默认从字符 offset 0 返回最多 20,000 个 UTF-8 字符，单次最多 1,000,000 个字符；`read-many` 每次读取 1 至 250 个文件，每个文件默认最多 20,000 个字符，总量最多 8 MiB；`find` 做大小写不敏感的字面搜索，默认最多 50 项、最多 200 项，正文 snippet 最多 200 个字符。达到结果上限时响应会显式设置 `truncated`；`find` 遇到二进制或不可读 UTF-8 文件时会累计 `skipped_count`。

`--format json` 的成功外壳固定为 `oks-fs-response/v1`，包含 `schema_version`、`operation`、canonical `uri` 和 `result`；失败外壳用相同 schema，并通过 `error.code` 与不含物理绝对路径的 `error.message` 报错。默认 `table` 格式供人直接阅读。

VFS 没有 `write`、`mkdir`、`mv`、`rm`、`cp` 或其他修改命令。保存材料、审核 Candidate、创建或更新 Wiki，需要使用各自的操作命令，VFS 不能绕过这些检查。`overview` 只统计目录，不生成摘要或附加说明文件；`find` 不调用模型、向量检索或重排序工具，也不会让 Agent 递归查询。`inspect` 用于执行一次带步骤记录的读取；它不是新的写入接口，也不会记录文件正文。

### Hook 可调参数（环境变量）

| 环境变量 | 默认 | 用途 |
|-----|------|------|
| `OKS_RECALL_FLOOR` | 0.7 | 最小 relevance 才注入 |
| `OKS_RECALL_TOPN` | 3 | 最多注入条数 |
| `OKS_RECALL_COOLDOWN` | 10 | 同 slug 重注入间隔（轮）|
| `OKS_MAIL_TOPN` | 3 | 最多注入未读 mail |
| `OKS_CONFLICT_WINDOW` | 300 | 文件冲突检测窗口（秒）|
| `OKS_AGENT_ID` | cwd basename | Agent 身份（registry key）|
| `OKS_SEARCH_BACKEND` | 配置文件值，缺省为 `fts5` | 检索后端：`native` \| `fts5` \| `fusion` \| `<connector-name>`（见下） |
| `OKS_POSTTOOL_FLOOR` | 0.9 | PostToolUse recall 补位最小 relevance（比 UserPromptSubmit 高，避免噪声）|
| `OKS_POSTTOOL_TOPN` | 2 | PostToolUse 最多注入条数（比 UserPromptSubmit 少）|

### 可切换的检索后端

`oks recall --search-backend <name>` 或 `OKS_SEARCH_BACKEND=<name>` 切换召回后端：

| 后端 | 说明 | 适用场景 |
|---------|------|----------|
| `native` | 逐页计算关键词、标题匹配和元数据分数 | 检查规则或复现旧结果 |
| `fts5` | SQLite FTS5、BM25、字段权重、持久化索引和增量更新；实现参考 [TreeSearch](https://github.com/shibing624/TreeSearch) 的 FTS5Index | 页面较多、需要复用索引的知识库 |
| `fusion` | 结合归一化后的 FTS5 与 native 分数重新排序（0.7f + 0.3n） | 实验性方法，效果需在同一评测集和知识库快照上比较 |
| `<connector-name>` | 第三方包通过 Python entry point `oks_search_backend` 注册 | 向量检索、代码搜索或其他检索实现 |

第三方包可以实现 `search()` 和 `index()` 接口，通过 entry point 注册后，再用 `oks recall --search-backend <name>` 选择。已随 OKS 提供的 `embedding` 和 `code` 后端仍需按用途准备相应依赖。当前排序规则见[召回引擎](../algorithms/recall-engine.html)，历史实验及比较限制见[召回评估](../algorithms/recall-evaluation.html)。

Registry、Mail 和 `records/*.jsonl` 使用独立的运行路径，不由 `oks recall` 返回。
`records/inject.jsonl` 记录哪些页面被注入，`oks wiki use` 可标记其是否被实际采用；
仅记录这些信号不会提升 `confidence`、改变审核状态或产生 `[verified]`。

## Wiki 元数据字段

Wiki 页开头的 frontmatter 保存元数据。下表列出常见字段；格式规范随 OKS 程序维护，知识库不必复制 `_meta/`：

| 字段 | 说明 |
|------|------|
| `title` / `type` / `area` | 标题 / 类型（concept \| strategy \| anti-pattern）/ 知识域 |
| `status` | provisional \| active \| stale \| dropped \| superseded |
| `importance` / `confidence` | 重要性 / 置信度元数据；置信度不是经过校准的正确概率，更新规则见[衰减系统](../algorithms/decay-system.html) |
| `created` / `human_reviewed_at` | 时间戳 |
| `pinned` / `archived` | 固定（增加评分，并在衰减维护时跳过退出处理）/ 归档（退出召回） |
| `tags` / `fingerprint` | 标签 / 内容指纹（dedup） |
| `traces` | evidence 链接（provenance） |
| `review` | `decision_correct` / `outcome` / `lesson` |
| `relates_to` / `relationship` | A4 关系（enriches / supersedes / confirms / challenges） |

draft frontmatter 用 `draft_type` / `draft_area`（不是 `type` / `area`），否则 promote 时 fallback 到 concept/computing。

## Trace 命令

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

轨迹存 `raw/executions/<id>/events.jsonl`。这类文件记录执行来源和过程，不进入普通 Recall。`blocker` 需同时写 `reason` 和 `needed`，只有 `human_action` 或 `checkpoint` 能解除，Agent 不能自行解除。`propose` 写入 `drafts/proposals/`，不会修改正式 Wiki。

## Raw Bundle 结构

机器可读事实源在仓库 `schemas/`（包内镜像 `knowledge_studio/schemas/` 做强制校验）：

- `capture-envelope.schema.json`：来源信封
- `capability-manifest.schema.json`：能力清单
- `processing-run.schema.json`：处理运行
- `raw-bundle-v0.2.schema.json`：Raw Bundle v0.2

当前版本为 `raw-multimodal/v0.2`。Agent 组织采集并整理待审核提议，OKS 保存材料、审核记录和知识，提供后续查询。`oks_connector` 随 OKS 一起发布，负责获取来源、转换格式、定位证据并记录处理状态。具体流程见[材料收录协议](ingest.html)。

## 远程 Provider 与凭据

远程 Provider（Firecrawl 等）会调用外部 API：

- **凭据来源**：环境变量（`FIRECRAWL_API_KEY` 等）、MCP Session Token 或操作系统凭据库。不要把凭据写入源码、Git、CLI 参数或 Recipe。
- **处理策略**：Source Envelope 的 `policy.remote_processing`（`deny`、`allow`、`ask`）控制是否允许远程处理。`deny` 只允许本地处理，`allow` 表示已经允许，`ask` 表示执行前需要确认。
- **脱敏**：外部输出进入 Raw Bundle 前，可用 `oks security sanitize` 清理常见 API Key、Bearer Token、Cookie 和内部 IP。检查同时使用敏感键名和常见值格式，但不能保证发现所有泄漏形式。
- **隔离**：每次采集使用 `.oks/runs/{run_id}/work/<provider>/` 中的独立工作目录，先保存工具的原始输出并校验大小，再由 Agent 分析内容。

Provider 缓存中的 Python 组件可以生成 `__pycache__/*.pyc`，这些运行时文件不参与源资产哈希比较。修改源文件或在缓存目录中加入其他文件会阻止缓存重用；文章、报告等任务产物应写入任务目录，不要混入 Provider 缓存。
