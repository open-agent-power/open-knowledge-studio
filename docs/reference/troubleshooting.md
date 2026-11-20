---
title: 故障排除
nav_order: 3
parent: 参考手册
---

# 故障排除

排查 OKS 时，先确认两件事：当前运行的是哪一份 `oks`，命令实际连接的是哪个知识库。保留终端中的原始错误和 `partial`、`failed`、`skipped` 状态，不要先删除目录或重装全部能力。

## 先做基础检查

```bash
oks --version
oks status
oks config show
```

`oks status` 显示的是本次命令实际使用的知识库。`oks config show` 显示用户级默认路径，两者不一定相同：`OKS_ROOT`、当前所在的有效知识库和用户配置都可能影响路径选择。

如果 `oks` 命令不存在，先运行 `pipx list` 检查 `open-knowledge-studio` 是否已经安装。已经安装但终端找不到命令时，运行 `pipx ensurepath` 后重新打开终端；尚未安装时按[安装与创建知识库](../installation.html)安装。不要通过重新初始化知识库来修复 PATH。

## 当前知识库不对

先比较 `oks status` 与 `oks config show` 中的路径，并检查当前终端是否设置了 `OKS_ROOT`。临时任务可以显式设置 `OKS_ROOT`；需要修改用户级默认值时运行：

```bash
oks config set knowledge_base_path <知识库路径>
oks status
```

修改后再次查看 `oks status`。只有它显示预期路径时，才继续收录、审核或编辑。切换知识库不会复制旧库中的 Raw、Candidate 或 Wiki。

## 材料没有收录成功

先检查当前机器有哪些可用 Provider：

```bash
oks capability status --text
oks ingest prepare <来源>
```

`oks ingest prepare` 会报告材料类型、运行目录、候选 Provider 和缺失资源。检查 Source 是否可访问、远程处理策略是否允许，以及 Recipe 要求的能力是否可用。Provider 失败时保留它的原始输出和错误，不要把步骤改写成成功。

如果已经得到 `run_id`，可以检查已保存的收录、Candidate 和可选 Mail 记录是否能互相对应：

```bash
oks ingest validate <run_id>
```

`raw-commit` 报错时，按错误中的文件路径检查 Manifest、Artifact、哈希、Fragment 引用和 `work/<provider>/output.*`。协议对象及常见校验项见[收录操作手册](ingest/agent-native-ingest-walkthrough.html)。

## Recall 没有找到预期内容

```bash
oks status
oks recall "<查询内容>" --explain
oks recall "<查询内容>" --knowledge-only --explain
```

先确认查询的是正确知识库。再检查目标内容是否真的位于 Wiki、是否被归档，以及状态是否为 `dropped` 或 `superseded`。`--knowledge-only` 只关闭 Raw 和 Profile 查询，已关联的团队库仍可能返回结果。

如果结果能命中但 Agent 没有使用，要求它打开命中页面，核对状态、审核记录、来源和适用范围。Recall 命中与 Agent 实际采用是两个事件。

## Hook 没有自动 Recall

先运行一次显式 Recall。显式查询也失败时，先处理知识库或检索问题；显式查询正常时，再检查 Hook：

```bash
oks hook status --path <知识库路径> --workspace <工作目录>
```

输出会分别说明脚本是否存在、解释器是否可用、Host 配置是否接线。`wired` 只表示本地配置存在，不能证明 Host 已经触发。需要重新安装时，先用 `oks hook install --help` 查看当前版本支持的 Host 和参数。

## Studio 打不开

先检查指定知识库的托管服务状态：

```bash
oks mail serve --path <知识库路径> --status
```

状态为 `stopped` 时，在前台启动：

```bash
oks mail serve --path <知识库路径>
```

终端会打印实际地址，默认是 `http://127.0.0.1:3182/`。端口被占用时用 `--port <端口>` 更换端口。打开页面后先核对右上角的知识库路径；服务只绑定本机回环地址，不能直接从另一台电脑访问。

## Candidate 接受后没有 Wiki

先确认 Agent 审核的是刚才展示的 Candidate 版本，并实际执行了 Promote：

```bash
oks drafts list
oks drafts get <slug>
oks drafts promote <slug>
```

接受消息、移动文件或直接运行 `oks wiki create` 都不能代替 Candidate 审核。Promote 成功后，检查生成的 Wiki、`human_reviewed_at` 和 Candidate 来源记录。详细步骤见[审核 Candidate](../usage/review.html)。

## 让 Agent 协助排查

可以把原始错误连同下面的要求交给 Agent：

```text
请排查这个 OKS 问题。先运行 oks status，报告实际知识库路径和失败命令。
保留原始错误与未完成状态，按“检查结果、原因、修复动作、复查结果”说明。
不要清空知识库，也不要用直接创建 Wiki 绕过 Candidate 审核。
```

命令名称和参数可能随版本变化。以本机 `oks --help` 和 `oks <命令> --help` 为准。
