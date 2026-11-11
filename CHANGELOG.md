## Unreleased

## [0.6.24] — 2026-11-11

- One-sentence cloud setup now guides environment detection, host installation, optional team linking and conversational Discuss → Goal → Learning.
- Add `oks skills-install --global --editor codex|claude|agents`; preserve existing entries unless explicitly forced, and back up replacements.
- Add `oks onboarding status|complete|skip|reset`, sharing Studio's existing progress record without auto-approving knowledge.
- Add committed README prerequisite inspection with `oks sources inspect`; expose library README as a read-only reference, outside approved knowledge recall.
- Keep new instances minimal: no copied top-level schemas/templates, author-specific profiles, example recipes or invented team goals. Preserve existing settings and profiles during upgrade.
- Keep bundled oh-my-oks in host installation locations rather than duplicating its source in personal skills/.
- Improve Studio date navigation and timeline playback with synchronized stage cards; remove dates from Learning and add native library folder selection.
- Federate standard team buckets with versioned read-only VFS access and preserve library/review identity.

- Skill routing searches reviewed capability descriptions without falling back to instruction text.
- Ordinary Wiki recall excludes Skill cards across retrieval backends; use `oks skills search` for capabilities.
- Cached Python helpers can generate bytecode without breaking subsequent loads; source edits and unrelated files remain checked.
- Prompt hooks discover active Goals in date folders and preserve relative identities for same-named daily Goals.

## [0.6.21] — 2026-08-31

### fix(test): `test_persistence` 不再依赖未跟踪的 `_assets/`

v0.6.19 新增的 `test_user_prompt_recall_reads_date_organized_mail` 把
hook 路径硬编码成 `cli/knowledge_studio/_assets/hooks/user-prompt-recall.py`。
但 `_assets/` 是 `cli/setup.py` 的构建产物、被 `.gitignore:52` 忽略
（`git ls-files` 返回 0 条）—— 全新 clone 上文件不存在，测试直接失败；
即便存在也可能是陈旧副本，测的不是权威源。

改为和其余测试一致走 `cli_module._asset_source()`（git checkout 下优先
`assets/`，wheel 下回落 `_assets/`）。实测解析到
`assets/hooks/user-prompt-recall.py`（`git ls-files` 有此条目），
全量 332 passed。

## [0.6.20] — 2026-08-31

### fix(test): user-prompt-recall 测试补 `sys.path`

v0.6.19 的新测试用 `importlib` 直接加载 hook，而 hook 内部
`from _persistence import ...` 在这种加载方式下解析不到同目录模块。
加载前把 hook 所在目录插入 `sys.path`。

## [0.6.19] — 2026-08-31

### fix(hooks): `_load_unread_mail` 改 `rglob`，读得到日期子目录

v0.6.16 起 mail 按 `mail/inbox/<YYYY>/<MM>/<DD>/` 分层存放，而
`user-prompt-recall.py` 的 `_load_unread_mail` 仍用 `glob("*.md")`
只扫 `inbox/` 顶层 —— 于是所有新邮件对 Agent 不可见，自动通知静默失效。
改为 `rglob("*.md")`。新增
`test_user_prompt_recall_reads_date_organized_mail` 回归防护。

## [0.6.18] — 2026-08-31

### fix(init): `--upgrade` 不再把 wrapper 的解释器打回 `python3`

接着上一条继续查，发现同一类的第二个缺陷：`--upgrade` 把打包的
`user-prompt-recall.sh` / `post-tool-edit.sh` 原样盖回去，顺手把
`${OKS_PYTHON:-<解释器>}` 里 `oks hook install` bake 进去的解释器重置成
裸 `python3`。pipx / venv / conda 装的 `oks`，`python3` 根本 import 不到
`knowledge_studio` —— 于是 `--upgrade` 一边刷新引擎、一边让 hook 失效，
而这条路正是 `oks hook status` 推荐给用户的。

实测（真实 KB `artboy-knowledge` 的副本，136M 全量）：修复前
`.claude/hooks/user-prompt-recall.sh` 的
`OKS_PYTHON:-/opt/homebrew/.../python3.13` → `OKS_PYTHON:-python3`；
修复后 bake 保持不变，引擎仍刷新到最新，接线三个文件逐字节不变，
升级后的副本里直接跑 wrapper：exit 0 / stdout 692 字节
`<recalled-memory>` / stderr 0 字节。

修复：bake 与接线同属运行态。`_materialize_assets` 在拷贝前快照各
wrapper 的非默认 bake，拷贝后写回，因此升级只换正文不换解释器。
新增 `test_init_upgrade_keeps_the_baked_interpreter`（331 passed）。

## [0.6.17] — 2026-08-31

### fix(init): `--upgrade` 不再冲掉 hook 接线

