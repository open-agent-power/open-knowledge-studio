---
title: 系统由哪些部分组成
nav_order: 1
parent: 工作原理
---

# 系统由哪些部分组成

OKS 由工具和知识库两部分组成。工具安装在 Python 环境中，提供 `oks` CLI 以及随发行版提供的 Skill、Hook 脚本和 Studio。知识库是另一个独立文件夹，保存你自己的 Markdown、来源文件、配置和记录。升级 OKS 工具不等于替换知识库，切换知识库也不需要复制源码仓库。

## 各部分的职责

| 部分 | 负责什么 | 不负责什么 |
|---|---|---|
| 人 | 提供目标和材料；审核 Candidate；决定知识是否继续使用 | 不需要手工记住所有命令或内部字段 |
| Agent | 理解任务；阅读材料；调用 Skill 和 CLI；整理 Candidate；解释 Recall 结果 | 不能用自己的判断代替人的审核决定 |
| CLI | 创建目录；校验和保存文件；记录审核决定；执行查询和维护命令 | 不会自行理解一篇材料应得出什么结论 |
| Skill | 给 Agent 提供操作步骤、约束、脚本和资源 | 不是后台进程，也不会仅因安装就自动执行 |
| Hook | 在宿主支持的事件上调用查询或记录逻辑 | 是可选集成；没有 Hook 仍可显式运行命令 |
| Studio | 在本地网页中查看和编辑知识库、审核 Candidate、检查查询与评测结果 | 不是 Agent；打开页面不会自动执行任务 |
| 知识库 | 保存 Raw、Candidate、Wiki、Profile、Goal、Skill 和记录 | 不训练模型，也不会自动同步到其他电脑 |

实际工作通常是：你提出任务，Agent 根据需要读取 Skill，调用 CLI 读取或修改知识库，再把结果交给你检查。Hook 可以在宿主支持时自动触发其中一部分操作；Studio 提供另一种查看和编辑同一批文件的方式。

```text
你给出任务、材料和决定
          │
          ▼
Agent 理解任务并选择操作
          │
          ├── 读取 Skill
          ├── 调用 oks CLI
          └── 读取或修改知识库文件
                    │
                    ├── Raw / Candidate / Wiki
                    ├── Profile / Goal / Skill
                    └── Mail / Trace / records

可选：Hook 在宿主事件上调用命令
可选：Studio 展示和编辑同一知识库
```

## 主要内容流

{% include knowledge-cycle.html %}

这条路径分成三件事：收录协议保存 Source 和提取结果，Agent 根据证据整理 Candidate，人针对 Candidate 的具体版本作出审核决定。只有 Promote 会把已接受版本和审核证据一起写入 Wiki。对象状态、直接创建 Wiki 和取消归档等规则见[知识对象与生命周期](philosophy.html)，收录细节见[材料收录协议](../reference/ingest.html)。

Recall 位于这条路径的读取端。它返回可能相关的 Raw、Profile、个人 Wiki 和团队知识，Agent 再判断哪些内容适用于当前任务。查询、注入、采用和显式 Use 记录的区别见[查询与引用](../usage/recall.html)。

## 与内容流并行的记录

Profile、Goal 和讨论保存背景、范围与未确定事项，不是 Raw 到 Wiki 的中间阶段。Mail、Trace、任务记录和 `records/` 保存协作或执行事实，也不会自动变成知识。它们可以引用 Raw、Candidate 和 Wiki，便于后来核对来源和进度。

## 可选接口

没有 Hook 时，Agent 仍可显式运行 Recall 和其他命令。Hook 只是在 Host 支持的事件上调用这些能力。Studio 读取同一个知识库，提供浏览、编辑和审核界面；打开页面不会启动 Agent，也不会自动完成任务。

下一步阅读[知识对象与生命周期](philosophy.html)，或直接完成[第一次实践](../first-knowledge-loop.html)。
