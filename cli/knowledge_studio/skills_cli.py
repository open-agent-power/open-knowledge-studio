"""Agent-facing commands for independent Skill knowledge and on-demand loading."""
from pathlib import Path
from typing import Optional
import json
import yaml

import typer

from knowledge_studio import skills

app = typer.Typer(help="Manage Skills under Wiki: import, review, search and load on demand.")


def _run(operation):
    try:
        result = operation()
    except (ValueError, OSError, KeyError, yaml.YAMLError) as exc:
        typer.echo(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise typer.Exit(2)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("import")
def import_cmd(
    source: Path = typer.Argument(help="Skill folder/SKILL.md, or a collection with --all"),
    kind: str = typer.Option("strategy", "--type", help="strategy | anti-pattern | concept"),
    category: str = typer.Option("general", "--category", help="Fine category, e.g. development/java"),
    skill_id: Optional[str] = typer.Option(None, "--id", help="Portable Skill identifier"),
    all_skills: bool = typer.Option(False, "--all", help="Import immediate Skill subfolders as review candidates"),
):
    """Capture immutable assets and prepare drafts; never automatically approve."""
    def execute():
        if not all_skills:
            return skills.import_skill(source, kind=kind, category=category, skill_id=skill_id)
        if skill_id:
            raise ValueError("--id is only valid for one Skill")
        sources = sorted(p for p in source.iterdir() if p.is_dir() and (p / "SKILL.md").is_file() and p.name != "oks")
        if not sources:
            raise ValueError("No immediate Skill subfolders were found")
        results, errors = [], []
        for path in sources:
            try:
                results.append(skills.import_skill(path, kind=kind, category=category))
            except (ValueError, OSError, yaml.YAMLError) as exc:
                errors.append({"source": str(path), "error": str(exc)})
        return {"imported": results, "errors": errors, "status": "partial" if errors else "complete"}
    _run(execute)


@app.command("restore-router")
def restore_cmd(backup: Path = typer.Argument(help="Backup path returned by install-router --compact")):
    """Restore backed-up Skills without overwriting existing host copies."""
    _run(lambda: skills.restore_router_backup(backup))


@app.command("list")
def list_cmd(
    status: str = typer.Option("all", help="all | draft | active"),
    kind: Optional[str] = typer.Option(None, "--type"),
    category: Optional[str] = typer.Option(None, "--category"),
):
    """List only Skill entries, including pending review candidates by default."""
    def execute():
        if status not in {"all", "draft", "active"}:
            raise ValueError("Choose all, draft, or active")
        entries = skills.entries()
        if status != "all":
            entries = [e for e in entries if e.get("status") == status]
        if kind:
            entries = [e for e in entries if e.get("type", e.get("draft_type")) == kind]
        if category:
            skills.validate_category(category)
            entries = [e for e in entries if e.get("skill_category") == category or str(e.get("skill_category", "")).startswith(category + "/")]
        return {"entries": [skills.summary(e) for e in entries]}
    _run(execute)


@app.command("search")
def search_cmd(
    query: str = typer.Argument(),
    limit: int = typer.Option(5, "--limit", "-n", min=1, max=100),
    kind: Optional[str] = typer.Option(None, "--type"),
    category: Optional[str] = typer.Option(None, "--category"),
    agreement: Optional[Path] = typer.Option(None, "--agreement"),
    task_scope: Optional[str] = typer.Option(None, "--task-scope"),
    debug_record: bool = typer.Option(False, "--debug-record"),
):
    """Recall reviewed Skills via the shared FTS5 capability projection."""
    def execute():
        from knowledge_studio.handoff_cli import load_agreement
        return {"hits": skills.search(query, limit=limit, kind=kind, category=category,
                    agreement=load_agreement(agreement) if agreement else None,
                    task_scope=task_scope, debug_record=debug_record)}
    _run(execute)


@app.command("load")
def load_cmd(
    skill_id: str = typer.Argument(),
    version: Optional[str] = typer.Option(None, "--version"),
    target: Optional[str] = typer.Option(None, "--target", help="Optional project host: agents | claude | qoder | codebuddy"),
):
    """Read one reviewed Skill with its assets; optionally materialize it for a host."""
    _run(lambda: skills.load(skill_id, version=version, host=target))


@app.command("unload")
def unload_cmd(skill_id: str = typer.Argument(), target: str = typer.Option(..., "--target")):
    """Remove only an unchanged Skill copy previously loaded by this command."""
    _run(lambda: skills.unload(skill_id, host=target))


@app.command("install-router")
def router_cmd(
    target: str = typer.Option("agents", "--target"),
    compact: bool = typer.Option(False, "--compact", help="Back up unchanged bundled Skills from this host, preserving custom edits"),
):
    """Install one compact OKS entry; legacy skills-install remains available."""
    def execute():
        from knowledge_studio.cli import _asset_source
        source = _asset_source()
        if source is None:
            raise ValueError("No bundled Skill assets available")
        return skills.install_router(source, host=target, compact=compact)
    _run(execute)