追查上一条 `hook status` 建议时发现的真实缺陷：`_materialize_assets`
在 `overwrite=True` 下把打包的编辑器配置原样盖回
`.claude/settings.json`、`.qoder/settings.json`、`.codex/hooks.json`
——而这三个文件正是 `oks hook install` 写接线的地方。

实测（临时实例，codex 已接线）：`oks init . --upgrade` 之后
`codex: wired` → `not wired`，`hooks.json` 里整个 `UserPromptSubmit`
块被删掉，自动 recall 静默失效；同时已迁移成绝对路径的四个 lifecycle
命令被退回 `"$(git rev-parse --show-toplevel)/..."` 模板形式（`--no-git`
实例根本没有 toplevel，等于直接失效），把
`test_hook_install_migrates_codex_relative_lifecycle_paths` 修好的东西
又还原了。

修复：这三个文件属于用户运行态而非可刷新资产，已存在时 `--upgrade` 一律
不覆盖；全新 `init` 仍照常写入。修复后同一路径实测：引擎
`outdated → current`，`codex: wired` 保持，`hooks.json` 逐字节不变。

`test_init_upgrade_refreshes_assets_but_keeps_user_files` 原来拿
`.claude/settings.json` 当「会被刷新的打包文件」样本，改用真正的打包资产
`.claude/rules/wiki-writing.md`，并补断言：被编辑过的 `settings.json`
必须在 `--upgrade` 后保持原样。

### fix(hooks): wrapper 不再静默吞掉引擎崩溃

`user-prompt-recall.sh` / `post-tool-edit.sh` 原本是
`exec "$OKS_PYTHON" engine.py 2>/dev/null`。两个问题叠在一起：`2>/dev/null`
把引擎的 traceback 全丢了，`exec` 又把 python 的非零退出码原样传给编辑器
——注释写着「fails open」，实际是 fail-closed，而且崩溃和「没命中记忆」
在外部完全无法区分。

现在 stderr 落到临时文件：成功就丢掉（jieba 的噪声不该污染 stdout 的
`<recalled-memory>` 块），非零退出则打印
`oks hook: recall engine exited N — run 'oks hook install' to refresh it`
外加最后 5 行 traceback，并且始终 `exit 0`，prompt/工具永不被挡。

实测（artboy-knowledge 实例）：正常路径 exit 0 / stdout 1171 字节 / stderr 0
字节；`OKS_PYTHON=/usr/bin/python3`（3.9.6，引擎陈旧）exit 0 且 stderr 直接
点出 `TypeError: unsupported operand type(s) for |` 在
`user-prompt-recall.py:66`。修复前同一场景是 exit 1 + 零输出。

### fix(hooks): `oks hook install` 刷新过期的 wrapper 正文

`_ensure_recall_scripts` 判定 `.sh` 是否需要重写时只看「有没有当前解释器
的 bake」。于是 bake 正确、正文陈旧的实例会被跳过，上游 wrapper 修复永远
到不了它们。改为与打包资产逐字比对（把 bake 代入后），bake 陈旧和正文陈旧
都会重写；读不到资产时退回旧的 bake 子串判定。`.py` 引擎仍保持「存在就不
动」，刷新引擎请用 `oks init <root> --upgrade`。

### fix(hooks): `oks hook status` 分级结论，不再把陈旧当阻断

新增 `engine version: current / outdated` 一行（按内容比对打包资产），并把
结论分三档：有阻断项（脚本缺失、解释器 import 不了 knowledge_studio）才说
`a hook cannot inject context`，并明确 `wired` 只代表设置项存在；仅引擎与
打包版本不一致时降级为黄色提示，指向 `oks init --upgrade`；都正常则报
healthy。之前把「引擎陈旧」也算进阻断项，会对一个实际能注入的 hook 谎报
失效。

### fix(hooks): 修正 `hook install` 帮助文案 (P6)

原文案说「Copies the hook scripts ... (if missing)」「non-destructive:
existing hooks are preserved」，与实现不符——`.sh` 每次都会重写以重新 bake
解释器。改为如实说明：只保留既有 `.py` 引擎，`.sh` wrapper 会被重写，刷新
引擎用 `oks init <root> --upgrade`。

### test: +4 hook/init 回归测试 (326→330 passed)

- `test_hook_install_refreshes_an_outdated_wrapper_body`：bake 正确但正文陈旧
  必须被重写
- `test_hook_status_reports_a_differing_engine_as_a_warning`：引擎不一致只报
  警告，不得出现 `cannot inject context`
- `test_recall_wrapper_surfaces_engine_failure_and_still_exits_zero`：引擎失败
  要可见且 exit 0
- `test_init_upgrade_refreshes_engines_without_unwiring_hooks`：`--upgrade` 刷新
  引擎的同时接线不得丢失

## [0.6.16] — 2026-08-30

### feat(mail): inbox 按日期分目录 + `oks mail migrate` 迁移命令

