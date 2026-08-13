---
title: CLI
nav_order: 1
parent: 参考
---
# CLI 参考

`oks` 命令清单 + 关键契约。日常用前几个，后几个是改协议 / 写 Provider / 做评测时才查。

## 命令清单

| 命令 | 用途 |
|------|------|
| `oks init <path>` | 创建实例（物化认知桶、配置、Schema 与 Agent skills） |
| `oks status` | 知识库概览（wiki/raw 计数 + tier + 质量） |
| `oks metrics [--html]` | 知识指标；可生成基于注入与反馈记录的本地 HTML 报告和调参建议 |
| `oks recall "<q>"` | 召回（6+1 因子，双路 wiki + raw） |
| `oks ingest run <src>` | 摄入材料 → Raw Bundle |
| `oks ingest prepare <src>` | 生成 ingest 协议骨架 |
| `oks wiki create/list/get/pin/archive/use/export` | wiki 页管理 + OKF 导出 |
| `oks drafts list/promote/reject` | draft 候选审核 |
| `oks distill [--dry-run]` | 衰减 + 演化（dreaming 后半） |
| `oks capability list/install/status/guide` | 能力注册与选择指导 |
| `oks hook install/status` | opt-in 自动 recall 注入 |
| `oks trace *` | 执行追踪（provenance） |
| `oks mail send/inbox/read/count` | Agent 间消息接口；不属于 `oks recall` 结果 |
| `oks registry list/bind/remove` | 终端注册表（agent+cwd → profile/goal） |
| `oks lint` | 扫 wiki/ 一致性 |
| `oks config init/show/set` | 配置 |
| `oks security sanitize <file>` | 凭据脱敏 |
| `oks eval recall <dataset>` | 召回离线评测 |

完整命令：`oks --help`。

Registry、Mail 和 `records/*.jsonl` 使用独立的运行路径，不由 `oks recall` 返回。
`records/inject.jsonl` 记录哪些页面被注入，`oks wiki use` 可标记其是否被实际采用；
仅记录这些信号不会提升 `confidence`、改变审核状态或产生 `[verified]`。

## Frontmatter 字段

wiki 页 frontmatter（完整契约在仓库 `_meta/`）：

| 字段 | 说明 |
|------|------|
| `title` / `type` / `area` | 标题 / 类型（concept \| strategy \| anti-pattern）/ 知识域 |
| `status` | provisional \| active \| stale \| dropped \| superseded |
| `importance` / `confidence` | 0-1，人工设定重要性 / 可信度 |
| `created` / `human_reviewed_at` | 时间戳 |
| `pinned` / `archived` | 固定（不衰减）/ 归档（退出召回） |
| `tags` / `fingerprint` | 标签 / 内容指纹（dedup） |
| `traces` | evidence 链接（provenance） |
| `review` | `decision_correct` / `outcome` / `lesson` |
| `relates_to` / `relationship` | A4 关系（enriches / supersedes / confirms / challenges） |

draft frontmatter 用 `draft_type` / `draft_area`（不是 `type` / `area`），否则 promote 时 fallback 到 concept/computing。

## Trace 命令（provenance）

```bash
oks trace start <goal-id> --run-id <id>
oks trace append <id> --type retrieval --actor agent --payload '<json>'
oks trace judge <id> --outcome pass --comment "..."
oks trace feedback <id> --outcome accepted --comment "..."
oks trace blocker <id> --reason "..." --needed "..."
oks trace propose <id> --kind wiki --title "..." --summary "..."
oks trace finish <id> --result '{"outcome":"success"}'
oks trace validate <id> --completed
oks trace show <id>
```

轨迹存 `raw/executions/<id>/events.jsonl`，**排除召回**（provenance 非记忆）。`blocker` 需同时写 `reason` + `needed`，只有 `human_action` / `checkpoint` 能解除——agent 无法自解锁。`propose` 写 `drafts/proposals/`，不改正式 wiki。

## Raw Bundle 协议

机器可读事实源在仓库 `schemas/`（包内镜像 `knowledge_studio/schemas/` 做强制校验）：

- `capture-envelope.schema.json` — 来源信封
- `capability-manifest.schema.json` — 能力清单
- `processing-run.schema.json` — 处理运行
- `raw-bundle-v0.2.schema.json` — Raw Bundle v0.2

当前版本 `raw-multimodal/v0.2`。OKS 负责 Capture 编排 + Candidate + 人审 + wiki 晋升 + 召回；来源获取后的机械解析、证据定位、质量状态由独立发布的 `oks-connector` 负责。摄入流程见 [ingest](ingest.md)。

## Provider 凭证治理

远程 provider（Firecrawl 等）调外部 API：

- **凭据来源**：环境变量（`FIRECRAWL_API_KEY` 等）/ MCP session token / OS keychain（未来）。绝不硬编码、入 git、CLI 参数或 Recipe。
- **政策**：SourceEnvelope 的 `policy.remote_processing`（`deny` / `allow` / `ask`）控制是否调远程。`deny`=本地，`allow`=显式允许，`ask`=提示。Agent 必须遵守。
- **脱敏**：外部输出经 `oks security sanitize` 脱 API key / bearer / cookie / 内部 IP 后才入 Raw Bundle。键名规则（`*_token`、`*_secret` 等）+ 值扫描（AWS `AKIA...`、GitHub `ghp_...`、OpenAI `sk-...`、PEM 头）。best-effort，非完整防泄漏。
- **隔离**：每次 ingest 在 `.oks/runs/{run_id}/work/<provider>/` 隔离运行空间，raw output 落盘 + 校验大小后才做语义处理。
