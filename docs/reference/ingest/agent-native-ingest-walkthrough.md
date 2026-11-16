---
title: 收录操作手册
nav_order: 1
parent: 材料收录协议
grand_parent: 参考手册
---

# 收录操作手册

本页说明 Agent 或维护者怎样把一个 URL 或本地文件保存为 Raw Bundle。日常使用不需要手工编辑这些 JSON 文件，可以直接按[收录材料](../../usage/ingest.html)向 Agent 说明任务。

## 开始前先确认范围

1. 确认当前知识库路径，避免把材料写入另一个 Instance。
2. 用 `oks recall` 查询同主题内容，检查是否已有相同来源、相关 Wiki 或待审核 Candidate。
3. 说明材料所属的项目、版本、日期和用途。
4. 检查是否允许把内容发送给远程 Provider。

`oks ingest prepare` 对公开 URL 默认写入 `remote_processing: ask`，对本地文件和手工来源默认写入 `deny`。URL 可以访问，不等于已经允许把内容转交第三方服务。

## 选择执行路径

内置 Connector 能处理来源时，可以运行：

```bash
oks ingest run <source>
```

这个命令负责获取和转换材料，不会生成带审核记录的 Wiki。需要由 Agent 选择 Provider、组合多个处理结果，或检查每一步证据时，使用下面的协议路径。

## 1. 准备运行目录

```bash
oks ingest prepare <source>
```

命令会在 `.oks/runs/<run_id>/` 下创建运行目录，并返回：

- `manifest_dir`：协议文件所在目录；
- `text_ready`：本地文本是否已经预填内容；
- `recipe`：当前材料类型需要哪些能力，什么条件算完成；
- `candidate_providers`：可能满足这些能力的 Provider；
- `missing_assets`、`sensitive_content_redacted` 等准备结果。

生成的目录主要包含：

```text
.oks/runs/<run_id>/
├── manifest/
│   ├── source-envelope.json
│   ├── evidence-manifest.json
│   ├── fragments/
│   └── artifacts/
└── work/
```

本地 Markdown、纯文本、CSV、JSON 和 YAML 通常会得到 `text_ready: true`。CLI 会预填文本证据，并把脱敏后的副本写入运行目录，不修改原文件。Markdown 引用的本地图片缺失时，Manifest 会标为 `partial` 并列出缺失资源。

其他材料只会得到处理计划。此时 `evidence_records`、`steps` 和 `modalities` 留空是正常情况，Agent 必须根据实际运行结果填写，不能把计划写成已经执行。

## 2. 运行实际需要的 Provider

先根据 Recipe 和 `candidate_providers` 选择能够处理当前材料的 Provider。选择时应检查：

- Provider 当前是否可用；
- 是否覆盖 Recipe 要求的能力；
- 是否需要远程传输、登录凭据或付费服务；
- 失败后是否有本地或降级路径。

需要具体调用说明时运行：

```bash
oks capability guide <provider-id>
```

每次调用都要记录实际 Provider、工具和结果。不能使用 `curl` 获取内容，却把记录写成另一个 Provider 的输出。

## 3. 保存 Provider 原始输出

工具返回后，把未改写的原始输出保存到：

```text
.oks/runs/<run_id>/work/<provider-id>/output.<ext>
```

Manifest 中步骤状态为 `succeeded`、`degraded` 或 `partial` 时，`raw-commit` 会检查对应目录中是否存在非空的 `output.*`。这项检查也适用于 `runtime-tool` 和 `text-read`。只有 `agent-runtime` 和 `human` 不要求外部工具输出文件。

`work/` 保存的是工具实际返回内容。Agent 生成的摘要、翻译或重排文本应另作证据记录，不能覆盖原始输出。

## 4. 按实际结果完成协议对象

非文本来源的骨架仍需补全：

1. 每个实际处理尝试写入对应 Evidence Fragment。
2. 把采用的证据汇总到 Evidence Manifest。
3. 将产物放入 `manifest/artifacts/`，填写文件哈希和证据位置。
4. 在 `steps` 中记录成功、部分完成、降级、失败或跳过的步骤。
5. 根据 Recipe 的 `complete_when` 条件判断 Manifest 是 `complete` 还是 `partial`。