`oks mail send` 之前把所有信件平铺写在 `mail/inbox/{slug}.md`，一个
活跃实例会堆积几百个文件在一个目录里，肉眼和工具都难看。

v0.6.16 起 inbox 按 `{YYYY}/{MM}/{DD}/{slug}.md` 组织（slug 本身就带
`YYYYMMDD` 时间戳前缀，提取前 8 位即得日期）。`inbox`/`count` 改用
`rglob` 递归遍历，所以旧平铺信件仍能被读到（向后兼容）。

新增 `oks mail migrate` 命令：把旧实例的平铺信件一次性迁进日期子目录，
幂等（已在子目录的不动，无日期前缀的保留平铺仍可读）。

向后兼容：`show`/`read` 通过 `_mail_path` 自动算日期路径，旧 slug
（无日期前缀）fallback 到平铺顶层，不破坏现有实例。

### test: +2 mail 日期目录 / migrate 测试 (326 passed)

## [0.6.15] — 2026-08-29

### fix(hooks): 独立 hook 脚本兼容 Python 3.9 宿主

`user-prompt-recall.py` 和 `post-tool-edit.py` 用了 PEP 604 注解
(`Path | None`、`dict | None`、`list | None`)，需要 Python 3.10+。但 hook
是独立脚本，用宿主的 `python3` 跑，很多 macOS 系统默认还是 3.9.6 →
`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`。

`_persistence.py` 一直有 `from __future__ import annotations` 所以没事，
两个 hook 脚本漏了。补上后注解延迟求值为字符串，3.9 宿主也能跑。

实测: `echo '{"prompt":"test"}' | python3 .claude/hooks/user-prompt-recall.py`
在 3.9.6 下 exit 0 无 traceback (修复前 TypeError)。

回归防护 (test_persistence.py +2):
- `test_standalone_hooks_use_future_annotations_for_py39`: 静态检查两个
  hook 脚本含 `from __future__ import annotations` + `py_compile` 过
- `test_standalone_hooks_import_cleanly`: importlib 加载不报错
  (抓 `_persistence` 缺失 + 坏注解)

324 passed.

### 另: 手动维护的 .claude/hooks/ 缺 `_persistence.py`

开发仓库的 `.claude/hooks/` 是手动维护 (非 `oks hook install` 创建)，
P8 修 `_mark_mail_read` 时手动复制 `user-prompt-recall.py` 到 4 处，
漏了依赖模块 `_persistence.py` → `ModuleNotFoundError: No module
named '_persistence'`。`oks hook install` 的 `_HOOK_SUPPORT_FILES` 循环
逻辑是对的 (会复制)，这次只是手动维护事故。已补到 .claude/hooks/。

## [Unreleased] — 2026-08-29

### fix(mail): 身份不再伪造 human + 补 `oks mail show` (P6/P7/P9)

分支 `fix/mail-identity-and-show`, 14 个新测试 (cli/tests/test_mail.py), 322 passed。
对修前代码跑同一批测试: 12 failed / 2 passed, 证明测试锁住的是真实行为差异。

