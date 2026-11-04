---
title: 安装与创建知识库
nav_order: 1
parent: 开始使用
---

# 安装与创建知识库

把下面这段话交给你正在使用的 Agent。它需要能读取文件和执行本机命令。

```text
帮我安装或连接 Open Knowledge Studio。
先阅读 https://raw.githubusercontent.com/open-agent-power/open-knowledge-studio/main/SKILL.md，
检查本机环境和已有知识库；有实例就先连接，没有再创建独立知识库。
不要把个人资料放进 OKS 源码仓库。完成后告诉我知识库在哪里、
哪些能力可用、哪些步骤没有完成，以及我下一步该怎么做。
```

## 看什么结果

Agent 应展示当前连接的知识库位置、可用能力和下一步入口。新知识库没有长期知识是正常状态，不需要为了安装验收创建或批准知识。

Python 3.12 或更新版本、Git 和安装方式由 Agent 检查；已有知识库和配置需要替换时，应先说明影响并征得你的确认。自动召回按需开启，首次使用可以直接在对话中要求查询。

## 接下来这样说

```text
带我用一份短材料完成第一次知识循环。
每一步都告诉我保存了什么、在哪里查看，以及哪些内容需要我审核。
```

跟着[第一次知识循环](first-knowledge-loop.html)继续。有问题时，把错误交给 Agent，参考[故障排除](reference/troubleshooting.html)；需要自行操作的开发者可以查[手工安装](reference/cli.html#手工安装)。
