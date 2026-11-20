"""Instance scaffolding, onboarding, and bundled-skill installation.

Split out of :mod:`knowledge_studio.cli` (B2-2) so the instance lifecycle can
be read without the whole command surface. The root ``app`` still lives in
``cli.py`` and registers these commands through :func:`register`.

Deliberate constraints:

* ``_asset_source`` stays in ``cli.py`` and is imported lazily here. Tests
  monkeypatch ``cli.__file__`` / ``cli._asset_source``; a copy of the function
  would freeze the installation path and break them.
* ``_instance_root`` moved here (its only implementation), but ``cli.py``
  re-exports it so existing ``from knowledge_studio.cli import _instance_root``
  call sites and ``hooks_cli`` delegation keep working.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Optional

import typer
from rich.console import Console

from knowledge_studio import store
from knowledge_studio.hooks import (
    _HOOK_EDITORS,
    _RECALL_HOOK_SCRIPTS,
    _bake_codex_lifecycle_hooks,
)
from knowledge_studio.i18n import t

console = Console()

onboarding_app = typer.Typer(help="Shared conversation/Studio learning progress.", no_args_is_help=True)
team_app = typer.Typer(
    help="Shared team knowledge-base bootstrap and onboarding.",
    no_args_is_help=True,
)


def _asset_source() -> Path | None:
    """Delegate to cli.py, which owns the installed-vs-source asset lookup."""
    from .cli import _asset_source as locate

    return locate()


def _emit_json(data) -> None:
    """Delegate to cli.py so JSON output stays byte-identical everywhere."""
    from .cli import _emit_json as emit

    return emit(data)


_INSTANCE_DIRS = [
    "profiles/discuss",
    "skills",
    "records/studio",
    "profiles/users",
    "profiles/projects",
    "profiles/recipes",
    "profiles/goals",
    "raw",
    "wiki",
    "drafts",
    "mail/inbox",
    "mail/sent",
]

_INSTANCE_GITIGNORE = """\
# Python
__pycache__/
*.py[cod]
*.egg-info/

# Virtual env
.venv/
venv/
env/

# IDE / OS
.idea/
.vscode/
.DS_Store
Thumbs.db

# OKS local per-machine state (access counts, fingerprints) — NOT synced
.oks/