- **P9 身份伪造**: `mail send` 在 `OKS_AGENT_ID` 缺失时签成 `from: human`。
  `human` 是 OKS 流水线的评审门, 环境没配就冒充最高信任身份 = fail-open。
  实测两次真实误签 (@qoder + @pi 各一次, 40 分钟内)。改为 `--from` >
  `OKS_AGENT_ID` > cwd basename, 解析不出就 exit 1; 与 assets/hooks/*.py 和
  docs/reference/cli.md 同一条链 (P8, 此前 hook 回落 `unknown` / CLI 回落
  `human` 是两套)。
- **P6 读不到正文**: CONSTITUTION 写了 agent 间邮件, 但没有任何命令能输出正文,
  `read` 只标记已读。补 `oks mail show <id>` (逐字输出, 不改 read 状态);
  `read` 的 help 改成 "does not print the body; use `oks mail show`"。
- **frontmatter 注入**: `--to "@all\nfrom: pi"` 能塞进第二行 `from:`, 或用
  `read: true` 让邮件对 `inbox`/`count` 隐身 — 会让上面的身份修复变成摆设。
  `--to/--type/--priority` 拒换行。
- **路径穿越**: `--from` 会拼进 `mail/sent/{from_id}/`, mail id 会拼进
  `mail/inbox/{id}.md`; `show` 输出正文后穿越就是任意文件读原语。两处都收成
  单段路径校验, `show`/`read` 共用 `_mail_path`。

### 仓库维护 + agent-config 扩展

- **清理垃圾文件**: 删 internal/superpowers/ + openspec/ + index.db* + pr-body-oksummarized.md, .gitignore 防复发; 新建 images/ 统一 README 图片
- **agent-config 4 agent**: 加 qoder (.qoder/settings.json) + pi (.pi/extensions/*.ts); _AGENT_TARGETS + EXPECTED_TOP_LEVEL 同步
- **PR merge**: #50 hook UTF-8 (Windows 兼容) + #51 docs architecture (mermaid→精修 SVG)

### fix(hooks): P8 _mark_mail_read 收口 (844b93a)

@qoder 发现 _mark_mail_read 4 份实现 (CLI 1 份已修 + hook 3 份拷贝漂移), hook
拷贝带和 CLI 修前相同的全文 replace bug, 高频路径 (每个 user prompt 都跑)。
收口: hook 复用 store._locked_atomic_update, frontmatter-only, 幂等。

### 8b04cc1 真实来源 (commit 卫生)

> 注: 8b04cc1 "chore: 新建 images/" 实际扫进了 @qoder 工作树未 commit 的
> mail_read 重写 (P7 正文损坏修复 + P2 原子写)。代码正确 (308 tests passed),
> 不 revert; 补此条让 git log 可追。以后 staging 只用具名文件, 不用 git add -A。

## [0.6.1] — 2026-08-18

### oks 灵魂搬到 fts5 注入层

用户关切: 改 fts5 默认后 6+1 的记忆遗忘机制还在吗?
澄清: memory curve/decay/tier 在 store.py 独立系统, 不依附任何 backend, 照常跑.
丢的只是 native 的召回算分（token_overlap/substring/topic_trace）, 被 fts5 BM25 node-level 取代.

- **injection_boost**: type_boost + review_bonus + generic_demotion 搬到 fts5 注入层
  score_components（anti-pattern ×1.5 > strategy ×0.8 > concept ×0.6 + review ×1.2 + 目录页 ×0.5）.
  不改 fts5 召回顺序, 只作 boost 标注供 /query + eval 可见.
- **简化**: 面向用户只留 fts5 一个常用 search（native/fusion 代码保留作历史 + 向后兼容）.
- 三层 oks 灵魂: memory curve（store.py）+ goal boost（注入层重排）+ injection_boost（标注）.

192 tests passed, fts5 P@3 仍 96%.

## [0.6.0] — 2026-08-18

### 召回引擎重构（吸收 TreeSearch node-level）

- **fts5 升级 node-level**：吸收 TreeSearch 的 markdown tree parser，每个 `##` heading 段一个 FTS5 row。50-case 实测 P@3 = 96%（flat page-level 54%）。
- **关键 bug 修复**：CLI `--search-backend` Option 默认 `native` 覆盖了 yaml 配置——导致 fts5/fusion 从未生效。改默认 `None` + recall() 读 yaml。
- **默认 search_backend 改 fts5**（96% 最优召回）。native (6+1) 保留作 oks 原创。
- **fusion 重构**：fts5 主召回 + native 归一化 re-rank（0.7 fts5 + 0.3 native），limit<5 缩 native_top。
- **goal boost 接到注入层**：召回用 fts5 精度，注入时 goal 命中往前排（oks 灵魂分层）。
- **schema_version 检测**：旧 schema（5 列）自动 DROP 重建（6 列）。
- 删 pytreesearch 外部依赖（吸收完成，不依赖外部包）。

### 4 点优化（CV from karpathy-wiki）

1. Token Budget 分层：recall.yaml `inject` 配置（budget_chars/per_page_chars/title_only_floor）。
2. Backlink audit：lint 检查 `relates_to` 双向链接。
3. Query 答案存档：/query skill 步骤 7 存优质答案到 drafts/ + promote。
4. purpose.md anchor：recall goal boost（load_active_goals）已满足。

### 验证

- 192 tests passed
- 50-case eval：native 54% / fts5 96% / fusion 90%

# Changelog

## [Unreleased]

### Fixed

- 保留旧版 recall 环境变量作为临时覆盖，同时以 `settings/recall.yaml` 作为持久配置来源。
- 改进 recall preview，优先使用已有摘要，并尽量在完整行边界截断。
- 让并发访问计数在读改写期间保持一致，并在 Raw Bundle 发布失败时保留原内容。
- 补齐 Candidate 读取、人工审核覆盖与 Raw Bundle 成功后的临时文件清理测试。


## [0.6.8] — 2026-08-25

### fix(vfs): canonical uri 不再强制 .md 后缀

旧 `resolve()` 要求 uri 必须带 `.md` 后缀（如 `oks://wiki/.../slug.md`），否则 PATH_NOT_FOUND。recall 返回的 slug 字段不带 .md，用户/Agent 用 slug 构造 uri 会找不到文件。

**修复**：`resolve()` 在 candidate 不存在且无后缀时，透明尝试 `.md` sibling——canonical uri 可不带 .md（不暴露磁盘文件格式），带 .md 的旧 uri 向后兼容。

**指标**：vfs 测试 45→46 passed（+1 新测试 `test_stat_and_read_accept_uri_without_md_suffix`），全测试 270 passed。


## [0.6.7] — 2026-08-24

### fix(recall): L0 preview 质量优化（机械截取 → 语义完整截取）

旧 `body_preview = body[:200]` 机械截取 86% 的 wiki 页 preview 有质量问题
（标题重复 + 表格/段落中途截断）。新增 `_make_preview()`：

- 跳过 body 开头与 frontmatter `title` 重复的 `# title` 行
- 在 limit 内尽量在完整行边界截断（不破表格行/句子）
- frontmatter `abstract` 字段优先（Dreaming 层 AI 写的摘要），本函数作 fallback

**指标**：preview 质量问题率 86% → 0%（50 页样本，43 页修复）
**宪法**：P4 合规——纯文本操作，不调 AI API；abstract 生成属 Dreaming/Agent 层


## [0.6.6] — 2026-08-24

### feat: team bootstrap + Word skill + docs refresh（PR #45 by 1263-ux）

- 新增 `oks team init` 命令——共享团队知识库 bootstrap（多人协作场景）
- 新增 `knowledge-to-word` skill（`build_docx.py` 把 wiki 导出 Word 文档）
- health.py: `WIKI_STATUSES` 兼容旧实例的 `published` 状态（lint 不再误报）
- fts5.py: makedirs 注释（无逻辑改动）
- +8 测试（261→269 passed）

### docs: GitHub Pages broken links 修复（PR #44 by 1263-ux）

- 修复 docs/ 下 12 文件的失效链接


## [0.6.5] — 2026-08-21

### feat(vfs): 只读 oks:// 虚拟文件系统（PR #43 by Huxc2020）

新增 canonical `oks://` URI + 6 个只读 `oks fs` 命令（ls/tree/stat/read/overview/find）:
- 7 个只读 mount scope: profiles/raw/wiki/drafts/mail/skills/traces
- recall 命中项新增 canonical uri 字段（保留 slug/source_path 兼容）
- 安全: 严格只读（禁止 write/mv/rm 防绕过 raw-commit/draft/wiki 门控）
  + 目录穿越防护 + 符号链接逃逸检测
- 不引入新依赖（无向量库/LLM/OpenViking 代码）
- +62 测试（199→261 passed）

### docs: Agent-Native rewrite + DSH-OKS demo（PR #42 by 1263-ux）

- 71 docs + 26 截图（DSH-OKS 集成真实演示）
- maintainer rebase + 清理 raw-bundles/file-edits 残留后 merge


## [0.6.4] — 2026-08-18

### embedding fallback 策略

- `settings/recall.yaml` 加 `embedding_fallback: false`（默认关，embedding 慢 ~18s）
- `_recall_knowledge_via_backend`: fts5 召回空/不足（<limit/2）+ 开启 + connector 可用时切 embedding 补充
- except 静默回退原 fts5（不阻断召回）
- 开启：`embedding_fallback: true` + `pip install 'oks-connector[embedding]'`

### 代码清理（交付前 review）

- `fusion.py` 删 dead code（return 后旧 native 主+fts5 补盲逻辑，永不执行）
- `search/__init__.py` / `fusion.py` / `native.py` / `fts5.py` docstring 过时数据修正
  （fusion R@1 0.667→0.805, native 默认→legacy, fts5 flat→node-level）
- 删 `oks-connector-code` 重复包

199 tests passed.


## [0.6.3] — 2026-08-18

### Codex lifecycle parity（PR #38 by Huxc2020）

让 OKS Codex 集成与 Claude Code + Qoder 对等:
- Codex UserPromptSubmit / PostToolUse hook wiring
- 解析 Codex apply_patch 文件路径做 conflict detection
- 返回 Codex-compatible JSON additionalContext
- Wiki frontmatter 写入前校验
- PreCompact snapshot 输出
- 从 Git 仓库根解析 project-local hooks
- idempotent install/status + /hooks trust guidance
- +7 回归测试 (test_hooks.py, 192→199 passed)

### eval 增强（v0.6.2 续）

- oks eval recall --search-backend {fts5|native|fusion|embedding} 支持消融
- records/experiments/runs/ 归档 4 个 run json


## [0.6.2] — 2026-08-18

### OKS Triple-Layer Recall 命名 + 50-case 真实消融实验

定名 OKS Triple-Layer Recall = Node-BM25(召回) + Soul Boost(注入) + Memory Curve(衰减)。
50-case 语义改写消融实验(严格精确 slug 匹配):
- fts5(完整 Triple-Layer): R@1=0.825 R@3=0.925 MRR=0.907 nDCG@5=0.893 p50=93ms
- native(去 Node-BM25, 6+1 page-level): R@1=0.525 R@3=0.647 MRR=0.630 nDCG@5=0.624
- fusion(fts5+native rerank): R@1=0.805 R@3=0.905 MRR=0.900 nDCG@5=0.887
关键发现: Node-BM25 R@1+57%; fusion re-rank 反降精度(灵魂须在注入层); fts5 还更快.

3 个 eval bug 修复(之前 eval 一直测 native 不是 fts5!):
1. recall_knowledge 调 _recall_knowledge_with_context(纯 native) → 改调 _recall_knowledge_via_backend(真 backend 分发)
2. _recall_knowledge_via_backend search_backend=None 直接走 native → None 时读 settings/recall.yaml
3. _kb_snapshot 把 .oks/fts5.db 算进 hash → 误报 'mutated state', 排除 .oks(索引是缓存)

eval 增强: recall_knowledge + run_evaluation + eval_recall 全链加 search_backend 参数;
  cli: oks eval recall --search-backend {fts5|native|fusion} 支持消融.

docs: recall-engine/recall-evaluation/index/README/cli 11 处 P@3 虚高 96% → 真实 R@1=82.5%.
records/experiments/runs/ 归档 3 个 run json.


## v0.5.14 (2026-08-17)

### 全面 review 修复（2 个 bug）

**1. signal_rel_floor 半死配置 → 活起来**
- post-tool-edit.py 的 `_should_signal` 第 3 步硬编码 `rel < 2.5`，不读 yaml
- 改为读 `load_recall_params()['posttool_signal_rel_floor']`（fallback 2.5）
- 现在 yaml 改 signal_rel_floor 真正生效——dsh-oks 设置卡 + oks metrics + hook 三处一致

**2. oks config set recall 参数双轨漂移 → 写 recall.yaml**
- v0.5.12 声明 settings/recall.yaml 是唯一参数真源，但 `oks config set` 还写 ~/.oks/config.json
- recall 读 yaml 不读 config.json → search_backend 等参数配置了不生效
- 修复：config_set 对 _RECALL_YAML_KEYS（search_backend/recall_*/posttool_*/conflict_window/mail_topn）调 set_recall_yaml_param 写 yaml
- 其余 key（knowledge_base_path/handlers/api_keys/feishu）仍写 config.json

