from __future__ import annotations

import hashlib
from pathlib import Path

from knowledge_studio import draft_review, task_workflow, tasks
from knowledge_studio.workspace_home import build


def make_root(root: Path) -> Path:
    for relative in (".oks/tasks", "wiki/computing", "wiki/skills", "drafts", "settings"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def page(title: str, *, status="active", reviewed="2026-10-30", kind="concept", extra="") -> str:
    return f"---\ntitle: {title}\ntype: {kind}\nstatus: {status}\nhuman_reviewed_at: {reviewed}\n{extra}---\n\nBody.\n"


def test_counts_reviewed_knowledge_skill_subset_and_pending_drafts(tmp_path, monkeypatch):
    root = make_root(tmp_path / "kb")
    (root / "wiki/computing/decision.md").write_text(page("Decision"), encoding="utf-8")
    (root / "wiki/skills/citations.md").write_text(
        page("Citations", kind="skill", extra="artifact_kind: skill\n"), encoding="utf-8"
    )
    (root / "wiki/skills/archived.md").write_text(
        page("Archived", status="archived", kind="skill", extra="artifact_kind: skill\n"), encoding="utf-8"
    )

    pending = root / "drafts/pending.md"
    pending.write_text("---\ntitle: Pending\ndraft_type: concept\n---\n\nProposal.\n", encoding="utf-8")
    reviewed = root / "drafts/reviewed.md"
    reviewed_bytes = b"---\ntitle: Reviewed\ndraft_type: concept\n---\n\nAlready reviewed.\n"
    reviewed.write_bytes(reviewed_bytes)
    draft_review.record_decision(root, "reviewed", reviewed_bytes, "rejected")

    private = root / "drafts/private.md"
    private.write_text("---\ntitle: Private\nfeedback_origin: {scope_key: x}\n---\nsecret\n", encoding="utf-8")
    source_only = root / "drafts/source-only.md"
    source_only.write_text("---\ntitle: Source\nworkflow_mode: source_only\n---\nSource only.\n", encoding="utf-8")
    no_proposal = root / ("drafts/task-learning-" + "a" * 28 + ".md")
    no_proposal.write_text("---\ntitle: No proposal\nworkflow_source: {task_id: sample}\n---\nNo reusable learning.\n", encoding="utf-8")
    original_candidate = task_workflow.candidate_disposition
    monkeypatch.setattr(task_workflow, "candidate_disposition", lambda _root, relative, *args, **kwargs:
                        "not_proposed" if relative == no_proposal.relative_to(root).as_posix()
                        else original_candidate(_root, relative, *args, **kwargs))

    result = build(root)
    assert result["counts"]["reviewed_knowledge"] == 2
    assert result["counts"]["reusable_methods"] == 1
    assert result["counts"]["pending_drafts"] == 1
    assert result["pending_drafts"] == [{"path": "drafts/pending.md", "title": "Pending", "kind": "knowledge"}]


def test_task_states_preview_and_output_count_use_explicit_root(tmp_path, monkeypatch):
    root = make_root(tmp_path / "kb")
    other = make_root(tmp_path / "other")
    monkeypatch.setenv("OKS_ROOT", str(other))
    rows = [
        {"task_id": "active", "lifecycle": "active", "status": "current", "title": "Active title",
         "next_action": "Review output", "awaiting_confirmation": True},
        {"task_id": "closed", "lifecycle": "completed", "status": "current", "title": "Closed"},
        {"task_id": "needs-review", "lifecycle": "active", "status": "needs_review", "title": "Review"},
    ]
    monkeypatch.setattr(tasks, "overview", lambda selected_root: {
        "tasks": rows, "counts": {"active": 2}, "truncated": False,
    })
    monkeypatch.setattr(tasks, "show", lambda selected_root, task_id: {
        "progress": "Half done", "artifacts": [{"path": "outputs/a.md"}, {"path": "outputs/b.md"}],
    })

    result = build(root)
    assert result["knowledge_base"] == str(root.resolve())
    assert result["counts"]["active_tasks"] == 2
    assert result["counts"]["awaiting_confirmation"] == 1
    assert [task["task_id"] for task in result["next_tasks"]] == ["active", "needs-review"]
    assert result["next_tasks"][0] == {
        "task_id": "active", "title": "Active title", "progress": "Half done",
        "next_action": "Review output", "outputs_count": 2, "awaiting_confirmation": True,
    }


def test_storage_kind_distinguishes_temp_from_regular_folder(tmp_path, monkeypatch):
    temporary = make_root(tmp_path / "temporary-kb")
    monkeypatch.setattr("knowledge_studio.workspace_home.tempfile.gettempdir", lambda: str(tmp_path))
    assert build(temporary)["storage_kind"] == "temporary"

    folder = make_root(tmp_path / "folder-kb")
    monkeypatch.setattr("knowledge_studio.workspace_home.tempfile.gettempdir", lambda: str(tmp_path / "elsewhere"))
    assert build(folder)["storage_kind"] == "folder"


def test_truncation_and_bad_files_are_reported_without_false_zero(tmp_path, monkeypatch):
    root = make_root(tmp_path / "kb")
    for index in range(4):
        (root / f"wiki/computing/{index}.md").write_text(page(f"Page {index}"), encoding="utf-8")
    monkeypatch.setattr("knowledge_studio.workspace_home._LIMIT", 2)
    result = build(root)
    assert result["truncated"]["wiki"] is True
    assert result["counts"]["reviewed_knowledge"] is None
    assert {tuple(error.values()) for error in result["errors"]} >= {("wiki", "count_partial")}

    monkeypatch.setattr("knowledge_studio.workspace_home._LIMIT", 2000)
    (root / "drafts/broken.md").write_bytes(b"\xff\xfe")
    broken = build(root)
    assert broken["counts"]["pending_drafts"] is None
    assert {tuple(error.values()) for error in broken["errors"]} >= {("drafts", "candidate_unavailable")}


def test_build_does_not_change_kb_bytes(tmp_path, monkeypatch):
    root = make_root(tmp_path / "kb")
    (root / "wiki/computing/page.md").write_text(page("Page"), encoding="utf-8")
    (root / "drafts/pending.md").write_text("---\ntitle: Draft\n---\nPending.\n", encoding="utf-8")
    paths = [root / "wiki/computing/page.md", root / "drafts/pending.md"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    build(root)

    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before
