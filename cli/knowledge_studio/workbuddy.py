"""Read-only preflight for the WorkBuddy Agent-native OKS workflow."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter


DOCTOR_SCHEMA = "workbuddy-doctor-response/v1"
_EXCLUDED_PATH_PARTS = frozenset({"_shared", "personal", "drafts"})
_HOST_SKILL_RELATIVE_PATH = Path(".codebuddy/skills/oks-knowledge/SKILL.md")
_COMPATIBILITY_SKILL_RELATIVE_PATH = Path(".workbuddy/skills/oks-knowledge/SKILL.md")
_REQUIRED_SKILL_MARKERS = (
    'oks recall "<query>" --knowledge-only --format json --limit 3',
    'oks fs read "<oks-uri>" --format json',
)
_READ_ONLY_SKILL_MARKERS = (
    "OKS `wiki/` is the sole source of truth",
    "Do not run",
    "`oks raw-commit`",
    "`oks wiki create`",
    "`oks wiki pin`",
    "`oks wiki archive`",
    "`oks wiki unarchive`",
    "`oks wiki use`",
    "`oks drafts promote`",
    "`oks drafts reject`",
    "`oks decay`",
    "`oks distill`",
    "`oks config set`",
    "`oks hook install`",
    "`oks mail send`",
)


def _is_reviewed_page(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in _EXCLUDED_PATH_PARTS for part in relative.parts):
        return False
    try:
        metadata = frontmatter.load(path).metadata
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    if metadata.get("archived") is True:
        return False
    return bool(metadata.get("human_reviewed_at"))


def _reviewed_page_count(wiki_root: Path) -> int:
    return sum(
        _is_reviewed_page(page, wiki_root)
        for page in wiki_root.rglob("*.md")
        if page.is_file()
    )


def inspect_workbuddy_adapter(root: Path) -> dict[str, Any]:
    """Inspect the local adapter without changing OKS or calling WorkBuddy."""
    root = root.resolve()
    wiki_root = root / "wiki"
    skill_path = root / _HOST_SKILL_RELATIVE_PATH
    compatibility_skill_path = root / _COMPATIBILITY_SKILL_RELATIVE_PATH
    issues: list[str] = []

    wiki_ready = wiki_root.is_dir()
    if not wiki_ready:
        issues.append(f"missing wiki directory: {wiki_root}")

    skill_text = ""
    if skill_path.is_file():
        try:
            skill_text = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"cannot read project Skill: {exc}")
    elif compatibility_skill_path.is_file():
        issues.append(
            "missing WorkBuddy host Skill under .codebuddy; "
            f"the compatibility copy at {compatibility_skill_path} is not discovered by WorkBuddy 5.4.7"
        )
    else:
        issues.append(f"missing WorkBuddy host Skill: {skill_path}")

    workflow_ready = bool(skill_text) and all(
        marker in skill_text for marker in _REQUIRED_SKILL_MARKERS
    )
    boundary_ready = bool(skill_text) and all(
        marker in skill_text for marker in _READ_ONLY_SKILL_MARKERS
    )
    if skill_text and not workflow_ready:
        issues.append("project Skill is missing the required recall-then-read workflow")
    if skill_text and not boundary_ready:
        issues.append("project Skill is missing the read-only OKS safety boundary")

    reviewed_page_count = _reviewed_page_count(wiki_root) if wiki_ready else 0
    reviewed_pages_ready = reviewed_page_count > 0
    if wiki_ready and not reviewed_pages_ready:
        issues.append("No explicitly reviewed, non-archived Wiki pages are available.")

    return {
        "schema": DOCTOR_SCHEMA,
        "status": "ready" if wiki_ready and workflow_ready and boundary_ready and reviewed_pages_ready else "not_ready",
        "source_root": str(root),
        "checks": {
            "wiki": {"ready": wiki_ready, "path": str(wiki_root)},
            "project_skill": {
                "ready": workflow_ready and boundary_ready,
                "path": str(skill_path),
                "compatibility_path": str(compatibility_skill_path),
                "compatibility_present": compatibility_skill_path.is_file(),
                "required_read_workflow": workflow_ready,
                "read_only_boundary": boundary_ready,
            },
            "reviewed_wiki": {"ready": reviewed_pages_ready, "page_count": reviewed_page_count},
        },
        "issues": issues,
    }