### PR 处理（8 个）
- merge #29 #30 #32 #33 #35 #36 #37（7 个，含 capability health fix + recall scope fix + docs）
- close #34（signal_rel_floor 不删，已在 main 4fce21c 修复）

## v0.5.12 (2026-08-17)

### env 废弃 — settings/recall.yaml 是唯一参数真源

回应「参数不能永远跟随仓库配置文件吗？环境变量忘了怎么办？两边不同步怎么办？」

- **env 完全废弃**：`load_recall_params()` 去掉 env 读取，只读 yaml + 默认。
  参数永远跟随 `settings/recall.yaml`，git 同步，走到哪带到哪。
- **迁移警告**：检测到旧 `OKS_*` env 时警告提示迁移到 yaml + unset
  （`load_recall_params._warned` 防刷屏）
- **CLI flag 临时调参**：`oks recall --floor 0.9` 一次性调 floor，不改 yaml。
  recall_cmd 用 `floor_override` 过滤 rel 低于 floor 的结果。
- **metrics html 文案**：去掉「env 覆盖 yaml」，改为「settings/recall.yaml 是唯一
  参数真源 → git commit → 走到哪同步到哪。临时调参用 oks recall --floor」
- **去掉 `envvar=OKS_SEARCH_BACKEND`**：search_backend 也从 yaml 读，不读 env

