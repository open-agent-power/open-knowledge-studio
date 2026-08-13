---
title: 确认 OKS 正在工作
nav_order: 4
parent: 开始使用
---
# 确认 OKS 正在工作

按顺序检查，不要一次排查整个架构。

## 安装与实例

```bash
oks --version
oks status
```

通过：两条命令正常退出，`status` 指向你当前的知识库。

失败：确认 Python 3.12+、重新打开安装 pipx 后的终端，并检查当前目录或
`OKS_ROOT`。

## 摄入准备

```bash
oks ingest prepare <文件或URL>
```

通过：输出 Run Workspace 路径和下一步说明。公开 URL 的远程处理策略默认是
`ask`，不是自动授权。

失败：本地文件应先确认路径存在；URL 不应包含需要绕过的登录、付费墙或 DRM。

## Candidate 与审核

```bash
oks drafts list
```

通过：可以看到 Agent 生成的 Candidate。晋升后它离开待审队列并进入 Wiki；
拒绝后会保存最小审阅回执。

失败：检查 Agent 是否完成证据提交和 A/B/C 分级。B/C 级不会生成 Candidate，
但应在结果中保留判断与理由。

## Recall

```bash
oks recall "你的主题"
oks recall "你的主题" --knowledge-only
```

通过：第一条可返回 Raw episodic 与 Wiki knowledge；第二条只返回 Wiki。
`raw/executions/` 和 `raw/.logs/` 是溯源记录，不参与 Recall。

仍有问题时运行：

```bash
oks lint
oks capability status
```

然后查看[能力边界与选型指南](capability-boundaries.md)或在 GitHub 提交包含命令、
退出状态和已脱敏输出的问题。
