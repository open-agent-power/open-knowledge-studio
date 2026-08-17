---
title: 安装
nav_order: 2
parent: 开始使用
---
# 安装

要求：Python 3.12+、Git、pipx。

## 推荐安装

```bash
pipx install open-knowledge-studio
oks --version
oks init ./my-knowledge-base
cd ./my-knowledge-base
oks status
```

`oks init` 会创建文件式知识库，并安装 Claude Code、Codex 和通用 Agent 所需的
Skills。个人知识应保存在这个实例目录，而不是 OKS 工具源码仓库。

<details markdown="1">
<summary>还没有 pipx？</summary>

- Ubuntu：`sudo apt install pipx && pipx ensurepath`
- macOS：`brew install pipx && pipx ensurepath`
- Windows：`py -m pip install --user pipx && py -m pipx ensurepath`

安装后如果终端找不到 `oks`，重新打开终端再运行 `oks --version`。
</details>

{: .note }
源码 editable 安装属于贡献者工作流，不是普通用户的 Quick Start。

## 安装结果

成功时：

- `oks --version` 返回版本号；
- `oks status` 能读取当前知识库；
- 当前目录包含 `raw/`、`wiki/`、`drafts/`、`profiles/`、`mail/`、`settings/` 和 `_meta/`。

下一步：[完成第一个知识闭环](first-knowledge-loop.md)。
