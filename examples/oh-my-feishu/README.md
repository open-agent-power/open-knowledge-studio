# 案例：飞书采集审核闭环

把飞书当 OKS 的「日常控制面」——手机提交、异步采集、IM 里审核。
本文是可照做的操作流程；配套示例 goal 见 [`goal.md`](goal.md)。

> **飞书是可选组件，且已从 OKS CLI 核心迁出。** 自 v0.5 起，飞书集成作为
> 参考脚本位于 [`code/`](code/)（`feishu_base_worker.py` / `feishu_setup.py` /
> `feishu_worker/` 包），不再随 `oks` 命令分发。不配置它，`oks ingest` +
> `oks drafts promote` 的 CLI 路径完整可用。本案例的价值在于展示「人在环」
> 如何降到手机上一句话。脚本的安装与子命令清单见 [`code/README.md`](code/README.md)。

## 它解决什么

| 环节 | 没有飞书 | 有飞书 |
|---|---|---|
| 提交来源 | 回到电脑，由 Agent `/ingest` 或运行 `oks ingest run <url>` | 手机填表单，两下提交 |
| 采集等待 | 前台占着终端 | worker 异步跑，完成后推送通知 |
| 审核 | 打开终端看 draft、跑 promote | IM 里回一句 `通过` / `退回：理由` |

瓶颈从来不是算力，是**人不在电脑前**。刷到值得存的东西，当下不记就没了。

## 前置条件

```bash
# 1. lark-cli 已安装并认证（OKS 不代管你的飞书凭据）
lark-cli auth
# 找不到时用 LARK_CLI_EXE 指定绝对路径（Windows 上尤其有用）

# 2. 提取能力按需安装（这些仍是 oks 核心能力）
oks capability install watch --yes      # 视频/音频
oks capability install document --yes   # Office/HTML
oks capability install pdf --yes        # PDF
```

以下命令均从 `examples/oh-my-feishu/` 目录运行，使 `code/` 在相对路径可达。

## 一次性配置

```bash
python code/feishu_setup.py             # 自动创建 Base + 采集表 + 表单
```

`feishu_setup.py` 会打印 Base token 与表单地址，默认**脱敏输出**；需要完整
凭据时加 `--show-credentials`（只在你信任的终端里用）。

把凭据写进环境变量，worker 从这里读：

```bash
export OKS_FEISHU_BASE_TOKEN="<setup 输出的 base token>"
export OKS_FEISHU_TABLE_ID="<setup 输出的 table id>"
export OKS_FEISHU_REVIEW_USER_ID="<你的飞书 user id>"   # 接收审核通知
```

表单地址收藏到手机，日常就用它提交。

## 日常循环

### 1. 提交（手机或命令行）

手机填表单即可。命令行等价写法：

```bash
python code/feishu_base_worker.py enqueue "https://www.youtube.com/watch?v=..." --thought "为什么想存这个"
```

`--thought` 是给未来的自己看的：**当时为什么觉得它值得存**。
这句话在起草候选时会被 Agent 读到，比标题有用得多。

### 2. 采集（worker 跑一条）

```bash
python code/feishu_base_worker.py run-once
```

一次处理一条待办：认领记录 → 探测来源 → 路由到提取器 → 产出 Raw Bundle →
回写状态。中途失败会记可重试标记，下次 `run-once` 重新捡起来。

需要连续服务就用**外部调度器**（cron / launchd / 任务计划）定期调它——
OKS 自己不内置调度器。

### 3. 起草候选

Agent 读 `raw/index.json` 找到就绪的 Bundle，读 `digest.md` 了解内容，
用自己的话写成候选（不是复制原文），然后：

```bash
python code/feishu_base_worker.py publish-candidate --record <record-id>
```

候选会推送到你的飞书。

### 4. 审核（IM 里一句话）

在飞书回复即可，中英文都认：

| 你回复 | 含义 | 结果 |
|---|---|---|
| `通过` / `accept` | 接受 | 候选晋升为 wiki 页 |
| `修改：<意见>` / `edit` | 需要改 | 退回并附上你的意见 |
| `拒绝：<理由>` / `reject` | 不要 | 关闭，记录理由 |
| `暂缓` / `defer` | 先放着 | 保持候选状态 |

`edit` 与 `reject` **必须**附理由——退回的信息量比通过大，值得写一句。

拉取并应用审核结果：

```bash
python code/feishu_base_worker.py listen-reviews --max-events 1 --timeout 5m
python code/feishu_base_worker.py review-once          # 应用审核动作并晋升已接受的候选
```

漏掉的回复可以补：

```bash
python code/feishu_base_worker.py reconcile-review --record <record-id>
```

## 状态机速查

worker 在 Base 的「运行状态」字段流转，全部取值定义在
[`code/feishu_worker/states.py`](code/feishu_worker/states.py)（单一事实源，
`feishu_setup.py` 建表时的选项由它生成）：

```
待处理 → 已领取 → 探测中 → Raw就绪 → 候选待审 → 已晋升
                     ↓                    ↓
              可重试失败 / 最终失败    已拒绝 / 需人工
                     ↓
                  需授权
```

| 状态 | 你该做什么 |
|---|---|
| `可重试失败` | 勾选「重试」，下次 `run-once` 会重新处理 |
| `最终失败` | 看「错误说明」，通常是来源本身不可达 |
| `需授权` | 来源需要登录，换公开链接或手动下载后走附件 |
| `需人工` | 提取质量不足，需要你判断怎么办 |

## 边界（这不是「自动化到底」）

- **人审不可跳过。** worker 只做机械采集与状态流转，是否进 wiki 由人决定——
  宪章 A3 的硬约束，飞书路径不例外。
- **worker 不做知识判断。** 它执行的是**你已经做出的判断**（那句「通过」），
  自己不评估内容好坏、不改写、不分级。
- **没有内置调度器。** `run-once` / `listen-reviews` 都是有界的一次性操作，
  连续运行靠外部调度器——这样你随时能停，也能看清每一步做了什么。

## 相关

- 参考脚本说明：[`code/README.md`](code/README.md)
- 示例 goal：[`goal.md`](goal.md)
- 收录资料与 Connector 边界：[`docs/reference/ingest.md`](../../docs/reference/ingest.md)
- 架构不变量：[`docs/concepts/constitution.md`](../../docs/concepts/constitution.md)
- Candidate 人工审核：[`docs/review-candidates.md`](../../docs/review-candidates.md)
