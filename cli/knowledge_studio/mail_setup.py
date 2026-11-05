"""Install a portable, explicitly bound Mail skill without host configuration edits."""
from __future__ import annotations

import json
import re
from pathlib import Path

from knowledge_studio import store
from knowledge_studio.resources import asset_root


def agent_id(value: str) -> str:
    value = value.strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", value):
        raise ValueError("Agent ID must contain 1-80 letters, digits, dots, underscores or hyphens")
    return value


def validate_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if not (root / "mail").is_dir() or not (root / "wiki").is_dir():
        raise ValueError("Choose an existing OKS knowledge base (mail/ and wiki/); run oks init first")
    return root


def install_skill(root: Path, agent: str, skills_dir: Path) -> Path:
    root = validate_root(root)
    agent = agent_id(agent)
    if agent.lower() in {"human", "all", "unknown"}:
        raise ValueError("Choose a named Agent identity, not human, all or unknown")
    destination = skills_dir.expanduser().resolve() / "oks-mail"
    source = asset_root() / "skills" / "oks-mail"
    binding = json.dumps({"knowledge_base": str(root), "agent_id": agent}, ensure_ascii=False, indent=2) + "\n"
    files = {Path("SKILL.md"): (source / "SKILL.md").read_text(encoding="utf-8"),
             Path("scripts/mail.py"): (source / "scripts/mail.py").read_text(encoding="utf-8"),
             Path("references/connection.md"): (source / "references/connection.md").read_text(encoding="utf-8"),
             Path("binding.json"): binding}
    # Preflight all files so a conflicting binding never leaves a partial install.
    for relative, content in files.items():
        target = destination / relative
        if target.is_symlink() or (target.exists() and target.read_text(encoding="utf-8") != content):
            raise ValueError(f"Existing skill differs: {target}; choose a separate skills directory")
        if not target.resolve().is_relative_to(destination):
            raise ValueError("Skill paths must stay inside the destination")
    for relative, content in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        store._atomic_write(target, content)
    return destination