### 新优先级

```
CLI flag（一次性临时调参）> settings/recall.yaml（唯一持久真源）> 代码默认值
env 已废弃——不再读取
```

### 向后兼容

现有 env 用户升级后 env 不再生效。`oks init . --upgrade` 生成默认 yaml，
用户把 env 值搬到 yaml（或看警告手动迁移），unset env 即可。

## v0.5.11 (2026-08-17)

### 实验数据图表化 + 参数存知识库

将 PostToolUse 注入实验数据沉淀到文档与报告，参数可随知识库同步：

- **fig6 四模式对比图**（`docs/assets/experiments/fig6-posttool-modes.png`）：
  A(20KB) / D(8KB) / J(1KB) / K+J(1KB) token + signal 次数对比
- **docs/algorithms/oks-effectiveness.md 第十二节**：PostToolUse 注入模式对比，
  含四模式表 + J 闸门 3 条件 + 实测数据 + K 引导说明
- **`settings/recall.yaml` 参数文件**：`oks init` 生成实例级参数文件，
  改 → git commit → 走到哪同步到哪。OKS 只提供默认值，每人自调。
  优先级：env > settings/recall.yaml > 代码默认值
- **`load_recall_params()` 共享加载函数**（recall.py）：env / yaml / 默认 三级 fallback
- **post-tool-edit.py 用 load_recall_params**：取代直接 os.environ，读 yaml
- **`oks metrics --html` 增强**：加 PostToolUse 注入统计 + 当前参数表
  （recall.floor / posttool.mode / signal_rel_floor / search_backend）

