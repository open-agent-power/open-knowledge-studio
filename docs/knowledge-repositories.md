---
title: 个人库、团队库与工具仓库
nav_order: 5
parent: 工作原理
---

# 个人库、团队库与工具仓库

OKS 使用三类独立目录：个人库保存当前用户的知识和工作记录，团队库保存由团队维护的共享内容，工具仓库保存 OKS 源码。它们可以都由 Git 管理，但用途和读写规则不同。

| 目录 | 主要内容 | OKS 怎样使用 |
|---|---|---|
| 个人库 | 个人的 Raw、Candidate、Wiki、Profile、Goal、配置和记录 | 当前 Agent 和 CLI 的主要读写位置 |
| 团队库 | 团队提交并维护的知识、材料、Profile 和记录 | 由个人库关联，只读查询已提交版本 |
| 工具仓库 | `open-knowledge-studio` 源码、测试、发布资源和文档 | 用于开发 OKS，不作为日常知识库 |

文件夹名称本身不能决定它属于哪一类。应根据创建方式、实际内容和当前配置判断。

## 个人库

使用 `oks init` 创建个人库：

```bash
oks init /path/to/personal-knowledge
```

个人库是当前命令默认写入的位置。它可以保存私有 Profile、个人 Goal、本地材料和自己审核的 Wiki。这里的“个人”表示由个人维护，不表示文件天然加密或不会被 Git 分享；访问权限仍由本机文件系统和仓库设置决定。

OKS 可以从环境变量、用户配置或当前目录解析实际知识库。开始写入前，应运行 `oks status` 或让 Agent 报告实际路径，避免把内容写到工具仓库或另一个 Instance。配置方法见[安装与创建知识库](installation.html)。

## 团队库

团队库也是独立的 OKS Instance，可以用下面的命令创建：

```bash
oks team init /path/to/team-knowledge --name "Team Name"
```

这个命令复用普通 Instance 的目录结构，并增加团队 Profile。它不会自动创建团队目标，也不会把个人库复制进去。

团队库至少要有一个 Git commit，关联读取器才能解析 `HEAD`。每个成员先取得团队仓库的本地 clone，再从自己的个人库关联这个本地目录：

```bash
oks sources link /path/to/team-knowledge \
  --name team \
  --repository owner/team-knowledge
oks sources list
```

`sources link` 把路径、仓库标识和读取版本写入个人库的 `settings/sources.yaml`，不会移动或复制团队文件。如果团队库已经通过已提交元数据或受支持的 `origin` 声明仓库标识，还可以先运行 `oks sources inspect /path/to/team-knowledge`，读取已提交的 README 和版本信息。README 只是参考信息，OKS 不会执行其中的命令。

个人库与团队库必须保持为两个独立目录，不能互相包含。解除关联只会删除个人库中的配置，不会删除团队仓库。

## 关联后实际读取什么

团队库读取器只访问 Git 已提交的普通文件 blob，并有以下边界：

- 未提交和暂存区中的修改不会进入团队查询。
- OKS 不会自动执行 `fetch`、`pull`、`checkout`，也不会切换团队仓库的分支。
- OKS 不会执行团队仓库中的 Python、Shell、Hook 或 Skill。
- OKS 不会把团队文件复制到个人 `wiki/`，也不会从个人库直接写回团队库。
- 单个关联项可以使用 `HEAD`，也可以固定为完整的 40 位 commit SHA。

`HEAD` 在每次读取时解析为团队仓库当前的本地提交。因此，本地切换分支或产生新提交后，查询内容可能变化。完整 commit SHA 指向固定版本，适合需要复现结果的任务。两种方式都不会主动取得远端的新提交。

读取失败、版本不存在或目录不符合知识库格式时，该团队库会从本次 Recall 中排除，并返回警告。OKS 不会回退到未提交的工作区文件。

## 仓库标识怎样确定

`oks sources link` 要求显式提供 `--repository owner/name`。Studio 和 `oks sources inspect` 还可以从已提交的 `settings/library.yaml` 或 Catalog 元数据读取仓库标识；如果这些文件没有声明，再尝试读取 Git 的 `origin`。

当前从 `origin` 自动识别时，只支持 GitHub 的 SSH 和 HTTPS 形式，例如 `git@github.com:owner/repo.git` 和 `https://github.com/owner/repo.git`。其他 Git 服务或自定义远端不能依赖自动推断。即使通过元数据或 CLI 提供 `owner/name` 后可以读取本地 blob，当前结果链接仍按 GitHub 地址生成，不能把它描述成完整的多托管平台支持。

## 普通 OKS 格式与 Catalog 格式

