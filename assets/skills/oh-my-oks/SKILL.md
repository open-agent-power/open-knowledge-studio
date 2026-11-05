---
name: oh-my-oks
description: 操作本地 Open Knowledge Studio：查阅知识、记录讨论、维护每日目标、整理材料与知识候选、按已有人工决定审核更新。适用于使用或维护 OKS 知识库。
---

# Oh My OKS

围绕用户当前需要选择 Discuss → Goal → Learning 的最小闭环。OKS 保存上下文和证据；执行由当前 Agent 承担。

先用 `oks status` 确认知识库。用户已经提供路径时沿用该实例，跨目录通过 `OKS_ROOT` 指定，不擅自更换全局默认库。

- **讨论与目标**：查阅 [references/context.md](references/context.md)。讨论保留人的判断、AI 理解与待确认；每日目标以 Markdown 分支维护，修改可回放。
- **查阅与学习**：查阅 [references/learning.md](references/learning.md)。按任务查证据、准确记录采纳、把可复用结论写成待审核候选。
- **维护**：需要检查状态、链接或目录时查阅 [references/maintenance.md](references/maintenance.md)。

每次只读取所需参考，不预加载全部知识或能力。已有项目配方可提供该场景的输入、约束和验收方式，按需组合，不能从 cron 字段推断任务已运行。

个人知识与团队库保持各自仓库。遵守用户当前授权；保存材料或形成候选不等于同意安装能力、发消息、提交 PR 或发布。

本 Skill 保留基本知识操作。Office 生成、媒体处理、跨 Agent 通信、复杂评测和宿主适配按用户实际需要使用对应能力，不作为默认学习步骤。