### 数据同步路径

```
settings/recall.yaml (参数) + records/inject.jsonl (注入数据)
  → git commit → clone 即同步
  → oks metrics --html 随时看报告
  → 参数 + 数据不断积累沉淀，每人不同
```

## v0.5.10 (2026-08-17)

### K+J 混合：system prompt 引导 + 智能信号

PostToolUse recall 从 D 模式（每次工具 signal ~8KB）进化为 K+J 混合：

- **K（system prompt 引导）**：`oks init` 生成实例根 `AGENTS.md`，内含 OKS
  recall 引导——AI 读到即知晓有知识库 + 何时调 + query 来自任务意图。
  零 hook 注入，token 最省。
- **J（智能信号）**：`post-tool-edit.py` 加 `_should_signal()` 闸门，3 条件
  AND 才注入 signal：
  1. 工具类型：只 Edit/Write/MultiEdit/Grep/Glob（Bash/Read 跳过）
  2. query 质量：非通用词（git/status/ls 等），≥4 字符
  3. rel > 2.5（极高相关）
- 实测：20 工具长任务只 2-3 次 signal ≈ 1KB（vs A=20KB，省 95%）
- Bash/Read 全跳过——AI 已在读内容，signal 纯噪声

### 新增

- `_INSTANCE_AGENTS_MD` 模板常量 + `init` 写实例根 `AGENTS.md`
- `_should_signal()` 闸门 + `_query_from_tool` 路径过滤增强

## v0.5.9 (2026-08-17)

### 可插拔 search backend 架构

- **SearchBackend Protocol**（`cli/knowledge_studio/search/`）：第三方包通过
  `entry_points(group="oks_search_backend")` 注册 search backend，OKS 核心不改，
  recall 切 `--search-backend <name>` 即用
- 3 个内置 backend：
  - `native`（默认）：6+1 因子（jieba + IDF + title boost）
  - `fts5`：SQLite FTS5 + BM25 + column weights（title 5x > tags 3x > body 1x >
    code 0.5x）+ 增量 diff content_hash + 持久化 `.oks/fts5.db` + LIKE fallback
  - `fusion`：native top-3 主 + fts5 独有补 2（实验验证最优，RRF 伤 R@1）
- `oks recall --search-backend <name>` + `OKS_SEARCH_BACKEND` envvar

### CV TreeSearch 纯函数到 recall.py

- `estimate_idf`：平滑 IDF `log((N+1)/(df+1))+1`
- `compute_term_overlap`：IDF 加权 token overlap，bonus 加在 count×0.3 之上
- `check_title_match`：query term 逐个命中 title，+0.3/个
- `is_generic_page`：通用目录性页（index/overview/readme/目录/概述...）×0.5 降权
- 效果：baseline R@1 0.333→0.400，MRR 0.472→0.506

### lazy watch（FTS5 无守护进程刷新）

- `_wiki_fingerprint()`：stat-only（path, mtime_ns, size）
- `_maybe_reindex()`：recall 前比对 fingerprint，变了才增量重索引
- meta 表存 wiki_fingerprint 跨进程
- 速度：首次 552ms | 不变 3ms | 变 1 页 41ms

### PostToolUse recall 补位（长任务盲区）

- **post-tool-edit.py 新版**（367 行）：文件冲突检测 + recall 补位段
  （`_query_from_tool` + `_recall_supplement`）
- query 来自工具操作（Edit/Write/Read→file stem；Bash→command；Grep/Glob→pattern）
- 高 floor 0.9 + 低 topn 2 + 共享 cooldown + inject trace source=posttool
- `OKS_POSTTOOL_FLOOR` / `OKS_POSTTOOL_TOPN` env

### pi extension（oks-posttool-recall.ts）

- `.pi/extensions/oks-posttool-recall.ts`：监听 `tool_result`（pi 的 PostToolUse 等价）
- `_kbRoot()` 解析 OKS_ROOT / config → KB 实例（不依赖 process.cwd()）
- query-level cooldown 预检查（同 query 10 轮 0ms 跳过 Python）
- 真实注入验证：Bash/Edit → OSS call chain / AI agent 记忆（rel 3.17/2.741）

### oks-connector-code（独立包）

