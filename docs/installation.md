---
title: 安装与创建知识库
nav_order: 1
parent: 开始使用
---

# 安装与创建知识库

把下面这段话交给你正在使用的 Agent。它需要能读取文件和执行本机命令。

```text
请按 https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md 帮我安装或连接OKS，配置个人库和可选团队库，并在对话中带我体验 Discuss → Goal → Learning。
```

## 看什么结果

Agent先检测已有环境和实例，按当前宿主安装全局`oh-my-oks`入口；询问是否关联团队库，接受Git地址、本地目录或跳过。个人与团队文件独立，OKS逻辑关联。全局Skill与自动hook分别确认，不保证所有宿主均支持。

Agent应展示当前连接的知识库位置、入口作用范围、团队连接结果和下一步。新知识库没有长期知识是正常状态，不需要为了安装验收创建或批准知识。

Python 3.12 或更新版本、Git 和安装方式由 Agent 检查；已有知识库和配置需要替换时，应先说明影响并征得你的确认。自动召回按需开启，首次使用可以直接在对话中要求查询。

## 接下来这样说

```text
带我用一份短材料完成第一次知识循环。
每一步都告诉我保存了什么、在哪里查看，以及哪些内容需要我审核。
```

教学进度和网页共用`records/studio/onboarding.json`，可跳过或继续。新用户用当前的一件真实小事，逐步理解讨论、目标、学习；已有用户不重复走一遍。

跟着[第一次知识循环](first-knowledge-loop.html)继续。有问题时，把错误交给 Agent，参考[故障排除](reference/troubleshooting.html)；需要自行操作的开发者可以查[手工安装](reference/cli.html#手工安装)。
