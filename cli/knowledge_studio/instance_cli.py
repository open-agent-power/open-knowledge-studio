"""Bootstrap instances, install bundled assets, and synchronize team files."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Optional

import typer
from rich.console import Console

from . import hooks, resources, store
from .cli_common import instance_root
from .i18n import t

app = typer.Typer()
console = Console()


team_app = typer.Typer(
    help="Shared team knowledge-base bootstrap and onboarding.",
    no_args_is_help=True,
)

_INSTANCE_DIRS = [
    "goal",
    "discuss",
    "skill",
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

_SHARED_ASSETS = ("templates", "_meta", "settings", "profiles")

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

def _materialize_assets(root: Path, base: Path, overwrite: bool) -> list[str]:
    """Assemble instance directories from the single-source asset tree."""
    import shutil

    # Editor config files carry the live hook wiring that `oks hook install`
    # writes. Re-copying the pristine asset over them silently un-wires
    # UserPromptSubmit and reverts migrated absolute paths, so an upgrade must
    # leave an existing one alone; a fresh init still gets it.
    wiring_state = {root / rel for rel in hooks._HOOK_EDITORS.values()}

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
        for name in hooks._RECALL_HOOK_SCRIPTS:
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

    def copy_into(src: Path, dest: Path) -> bool:
        """Merge per file: never clobber what the user changed unless upgrading.

        A directory-level check would skip whole trees, because `init` creates
        the bucket directories (profiles/...) before assets are materialized.
        """
        wrote = False
        for item in sorted(src.rglob("*")):
            # pip compiles Python files inside packaged assets on installation.
            # Those caches are runtime noise, not part of a reusable Skill.
            if "__pycache__" in item.relative_to(src).parts or item.suffix in {".pyc", ".pyo"}:
                continue
            target = dest / item.relative_to(src)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if target.exists() and (not overwrite or target in wiring_state):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            wrote = True
        return wrote

    done: list[str] = []
    for name in _SHARED_ASSETS:
        src = base / name
        if src.is_dir() and copy_into(src, root / name):
            done.append(name)

    for dest_name, spec in _AGENT_TARGETS.items():
        dest = root / dest_name
        wrote = False
        if spec["config"]:
            config_dir = base / "agent-config" / spec["config"]
            if config_dir.is_dir():
                wrote |= copy_into(config_dir, dest)
        skill_names = spec.get("skill_names", ())
        if skill_names:
            for skill_name in skill_names:
                src = base / "skills" / skill_name
                if src.is_dir():
                    wrote |= copy_into(src, dest / "skills" / skill_name)
        for component in ("skills", "hooks", "rules"):
            src = base / component
            if spec[component] and src.is_dir():
                wrote |= copy_into(src, dest / component)
        if wrote:
            done.append(dest_name)
    for wrapper, bake in preserved_bakes.items():
        try:
            body = wrapper.read_text(encoding="utf-8")
        except OSError:
            continue
        if default_bake in body:
            wrapper.write_text(body.replace(default_bake, bake), encoding="utf-8")
    hooks._bake_codex_lifecycle_hooks(root)
    return done

@app.command()
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
        help="Re-copy bundled assets (skills/templates/_meta/settings), overwriting them; your memory (wiki/drafts/profiles) is untouched",
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
            + "\n  - .claude/ templates/ _meta/ settings/ (bundled assets)"
            + "\n  - .gitignore"
            + "\n\nRe-run with [bold]--force[/bold] to proceed anyway."
        )
        raise typer.Exit(1)

    root.mkdir(parents=True, exist_ok=True)

    for d in _INSTANCE_DIRS:
        p = root / d
        p.mkdir(parents=True, exist_ok=True)
        (p / ".gitkeep").touch()

    base = resources.asset_source()
    if base is None:
        console.print(
            "[yellow]No bundled assets found — skills/templates not materialized.[/yellow]\n"
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
    point and labels the bundled team profile/goal for the new workspace.
    """
    root = Path(path).expanduser().resolve()
    team_name = " ".join((name or root.name.replace("-", " ").replace("_", " ")).split())
    if not team_name:
        team_name = "Knowledge Studio Team"

    # `oks init --upgrade` refreshes bundled assets. Protect the two team
    # knowledge files before delegating so an upgrade cannot clobber edits.
    preserved_team_files: dict[Path, str] = {}
    if upgrade:
        for relative in (Path("profiles/team.md"), Path("profiles/goals/team.md")):
            candidate = root / relative
            if candidate.is_file():
                preserved_team_files[candidate] = candidate.read_text(encoding="utf-8")

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

    for candidate, contents in preserved_team_files.items():
        store._atomic_write(candidate, contents)

    def write_team_file(path: Path, contents: str) -> None:
        store._atomic_write(path, contents)

    def yaml_string(value: str) -> str:
        # JSON string quoting is a strict subset of YAML double-quoted syntax.
        return json.dumps(value, ensure_ascii=False)

    team_profile = root / "profiles" / "team.md"
    team_goal = root / "profiles" / "goals" / "team.md"
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
    else:
        profile_text = team_profile.read_text(encoding="utf-8")
        # The bundled upstream profile is a useful seed, but its default title
        # should not leak into a newly named team. Never rewrite a customized
        # profile on a rerun.
        if 'title: "Knowledge Studio Team"' in profile_text:
            profile_text = profile_text.replace(
                'title: "Knowledge Studio Team"',
                f"title: {yaml_string(team_name)}",
                1,
            ).replace("# Knowledge Studio Team", f"# {team_name}", 1)
            write_team_file(team_profile, profile_text)

    if not team_goal.exists():
        write_team_file(
            team_goal,
            "---\n"
            f"title: {yaml_string(team_name + ' Goals')}\n"
            "type: goal\n"
            "owner: team\n"
            "status: active\n"
            "domains: [computing, AI]\n"
            "keywords: [knowledge, collaboration, agent loop]\n"
            "source: team-init\n"
            "---\n\n"
            f"# {team_name} Goals\n\n"
            "Define the next shared outcome and keep it visible to every team member.\n",
        )
    else:
        goal_text = team_goal.read_text(encoding="utf-8")
        if "title: Team Goals 2026" in goal_text:
            goal_text = goal_text.replace(
                "title: Team Goals 2026",
                f"title: {yaml_string(team_name + ' Goals')}",
                1,
            ).replace("# Team Goals 2026-Q3", f"# {team_name} Goals", 1)
            write_team_file(team_goal, goal_text)

    console.print(
        f"\n[bold green]Team knowledge studio ready:[/bold green] {root}\n"
        f"  team profile: profiles/team.md ({team_name})\n"
        "  shared goal:   profiles/goals/team.md\n\n"
        "Next steps:\n"
        f"  1. Review the team profile and goal in {root}\n"
        "  2. Commit and share this folder through your normal Git workflow\n"
        "  3. Each member clones it, installs OKS skills, and binds their profile with:\n"
        "     oks registry bind --profile <user-id> --goals team\n"
        "     Run `oks team sync --push` when you want to exchange team files.\n"
        "  4. Use /query and the knowledge-to-word skill against the shared Wiki"
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
        result = sync(instance_root(path), push=push, message=message)
    except TeamSyncError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    actions = " → ".join(result.get("actions", [])) or "无变更"
    remote = "已配置 origin" if result.get("remote") else "未配置 origin"
    console.print(f"[green]团队同步完成:[/green] {actions} · {remote}")
    if result.get("ignored_changes"):
        console.print(f"[yellow]有 {result['ignored_changes']} 个非团队目录变更未纳入同步。[/yellow]")

@app.command(name="skills-install")
def skills_install(
    force: bool = typer.Option(False, "--force", help="Overwrite existing skills"),
) -> None:
    """Materialize bundled skills into supported Agent directories (current KB).

    Use after upgrading oks to refresh skills (e.g. /assess replacing /start),
    without re-running full `oks init`.
    """
    root = Path.cwd()
    if not (root / "wiki").is_dir():
        console.print("[red]Not in a knowledge base directory (no wiki/).[/red]")
        raise typer.Exit(1)
    base = resources.asset_source()
    if base is None:
        console.print("[red]No bundled assets found. Reinstall: pipx upgrade open-knowledge-studio[/red]")
        raise typer.Exit(1)
    import shutil
    done: list[str] = []
    for dest_name, spec in _AGENT_TARGETS.items():
        skill_names = tuple(spec.get("skill_names", ()))
        if not spec.get("skills") and not skill_names:
            continue
        dest = root / dest_name / "skills"
        if force and dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        wrote = False
        src = base / "skills"
        if src.is_dir():
            for item in sorted(src.rglob("*")):
                if "__pycache__" in item.relative_to(src).parts or item.suffix in {".pyc", ".pyo"}:
                    continue
                if skill_names and item.relative_to(src).parts[0] not in skill_names:
                    continue
                target = dest / item.relative_to(src)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if target.exists() and not force:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                wrote = True
        if wrote:
            done.append(dest_name)
    if done:
        skill_names = sorted(p.name for p in (base / "skills").iterdir() if p.is_dir()) if (base / "skills").is_dir() else []
        console.print(f"[green]Installed skills into:[/green] {', '.join(done)}")
        console.print(f"[dim]Skills: {', '.join(skill_names)}[/dim]")
    else:
        console.print("[dim]Skills already present (use --force to refresh).[/dim]")


app.add_typer(team_app, name="team")
