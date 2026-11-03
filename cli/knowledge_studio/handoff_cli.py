"""Prepare and check explicit, versioned handoffs using the active instance."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from knowledge_studio import handoff, mail, store, trace

app = typer.Typer(help="Freeze and verify task context for an existing Mail handoff.")


def load_agreement(path: Path) -> dict:
    with path.open("rb") as handle:
        data = handle.read(handoff.MAX_BYTES + 1)
    if len(data) > handoff.MAX_BYTES:
        raise ValueError("Agreement exceeds handoff size limit")
    try:
        return handoff.validate(json.loads(data))
    except RecursionError as exc:
        raise ValueError("Agreement nesting exceeds parser limits") from exc


@app.command("prepare")
def prepare(
    goal: str = typer.Option(..., "--goal", help="KB-relative profiles/goals/*.md path"),
    scope: str = typer.Option(..., "--scope", help="Explicit task/project label; not an authorization identity"),
    wiki: list[str] = typer.Option([], "--wiki", help="Reviewed Wiki slug; repeatable"),
    output: Path = typer.Option(..., "--output", "-o", help="New JSON snapshot file"),
) -> None:
    try:
        root = store.repo_root().resolve()
        paths = []
        for slug in wiki:
            matches = [path for path in (root / "wiki").rglob("*.md") if path.stem == slug]
            if len(matches) != 1:
                raise ValueError(f"Wiki slug must identify exactly one page: {slug}")
            # Do not parse/score the page before the bounded bucket-safe reader.
            paths.append(matches[0].relative_to(root).as_posix())
        agreement = handoff.prepare(root, goal, paths, scope)
        # Serialize competing prepares; never replace a user-edited snapshot.
        with store._file_lock(output.with_name(output.name + ".lock")):
            if output.exists():
                raise ValueError("Output already exists; choose a new snapshot path")
            store._atomic_write(output, json.dumps(agreement, ensure_ascii=False, indent=2) + "\n")
        typer.echo(json.dumps({"path": str(output), "sha256": agreement["sha256"],
                               "knowledge_count": len(paths)}, ensure_ascii=False))
    except (OSError, ValueError, UnicodeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)


@app.command("check")
def check(
    message_id: str,
    scope: str = typer.Option(..., "--scope", help="Expected task/project label"),
    run_id: str = typer.Option("", "--run-id", help="Append result to an existing Trace for the same Goal slug"),
) -> None:
    try:
        root = store.repo_root().resolve()
        message = mail.parse_message(mail.canonical_path(root, message_id))
        if message is None:
            raise ValueError("Mail message not found")
        encoded = message["meta"].get("handoff_agreement_b64")
        if not encoded:
            raise ValueError("Message has no versioned agreement; legacy handoff remains readable")
        agreement = handoff.decode(encoded)
        result = handoff.check(root, agreement, scope)
        result["message_id"] = message["meta"]["message_id"]
        if run_id:
            manifest = trace.load_manifest(run_id)
            if manifest["goal_id"] != Path(agreement["goal"]["path"]).stem:
                raise ValueError("Trace Goal does not match this agreement")
            event = trace.append_event(run_id, "tool_observation", "tool", {"handoff_check": result})
            result["trace_event_id"] = event["event_id"]
        typer.echo(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, UnicodeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)
    if result["status"] != "current":
        raise typer.Exit(1)