团队库有两种读取方式。二者都只读取已提交版本，但审核校验强度不同。

| 项目 | 普通 OKS 格式 | Catalog 格式 |
|---|---|---|
| 内容发现 | 扫描标准目录中的 Markdown；团队 Recall 只选符合条件的 `wiki/` 页面 | 由 Catalog 明确列出 Candidate、知识页、来源和审核记录 |
| 进入团队 Recall 的依据 | Wiki 元数据包含有效的 `human_reviewed_at` | 条目状态为 `approved`，并有匹配的审核记录 |
| 正文版本校验 | 返回当前正文 SHA，但不把它与审核时版本绑定 | 校验审核记录中的 `body_sha256` 与当前正文完全一致 |
| 适合场景 | 普通团队协作，沿用个人库的 Wiki 元数据 | 需要严格证明“审核的是当前这个正文版本”的团队库 |

普通格式会把带 `human_reviewed_at` 的 Wiki 视为已批准，除非页面设置了 `archived: true`，或状态为 `archived`、`deprecated`、`rejected`。这个字段只记录审核时间，不能单独证明审核人和决定依据。当前实现不会自动排除状态为 `dropped` 或 `superseded` 的团队页面，也不会检查正文是否在审核后被修改。团队维护者需要在提交前清理这些页面；需要严格版本约束时，应使用 Catalog 格式。

普通格式可以在图谱或文件视图中展示团队库的其他目录，但团队 Recall 不会把团队 Skill 卡片当作知识正文注入。关联团队库也不会安装其中的 Skill。

Catalog 格式使用 `records/catalog/knowledge.yaml`，并通过来源索引和审核记录校验条目。旧团队库的 `catalog/knowledge.yaml`、`knowledge/` 和 `sources/index.json` 仍可读取。对于 `approved` 条目，审核记录必须指向同一条知识，包含审核人、决定时间和决定依据，并且记录的正文 SHA 必须与当前提交中的正文一致。

Git 合并或 PR 合并只说明文件变更已经进入仓库，不等于知识通过审核。普通格式需要正确写入 Wiki 审核元数据；Catalog 格式还需要有效的审核记录和正文 SHA。

## Recall 怎样展示团队结果

显式执行 `oks recall` 时，团队知识通过独立的 `team_knowledge` 通道查询。它使用自己的词语匹配分数，不与个人 Wiki 的 BM25、衰减或目标加权分数混合比较。结果一起显示，只表示它们都匹配当前查询，不表示团队结果比个人结果更可信。

`--knowledge-only` 只关闭 Raw 和 Profile 所在的 `episodic` 通道，仍会查询个人 Wiki 和团队知识。当前默认 Prompt Hook 只把个人 `knowledge` 结果注入上下文，不会自动注入 `team_knowledge`；需要团队内容时，应显式执行 Recall 并检查返回来源。

团队结果会保留库名、仓库标识、commit、路径和正文 SHA。VFS 可以通过 `oks://team/<source-name>/...` 读取已建立索引的团队文件。这个入口仍然是只读视图，不能访问任意仓库路径，也不能执行文件内容。

Recall 命中不等于 Agent 已采用该知识。Agent 还要检查提交版本、适用项目、审核方式和正文内容。查询与使用记录的区别见[查询、使用与评测记录](linked-knowledge-observability.html)。

## 怎样向团队库贡献内容

个人库关联团队库后，不会获得写入团队库的通道。要贡献内容，应在团队仓库自己的工作区中准备 Candidate、证据和审核记录，再按团队的 Git 流程提交。个人信息和私有材料在进入团队仓库前需要单独检查。

个人补充可以继续留在个人库，并在正文中引用团队条目的库名、路径和 commit。标题相同不会让 OKS 自动认定两页知识相同；跨库关系需要使用明确 ID、相对链接或 `oks://team/` 链接。

## 工具仓库不是知识库

`open-knowledge-studio/` 保存 CLI、Studio、内置 Skill、测试和本文档。安装或升级 Python 包会更新工具，不会替换个人库和团队库。

源码仓库为了保持发布内容干净，默认忽略其中的本地 `wiki/`、`raw/`、`drafts/` 和 `.oks/` 数据。普通 Instance 的 `.gitignore` 则允许跟踪知识和可共享记录，只默认排除 `.oks/` 等本机状态。把日常知识写进工具仓库，既容易选错活动知识库，也可能让内容没有进入 Git。

开发 OKS 时可以在工具仓库运行测试和修改文档；维护个人或团队知识时，应使用 `oks init` 或 `oks team init` 创建的独立 Instance。各目录的具体职责见[知识库目录与本地状态](instance-layout.html)。
