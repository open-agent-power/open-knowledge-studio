"""Tests for the WorkBuddy Agent-native preflight."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from knowledge_studio.cli import app
from knowledge_studio.workbuddy import DOCTOR_SCHEMA


runner = CliRunner()
_FORBIDDEN_WRITES = (
    "raw-commit", "wiki create", "wiki pin", "wiki archive", "wiki unarchive",
    "wiki use", "drafts promote", "drafts reject", "decay", "distill",
    "config set", "hook install", "mail send",
)


def _page(path: Path, metadata: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{metadata}\n---\n\nReviewed content.\n", encoding="utf-8")


def _instance(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    monkeypatch.setenv("OKS_ROOT", str(root))
    skill = root / ".codebuddy" / "skills" / "oks-knowledge" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "\n".join(
            [
                "OKS `wiki/` is the sole source of truth",
                'oks recall "<query>" --knowledge-only --format json --limit 3',
                'oks fs read "<oks-uri>" --format json',
                "Do not run " + ", ".join(f"`oks {command}`" for command in _FORBIDDEN_WRITES),
            ]
        ),
        encoding="utf-8",
    )
    return root


def test_workbuddy_doctor_validates_the_read_only_cli_workflow(tmp_path, monkeypatch):
    root = _instance(tmp_path, monkeypatch)
    _page(root / "wiki" / "approved.md", "title: Approved\nhuman_reviewed_at: 2026-09-05T00:00:00Z")

    result = runner.invoke(app, ["workbuddy", "doctor", "--format", "json"])

    assert result.exit_code == 0, result.output
    response = json.loads(result.output)
    assert response["schema"] == DOCTOR_SCHEMA
    assert response["status"] == "ready"
    assert response["checks"]["project_skill"]["required_read_workflow"] is True
    assert response["checks"]["project_skill"]["read_only_boundary"] is True
    assert response["checks"]["reviewed_wiki"]["page_count"] == 1


def test_workbuddy_doctor_rejects_a_compatibility_only_skill(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    monkeypatch.setenv("OKS_ROOT", str(root))
    _page(root / "wiki" / "approved.md", "title: Approved\nhuman_reviewed_at: 2026-09-05T00:00:00Z")
    legacy = root / ".workbuddy" / "skills" / "oks-knowledge" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy skill\n", encoding="utf-8")

    result = runner.invoke(app, ["workbuddy", "doctor", "--format", "json"])

    assert result.exit_code == 1
    response = json.loads(result.output)
    assert response["checks"]["project_skill"]["compatibility_present"] is True
    assert ".codebuddy" in response["issues"][0]


def test_workbuddy_doctor_rejects_a_skill_missing_a_write_prohibition(tmp_path, monkeypatch):
    root = _instance(tmp_path, monkeypatch)
    _page(root / "wiki" / "approved.md", "title: Approved\nhuman_reviewed_at: 2026-09-05T00:00:00Z")
    skill = root / ".codebuddy" / "skills" / "oks-knowledge" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("`oks wiki create`", ""), encoding="utf-8")

    result = runner.invoke(app, ["workbuddy", "doctor", "--format", "json"])

    assert result.exit_code == 1
    response = json.loads(result.output)
    assert response["checks"]["project_skill"]["read_only_boundary"] is False
