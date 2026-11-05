"""Agent-facing commands for independent Skill knowledge and on-demand loading."""
from pathlib import Path
from typing import Optional
import json
import yaml

import typer

from knowledge_studio import skills
from knowledge_studio import resources

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


@app.command("versions")
def versions_cmd(skill_id: str = typer.Argument(help="Skill identifier")):
    """List immutable versions, review states and package integrity."""
    _run(lambda: skills.list_versions(skills._root(), skill_id))


@app.command("diff")
def diff_cmd(
    skill_id: str = typer.Argument(help="Skill identifier"),
    from_version: str = typer.Option(..., "--from-version", help="Full SHA256 version"),
    to_version: str = typer.Option(..., "--to-version", help="Full SHA256 version"),
):
    """Compare immutable Skill snapshots without executing or installing them."""
    _run(lambda: skills.compare_versions(skills._root(), skill_id, from_version, to_version))


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
    retrieval_id: Optional[str] = typer.Option(None, "--retrieval-id", help="Explicit query record to link this pinned read"),
):
    """Read one reviewed Skill with its assets; optionally materialize it for a host."""
    def execute():
        if retrieval_id:
            from knowledge_studio import retrieval_debug, store
            root = store.repo_root()
            selected = skills._selected(skill_id, version)
            source = Path(selected['file_path']).resolve().relative_to(root.resolve()).as_posix()
            hit = retrieval_debug.source_hit(root, retrieval_id, source)
            if hit.get('skill_version') != selected['skill_version']:
                raise ValueError('Selected Skill version differs from query; query again')
        result = skills.load(skill_id, version=version, host=target)
        if retrieval_id:
            result['retrieval_id'] = retrieval_id
            result['load_receipt'] = retrieval_debug.record_load(root, retrieval_id, source,
                selected['skill_version'], 'host_copy' if target else 'instructions_returned')
        return result
    _run(execute)


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
        source = resources.asset_source()
        if source is None:
            raise ValueError("No bundled Skill assets available")
        return skills.install_router(source, host=target, compact=compact)
    _run(execute)


@app.command('derive')
def derive_cmd(
    skill_id: str = typer.Argument(),
    version: str = typer.Option(..., '--version'),
    notes: Optional[str] = typer.Option(None, '--notes', help='Personal requirements appended to the approved instructions'),
    changes: Optional[Path] = typer.Option(None, '--changes', help='JSON map of relative files to UTF-8 content or null'),
    variant_id: Optional[str] = typer.Option(None, '--id'),
):
    """Prepare a separate personal Skill Draft; preserve the reviewed base."""
    def execute():
        from . import skill_derivation, store
        root = store.repo_root()
        if (notes is None) == (changes is None):
            raise ValueError('Choose exactly one of --notes or --changes')
        if changes:
            if changes.stat().st_size > 2 * 1024 * 1024:
                raise ValueError('Changes file exceeds 2 MiB')
            edits = json.loads(changes.read_text(encoding='utf-8-sig'))
        else:
            if not notes.strip():
                raise ValueError('Personal notes must not be empty')
            source = skill_derivation.detail(root, {'id': skill_id, 'version': version})
            edits = {'SKILL.md': source['instructions'] + '\n\n## 我的补充要求\n\n' + notes.strip() + '\n'}
        return skill_derivation.derive(root, {'base': {'id': skill_id, 'version': version},
                                            'variant_id': variant_id, 'changes': edits})
    _run(execute)


@app.command('merge-preview')
def merge_preview_cmd(
    skill_id: str = typer.Argument(),
    version: str = typer.Option(..., '--version'),
    upstream_version: str = typer.Option(..., '--upstream-version'),
):
    """Compare a personal Skill, its recorded base and an approved upstream version."""
    def execute():
        from . import skill_derivation, store
        root = store.repo_root()
        source = skill_derivation.detail(root, {'id': skill_id, 'version': version})
        lineage = source.get('lineage')
        if not lineage:
            raise ValueError('This Skill has no recorded upstream lineage')
        return skill_derivation.preview_merge(root, {'ours': {'id': skill_id, 'version': version},
            'theirs': {'id': lineage['upstream_base']['id'], 'version': upstream_version}})
    _run(execute)


@app.command('merge-prepare')
def merge_prepare_cmd(
    preview: Path = typer.Argument(help='JSON returned by merge-preview'),
    resolutions: Optional[Path] = typer.Option(None, '--resolutions', help='Explicit per-file conflict choices as JSON'),
):
    """Recheck the exact preview and prepare a reviewed update candidate."""
    def execute():
        from . import skill_derivation, store
        if preview.stat().st_size > 2 * 1024 * 1024 or resolutions and resolutions.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('Input exceeds 2 MiB')
        plan = json.loads(preview.read_text(encoding='utf-8-sig'))
        choices = json.loads(resolutions.read_text(encoding='utf-8-sig')) if resolutions else {}
        return skill_derivation.prepare_merge(store.repo_root(), {
            'ours': {'id': plan['ours']['id'], 'version': plan['ours']['version']},
            'theirs': {'id': plan['theirs']['id'], 'version': plan['theirs']['version']},
            'expected_plan_digest': plan['plan_digest'], 'resolutions': choices})
    _run(execute)
