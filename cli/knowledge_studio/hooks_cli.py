"""CLI entry points for editor-hook installation, recall and history."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Optional

import typer
from rich.console import Console

from . import hooks, resources
from .cli_common import emit_json, instance_root

console = Console()


app = typer.Typer(help="Optional editor hooks for recall, conflict detection, collaboration, and workflow.")

@app.command("recall")
def hook_recall(
    prompt: str = typer.Argument(help="User prompt to run through the installed auto-recall policy"),
    output_format: str = typer.Option("json", "--format", help="Output format: json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
    session_id: str = typer.Option("", "--session-id", help="Stable caller session id for cooldown"),
    cwd: str = typer.Option("", "--cwd", help="Caller working directory for registry/history scope"),
    agent_id: str = typer.Option("", "--agent-id", help="Caller agent id for registry scope"),
) -> None:
    """Run the existing UserPromptSubmit recall policy and emit a JSON result."""
    if output_format.strip().lower() != "json":
        console.print("[red]--format must be json[/red]")
        raise typer.Exit(2)
    root = instance_root(path)
    emit_json(hooks._run_hook_recall(root, prompt, session_id, cwd, agent_id))

@app.command("history")
def hook_history(
    output_format: str = typer.Option("json", "--format", help="Output format: json"),
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
    limit: int = typer.Option(12, "--limit", min=1, max=50, help="Maximum retained injection summaries"),
    session_id: str = typer.Option("", "--session-id", help="Optional stable caller session id filter"),
    cwd: str = typer.Option("", "--cwd", help="Optional caller directory filter"),
) -> None:
    """Read retained auto-recall summaries without exposing prompts or bodies."""
    if output_format.strip().lower() != "json":
        console.print("[red]--format must be json[/red]")
        raise typer.Exit(2)
    emit_json(hooks._read_hook_history(instance_root(path), limit, session_id, cwd))

@app.command("install")
def hook_install(
    editor: str = typer.Option(
        "both", "--editor", "-e", help="Which editor(s) to wire: claude | qoder | codex | both"
    ),
    collaboration: bool = typer.Option(
        False, "--collaboration", help="Opt in to automatic subagent lifecycle Mail records (Claude or Codex only)"
    ),
    workflow: bool = typer.Option(
        False, "--workflow", help="Enable opt-in automatic task archival and learning candidates (Claude or Codex only)"
    ),
    path: Optional[str] = typer.Option(
        None, "--path", help="Instance root (default: active KB from ~/.oks/config.json)"
    ),
    workspace: Optional[str] = typer.Option(
        None, "--workspace", help="Workspace whose .claude/.codex hooks should be wired (only with --workflow; defaults to the KB root)"
    ),
):
    """Wire prompt recall and conflict hooks; optionally record collaboration/workflow events.

    Copies the hook scripts into the chosen editor's hook directory (if missing)
    and adds UserPromptSubmit + PostToolUse entries. `--collaboration` opts in
    to SubagentStart/SubagentStop Mail recording. `--workflow` enables archival
    and learning-candidate events and implies `--collaboration`.
    Idempotent and non-destructive: existing settings and hooks are preserved.
    """
    editor = editor.lower().strip()
    if editor not in ("claude", "qoder", "codex", "both"):
        console.print("[red]--editor must be one of: claude, qoder, codex, both[/red]")
        raise typer.Exit(1)
    if (collaboration or workflow) and editor not in ("claude", "codex"):
        console.print(
            "[red]--collaboration and --workflow require exactly one supported editor: --editor claude or --editor codex[/red]"
        )
        raise typer.Exit(1)
    if workspace is not None and not workflow:
        console.print("[red]--workspace can only be used with --workflow[/red]")
        raise typer.Exit(1)
    if workspace is not None and not workspace.strip():
        console.print("[red]--workspace must name an existing directory[/red]")
        raise typer.Exit(1)
    collaboration = collaboration or workflow
    if collaboration:
        base = resources.asset_source()
        candidate = base / "hooks" / hooks._SUBAGENT_COLLABORATION_SCRIPT if base else None
        if candidate is None or not candidate.is_file():
            console.print(
                f"[red]Bundled hook script not found: {hooks._SUBAGENT_COLLABORATION_SCRIPT}[/red]"
            )
            raise typer.Exit(1)

    if os.name == "nt":
        if editor == "codex":
            console.print(
                "[dim]Native Windows: Codex prompt/conflict hooks use Python directly.[/dim]\n"
                "  Codex lifecycle hooks (PreToolUse/PreCompact/SessionStart) remain Bash-based; "
                "use WSL or Git Bash for those hooks."
            )
        else:
            console.print(
                "[dim]Native Windows: Claude prompt/conflict hooks use Python direct-exec.[/dim]\n"
                "  Qoder and lifecycle hooks still require WSL or Git Bash."
            )

    root = instance_root(path)
    if not root.is_dir():
        console.print(f"[red]Instance root not found:[/red] {root}")
        raise typer.Exit(1)

    workspace_root = Path(workspace).expanduser().resolve() if workspace is not None else root.resolve()
    if workflow and not workspace_root.is_dir():
        console.print(f"[red]Workspace directory not found:[/red] {workspace_root}")
        raise typer.Exit(1)
    cross_workspace = workflow and workspace_root != root.resolve()

    if workflow:
        settings_path = workspace_root / hooks._HOOK_EDITORS[editor]
        workflow_path = root / hooks._WORKFLOW_CONFIG_RELATIVE_PATH
        try:
            # Validate all state this command will touch before baking scripts,
            # migrating Codex paths, or wiring any event.
            if settings_path.exists():
                settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
                if not isinstance(settings_data, dict):
                    raise ValueError(f"{settings_path} must contain a JSON object")
                hook_map = settings_data.get("hooks", {})
                if not isinstance(hook_map, dict):
                    raise ValueError(f"{settings_path} hooks field must be a JSON object")
                for event in set(("UserPromptSubmit", "PostToolUse", *hooks._WORKFLOW_EVENTS)):
                    groups = hook_map.get(event, [])
                    if not isinstance(groups, list) or any(
                        not isinstance(group, dict)
                        or not isinstance(group.get("hooks", []), list)
                        or any(not isinstance(handler, dict) for handler in group.get("hooks", []))
                        for group in groups
                    ):
                        raise ValueError(f"{settings_path} has an invalid hooks.{event} structure")
            hooks._read_task_workflow_config(workflow_path)
            assets = resources.asset_source()
            if assets is None:
                raise FileNotFoundError("bundled hook assets are unavailable")
            required_assets = (*hooks._HOOK_SUPPORT_FILES, *hooks._RECALL_HOOK_SCRIPTS, hooks._SUBAGENT_COLLABORATION_SCRIPT)
            missing_assets = [name for name in required_assets if not (assets / "hooks" / name).is_file()]
            if missing_assets:
                raise FileNotFoundError("missing bundled hook assets: " + ", ".join(missing_assets))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            console.print(f"[red]Cannot enable workflow without changing files:[/red] {error}")
            raise typer.Exit(1)

    if editor == "codex":
        hooks._bake_codex_lifecycle_hooks(workspace_root)

    editors = ("claude", "qoder") if editor == "both" else (editor,)

    # Claude and Qoder share one script directory; Codex has its own project
    # hook layer. Materialize each directory once even when both shared editors
    # are selected.
    hook_dirs = []
    for name in editors:
        hooks_dir = workspace_root / hooks._HOOK_SCRIPT_DIRS[name]
        if hooks_dir not in hook_dirs:
            hook_dirs.append(hooks_dir)
    for hooks_dir in hook_dirs:
        try:
            created = hooks._ensure_recall_scripts(root, hooks_dir=hooks_dir)
            if workflow and cross_workspace:
                runner_source = resources.asset_source() / "hooks" / "_hook_runner.py"
                runner_target = hooks_dir / "_hook_runner.py"
                if runner_target.read_bytes() != runner_source.read_bytes():
                    shutil.copy2(runner_source, runner_target)
                    if "_hook_runner.py" not in created:
                        created.append("_hook_runner.py")
            if collaboration and hooks._ensure_subagent_collaboration_script(hooks_dir):
                created.append(hooks._SUBAGENT_COLLABORATION_SCRIPT)
        except FileNotFoundError as e:
            console.print(
                f"[red]Cannot install hook — bundled assets missing.[/red]\n"
                f"  {e}\n"
                f"  This happens when oks was installed from source without the asset bundle.\n"
                f"  Fix: [bold]pipx upgrade open-knowledge-studio[/bold],\n"
                f"  or run [bold]python cli/scripts/bundle_assets.py[/bold] in the repo before installing."
            )
            raise typer.Exit(1)
        if created:
            console.print(
                f"[green]Installed hook script ({hooks_dir}):[/green] {', '.join(created)}"
            )

    for name in editors:
        settings_path = workspace_root / hooks._HOOK_EDITORS[name]
        script_dir = workspace_root / hooks._HOOK_SCRIPT_DIRS[name]
        hook_args: list[str] | None = None
        post_args: list[str] | None = None
        if name == "codex":
            hooks._migrate_codex_hook_paths(settings_path, workspace_root)
        if workflow and cross_workspace:
            hook_cmd, hook_args = hooks._workflow_hook_command(
                script_dir, "user-prompt-recall.py", root.resolve(), name
            )
            post_cmd, post_args = hooks._workflow_hook_command(
                script_dir, "post-tool-edit.py", root.resolve(), name
            )
            collaboration_cmd, collaboration_args = hooks._workflow_hook_command(
                script_dir, hooks._SUBAGENT_COLLABORATION_SCRIPT, root.resolve(), name
            )
        elif name == "codex" and os.name == "nt":
            hook_cmd = hooks._codex_python_hook_command(script_dir, "user-prompt-recall.py")
            post_cmd = hooks._codex_python_hook_command(script_dir, "post-tool-edit.py")
            collaboration_cmd = hooks._codex_python_hook_command(
                script_dir, hooks._SUBAGENT_COLLABORATION_SCRIPT, suppress_stderr=False
            ) if collaboration else ""
            collaboration_args = None
        elif name == "claude" and os.name == "nt":
            hook_cmd, hook_args = hooks._windows_python_hook_exec(
                script_dir, "user-prompt-recall.py"
            )
            post_cmd, post_args = hooks._windows_python_hook_exec(
                script_dir, "post-tool-edit.py"
            )
            if collaboration:
                collaboration_cmd, collaboration_args = hooks._windows_python_hook_exec(
                    script_dir, hooks._SUBAGENT_COLLABORATION_SCRIPT
                )
            else:
                collaboration_cmd, collaboration_args = "", None
        else:
            hook_cmd = (script_dir / hooks._RECALL_HOOK_SCRIPT_NAME).resolve().as_posix()
            post_cmd = (script_dir / hooks._POST_TOOL_SCRIPT_NAME).resolve().as_posix()
            collaboration_script = (
                script_dir / hooks._SUBAGENT_COLLABORATION_SCRIPT
            ).resolve()
            collaboration_cmd = (
                f"{shlex.quote(sys.executable)} {shlex.quote(str(collaboration_script))}"
                if collaboration
                else ""
            )
            collaboration_args = None
        result = hooks._wire_userpromptsubmit(settings_path, hook_cmd, hook_args)
        post_result = hooks._wire_posttooluse(settings_path, post_cmd, post_args)
        label = "[green]wired[/green]" if result == "wired" else "[dim]already wired[/dim]"
        post_label = "[green]+conflict[/green]" if post_result == "wired" else "[dim]+conflict (exists)[/dim]"
        console.print(f"  {name}: {label} {post_label} → {settings_path}")
        if collaboration:
            events = hooks._WORKFLOW_EVENTS if workflow else ("SubagentStart", "SubagentStop")
            for event in events:
                event_result = hooks._wire_subagent_collaboration(
                    settings_path, event, collaboration_cmd, collaboration_args
                )
                event_label = (
                    "[green]wired[/green]"
                    if event_result == "wired"
                    else "[dim]already wired[/dim]"
                )
                scope_label = "workflow" if workflow else "collaboration"
                console.print(f"  {name} {scope_label} {event}: {event_label}")

    if workflow:
        try:
            hooks._enable_task_workflow(root / hooks._WORKFLOW_CONFIG_RELATIVE_PATH, editor)
        except (OSError, ValueError) as error:
            console.print(f"[red]Hook events were wired, but workflow settings could not be saved:[/red] {error}")
            raise typer.Exit(1)

    features = ["auto-recall", "conflict detection"]
    if collaboration:
        features.append("opt-in subagent lifecycle hooks")
    if workflow:
        features.append("automatic workflow hooks (no model is started by install)")
    conflict_message = "File edits across agents trigger conflict mail.\n"
    trust_message = (
        "Codex: run `/hooks` in Codex to review and trust the current hook definitions.\n"
        if "codex" in editors
        else ""
    )
    message = (
        f"\n[bold]{' + '.join(features).capitalize()} enabled.[/bold]\n"
        + "New prompts inject relevant memory.\n"
        + conflict_message
        + trust_message
        + "Tune in settings/recall.yaml: recall.floor (0.7), recall.topn (3), recall.minlen (6),\n"
        + "  and conflict.window (300s)."
    )
    console.print(message)

@app.command("status")
def hook_status(
    path: Optional[str] = typer.Option(None, "--path", help="Instance root (default: active KB)"),
    workspace: Optional[str] = typer.Option(None, "--workspace", help="Workspace whose .claude/.codex hooks should be checked (defaults to the KB root)"),
):
    """Read the KB workflow setting and editor hook wiring without changing files."""
    root = instance_root(path)
    console.print(f"[bold]Instance:[/bold] {root}")
    if workspace is not None and not workspace.strip():
        console.print("[red]--workspace must name an existing directory[/red]")
        raise typer.Exit(1)
    workspace_root = Path(workspace).expanduser().resolve() if workspace is not None else root.resolve()
    if not workspace_root.is_dir():
        console.print(f"[red]Workspace directory not found:[/red] {workspace_root}")
        raise typer.Exit(1)
    console.print(f"[bold]Hook workspace:[/bold] {workspace_root}")
    import os
    import re
    import subprocess
    shown_dirs = []
    blockers: list[str] = []
    warnings: list[str] = []
    wiring: dict[str, tuple[bool, bool]] = {}
    active_hook_dirs: set[Path] = set()
    for name, rel in hooks._HOOK_EDITORS.items():
        settings_path = workspace_root / rel
        prompt_wired = hooks._hook_is_wired(settings_path)
        post_wired = hooks._hook_event_is_wired(
            settings_path, "PostToolUse", hooks._POST_TOOL_SCRIPT_NAMES
        )
        wiring[name] = (prompt_wired, post_wired)
        if prompt_wired or post_wired:
            active_hook_dirs.add(workspace_root / hooks._HOOK_SCRIPT_DIRS[name])
    any_wired = bool(active_hook_dirs)
    for name in hooks._HOOK_EDITORS:
        hooks_dir = workspace_root / hooks._HOOK_SCRIPT_DIRS[name]
        if hooks_dir in shown_dirs:
            continue
        shown_dirs.append(hooks_dir)
        script = hooks_dir / hooks._RECALL_HOOK_SCRIPT_NAME
        label = "script" if name == "claude" else f"{name} script"
        console.print(f"  {label}: {'present' if script.is_file() else 'missing'} ({script})")
        if not script.is_file():
            if hooks_dir in active_hook_dirs:
                blockers.append(f"{label} is missing — run `oks hook install`")
            continue
        m = re.search(r"\$\{OKS_PYTHON:-([^}]+)\}", script.read_text(encoding="utf-8"))
        py = os.environ.get("OKS_PYTHON") or (m.group(1) if m else "python3")
        try:
            if os.name == "nt" and name == "claude" and (hooks_dir / "_hook_runner.py").is_file():
                package_root = str(Path(__file__).resolve().parents[1])
                probe = f"import sys; sys.path.insert(0, {package_root!r}); import knowledge_studio"
            else:
                probe = "import knowledge_studio"
            ok = subprocess.run(
                [py, "-c", probe],
                capture_output=True, timeout=15,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        state = ("[green]importable[/green]" if ok
                 else "[red]hook script has stale interpreter — "
                      "run `oks hook install` to re-bake[/red]")
        console.print(f"  {label} engine: {state} (python: {py})")
        if not ok and hooks_dir in active_hook_dirs:
            blockers.append(
                f"{label} interpreter cannot import knowledge_studio ({py}) — "
                "run `oks hook install` to re-bake"
            )
        stale = hooks._stale_hook_engines(hooks_dir)
        if stale:
            console.print(
                f"  {label} engine version: [yellow]outdated[/yellow] ({', '.join(stale)})"
            )
            warnings.append(
                f"{label} engine differs from the bundled one ({', '.join(stale)}) — "
                f"run `oks init {root} --upgrade`; `oks hook install` keeps an "
                "existing engine and cannot refresh it"
            )
        else:
            console.print(f"  {label} engine version: [green]current[/green]")
    for name, rel in hooks._HOOK_EDITORS.items():
        wired, post_wired = wiring[name]
        state = "[green]wired[/green]" if wired else "[dim]not wired[/dim]"
        console.print(f"  {name}: {state}")
        post_state = "[green]wired[/green]" if post_wired else "[dim]not wired[/dim]"
        console.print(f"  {name} PostToolUse: {post_state}")
        for event in ("SubagentStart", "SubagentStop"):
            event_wired = hooks._hook_event_is_wired(
                workspace_root / rel, event, hooks._SUBAGENT_COLLABORATION_SCRIPT
            )
            event_state = "[green]wired[/green]" if event_wired else "[dim]not wired[/dim]"
            console.print(f"  {name} collaboration {event}: {event_state}")
        if name in ("claude", "codex"):
            workflow_path = root / hooks._WORKFLOW_CONFIG_RELATIVE_PATH
            try:
                workflow_config = hooks._read_task_workflow_config(workflow_path) if workflow_path.exists() else None
                configured = bool(
                    workflow_config
                    and workflow_config.get("enabled") is True
                    and name in workflow_config.get("hosts", [])
                )
                config_state = "enabled for this host" if configured else "not enabled for this host"
            except (OSError, ValueError) as error:
                workflow_config = None
                configured = False
                config_state = f"invalid settings ({error})"
            setting_label = "已启用" if configured else "未启用"
            if workflow_config is None and workflow_path.exists():
                setting_label = config_state
            console.print(f"  {name} workflow setting: {setting_label}")
            states = []
            for event in hooks._WORKFLOW_EVENTS:
                event_wired = hooks._hook_event_is_wired(
                    workspace_root / rel, event, hooks._SUBAGENT_COLLABORATION_SCRIPT
                )
                states.append(f"{event}={'已配置' if event_wired else '未配置'}")
            console.print(f"  {name} workflow hooks: " + ", ".join(states))
            console.print("  这里只检查本地配置，不验证宿主是否实际触发。")
        if name == "codex":
            console.print("  codex trust: review with `/hooks`")
