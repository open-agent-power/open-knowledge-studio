"""Synthetic report feedback: privacy, review, correction and real consumption."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import yaml
from typer.testing import CliRunner

from knowledge_studio import feedback, handoff, store, trace
from knowledge_studio.cli import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    for name in ("wiki/computing/strategies", "profiles/goals", "mail", "settings"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "profiles/goals/report.md").write_text("---\ntype: goal\ntitle: Report\nstatus: active\n---\nKeep citations.\n", encoding="utf-8")
    asset = "wiki/computing/strategies/report.md"
    (root / asset).write_text("---\ntitle: Report policy\ntype: strategy\narea: computing\nstatus: active\nhuman_reviewed_at: '2026-10-27'\noptions: []\n---\nReport sources.\n", encoding="utf-8")
    monkeypatch.setenv("OKS_ROOT", str(root))
    monkeypatch.setenv("OKS_FEEDBACK_HOME", str(tmp_path / "private"))
    selection = {"subject": "alice", "project": "report-project", "task": "report-task"}
    agreement = handoff.prepare(root, "profiles/goals/report.md", [asset], selection["task"])
    request = {"scope": selection, "event_id": "e1", "action": "adopted", "reason": "PRIVATE_REASON_KEEP_CITATIONS",
               "agreement": agreement, "asset_path": asset}
    return root, selection, agreement, request


def approve(setup, *, event_id="e1", candidate_id="c1"):
    root, selection, agreement, request = setup
    feedback.record(root, {**request, "event_id": event_id})
    proposal = feedback.propose(root, {"scope": selection, "candidate_id": candidate_id, "event_ids": [event_id],
                                        "title": "Citations policy", "summary": "PRIVATE_CANDIDATE: cite each source."})
    return feedback.review(root, {"scope": selection, "candidate_id": candidate_id, "decision": "approve",
                                  "expected_revision": proposal["revision"], "comment": "Reviewed this task only"})


def test_record_is_private_idempotent_and_trace_reference_is_opaque(setup):
    root, selection, agreement, request = setup
    trace.start_trace("report", "feedback-trial")
    request["run_id"] = "feedback-trial"
    assert feedback.record(root, request)["trace_status"] == "recorded"
    assert feedback.record(root, request)["duplicate"]
    view = feedback.inspect(root, selection)
    assert len(view["events"]) == 1
    shared = (root / trace.load_manifest("feedback-trial")["trace_path"]).read_text(encoding="utf-8")
    assert request["reason"] not in shared
    assert "alice" not in shared
    assert shared.count('"schema_version":"feedback-reference/v1"') == 1
    with pytest.raises(ValueError, match="different content"):
        feedback.record(root, {**request, "reason": "different"})


@pytest.mark.parametrize("field", ["subject", "project", "task"])
def test_scope_filters_before_reads_and_missing_scope_is_empty(setup, field):
    root, selection, agreement, request = setup
    approve(setup)
    assert feedback.inspect(root)["candidates"] == []
    assert feedback.inspect(root, {**selection, field: "other"})["candidates"] == []
    with pytest.raises(ValueError, match="required"):
        feedback.inspect(root, {"subject": "alice"})


def test_pending_rejected_and_observed_never_become_context(setup):
    root, selection, agreement, request = setup
    feedback.record(root, {**request, "action": "observed"})
    with pytest.raises(ValueError, match="Exposure"):
        feedback.propose(root, {"scope": selection, "candidate_id": "c0", "event_ids": ["e1"], "title": "x", "summary": "y"})
    feedback.record(root, {**request, "event_id": "e2"})
    candidate = feedback.propose(root, {"scope": selection, "candidate_id": "c1", "event_ids": ["e2"], "title": "x", "summary": "y"})
    assert feedback.context(root, selection, agreement) == []
    with pytest.raises(ValueError, match="changed"):
        feedback.review(root, {"scope": selection, "candidate_id": "c1", "decision": "approve", "expected_revision": "wrong", "comment": "ok"})
    feedback.review(root, {"scope": selection, "candidate_id": "c1", "decision": "reject", "expected_revision": candidate["revision"], "comment": "insufficient evidence"})
    assert feedback.context(root, selection, agreement) == []


@pytest.mark.parametrize("operation", ["withdraw", "correct", "source_change", "conflict"])
def test_stale_and_withdrawn_candidates_stop_consumption(setup, operation):
    root, selection, agreement, request = setup
    approve(setup)
    assert len(feedback.context(root, selection, agreement)) == 1
    if operation == "withdraw":
        feedback.withdraw(root, {"scope": selection, "event_id": "e1"})
    elif operation == "correct":
        feedback.record(root, {**request, "event_id": "e2", "action": "revised", "replaces": "e1", "reason": "Use revised citation style"})
    elif operation == "conflict":
        feedback.record(root, {**request, "event_id": "e2", "action": "rejected"})
        assert feedback.inspect(root, selection)["conflicts"]
    else:
        with (root / request["asset_path"]).open("a", encoding="utf-8") as stream:
            stream.write("Changed source")
        with pytest.raises(ValueError, match="needs review"):
            feedback.context(root, selection, agreement)
        return
    assert feedback.context(root, selection, agreement) == []


def test_export_requires_explicit_sharing_and_withdrawn_source_blocks_promotion(setup):
    root, selection, agreement, request = setup
    approved = approve(setup)
    export = {"scope": selection, "candidate_id": "c1", "expected_revision": approved["revision"]}
    with pytest.raises(ValueError, match="confirm-share"):
        feedback.export(root, export)
    result = feedback.export(root, export, confirm_share=True)
    draft = root / result["path"]
    assert "PRIVATE_REASON" not in draft.read_text()
    assert "alice" not in draft.read_text()
    feedback.withdraw(root, {"scope": selection, "event_id": "e1"})
    with pytest.raises(ValueError, match="inactive|withdrawn"):
        store.promote_draft(draft.stem)
    assert draft.exists()


def test_normal_review_promotes_but_forgetting_never_deletes_formal_wiki(setup):
    root, selection, agreement, request = setup
    approved = approve(setup)
    exported = feedback.export(root, {"scope": selection, "candidate_id": "c1", "expected_revision": approved["revision"]}, confirm_share=True)
    slug = store.promote_draft(Path(exported["path"]).stem)
    page = store.get_wiki_page(slug)
    assert page["human_reviewed_at"]
    result = feedback.forget(root, selection)
    assert result["status"] == "partial" and result["external_copies"]
    assert store.get_wiki_page(slug)
    assert feedback.context(root, selection, agreement) == []
    private = feedback._location(root, feedback.digest(selection)).read_text()
    assert "PRIVATE_REASON" not in private and "PRIVATE_CANDIDATE" not in private
    with pytest.raises(ValueError, match="forgotten"):
        feedback.record(root, request)


def test_removed_export_origin_cannot_bypass_withdrawal(setup):
    root, selection, agreement, request = setup
    approved = approve(setup)
    exported = feedback.export(root, {"scope": selection, "candidate_id": "c1", "expected_revision": approved["revision"]}, confirm_share=True)
    draft = root / exported["path"]
    _, front, body = draft.read_text(encoding="utf-8").split("---", 2)
    meta = yaml.safe_load(front); meta.pop("feedback_origin")
    draft.write_text("---\n" + yaml.safe_dump(meta) + "---" + body, encoding="utf-8")
    feedback.withdraw(root, {"scope": selection, "event_id": "e1"})
    with pytest.raises(ValueError, match="missing its provenance"):
        store.promote_draft(draft.stem)


@pytest.mark.parametrize("field", ["subject", "project"])
def test_populated_scopes_with_opposite_choices_do_not_conflict(setup, field):
    root, selection, agreement, request = setup
    approve(setup)
    other = {**selection, field: "other"}
    feedback.record(root, {**request, "scope": other, "action": "rejected", "reason": "Different audience"})
    candidate = feedback.propose(root, {"scope": other, "candidate_id": "c1", "event_ids": ["e1"], "title": "Other", "summary": "Only the other scope"})
    feedback.review(root, {"scope": other, "candidate_id": "c1", "decision": "approve", "expected_revision": candidate["revision"], "comment": "Confirmed"})
    assert feedback.context(root, selection, agreement)[0]["summary"] == "PRIVATE_CANDIDATE: cite each source."
    assert feedback.context(root, other, agreement)[0]["summary"] == "Only the other scope"


def test_failed_export_receipt_cannot_leave_shared_copy(setup, monkeypatch):
    root, selection, agreement, request = setup
    approved = approve(setup)
    def fail(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(store, "_atomic_write", fail)
    with pytest.raises(OSError):
        feedback.export(root, {"scope": selection, "candidate_id": "c1", "expected_revision": approved["revision"]}, confirm_share=True)
    assert not list((root / "drafts").glob("feedback-*.md"))


def test_completed_trace_is_partial_and_duplicate_preserves_that_state(setup):
    root, selection, agreement, request = setup
    trace.start_trace("report", "complete")
    trace.finish_trace("complete", {"outcome": "success"})
    request["run_id"] = "complete"
    assert feedback.record(root, request)["trace_status"] == "partial"
    assert feedback.record(root, request)["trace_status"] == "partial"


def test_private_storage_inside_repository_rejected(setup, monkeypatch):
    root, selection, agreement, request = setup
    monkeypatch.setenv("OKS_FEEDBACK_HOME", str(root / ".oks/private"))
    with pytest.raises(ValueError, match="outside"):
        feedback.record(root, request)


def test_write_failure_preserves_prior_state(setup, monkeypatch):
    root, selection, agreement, request = setup
    approve(setup)
    original = feedback._location(root, feedback.digest(selection)).read_bytes()
    def fail(*args, **kwargs):
        raise OSError("synthetic disk failure")
    monkeypatch.setattr(store, "_atomic_write", fail)
    with pytest.raises(OSError):
        feedback.forget(root, selection)
    assert feedback._location(root, feedback.digest(selection)).read_bytes() == original


def test_hook_and_read_only_debug_follow_withdrawal(setup):
    from knowledge_studio.mail_web import create_server
    root, selection, agreement, request = setup
    approve(setup)
    agreement_path = root.parent / "agreement.json"
    agreement_path.write_text(json.dumps(agreement), encoding="utf-8")
    hook = Path(__file__).resolve().parents[2] / "assets/hooks/user-prompt-recall.py"
    env = {**os.environ, "OKS_FEEDBACK_SUBJECT": selection["subject"], "OKS_FEEDBACK_PROJECT": selection["project"],
           "OKS_TASK_SCOPE": selection["task"], "OKS_TASK_AGREEMENT": str(agreement_path), "OKS_HOOK_OUTPUT": "json"}
    def invoke():
        done = subprocess.run([sys.executable, "-X", "utf8", str(hook)],
                              input=json.dumps({"prompt": "continue report with sources", "cwd": str(root), "session_id": "feedback-hook"}),
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        assert done.returncode == 0, done.stderr
        return done.stdout
    assert "PRIVATE_CANDIDATE" in invoke()
    feedback.withdraw(root, {"scope": selection, "event_id": "e1"})
    assert "PRIVATE_CANDIDATE" not in invoke()
    server = create_server(root, port=0)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        def read(payload, origin=base):
            request = Request(base + "/api/feedback/inspect", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json", "Origin": origin})
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        assert read({})["status"] == "scope_required"
        assert read({"scope": selection})["candidates"][0]["effective_status"] == "invalidated"
        with pytest.raises(HTTPError) as exc:
            read({"scope": selection}, "https://example.invalid")
        assert exc.value.code == 403
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=5)


def test_cli_json_roundtrip(setup, tmp_path):
    root, selection, agreement, request = setup
    path = tmp_path / "request.json"; path.write_text(json.dumps(request), encoding="utf-8")
    result = CliRunner().invoke(app, ["feedback", "record", str(path)])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(app, ["feedback", "list", "--subject", "alice", "--project", selection["project"], "--task", selection["task"]])
    assert result.exit_code == 0 and "PRIVATE_REASON" in result.output


def test_recall_selects_private_requirements_without_logging_them(setup):
    from knowledge_studio.recall import recall
    root, selection, agreement, request = setup
    approve(setup)
    feedback.propose(root, {"scope": selection, "candidate_id": "pending", "event_ids": ["e1"], "title": "pending", "summary": "private pending"})
    def query():
        return recall("report", agreement=agreement, task_scope=selection["task"],
                      feedback_subject=selection["subject"], feedback_project=selection["project"], debug_record=True)
    result = query()
    assert result["task_context"]["candidates"][0]["summary"].startswith("PRIVATE_CANDIDATE")
    assert result["diagnostics"]["task_context"] == {"status": "selected", "selected_count": 1, "excluded_counts": {"pending": 1}}
    shared = (root / ".oks/retrieval-debug.json").read_text(encoding="utf-8")
    for private in ("alice", "report-project", "PRIVATE_CANDIDATE", "PRIVATE_REASON", "private pending"):
        assert private not in shared
    feedback.withdraw(root, {"scope": selection, "event_id": "e1"})
    assert query()["task_context"] == {"status": "empty", "candidates": [], "excluded_counts": {"invalidated": 2}}


def test_recall_does_not_read_private_store_without_complete_opt_in(setup, monkeypatch):
    from knowledge_studio.recall import recall
    root, selection, agreement, request = setup
    approve(setup)
    def forbidden(*args, **kwargs):
        raise AssertionError("private store must not be read")
    monkeypatch.setattr(feedback, "select_context", forbidden)
    assert recall("report", user_id="alice", project_slug="report-project")["task_context"]["status"] == "not_requested"
    assert recall("report", feedback_subject="alice")["task_context"]["status"] == "scope_incomplete"
    assert recall("report", feedback_subject="alice", feedback_project="report-project")["task_context"]["status"] == "agreement_required"


def test_recall_private_store_error_preserves_wiki_and_hides_error_text(setup, monkeypatch):
    from knowledge_studio.recall import recall
    root, selection, agreement, request = setup
    def fail(*args, **kwargs):
        raise ValueError("PRIVATE_SECRET_PATH")
    monkeypatch.setattr(feedback, "select_context", fail)
    result = recall("report", agreement=agreement, task_scope=selection["task"], feedback_subject="alice", feedback_project="report-project")
    assert result["knowledge"]
    assert result["task_context"]["status"] == "unavailable"
    assert "PRIVATE_SECRET_PATH" not in json.dumps(result)


def test_recall_cli_uses_same_explicit_environment_as_hook(setup, monkeypatch):
    root, selection, agreement, request = setup
    approve(setup)
    path = root.parent / "agreement.json"
    path.write_text(json.dumps(agreement), encoding="utf-8")
    for key, value in {"OKS_TASK_AGREEMENT": str(path), "OKS_TASK_SCOPE": selection["task"],
                       "OKS_FEEDBACK_SUBJECT": selection["subject"], "OKS_FEEDBACK_PROJECT": selection["project"]}.items():
        monkeypatch.setenv(key, value)
    result = CliRunner().invoke(app, ["recall", "report", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["task_context"]["candidates"]) == 1
    changed = CliRunner().invoke(app, ["recall", "report", "--feedback-project", "other", "--format", "json"])
    assert json.loads(changed.output)["task_context"]["candidates"] == []
    (root / "profiles/goals/report.md").write_text("Changed constraint", encoding="utf-8")
    stale = CliRunner().invoke(app, ["recall", "report", "--format", "json"])
    assert stale.exit_code == 2 and "PRIVATE_CANDIDATE" not in stale.output
