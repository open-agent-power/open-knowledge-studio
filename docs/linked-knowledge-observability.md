---
title: 查询、使用与评测记录
nav_order: 7
parent: 工作原理
---

# 查询、使用与评测记录

本页说明怎样检查 Recall、VFS 和人工反馈留下的记录。内容面向需要排查查询结果或制作评测集的维护者。第一次使用 OKS 不需要配置这些记录。

团队知识库的格式、Git 提交读取规则和审核边界见[个人库、团队库与工具仓库](knowledge-repositories.html)。本页不重复这些规则，只说明一次查询及其后续操作分别留下什么记录，以及这些记录能证明什么。

## Recall 返回了什么

先查看命令本身的结果：

```bash
oks recall "任务问题" --format json --explain
```

JSON 中有三条结果通道：

| 通道 | 内容 |
|---|---|
| `episodic` | `raw/` 中的材料，以及符合当前身份范围的 Profile |
| `knowledge` | 当前个人库中的 Wiki |
| `team_knowledge` | 已关联团队库中符合读取条件的知识 |

`--knowledge-only` 只关闭 `episodic`，不会关闭 `team_knowledge`。默认 Prompt Hook 会执行 Recall，但当前只把个人 `knowledge` 注入提示词；命令返回团队结果，不表示 Hook 已把这些结果交给 Agent。

每次 Recall 还会把一条调用记录写入 `records/observability/recall.json`。记录包含查询哈希、命中来源、阶段耗时和输出大小，不保存问题原文，也不记录 Host 或模型之后做了什么。该文件最多保留最近 200 条记录。

## 这些事件分别说明什么

| 事件 | 能说明什么 |
|---|---|
| Recall 命中 | 检索器认为条目与问题相关 |
| Hook 注入 | Host 收到了 Hook 选中的个人知识 |
| Agent 采用 | Agent 实际把某条内容用于当前任务 |
| `oks wiki use` | 系统保存了一次明确的使用声明 |
| 人工审核 Candidate | 用户接受了当时展示的 Candidate 版本 |
| 评测标签 | 用户针对一次查询确认了相关或不相关条目 |

前一个事件不能自动推出后一个事件。检索分数高也不能证明答案正确或任务已经完成。

## 记录实际使用

```bash
oks wiki use <slug> --observation <observation_id>
```

`oks use` 是同一命令的别名。提供 `observation_id` 时，使用记录会关联到那次查询；不提供时只保存一条独立使用记录，不会猜测它属于最近哪次 Recall。

自动注入记录保存在 `records/inject.jsonl`。旧记录中的整组 `used` 只能说明有人报告使用了该组中的内容，不能证明每个命中都被采用。`oks wiki use` 也不会提升 `confidence`、修改 Wiki 状态或生成审核证据。

## 收集人工反馈

评测采集默认关闭。需要制作数据集时先开启：

```bash
oks eval capture --enabled --hash-query
oks recall "任务问题" --format json
oks eval candidates
```

`--hash-query` 只保存问题哈希。只有明确使用 `--retain-query` 时，评测观察记录才保留问题原文。

检查某次观察后，逐条提交判断：

```bash
oks eval review <id> \
  --query "任务问题" \
  --accept useful-slug \
  --reject irrelevant-slug \
  --reason "与当前任务范围不符" \
  --confirm
```

没有标签的命中保持未知。明确的 Use 记录只是参考信号，不会自动变成相关性标签。`--clear <slug>` 可以撤回已有标签；如果审核时改写了原问题，还要使用 `--derived-query` 明确表示这是派生问题。

反馈与来源版本绑定。Wiki 正文变化后，旧标签不能直接导出，必须重新查询并审核。

## 导出评测数据

```bash
oks eval export --name personal-recall --kind recall
oks eval export --name personal-preferences --kind preference
```

`recall` 数据集需要至少一条已确认的相关 Wiki。`preference` 数据集还要求同一次查询同时有接受和拒绝的条目，然后按版本生成知识选择偏好对。它只记录检索结果之间的选择，不是完整对话训练数据。

评测数据位于 `records/evaluation/`，其中包括：

- `observations/`：开启评测采集后保存的查询观察。
- `use-events/`：显式 Use 记录。
- `feedback/` 与 `feedback-events/`：当前标签和追加式审核事件。
- `exports/`：导出的评测集或偏好对。

检索调试记录、Recall 调用记录和旧注入记录也可以出现在候选列表中，但只有明确确认且来源版本未变化的标签能进入导出结果。

## 观察 VFS 读取

Studio 的“学习 > 文件”和 `oks fs` 使用同一套只读 VFS 路径。常用命令：

```bash
oks fs ls oks:// --format json
oks fs read oks://wiki/example.md --format json
oks fs read-many oks://wiki/a.md oks://wiki/b.md --format json
oks fs inspect oks://wiki/example.md --operation compare --limit 20000
```

`oks://skills/` 指向知识库管理的 Skill。Host 的 Skill 安装目录不会显示在根目录；旧的 `oks://host-skills/`、`oks://skill/`、`oks://goal/` 和 `oks://discuss/` 只保留兼容读取。关联团队库后，根目录还会出现动态的 `oks://team/` scope。

普通 `oks fs` 命令保持原有输出，同时保存调用记录。`oks fs inspect` 支持 `ls`、`stat`、`read`、`overview`、`find` 和 `compare`，并把结果与步骤时间线一起返回。记录包含解析、读取、裁剪和序列化等实际步骤，也会保留失败状态，但不保存读取到的正文。

VFS 历史位于 `records/observability/vfs.json`，最多保留 200 条。VFS 与 Recall 记录都不是 Agent 的思考过程。

## 怎样理解耗时数据

`compare` 固定读取同一文件、同一 `offset` 和 `limit`，先走 VFS，再直接读取文件或 Git blob。它检查两次读取的内容是否一致，并展示这一对操作的耗时。

这个数字不能用来证明某种读取方式普遍更快，原因包括：

- 操作系统缓存没有被控制，执行顺序也固定。
- 计时不包含记录持久化、HTTP 请求、Host 执行和模型执行。
- `output_bytes` 是序列化结果的字节数，不是模型 Token 数。
- 单次读取只代表该文件、该提交和该切片。

要比较 Recall 配置，应固定知识库快照和同一评测集，再运行离线评测。方法见[召回评估](algorithms/recall-evaluation.html)。
