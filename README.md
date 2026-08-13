<div align="center">

<img src="docs/assets/oks-logo-readme.png" width="420" alt="Open Knowledge Studio">

# Open Knowledge Studio

Turn sources into reviewed, traceable knowledge that your Agent can recall later.

[English](#english) · [中文](#chinese) · [Documentation](https://open-agent-power.github.io/open-knowledge-studio/)

</div>

---

<a id="english"></a>

## English

Open Knowledge Studio (OKS) is an Agent-native, filesystem-first knowledge
workspace. It preserves source evidence, lets an Agent draft reusable knowledge,
keeps a human in control of promotion, and recalls the result in later work.

```text
your source → Candidate → human review → Wiki → Recall
```

### Quick Start

Requirements: Python 3.12+, Git, and pipx.

```bash
pipx install open-knowledge-studio
oks init ./my-knowledge-base
cd ./my-knowledge-base
oks status
```

In Claude Code, Codex, or another compatible Agent host, give the Agent a real
source and ask it to ingest it:

> Ingest this PDF into my OKS knowledge base.

The Agent follows the installed `/ingest` skill, records evidence, and creates a
Candidate in `drafts/`. Review it before promotion:

```bash
oks drafts list
oks drafts promote <slug>
oks recall "what did we decide?"
```

Without an Agent, prepare a run workspace explicitly:

```bash
oks ingest prepare <file-or-url>
```

`prepare` does not call an Agent. It creates the protocol workspace and prints
the next steps. For connector-managed acquisition, use
`oks ingest run <file-or-url>`; that compatibility path delegates extraction to
the separately packaged `oks-connector` runtime.

### Product Boundaries

- The `oks` core performs filesystem operations, validation, review lifecycle,
  and Recall scoring; it does not call AI APIs.
- `oks-connector` is a separate PyPI dependency that performs acquisition and
  extraction work.
- Providers create evidence, not Wiki knowledge. Human review is the promotion
  gate from Candidate to Wiki.
- Feishu is an optional reference implementation under
  [`examples/feishu-loop`](examples/feishu-loop/), not a Core CLI command or
  dependency.
- `partial`, `failed`, `skipped`, and `environment_limited` are honest outcomes,
  not states to hide.

### Learn More

- [Start here](docs/start-here.md)
- [Complete your first knowledge loop](docs/first-knowledge-loop.md)
- [Verify that OKS works](docs/verify-it-works.md)
- [Core architecture](docs/architecture/oks-core-architecture.md)
- [Capability boundaries](docs/capability-boundaries.md)

---

<a id="chinese"></a>

## 中文

Open Knowledge Studio（OKS）是一个 Agent-native、文件系统优先的知识工作台：
它保存来源证据，让 Agent 起草可复用知识，由人决定是否晋升，并在未来任务中重新召回。

```text
你的资料 → Candidate → 人工审核 → Wiki → Recall
```

### 快速开始

要求：Python 3.12+、Git、pipx。

```bash
pipx install open-knowledge-studio
oks init ./my-knowledge-base
cd ./my-knowledge-base
oks status
```

在 Claude Code、Codex 或兼容 Agent 中，把一份自己的真实资料交给 Agent：

> 把这份 PDF 收录到我的 OKS 知识库。

Agent 会按已安装的 `/ingest` Skill 保存证据，并在 `drafts/` 生成 Candidate。
审核后再晋升：

```bash
oks drafts list
oks drafts promote <slug>
oks recall "我们当时做了什么决定？"
```

没有 Agent 时，可以显式准备 Run Workspace：

```bash
oks ingest prepare <文件或URL>
```

`prepare` 不会自行调用 Agent，只创建协议工作区并输出下一步说明。需要 connector
托管采集时，使用 `oks ingest run <文件或URL>`；这条兼容路径把提取交给独立发布的
`oks-connector`。

### 产品边界

- `oks` Core 负责文件操作、协议校验、审核生命周期和 Recall 评分，不调用 AI API。
- 采集与提取由独立 PyPI 依赖 `oks-connector` 执行。
- Provider 产生证据，不直接产生 Wiki 知识；Candidate 必须经过人工审核。
- 飞书位于 [`examples/feishu-loop`](examples/feishu-loop/)；它是可选参考实现，
  不是 Core CLI 命令或依赖。
- `partial`、`failed`、`skipped`、`environment_limited` 都必须如实保留。

### 继续阅读

- [从这里开始](docs/start-here.md)
- [完成第一个知识闭环](docs/first-knowledge-loop.md)
- [确认 OKS 正在工作](docs/verify-it-works.md)
- [核心架构](docs/architecture/oks-core-architecture.md)
- [能力边界](docs/capability-boundaries.md)

## License

MIT