Fragment 的 `status` 只能是 `succeeded`、`partial` 或 `failed`。`oks ingest prepare` 为非文本来源生成的骨架可能仍是 `pending`，提交前必须改成实际结果。

Manifest 的 `status` 只有 `complete` 和 `partial`。选择 `partial` 时，应在 `warnings` 中写清缺少的证据，并且必须把 `failure_disposition` 设为非 `none` 值，说明下一步需要授权、用户操作、重试，还是已经达到当前条件下的最终结果。

详细字段见[协议对象与状态](protocol-objects.html)。

## 5. 校验并保存 Raw Bundle

```bash
oks raw-commit .oks/runs/<run_id>/manifest/
```

`raw-commit` 会检查：

- Source Envelope、Evidence Manifest 和 Fragment 是否符合 Schema；
- `source_id`、`fragment_id`、`artifact_id` 和 `evidence_id` 的引用是否对应；
- Artifact 是否存在，SHA-256 是否匹配；
- Evidence Locator 是否符合格式；
- 步骤声明的 Provider 输出是否保存在 `work/` 中；
- Manifest 中的证据数量是否与各 modality 的计数一致。

通过后，CLI 先在临时目录组装完整 Raw Bundle，全部文件可用后再替换目标目录。校验失败时不会留下半个新 Bundle。

常见错误：

| 错误码 | 原因 | 处理方法 |
|---|---|---|
| `PROVENANCE_STEPS_MISSING` | Manifest 没有记录实际步骤 | 补全 `steps`，不要只写证据正文 |
| `PROVENANCE_UNVERIFIABLE` | 某个步骤缺少非空 `work/<provider>/output.*` | 保存该工具的原始输出，并核对 Provider ID |
| `MISSING_ARTIFACT` | 声明的 Artifact 文件不存在 | 检查 `artifacts/` 和相对路径 |
| `ARTIFACT_HASH_MISMATCH` | 文件内容与声明哈希不同 | 确认最终文件后重新计算哈希 |
| `ORPHAN_EVIDENCE` | Evidence 引用了不存在的 Artifact | 修正 `artifact_id` |
| `EVIDENCE_COUNT_MISMATCH` | modality 计数与证据条数不同 | 按实际证据更新计数 |
| `INVALID_LOCATOR` | 证据位置缺少类型或字段不合法 | 按 Locator Schema 修正位置 |

## 6. 检查保存结果

Raw Bundle 通常位于按日期组织的 `raw/` 目录。至少检查：

- `content.md` 是否能读取主要内容；
- `source/` 是否保存主要来源文件；
- `evidence.jsonl` 是否能回到具体 Artifact 和位置；
- `quality-report.json` 与 `bundle.json` 是否保留 `complete` 或 `partial`；
- `derived/` 是否保存 OCR、转写、截图或其他派生产物；
- 警告和失败没有被后续摘要覆盖。

Raw Bundle 保存成功只证明文件和协议引用通过检查。来源可信度、提取准确性和结论是否可复用仍要另行判断。

## 7. 决定是否提出 Candidate

Agent 在 Raw 保存后评估材料：

| 等级 | 处理方式 |
|---|---|
| A | 证据支持可复用内容，生成 Candidate |
| B | 材料有价值，但证据不足或只适用于当前情境，保留 Raw 和原因 |
| C | 重复、噪声或没有形成可复用内容，保留 Raw 和原因 |

只有 A 级生成 Candidate。Candidate 是 `drafts/` 中的 Markdown 文件，不是收录协议对象，也没有对应的 `oks schema show candidate`。

Candidate 使用 `draft_type` 和 `draft_area` 指定目标类型与领域。进入人工审核前，应写清 `source_bundle_id`、证据、适用范围和与已有 Wiki 的关系。具体审核步骤见[审核 Candidate](../../usage/review.html)。

## 8. 工作流校验不代替执行

Agent 可以为本次运行写入 `.oks/runs/<run_id>/result.json`，再执行：

```bash
oks ingest validate <run_id>
oks ingest finalize <run_id>
```

这两个命令读取已经保存的 Bundle、Candidate、审核和可选 Mail 记录，检查它们能否互相对应。`finalize` 不会重新获取来源、发送缺失的消息、批准 Candidate 或 Promote Wiki。只做独立材料收录时，使用 `oks ingest finalize <run_id> --source-only`。
