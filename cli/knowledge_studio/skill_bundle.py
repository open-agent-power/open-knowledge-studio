"""One small default Skill; legacy and specialized bundles remain opt-in."""

from pathlib import Path
from datetime import datetime, UTC
import hashlib
import json
from uuid import uuid4
from . import store, tasks

CORE = "oh-my-oks"


def install_global(base, editor, *, overwrite=False):
    """Install only the core entry, without needing or modifying a KB."""
    import os
    import shutil

    hosts = {"codex": ".codex", "claude": ".claude", "agents": ".agents"}
    if editor not in hosts:
        raise ValueError("Global installation supports codex, claude or agents; use the actual host's documented Skill directory for other hosts")
    home = Path.home()
    host = (Path(os.environ["CODEX_HOME"]).expanduser() if editor == "codex" and os.environ.get("CODEX_HOME") else home / hosts[editor]).resolve()
    source = Path(base) / "skills" / CORE
    if not (source / "SKILL.md").is_file():
        raise ValueError("Bundled oh-my-oks is missing")
    dest = host / "skills" / CORE
    if dest.is_symlink() or (dest.exists() and not dest.is_dir()):
        raise ValueError("Existing Skill is a link or non-directory; inspect it before replacement")
    backup = None
    if dest.exists():
        if not overwrite:
            return {"status": "preserved", "path": str(dest), "editor": editor}
        backup = home / ".oks" / "skill-backups" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]) / CORE
        shutil.copytree(dest, backup, symlinks=True)
    copy(host, source, "skills/" + CORE, overwrite=overwrite)
    return {"status": "installed", "path": str(dest), "editor": editor,
            "backup": str(backup) if backup else None}


def copy(root, source, relative, *, overwrite=False):
    dest = tasks._inside(root, relative)
    wrote = False
    for item in sorted(source.rglob("*")):
        if "__pycache__" in item.parts or item.suffix in {".pyc", ".pyo"}:
            continue
        if item.is_symlink():
            raise ValueError("Skill assets must be regular files")
        if not item.is_file():
            continue
        target = tasks._inside(
            root, (dest / item.relative_to(source)).relative_to(root).as_posix()
        )
        if target.exists() and not overwrite:
            continue
        store._atomic_write(target, item.read_text(encoding="utf-8"))
        wrote = True
    return wrote


def consolidate(root, base, hosts):
    """Archive only named bundled packages; preserve unknown user Skills."""
    names = {
        p.name
        for p in (base / "skills").iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    } - {CORE}
    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    relative = "records/skill-migration/" + batch
    items = []
    preserved = []
    for host in hosts:
        folder = tasks._inside(root, host + "/skills")
        for name in sorted(names):
            source = folder / name
            if source.is_symlink():
                preserved.append(host + "/skills/" + name)
                continue
            if not source.is_dir():
                continue
            files = []
            for p in source.rglob("*"):
                if p.is_symlink():
                    raise ValueError(
                        "Skill contains a symlink; inspect before migration"
                    )
                if p.is_file():
                    files.append(
                        {
                            "path": p.relative_to(source).as_posix(),
                            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        }
                    )
            items.append(
                {
                    "from": host + "/skills/" + name,
                    "to": relative + "/packages/" + host.removeprefix(".") + "/" + name,
                    "files": files,
                    "status": "pending",
                }
            )
    if not items:
        return {"status": "unchanged", "items": [], "preserved": preserved}
    record = {
        "status": "in_progress",
        "items": items,
        "preserved": preserved,
        "meaning": "Legacy packages archived, not deleted; no review or capability execution implied",
    }
    manifest = tasks._inside(root, relative + "/manifest.json")
    with store._file_lock(tasks._inside(root, ".oks/locks/skill-migration.lock")):

        def save():
            store._atomic_write(
                manifest, json.dumps(record, ensure_ascii=False, indent=2) + "\n"
            )

        save()
        for item in items:
            source = tasks._inside(root, item["from"])
            dest = tasks._inside(root, item["to"])
            for file in item["files"]:
                if (
                    hashlib.sha256((source / file["path"]).read_bytes()).hexdigest()
                    != file["sha256"]
                ):
                    raise ValueError("Skill changed; migration remains partial")
            dest.parent.mkdir(parents=True, exist_ok=True)
            source.replace(dest)
            item["status"] = "archived"
            save()
        record["status"] = "completed"
        save()
    return {**record, "manifest": manifest.relative_to(root).as_posix()}
