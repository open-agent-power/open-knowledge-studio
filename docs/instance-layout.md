---
title: 知识库目录与本地状态
nav_order: 6
parent: 工作原理
---

# 知识库目录与本地状态

一个 OKS Instance 就是一个独立的知识库目录。`oks init` 会创建基础目录、默认配置和 Host 接入文件，后续命令再按需要写入材料、Candidate、知识页和记录。

目录名表示内容的用途，不表示内容已经通过审核，也不表示某项操作已经执行。`wiki/` 是知识页目录，不是“全部已审核”的目录；`.agents/skills/` 等 Host 目录中出现文件，也只能说明目录中已有副本。

## 目录概览

下面是常见结构。部分子目录只有在相应功能运行后才会出现。

```text
knowledge/
├── README.md                    # 本库的用途和使用前提
├── AGENTS.md                    # Agent 在本库工作时读取的项目说明
├── profiles/
│   ├── users/                   # 用户背景、偏好和边界
│   ├── projects/                # 项目背景和约束，不保存项目源码
│   ├── agents/                  # Agent 角色和协作约定
│   ├── recipes/                 # 场景步骤和验收条件
│   ├── goals/YYYY/MM/DD/        # 按日期保存的目标
│   └── discuss/YYYY/MM/DD/      # 按日期保存的讨论
├── raw/                         # 来源、原文、提取产物和处理状态
├── drafts/                      # 等待人工审核的 Candidate
├── wiki/                        # 知识页，审核状态以页面元数据为准
│   └── skills/                  # 审核后的 Skill 卡片及版本信息
├── skills/                      # 共享文件和旧版 Skill 路径的兼容目录
├── mail/                        # Agent 间的消息和交接文件
├── settings/                    # Recall、关联知识库等持久配置
├── records/                     # 审核、评测、时间线、迁移等可追查记录
├── .agents/skills/              # 某些 Host 可直接读取的项目级 Skill
├── .claude/skills/              # 其他 Host 的项目级 Skill，按安装情况出现
└── .oks/                        # 锁、缓存、运行工作区等本机状态
```

知识库不负责保存当前项目的全部源码和产物。项目仍放在自己的工作区，`profiles/projects/` 只记录理解项目所需的背景、约束和引用。

## Raw、Candidate 和 Wiki

这三个目录对应不同的内容阶段：

| 目录 | 保存什么 | 不能据此断定什么 |
|---|---|---|
| `raw/` | 来源文件、原文、附件、提取结果、Evidence Fragment 和 Evidence Manifest | 来源中的说法正确，或材料已经整理成知识 |
| `drafts/` | Agent 根据证据整理的 Candidate | Candidate 已被接受，或已经进入 Recall |
| `wiki/` | 可供知识查询使用的知识页 | 页面一定经过人工审核，或仍适用于当前任务 |

Candidate 通过 `oks drafts promote` 后，会生成 `status: active` 的 Wiki 页面，并写入 `human_reviewed_at` 和来源 Candidate 的信息。`oks wiki create` 直接创建的页面是 `provisional`，没有这次人工审核记录。`oks wiki unarchive` 也只把页面恢复为 `provisional`。

因此，判断一页知识能否使用时，需要同时检查 `status`、`human_reviewed_at`、来源和适用范围。完整规则见[知识对象与生命周期](concepts/philosophy.html)。

## Profile、Goal 和讨论

`profiles/` 提供任务背景，不属于 Raw 到 Wiki 的中间步骤。

- `users/` 说明人的角色、偏好和限制。
- `projects/` 说明项目的技术背景、约束和外部仓库位置。
- `agents/` 说明 Agent 的角色和协作约定。运行中的 Agent 连接记录属于 `records/` 或 `.oks/`，不能只看 Profile 判断 Agent 是否在线。
- `recipes/` 保存某类任务的输入、步骤和验收条件。Recipe 不会自行运行。
- `goals/` 记录准备完成的事情和验收条件。
- `discuss/` 记录问题、判断和未确定事项。

编辑 Goal 或讨论只会修改相应文件。它不会自动执行目标，也不会把讨论内容变成 Wiki。

## `records/` 与 `.oks/` 的区别

这两个目录都会保存记录，但用途不同。

`records/` 保存以后仍可能需要核对、共享或评测的数据，例如审核结果、Recall 使用记录、评测语料与结果、Studio 时间线、终端登记和目录迁移报告。默认 Instance 的 Git 配置允许跟踪这些文件，但是否提交仍取决于当前仓库的 `.gitignore` 和团队规则。

`.oks/` 保存本机运行状态，例如锁文件、临时任务、收录工作区、缓存、调试数据、Skill 加载回执和本地备份。`oks init` 生成的 `.gitignore` 默认排除整个 `.oks/`。因此，只备份 Git 仓库不能恢复全部本机运行状态。

不要把 `.oks/` 中出现的临时结果当作长期记录。需要留存的材料应进入 `raw/`，需要审核的提议应进入 `drafts/`，需要共享的执行或评测结果应写入对应的 `records/` 路径。

## Skill 有三种位置

文档中出现“Skill”时，要先确认指的是哪一层。

### 随 OKS 发布的 Skill

这些文件随 Python 包或源码仓库发布。`oks skills-install` 会把所选入口复制到当前知识库支持的 Host 目录；`oks skills-install --global` 会写入所选 Host 的全局目录。它们用于告诉 Agent 怎样操作 OKS，不属于用户积累的知识。

### 知识库管理的 Skill

`oks skills import` 会把一个 Skill 的文件快照保存到 `raw/`，并在 `drafts/` 创建 Candidate。人工审核后，Skill 卡片进入 `wiki/skills/`，其中记录版本、包哈希和来源。只有满足审核与状态要求的版本才能由 `oks skills load` 读取或加载到 Host。

根目录 `skills/` 仍用于共享文件和旧版路径兼容，VFS 也通过 `oks://skills/` 展示它。文件放在这里不会自动获得审核记录，也不会自动成为可加载版本。

### 供 Host 加载的 Skill 副本

`.agents/skills/`、`.claude/skills/`、`.qoder/skills/` 和 `.codebuddy/skills/` 等目录由对应 Host 读取。它们是运行入口或受控副本，不是知识审核记录。`oks skills load --target ...` 只负责写入副本并记录加载信息，不会执行 Skill 中的任务；Host 还可能要求重新加载项目或会话。

## 持久配置和关联信息

`settings/` 保存会影响后续命令的配置。常见文件包括 Recall 参数和 `settings/sources.yaml` 中的团队库关联。修改这些文件会改变以后怎样查询或读取知识，但不会改写已有 Raw、Candidate 或 Wiki。

机器级登记的知识库路径保存在用户目录下的 OKS 配置中，不在当前 Instance 里。也可以通过 `OKS_ROOT`，或在支持该参数的命令中使用 `--path` 选择其他知识库。执行写操作前，Agent 应先核对实际解析出的知识库路径。

## 旧目录迁移

旧版 Instance 可能使用根目录 `goal/`、`discuss/`、`skill/`，或把 Goal 和讨论文件直接放在 `profiles/` 的一级目录。可以运行：

```bash
oks layout-migrate
```

迁移会先检查目标文件冲突，再移动文件，并把路径、内容 SHA 和执行状态写入 `records/layout/migration.json`。兼容读取不等于文件已经迁移；需要统一目录时，应查看迁移报告并核对实际文件。

个人库、团队库和工具仓库的区别见[个人库、团队库与工具仓库](knowledge-repositories.html)。备份范围见[备份与导出](connect/backup-export.html)。