- AST 解析 raw/*.py，函数/类级召回（FunctionDef/AsyncFunctionDef/ClassDef）
- token overlap：name hit 5x body hit
- `entry_points(group="oks_search_backend", name="code")`
- 独立仓库 `oks-connector-code`

### 文档 + 实验

- algorithms/oks-effectiveness.md：11 节（召回评估 / 记忆腐化 / 注入分布 /
  PostToolUse 冲突 / TreeSearch 融合 / CV / search backend / is_generic / lazy watch）
- fig1-5 实验图表
- docs/cli.md + recall-engine.md + context-injection.md 更新

### PostToolUse 测试结论

三层注入全部工作：UserPromptSubmit ✅ + PostToolUse recall ✅ + PostToolUse 冲突 ✅
20 次真实注入，11 个不同 wiki 命中，floor=0.9 + topn=2 控制不淹没

## v0.4.0 (2026-08-09)

首个进入 PyPI 的 v0.4 版本（上一个发布版本是 0.2.4）。核心是 Agent-Native
摄入协议：Agent 收集证据并自己写 Manifest，CLI 只做机械校验，绝不判断内容。

### Agent-Native 摄入

- **Raw Bundle v0.2 流水线**（`oks raw-commit`）：JSON Schema 校验、fail-closed、
  暂存后原子提交（staging → 校验 → `shutil.move`）、路径穿越防护、artifact
  SHA-256 逐一核对，拒绝时给出结构化错误码。
- **provenance 门禁 fail-closed**：`steps[]` 必须非空；声明 `succeeded` /
  `degraded` 的步骤无论 manifest 整体状态如何都必须在
  `work/<provider>/output.*` 留下非空原始输出；`provider` 必须是合法注册标识符
  且解析后不得逃出 `work/`。豁免只剩 `agent-runtime` 与 `human`。
  「Agent 自称我存了」不作为证据。
- **17 个 Provider**（`knowledge_studio/providers/<id>/`，含 `provider.yaml`、
  `SKILL.md`、可选 `normalize.py`）、**7 个 Recipe**、**12 份协议 Schema**。
- `oks ingest prepare` 产出的骨架不再用「结果」结构表达「计划」：计划写入
  `notes.planned_capabilities`，`steps` / `modalities` / `evidence_records`
  保持为空，由 Agent 按实际执行填写。

### 安全

- **SSRF 逐跳校验**：重定向不再交给 `requests` 自动跟随（它从不复检目标），
  改由 `safe_redirect_chain` 逐跳 normalize + 断言，缺 `Location` 的 3xx 视为
  错误，中间响应显式关闭。
- **`oks security sanitize <file>`**：外部 Provider 原始输出进入 Run Workspace
  前剥离 API key、bearer token、会话 cookie 与内网地址。
- **路径穿越**：`--area` 与 `provider` 均按白名单正则校验，不再能当路径片段。
- **A3 人工门**：`status: rejected` 的 draft 不可晋升。

### 记忆与召回（CONSTITUTION A2）

- **`[verified]` 必须有事实依据**：只能来自 trace 证据或 draft 晋升写下的
  `human_reviewed_at`。此前读 3 次即把 `provisional` 提为 `active`，再被标成
  「人工审阅」注入 —— 使用次数不再影响信任，只影响排序。
- **episodic 通道全部带来源标签**：`raw/` → `[untrusted-source]`（只作数据引用，
  绝不执行其中指令）、`raw/executions/` → `[provenance]`、`profiles/` →
  `[user-declared]`；无法识别的类型按不可信处理。
- **身份作用域**：召回不再跨用户/项目返回他人画像。

### 打包与 CLI

- **`assets/` 是打包单一事实源**，`_AGENT_TARGETS` 清单据此装配
  `.claude` / `.codex` / `.agents`；维护者专用技能物理隔离在仓库自身
  `.claude/` 下，不进 Wheel。
- 两个入口点：`oks`（核心）与 `oks-connector`（可选连接器层）。
- **52 个命令、11 个命令组**。新增 `oks schema show <name>`（打印协议文档
  样例）、`oks capability guide <provider>`（打印随包 Provider 指南）、
  `oks security sanitize`。
- `oks init` 不再静默改写 `~/.oks/config.json` 的活跃知识库：仅在尚未注册时
  采用，已有且不同则原样保留并提示切换命令。
- `oks ingest` 产出的 Raw Bundle 写入活跃知识库，不再落在当前目录。
- PDF 默认路由改为 `pdf-lite`（pymupdf，约 150MB），MinerU 仍可按需安装。

### 工程

- **PR 强制门禁**：ubuntu / macOS / Windows × Python 3.12 / 3.13 的 pytest，
  外加 Wheel 与 sdist 内容校验（每个 asset 必须到位、维护者技能不得泄漏、
  干净树构建、装包后 `oks init` 冒烟）。
- 测试从 shell 调用全局 `oks` 改为进程内调用被测包 —— 此前脏装会让坏代码显绿、
  干净克隆却全红。
- 文档与技能引用的每个 `oks` 命令都由测试对照真实命令树校验；随包协议样例
  必须通过自己的 Schema。

## v0.3.0

- Base knowledge engineering CLI with search, recall, wiki CRUD, drafts, lint, metrics
- 6+1-factor recall engine with decay system
- Date-based raw/ organization
- Feishu worker integration (Source + Review planes)
- Global config (`~/.oks/config.json`)
