# 维护案例：文档与实现的一致性

*一个 SKILL.md 里写了但代码里没有的命令，怎么被发现、修好、并借机 design check。讲给 OKS 贡献者听。*

## 故事

### 起因：删 /start 建 /assess

把 onboarding skill `/start`（一次性建结构）替换成 `/assess`（Q&A 建 profile + goals + 验证召回，可重复跑调优）。建好 `/assess` 后，要测 `oks skills-install` 把它装进实例。

### 第一步：报错

```bash
$ oks skills-install --force
No such command 'skills-install'.
```

但 `SKILL.md` / `AGENTS.md` / `CLAUDE.md` 都写着 `oks skills-install` 是安装流程第 4 步。**文档有，命令没有。**

### 第二步：调查

`oks --help` 列出 18 个命令，没有 `skills-install`。grep `cli.py` 找 skill 安装逻辑——发现它藏在 `oks init` 里（`_materialize_assets` 函数）：

```python
# cli.py init 命令内
copied = _materialize_assets(root, base, overwrite=upgrade)
```

`init` 调 `_materialize_assets` 装所有 assets（templates / _meta / settings / profiles + skills + hooks + rules）。**没有独立 `skills-install` 命令**——文档与实现不符。

### 第三步：根因

`SKILL.md` 是 Agent 读的**安装契约**——用户对 Agent 说"读这个 URL 装好 OKS"，Agent 按文档跑。文档写 `oks skills-install`，Agent 跑到那步就失败。

为什么没被发现？因为：

1. `oks init` 已装 skills（用户跑完 init 就有 skills，不会单独跑 skills-install）
2. 但 SKILL.md 安装流程明确把 skills-install 列为独立第 4 步——新装用户 / Agent 会跑

### 第四步：修复

两个选择：

- **A. 加 skills-install 命令**（让文档与实现一致）
- **B. 删文档的 skills-install，改用 `oks init . --upgrade`**（让实现与文档一致）

design check（用 wiki `design-check` 5 问）：

1. **作者已解决了吗？** `oks init . --upgrade` 能装 skills，功能重叠
2. **问题在别的层吗？** 根本问题是文档写了不存在的命令——可改文档
3. **新增不改主干？** skills-install 是独立 wrapper，不改 init

权衡：`init --upgrade` 太重（建实例 + git init + config + 装所有 assets），用户只想刷 skills。skills-install 轻量独立语义清晰。选 A。

实现：轻量 wrapper，只装 skills（`.claude/skills/` + `.agents/skills/`），不碰 config / git / wiki / templates：

```python
@app.command(name="skills-install")
def skills_install(force: bool = ...):
    # 只 copy assets/skills/ → .claude/skills/ + .agents/skills/
```

### 第五步：借机修 skill count

顺便发现 SKILL.md 说"10 skills 含 /accept"，但 `assets/skills/` 只有 9 个。`/accept` 在 `.claude/skills/accept/`——是 **maintainer-only**（`bundle_assets.py` 注释："Maintainer-only tooling lives in the repo's own .claude/, outside assets/"），不随 wheel 分发。

修：SKILL.md "10 skills" → "9 skills"（删 /accept）；AGENTS.md / CLAUDE.md /accept 标注 "(maintainer-only, not in wheel)"。

## 教训

### 1. 文档是契约

SKILL.md 不是普通文档——是 Agent 读的机器可执行契约。写了 `oks skills-install`，实现就得有。否则用户对 Agent 说"装好 OKS"，Agent 跑到第 4 步就失败。

**检查**：文档列的每个命令，`oks --help` 必须能找到。

### 2. design check 新命令

加命令前用 `design-check` 5 问审视（见 wiki `design-check`）：

- 作者已解决了吗？（`init --upgrade` 能装，功能重叠）
- 问题在别的层吗？（根因是文档与实现不符）
- 新增不改主干？（独立 wrapper，不改 init）

结论：skills-install 是补文档承诺 + 独立轻量，值得加。不是为了加而加。

### 3. maintainer-only vs wheel 边界

`/accept` 是 maintainer 验收 skill（测 wheel 能装 / ingest / promote / recall），在 `.claude/skills/`，不随 wheel 分发。用户实例没有 /accept 是对的。文档要把这个边界讲清——不能让用户以为实例有 10 个 skill。

## 检查清单：避免文档与实现不符

- [ ] SKILL.md 列的每个命令，`oks --help` 能找到
- [ ] `assets/skills/` 的 skill 数 = SKILL.md 说的数
- [ ] maintainer-only skill（`.claude/skills/`）不混进 `assets/skills/`
- [ ] 新增命令前 design check（init 已能做？文档改就行？不改主干？）

## 第一步 + 接下来读

如果你是 OKS 贡献者：

1. clone 仓库，`pip install -e cli/`
2. 改完跑 `python3 cli/scripts/bundle_assets.py`（`assets/` → `cli/_assets/`）
3. `oks skills-install --force` 在实例测装
4. `pytest cli/tests/` 不破坏

* 接下来读 [上下文注入](../../docs/usage/context-injection.md)（hook 怎么用 skills）+ [召回引擎](../../docs/algorithms/recall-engine.md)（`/assess` 验证 goal boost 的机制）