# Trace append locks (runtime state, not trace content)
raw/executions/*/.append.lock

# NOTE: wiki/, drafts/, profiles/ are intentionally TRACKED — they ARE your
# memory. Unlike the open-knowledge-studio code repo (which ignores wiki/ &
# drafts/ so it ships clean), an instance commits its knowledge to git.
"""


_INSTANCE_AGENTS_MD = """\
# {name}

OKS 知识库实例（open-knowledge-studio）。

## OKS recall：system prompt 引导 + 智能信号（K+J 混合）

你有 OKS 知识库。任务涉及不确定的概念 / 模式 / 历史决策 / 竞品对照时，调：
  ```bash
  oks recall "<任务意图 query>" --explain --limit 3
  ```
query 用任务意图（如"OKS 记忆体系 对比 ai-book"），不是工具操作。
不调也行——任务简单 / 已读够时不调。零 token 浪费。

### J：智能信号（PostToolUse 补提醒）

Edit/Write 代码文件后，检测到高相关（rel > 2.5）时，会看到轻量提示：
  <oks-memory-signal>...</oks-memory-signal>
只 slug + rel（不注入 body）。你判断需要才调 oks recall。
Bash/Read 不触发信号。

### UserPromptSubmit（用户意图注入）

用户说话时自动注入相关记忆——真 recall 时机。

## 常用命令

```bash
oks recall "<query>"           # 召回相关 wiki
oks recall "<query>" --explain # 显示评分因子
oks status                     # 知识库状态
oks wiki use <slug>            # 标记引用
```
"""


# Schemas and templates stay with the tool/Skill. Never seed a personal
# instance with the tool author's team, active goals or example recipes.
_SHARED_ASSETS = ("settings",)
_INSTANCE_README_MD = """# Knowledge

本库保存材料、待审核知识、Wiki、Skill、上下文、记录与配置。

## 前置要求

- 本地查询：Python 3.12+与可用的OKS CLI。
- Git：用于版本管理或关联团队已提交知识；不自动推送。
- GitHub、云效、飞书等账号仅在所选材料或工作流确实需要时配置，沿用用户已有身份。此空库不要求全部登录。
- 不把密钥、Cookie或令牌写入README与知识正文。

## 使用

讨论明确理解，目标形成约定，学习提议并审核知识更新。Raw按任务读取，不逐份转换为Wiki。Wiki保存判断，Skill保存执行方法；来源与执行权限分开。

团队库物理独立，关联前先读取其README中的工具、身份、权限及适用范围要求。README是配置参考，不自动授权执行脚本或访问服务。
"""
_DEFAULT_CORE_SKILLS = ('oh-my-oks',)

# How each agent ecosystem's directory is assembled from the single-source
# components under assets/. Supporting another agent is one line here.
_AGENT_TARGETS = {
    ".claude": {"config": "claude", "skills": True, "hooks": True, "rules": True},
    ".qoder": {"config": "qoder", "skills": True, "hooks": False, "rules": True},  # plan A (qoder-cli): .qoder/hooks 是死重量 — settings.json 指 .claude/hooks, 铺了无引用 (P8)
    ".pi": {"config": "pi", "skills": False, "hooks": False, "rules": False},
    ".codex": {"config": "codex", "skills": False, "hooks": True, "rules": False},
    ".agents": {"config": None, "skills": True, "hooks": False, "rules": False},
    # WorkBuddy 5.4.7 discovers project Skills from .codebuddy.  Keep the
    # compatibility tree so local projects have one stable place for
    # WorkBuddy-specific guidance as the host evolves.
    ".codebuddy": {
        "config": "workbuddy",
        "skills": False,
        "skill_names": ("oks-knowledge",),
        "hooks": False,
        "rules": False,
        "install_config": True,
    },
    ".workbuddy": {
        "config": "workbuddy",
        "skills": False,
        "hooks": False,
        "rules": False,
        "install_config": True,
    },
}


def _copy_tree(
    src: Path,
    dest: Path,
    *,
    overwrite: bool,
    names: tuple[str, ...] | None = None,
    preserve_existing: bool = False,
    protected: frozenset[Path] = frozenset(),
) -> bool:
    """Copy an asset tree file-by-file; the single copy primitive of this module.

    ``names`` limits the copy to those top-level package names (bundled
    Skills); ``preserve_existing`` never clobbers; ``protected`` lists live
    install state (editor configs, hook wrappers) an upgrade must leave alone.
    Bytecode never ships — pip compiles packaged assets, and those caches are
    runtime noise rather than part of a reusable Skill.
    """
    import shutil

    if not src.is_dir():
        return False
    wrote = False
    for item in sorted(src.rglob("*")):
        parts = item.relative_to(src).parts
        if "__pycache__" in parts or item.suffix in {".pyc", ".pyo"}:
            continue
        if names and parts[0] not in names:
            continue
        target = dest / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists() and (preserve_existing or not overwrite or target in protected):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        wrote = True
    return wrote


def _materialize_assets(root: Path, base: Path, overwrite: bool) -> list[str]:
    """Assemble instance directories from the single-source asset tree."""
    # Editor config files carry the live hook wiring that `oks hook install`
    # writes. Re-copying the pristine asset over them silently un-wires
    # UserPromptSubmit and reverts migrated absolute paths, so an upgrade must
    # leave an existing one alone; a fresh init still gets it.
    wiring_state = {root / rel for rel in _HOOK_EDITORS.values()}

    # The interpreter baked into a wrapper's OKS_PYTHON fallback is also live
    # install state, written by `oks hook install`. Copying the pristine asset
    # resets it to `python3`, which cannot import knowledge_studio on a
    # pipx/venv install — so an upgrade would refresh the engines and disable
    # the hooks in the same breath. Snapshot each bake and restore it after.
    default_bake = '"${OKS_PYTHON:-python3}"'
    preserved_bakes: dict[Path, str] = {}
    for dest_name, spec in _AGENT_TARGETS.items():
        if not spec["hooks"]:
            continue
        for name in _RECALL_HOOK_SCRIPTS:
            if not name.endswith(".sh"):
                continue
            wrapper = root / dest_name / "hooks" / name
            try:
                body = wrapper.read_text(encoding="utf-8")
            except OSError:
                continue
            found = re.search(r"\$\{OKS_PYTHON:-([^}]+)\}", body)
            if found and found.group(1) != "python3":
                preserved_bakes[wrapper] = f'"${{OKS_PYTHON:-{found.group(1)}}}"'

    done: list[str] = []
    for name in _SHARED_ASSETS:
        src = base / name
        if _copy_tree(src, root / name, overwrite=overwrite, preserve_existing=True):
            done.append(name)
    index = base / "profiles" / "INDEX.md"
    if index.is_file() and not (root / "profiles" / "INDEX.md").exists():
        store._atomic_write(root / "profiles" / "INDEX.md", index.read_text(encoding="utf-8"))
        done.append("profiles/INDEX.md")

    for dest_name, spec in _AGENT_TARGETS.items():
        dest = root / dest_name
        wrote = False
        if spec["config"]:
            config_dir = base / "agent-config" / spec["config"]
            wrote |= _copy_tree(
                config_dir, dest, overwrite=overwrite, protected=wiring_state
            )
        for skill_name in spec.get("skill_names", ()):
            skills_dest = dest / "skills" / skill_name
            wrote |= _copy_tree(
                base / "skills" / skill_name, skills_dest, overwrite=overwrite
            )
        for component in ("skills", "hooks", "rules"):
            src = base / component
            if not spec[component] or not src.is_dir():
                continue
            if component == "skills":
                for skill_name in _DEFAULT_CORE_SKILLS:
                    wrote |= _copy_tree(
                        src / skill_name,
                        dest / component / skill_name,
                        overwrite=overwrite,
                    )
            else:
                wrote |= _copy_tree(
                    src, dest / component, overwrite=overwrite, protected=wiring_state
                )
        if wrote:
            done.append(dest_name)
    for wrapper, bake in preserved_bakes.items():
        try:
            body = wrapper.read_text(encoding="utf-8")
        except OSError:
            continue
        if default_bake in body:
            wrapper.write_text(body.replace(default_bake, bake), encoding="utf-8")
    _bake_codex_lifecycle_hooks(root)
    return done


def init(
    path: str = typer.Argument(..., help="Target directory for the new knowledge instance"),
    set_default: Optional[bool] = typer.Option(
        None, "--set-default/--no-set-default",
        help=(
            "Register this folder as the active KB in ~/.oks/config.json. "
            "Default: only when no active KB is registered yet"
        ),
    ),
    git: bool = typer.Option(
        True, "--git/--no-git", help="Run `git init` in the instance folder",
    ),
    upgrade: bool = typer.Option(
        False, "--upgrade",
        help="Refresh bundled skills and hooks; preserve existing knowledge and settings, and add missing defaults",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Scaffold into a non-empty directory that is not already a knowledge base",
    ),
):
    """Scaffold a new knowledge INSTANCE folder (e.g. your personal artboy-knowledge-studio).

    Creates the bucket structure and a .gitignore that TRACKS your memory
    (wiki/, drafts/, profiles/) while ignoring only per-machine state (.oks/).
    Points ~/.oks/config.json at the new folder only when no active KB is
    registered yet; pass --set-default to switch an existing one.
    """
    root = Path(path).expanduser().resolve()

    # Refuse to scaffold into an existing non-empty directory that is not
    # already a KB (missing wiki/) — protects arbitrary folders from being
    # hijacked. Re-running on an existing KB is idempotent and allowed.
    if (
        root.is_dir()
        and any(root.iterdir())
        and not (root / "wiki").is_dir()
        and not force
    ):
        console.print(
            f"[red]Refusing to scaffold into non-empty directory:[/red] {root}\n"
            f"It does not look like a knowledge base (no wiki/). Init would create:\n"
            + "\n".join(f"  - {d}/" for d in _INSTANCE_DIRS)
            + "\n  - host integration and settings/ (missing defaults only)"
            + "\n  - .gitignore"
            + "\n\nRe-run with [bold]--force[/bold] to proceed anyway."
        )
        raise typer.Exit(1)

    root.mkdir(parents=True, exist_ok=True)
    from .studio_history import initialize
    initialize(root)

    for d in _INSTANCE_DIRS:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        (p / ".gitkeep").touch()

    if not (root / "README.md").exists():
        store._atomic_write(root / "README.md", _INSTANCE_README_MD)

    base = _asset_source()
    if base is None:
        console.print(
            "[yellow]No bundled assets found — skills/settings not materialized.[/yellow]\n"
            "  Reinstall the canonical main source with pipx, then retry:\n"
            "  pipx upgrade open-knowledge-studio\n"
            "  or run python cli/scripts/bundle_assets.py in the repo before installing."
        )
    else:
        copied = _materialize_assets(root, base, overwrite=upgrade)
        if copied:
            console.print(f"[green]Materialized assets:[/green] {', '.join(copied)}")
        else:
            console.print("[dim]Assets already present (use --upgrade to refresh).[/dim]")

    agents_md = root / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(
            _INSTANCE_AGENTS_MD.format(name=root.name),
            encoding="utf-8",
        )
        console.print(f"[green]Wrote[/green] {agents_md}")

    gitignore = root / ".gitignore"
    if gitignore.exists():
        console.print(f"[yellow]Kept existing[/yellow] .gitignore ({gitignore})")
    else:
        gitignore.write_text(_INSTANCE_GITIGNORE, encoding="utf-8")
        console.print(f"[green]Wrote[/green] {gitignore}")

    if git and not (root / ".git").exists():
        import subprocess
        try:
            subprocess.run(
                ["git", "init"], cwd=str(root),
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            console.print(f"[green]git init[/green] {root}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            console.print(f"[yellow]Skipped git init:[/yellow] {e}")

    if set_default is not False:
        from knowledge_studio.config import init_config, load_config

        current = load_config().get("knowledge_base_path")
        adopting = set_default is True or not current
        if adopting:
            init_config(str(root))
            console.print(f"[green]Active KB set:[/green] {root}")
        elif Path(current).resolve() != root:
            # Replacing this silently loses the old path for good, and every
            # later `oks ingest` / `oks wiki create` would write here instead.
            console.print(
                f"[yellow]Active KB left unchanged:[/yellow] {current}\n"
                f"  to switch: [bold]oks init {root} --set-default[/bold]"
            )

    console.print(
        f"\n[bold]{t('init_ready')}[/bold]\n"
        f"{t('init_step_install')}\n"
        f"{t('init_step_ingest')}\n"
        f"{t('init_step_status')}\n"
        f"\n[dim]{t('init_capabilities')}[/dim]\n"
        f"  [dim]watch    - 视频/音频 (faster-whisper + yt-dlp + RapidOCR)[/dim]\n"
        f"  [dim]document - Office/HTML/文本 (markitdown)[/dim]\n"
        f"  [dim]pdf      - PDF (MinerU)[/dim]\n"
        f"  [dim]formula  - 公式 OCR (PaddleOCR)[/dim]"
    )


@team_app.command("init")
def team_init(
    path: str = typer.Argument(
        "./team-knowledge-studio",
        help="Target directory for the shared team knowledge instance",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        help="Human-readable team name (defaults to the folder name).",
    ),
    set_default: Optional[bool] = typer.Option(
        None,
        "--set-default/--no-set-default",
        help="Register this folder as the active KB (default: only when none exists).",
    ),
    git: bool = typer.Option(
        True,
        "--git/--no-git",
        help="Initialize a Git repository for shared team history.",
    ),
    upgrade: bool = typer.Option(
        False,
        "--upgrade",
        help="Refresh bundled assets while keeping team knowledge files intact.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Scaffold into a non-empty directory that is not already a knowledge base.",
    ),
):
    """Create a shared team instance on top of the normal OKS scaffold.

    Team knowledge is still stored as tracked Markdown under profiles/, raw/,
    wiki/, and drafts/. This command only adds an explicit team-oriented entry
    point and creates a minimal team profile; goals are created by the user.
    """
    root = Path(path).expanduser().resolve()
    team_name = " ".join((name or root.name).split())
    if not team_name:
        team_name = "Knowledge Studio Team"

    # Reuse the well-tested personal scaffold so both modes share the same
    # non-empty-directory guard, asset materialization, git setup, and active
    # KB semantics.
    init(
        path=str(root),
        set_default=set_default,
        git=git,
        upgrade=upgrade,
        force=force,
    )

    def write_team_file(path: Path, contents: str) -> None:
        store._atomic_write(path, contents)

    def yaml_string(value: str) -> str:
        # JSON string quoting is a strict subset of YAML double-quoted syntax.
        return json.dumps(value, ensure_ascii=False)

    team_profile = root / "profiles" / "team.md"
    if not team_profile.exists():
        write_team_file(
            team_profile,
            "---\n"
            f"title: {yaml_string(team_name)}\n"
            "type: profile\n"
            "tags: [team, knowledge-base]\n"
            "status: active\n"
            "source: team-init\n"
            "---\n\n"
            f"# {team_name}\n\n"
            "Shared context for the team knowledge workspace.\n",
        )
    console.print(
        f"\n[bold green]Team knowledge studio ready:[/bold green] {root}\n"
        f"  team profile: profiles/team.md ({team_name})\n\n"
        "Create shared knowledge and dated goals when needed.\n"
        "Each member links this independent repository through their personal "
        "settings/sources.yaml; existing files are not copied into personal Wiki.\n"
        "Commit and share through the team's authorized Git workflow."
    )



@team_app.command("sync")
def team_sync_command(
    path: Optional[str] = typer.Option(None, "--path", help="Knowledge base root"),
    push: bool = typer.Option(False, "--push/--no-push", help="Push the committed team files to origin"),
    message: str = typer.Option("同步 OKS 团队资料", "--message", help="Commit message for shared files"),
) -> None:
    """One-step team transport: commit shared files, rebase, optionally push."""
    from knowledge_studio.team_sync import TeamSyncError, sync

    try:
        result = sync(_instance_root(path), push=push, message=message)
    except TeamSyncError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    actions = " → ".join(result.get("actions", [])) or "无变更"
    remote = "已配置 origin" if result.get("remote") else "未配置 origin"
    console.print(f"[green]团队同步完成:[/green] {actions} · {remote}")
    if result.get("ignored_changes"):
        console.print(f"[yellow]有 {result['ignored_changes']} 个非团队目录变更未纳入同步。[/yellow]")


def skills_install(
    force: bool = typer.Option(False, "--force", help="Overwrite existing skills"),
    all_bundled: bool = typer.Option(False,'--all-bundled',help='Opt in to legacy and specialized bundled Skills'),
    consolidate: bool = typer.Option(False,'--consolidate',help='Archive old bundled host Skills and keep the minimal core entry'),
    global_install: bool = typer.Option(False, "--global", help="Install only oh-my-oks into one global host directory"),
    editor: Optional[str] = typer.Option(None, "--editor", help="Global host: codex, claude or agents"),
) -> None:
    """Materialize bundled skills into supported Agent directories (current KB).

    Use after upgrading oks to refresh the minimal oh-my-oks entry,
    without re-running full `oks init`.
    """
    if global_install:
        if all_bundled or consolidate or not editor:
            raise typer.BadParameter("Use --global --editor codex|claude|agents; do not combine with --all-bundled or --consolidate")
        from . import skill_bundle
        base = _asset_source()
        if base is None:
            raise typer.BadParameter("Bundled assets unavailable; reinstall OKS")
        try:
            _emit_json(skill_bundle.install_global(base, editor, overwrite=force))
        except (OSError, ValueError) as exc:
            raise typer.BadParameter(str(exc))
        return
    if editor:
        raise typer.BadParameter("--editor is for --global installation")
    root = Path.cwd()
    if not (root / "wiki").is_dir():
        console.print("[red]Not in a knowledge base directory (no wiki/).[/red]")
        raise typer.Exit(1)
    base = _asset_source()
    if base is None:
        console.print("[red]No bundled assets found. Reinstall: pipx upgrade open-knowledge-studio[/red]")
        raise typer.Exit(1)
    from . import skill_bundle

    if all_bundled and consolidate:
        raise typer.BadParameter("Choose --all-bundled or --consolidate")
    if consolidate:
        archived = skill_bundle.consolidate(
            root, base, [name for name, spec in _AGENT_TARGETS.items() if spec["skills"]]
        )
        if archived.get("manifest"):
            console.print("Archived legacy packages: " + archived["manifest"], markup=False)
    done: list[str] = []
    for dest_name, spec in _AGENT_TARGETS.items():
        skill_names = tuple(spec.get("skill_names", ()))
        if not spec.get("skills") and not skill_names:
            continue
        if spec.get("skills") and not all_bundled:
            skill_names = _DEFAULT_CORE_SKILLS
        dest = root / dest_name / "skills"
        dest.mkdir(parents=True, exist_ok=True)
        if _copy_tree(base / "skills", dest, overwrite=force, names=skill_names):
            done.append(dest_name)
    if done:
        skill_names = sorted(p.name for p in (base / "skills").iterdir() if p.is_dir()) if all_bundled else list(_DEFAULT_CORE_SKILLS)
        console.print(f"[green]Installed skills into:[/green] {', '.join(done)}")
        console.print(f"[dim]Skills: {', '.join(skill_names)}[/dim]")
    else:
        console.print("[dim]Skills already present (use --force to refresh).[/dim]")


def _instance_root(path: str | None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    from knowledge_studio.config import get_kb_root
    return get_kb_root()


def _onboarding_root(path):
    root = _instance_root(path)
    if not (root / "wiki").is_dir():
        raise typer.BadParameter("Choose an existing knowledge instance (--path)")
    return root


@onboarding_app.command("status")
def onboarding_status(path: Optional[str] = typer.Option(None, "--path")):
    """Read the same progress that Studio displays; no completion is inferred."""
    from .studio_history import onboarding
    _emit_json(onboarding(_onboarding_root(path)))


@onboarding_app.command("complete")
def onboarding_complete(step: str, path: Optional[str] = typer.Option(None, "--path")):
    """Record an explicitly finished teaching step: discuss, goals or learning."""
    from .studio_history import onboarding
    try:
        _emit_json(onboarding(_onboarding_root(path), {"action": "complete_step", "step": step}))
    except ValueError as exc:
        raise typer.BadParameter(str(exc))


@onboarding_app.command("skip")
def onboarding_skip(path: Optional[str] = typer.Option(None, "--path")):
    """Skip teaching without marking its steps complete."""
    from .studio_history import onboarding
    _emit_json(onboarding(_onboarding_root(path), {"action": "skip"}))


@onboarding_app.command("reset")
def onboarding_reset(path: Optional[str] = typer.Option(None, "--path")):
    """Explicitly reopen the three-step teaching flow."""
    from .studio_history import onboarding
    _emit_json(onboarding(_onboarding_root(path), {"action": "reset"}))


def register(app: typer.Typer) -> None:
    """Attach the top-level instance commands to the root CLI.

    A decorator at import time would bind them to this module's (nonexistent)
    app; registering explicitly keeps the command tree identical to the
    pre-split CLI.
    """
    app.command()(init)
    app.command(name="skills-install")(skills_install)
