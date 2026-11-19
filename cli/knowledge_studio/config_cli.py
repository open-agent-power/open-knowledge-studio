"""`oks config` — global configuration at ~/.oks/config.json.

Split out of `cli.py` as a verbatim move (B4-5b). `_RECALL_YAML_KEYS` moved with
`config_set` because nothing else referenced it.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel

console = Console()

config_app = typer.Typer(help="Global configuration (~/.oks/config.json).")


# Keys that live in settings/recall.yaml rather than config.json.
_RECALL_YAML_KEYS = {
    "search_backend": (None, "search_backend"),
    "recall_floor": ("recall", "floor"),
    "recall_topn": ("recall", "topn"),
    "recall_minlen": ("recall", "minlen"),
    "recall_cooldown": ("recall", "cooldown"),
    "posttool_mode": ("posttool", "mode"),
    "posttool_signal_rel_floor": ("posttool", "signal_rel_floor"),
    "conflict_window": ("conflict", "window"),
    "mail_topn": (None, "mail_topn"),
}


@config_app.command("init")
def config_init(
    kb_path: str = typer.Option(None, "--kb-path", help="Knowledge base path"),
):
    """Initialize global config at ~/.oks/config.json."""
    from knowledge_studio.config import init_config

    try:
        path = init_config(kb_path)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Config created:[/green] {path}")

    from knowledge_studio.config import load_config
    config = load_config()
    console.print(f"  [dim]KB path: {config.get('knowledge_base_path', '')}[/dim]")


@config_app.command("show")
def config_show():
    """Show current global configuration."""
    from knowledge_studio.config import load_config, config_path, VALID_STRATEGIES

    config = load_config()
    strategy = config.get("strategy", "")
    strategy_display = strategy if strategy else "(not set)"

    console.print(f"[dim]Config file: {config_path()}[/dim]\n")
    console.print(Panel.fit(
        f"[bold]Knowledge Base[/bold]\n  {config.get('knowledge_base_path', '(not set)')}\n\n"
        f"[bold]Strategy[/bold]\n  {strategy_display}\n"
        f"  Valid values: {', '.join(sorted(VALID_STRATEGIES))}\n\n"
        f"[dim]The core CLI stores no model credentials or handler configuration.[/dim]",
        border_style="cyan",
    ))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Config key (normally knowledge_base_path)"),
    value: str = typer.Argument(help="Config value"),
):
    """Set a config value."""
    from knowledge_studio.config import load_config, save_config

    config = load_config()

    keys = key.split(".")
    target = config
    for k in keys[:-1]:
        if k not in target:
            target[k] = {}
        target = target[k]

    if key == "knowledge_base_path":
        resolved = Path(value).expanduser().resolve()
        if not resolved.is_dir():
            console.print(
                f"[yellow]Warning:[/yellow] directory does not exist: {resolved}"
            )
        value = str(resolved)
        target[keys[-1]] = value
    elif key == "strategy":
        from knowledge_studio.config import set_strategy as _set_strategy
        _set_strategy(value)
        console.print(f"[green]Set:[/green] strategy = {value}")
        return
    elif key in _RECALL_YAML_KEYS:
        # v0.5.12: settings/recall.yaml is the single source of truth for
        # recall params. `oks config set` routes them to yaml, not config.json,
        # so `oks recall` (which reads yaml) actually honors the value.
        from knowledge_studio.recall import set_recall_yaml_param
        from knowledge_studio.store import repo_root
        set_recall_yaml_param(repo_root(), _RECALL_YAML_KEYS[key], value)
        console.print(f"[green]Set:[/green] {key} = {value}  [dim](settings/recall.yaml)[/dim]")
        return
    elif value.lower() in ("true", "false"):
        target[keys[-1]] = value.lower() == "true"
    elif value.isdigit():
        target[keys[-1]] = int(value)
    else:
        target[keys[-1]] = value

    save_config(config)
    console.print(f"[green]Set:[/green] {key} = {value}")
