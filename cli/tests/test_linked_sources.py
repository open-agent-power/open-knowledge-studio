import hashlib
import json
import subprocess
import pytest
import yaml
from knowledge_studio import linked_sources as sources


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


def commit(repo):
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def linked(tmp_path):
    root = tmp_path / "personal"
    root.mkdir()
    repo = tmp_path / "team"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "catalog").mkdir()
    (repo / "knowledge").mkdir()
    (repo / "sources/reviews").mkdir(parents=True)
    body = "# Quartz cancellation\nUse explicit refunds."
    (repo / "knowledge/one.md").write_text(body, encoding="utf-8", newline="\n")
    (repo / "sources/index.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "one",
                        "url": "https://example.org/evidence",
                        "version": "v1",
                        "sha256": "a" * 64,
                    }
                ]
            }
        )
    )
    rows = {
        "schema_version": 1,
        "repository": "org/team",
        "knowledge": [
            {
                "id": "one",
                "title": "Quartz cancellation",
                "path": "knowledge/one.md",
                "kind": "how-to",
                "topics": ["test"],
                "status": "candidate",
                "approval": None,
            }
        ],
    }
    (repo / "catalog/knowledge.yaml").write_text(yaml.safe_dump(rows))
    commit(repo)
    sources.link(root, "team", repo, "org/team")
    return root, repo, rows


def approve(repo, rows):
    rows["knowledge"][0].update(status="approved", approval="sources/reviews/one.json")
    (repo / "catalog/knowledge.yaml").write_text(yaml.safe_dump(rows))
    (repo / "sources/reviews/one.json").write_text(
        json.dumps(
            {
                "id": "one",
                "decision": "approved",
                "reviewer": "Human",
                "decided_at": "2026-11-05T00:00:00Z",
                "decision_ref": "https://example.org/decision",
                "body_sha256": hashlib.sha256(
                    (repo / "knowledge/one.md").read_bytes()
                ).hexdigest(),
            }
        )
    )
    return commit(repo)


def test_candidates_are_visible_but_never_recalled_and_upstream_unchanged(linked):
    root, repo, rows = linked
    before = git(repo, "status", "--porcelain")
    assert sources.catalog(root)["sources"][0]["candidate_count"] == 1
    assert sources.search(root, "quartz")[0] == []
    assert git(repo, "status", "--porcelain") == before
    assert not (repo / ".oks").exists() and not (root / "wiki").exists()


def test_head_refresh_is_committed_and_versioned_without_copying(linked):
    root, repo, rows = linked
    sha = approve(repo, rows)
    hits, warnings = sources.search(root, "quartz")
    assert not warnings and hits[0]["revision"] == sha
    assert "/blob/" + sha + "/" in hits[0]["url"]
    (repo / "knowledge/one.md").write_text("# changed without approval")
    assert (
        sources.search(root, "quartz")[0][0]["source_sha256"]
        == hits[0]["source_sha256"]
    )
    commit(repo)
    assert sources.search(root, "quartz")[0] == []
    assert sources.catalog(root)["warnings"]  # fail closed on stale approval


def test_pinned_revision_and_unlink_leave_upstream_alone(linked):
    root, repo, rows = linked
    first = git(repo, "rev-parse", "HEAD")
    sources.link(root, "team", repo, "org/team", first)
    approve(repo, rows)
    assert sources.search(root, "quartz")[0] == []
    sources.unlink(root, "team")
    assert sources.configuration(root) == []
    assert git(repo, "status", "--porcelain") == ""


def test_symlink_blob_cannot_leak_and_no_upstream_code_is_run(linked):
    root, repo, rows = linked
    (repo / "knowledge/one.md").unlink()
    (repo / "knowledge/one.md").symlink_to("/etc/passwd")
    commit(repo)
    assert sources.catalog(root)["sources"] == []
    assert sources.catalog(root)["warnings"]


def test_bad_settings_exclude_team_without_breaking_personal_recall(tmp_path):
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings/sources.yaml").write_text("sources: [bad]")
    assert sources.search(tmp_path, "quartz")[0] == []
    assert sources.catalog(tmp_path)["warnings"]
