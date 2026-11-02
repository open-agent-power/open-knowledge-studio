"""Workflow handoff checks operate on evidence, never declared success alone."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from knowledge_studio import mail
from knowledge_studio.cli import app
from knowledge_studio.ingest_workflow import finalize_workflow, validate_workflow


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    (tmp_path / "wiki").mkdir()
    (tmp_path / "drafts").mkdir()
    bundle = tmp_path / "raw/2026/source"
    bundle.mkdir(parents=True)
    (bundle / "bundle.json").write_text(json.dumps({
        "bundle_id": "bundle:sample", "processing_status": "complete",
    }), encoding="utf-8")
    (bundle / "content.md").write_text("Original source", encoding="utf-8")
    candidate = "drafts/takeaway.md"
    (tmp_path / candidate).write_text("---\n" + yaml.safe_dump({
        "title": "Takeaway", "draft_type": "concept", "draft_area": "computing",
        "status": "pending", "source_bundle_id": "bundle:sample",
    }) + "---\n\nA bounded takeaway from the source.\n", encoding="utf-8")
    result = {"status": "complete", "bundle_id": "bundle:sample", "intake_grade": "A",
              "candidate_path": candidate, "review_status": "pending",
              "workflow_status": "awaiting_human_review"}
    path = tmp_path / ".oks/runs/run-example/result.json"
    path.parent.mkdir(parents=True)
    def save():
        path.write_text(json.dumps(result), encoding="utf-8")
    save()
    return tmp_path, result, save


def record_handoffs(root, result, *, recipient="human", run_id="run-example"):
    refs = [{"type": "run", "id": run_id},
            {"type": "bundle", "id": result["bundle_id"]},
            {"type": "candidate", "path": result["candidate_path"]}]
    messages, thread, previous = {}, "", ""
    for kind in ["goal", "result", "review_request"]:
        sent = mail.write_message(root, sender="worker", recipients=recipient,
                                  sender_kind="agent", record_kind=kind, body=kind,
                                  thread_id=thread, reply_to=previous, evidence_refs=refs)
        thread, previous = sent["thread_id"], sent["message_id"]
        messages[kind] = previous
    result["collaboration"] = {"status": "recorded", "thread_id": thread, "messages": messages}


def test_complete_claim_does_not_substitute_for_missing_handoffs(workflow):
    root, result, save = workflow
    result["collaboration"] = {"status": "recorded", "thread_id": "absent"}
    save()
    assert not validate_workflow("run-example")["valid"]
    checked = validate_workflow("run-example", collaboration=True)
    assert not checked["valid"]
    assert "message_not_visible:review_request" in checked["errors"]
    cli = CliRunner().invoke(app, ["ingest", "validate", "run-example", "--collaboration"])
    assert cli.exit_code == 2


def test_real_visible_handoff_is_pending_and_validation_is_read_only(workflow):
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    checked = validate_workflow("run-example", collaboration=True)
    assert checked["valid"], checked
    assert checked["workflow_status"] == "awaiting_human_review"
    assert before == {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert not (root / "mail/receipts").exists()


@pytest.mark.parametrize("mutation,error", [
    ("private", "message_not_visible:goal"),
    ("missing_candidate", "candidate_missing:drafts/takeaway.md"),
    ("wrong_bundle", "candidate_bundle_mismatch:drafts/takeaway.md"),
    ("wrong_parent", "reply_parent_mismatch:result"),
    ("missing_refs", "message_evidence_missing:review_request"),
    ("premature_complete", "premature_workflow_completion"),
])
def test_inconsistent_handoff_never_passes(workflow, mutation, error):
    root, result, save = workflow
    record_handoffs(root, result, recipient="private" if mutation == "private" else "human")
    candidate = root / result["candidate_path"]
    if mutation == "missing_candidate":
        candidate.unlink()
    if mutation == "wrong_bundle":
        candidate.write_text(candidate.read_text("utf-8").replace("bundle:sample", "bundle:other"), encoding="utf-8")
    if mutation in {"wrong_parent", "missing_refs"}:
        kind = "result" if mutation == "wrong_parent" else "review_request"
        path = mail.canonical_path(root, result["collaboration"]["messages"][kind])
        body = path.read_text("utf-8")
        if mutation == "wrong_parent":
            body = body.replace(result["collaboration"]["messages"]["goal"], "absent")
        else:
            body = body.replace('"bundle:sample"', '"bundle:other"')
        path.write_text(body, encoding="utf-8")
    if mutation == "premature_complete":
        result["workflow_status"] = "complete"
    save()
    assert error in validate_workflow("run-example", collaboration=True)["errors"]


@pytest.mark.parametrize("path", ["drafts/../../outside.md", "wiki/other.md", "C:/outside.md"])
def test_candidate_paths_cannot_escape_drafts(workflow, path):
    _, result, save = workflow
    result["candidate_path"] = path
    save()
    with pytest.raises(ValueError):
        validate_workflow("run-example")


@pytest.mark.parametrize("field", ["status", "intake_grade"])
def test_malformed_result_is_a_structured_cli_error(workflow, field):
    _, result, save = workflow
    result[field] = []
    save()
    called = CliRunner().invoke(app, ["ingest", "validate", "run-example"])
    assert called.exit_code == 2
    assert json.loads(called.output)["valid"] is False


@pytest.mark.parametrize("status", ["partial", "failed", "skipped"])
def test_extraction_state_is_preserved(workflow, status):
    _, result, save = workflow
    result["status"] = status
    save()
    checked = validate_workflow("run-example")
    assert checked["extraction_status"] == status
    assert checked["valid"] == (status == "partial")


@pytest.mark.parametrize("grade", ["B", "C"])
def test_source_only_intake_does_not_require_review_messages(workflow, grade):
    _, result, save = workflow
    result.update(intake_grade=grade, candidate_path=None, review_status=None)
    save()
    checked = validate_workflow("run-example")
    assert checked["valid"], checked
    assert checked["workflow_status"] == "source_only"


def test_candidate_symlink_is_not_accepted_as_evidence(workflow, tmp_path):
    root, result, save = workflow
    target = tmp_path / "outside.md"
    target.write_text("private", encoding="utf-8")
    link = root / "drafts/linked.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")
    result["candidate_path"] = "drafts/linked.md"
    save()
    with pytest.raises(ValueError, match="Symlinks"):
        validate_workflow("run-example")


def test_concurrent_acknowledgements_remain_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_MACHINE_ID", "machine-a")
    sent = mail.write_message(tmp_path, sender="human", recipients="writer", body="confirm")
    row = next(mail.iter_messages(tmp_path, "writer"))
    mail.record_delivery(tmp_path, "s1", row, agent_id="writer")
    def ack(_):
        return mail.acknowledge_delivery(tmp_path, "s1", sent["message_id"], agent_id="writer")
    with ThreadPoolExecutor(max_workers=4) as executor:
        assert all(r["status"] == "acknowledged" for r in executor.map(ack, range(8)))
    assert [e["event_type"] for e in mail.iter_receipt_events(tmp_path, "s1", sent["message_id"])] == ["presented", "acknowledged"]


def test_isolated_skill_to_ingest_review_and_recall_lifecycle(tmp_path, monkeypatch):
    """Human approval is simulated only in this disposable fixture."""
    from knowledge_studio import skills, store
    from knowledge_studio.ingest_prepare import prepare_ingest
    from knowledge_studio.raw_commit import raw_commit
    from knowledge_studio.recall import recall

    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    monkeypatch.setenv("OKS_ROOT", str(root))
    skill = Path(__file__).resolve().parents[2] / "assets/skills/ingest"
    imported = skills.import_skill(skill, category="knowledge/ingestion")
    store.promote_draft(imported["entry"]["slug"])
    hit = skills.search("知识提取")[0]
    loaded = skills.load(hit["skill_id"], version=hit["skill_version"])
    assert not loaded["executed"]
    assert "oks ingest finalize" in json.dumps(loaded)

    source = tmp_path / "source.txt"
    source.write_text("Nebula memory records preserve task state outside a context window.\n", encoding="utf-8")
    prepared = prepare_ingest(str(source), kb_root=root)
    committed = raw_commit(Path(prepared["manifest_dir"]))
    result = {"status": "complete", "bundle_id": committed["bundle_id"], "intake_grade": "A",
              "candidate_path": "drafts/nebula-memory.md", "review_status": "pending",
              "workflow_status": "awaiting_human_review"}
    (root / result["candidate_path"]).write_text("---\n" + yaml.safe_dump({
        "title": "Nebula memory", "draft_type": "concept", "draft_area": "computing",
        "status": "pending", "source_bundle_id": committed["bundle_id"],
        "summary": "Durable notes preserve task state.",
        "source_raw_bundle": str(Path(committed["bundle_path"]).relative_to(root)).replace("\\", "/"),
    }) + "---\n\nNebula memory preserves durable task state outside a context window; "
        "read it back when needed. This fixture tests the review lifecycle.\n", encoding="utf-8")
    record_handoffs(root, result, run_id=prepared["run_id"])
    store._atomic_write(Path(prepared["workspace"]) / "result.json", json.dumps(result))
    finalized = CliRunner().invoke(app, ["ingest", "finalize", prepared["run_id"]])
    assert finalized.exit_code == 0, finalized.output
    checked = json.loads(finalized.output)
    assert checked["valid"], checked
    assert checked["workflow_status"] == "awaiting_human_review"
    assert not [p for p in store.list_wiki_pages() if p.get("area") == "computing"]

    # Simulate the explicit human review boundary, never do this to user data.
    promoted = store.promote_draft("nebula-memory")
    page = store.get_wiki_page(promoted)
    assert page["source_bundle_id"] == committed["bundle_id"]
    assert page["summary"] == "Durable notes preserve task state."
    found = recall("Nebula memory", knowledge_only=True, goal="none")["knowledge"]
    assert any(hit["slug"] == promoted and hit["human_reviewed_at"] for hit in found)
    closed = finalize_workflow(prepared["run_id"])
    assert closed["valid"], closed
    assert closed["workflow_status"] == "complete"
    assert closed["promoted_pages"][result["candidate_path"]] == Path(page["file_path"]).relative_to(root).as_posix()
    assert finalize_workflow(prepared["run_id"]) == closed


@pytest.mark.parametrize("field,value", [("source_bundle_id", "bundle:wrong"),
    ("source_candidates", ["drafts/other.md"]), ("source_candidates", 'drafts/takeaway.md'), ("human_reviewed_at", None),
    ("status", "provisional"), ("archived", True)])
def test_finalization_rejects_unproven_promotion(workflow, field, value):
    from knowledge_studio import store
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    page = store.get_wiki_page(store.promote_draft("takeaway"))
    store._update_frontmatter_field(Path(page["file_path"]), field, value)
    checked = finalize_workflow("run-example")
    assert not checked["valid"]
    assert checked["workflow_status"] == "incomplete"
    assert checked["promoted_pages"] == {}


def test_retained_review_only_completes_the_exact_approved_candidate(workflow):
    from knowledge_studio import store
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    candidate = root / result['candidate_path']
    original = candidate.read_bytes()
    store.promote_draft('takeaway')
    assert candidate.read_bytes() == original
    assert validate_workflow('run-example', collaboration=True)['workflow_status'] == 'complete'
    candidate.write_bytes(original + b'\nNew unreviewed material.\n')
    checked = validate_workflow('run-example', collaboration=True)
    assert checked['valid'] and checked['workflow_status'] == 'awaiting_human_review'
    assert checked['promoted_pages'] == {}


def test_wiki_labels_without_original_do_not_prove_finalized_review(workflow):
    from knowledge_studio import store
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    store.promote_draft('takeaway')
    (root / result['candidate_path']).unlink()
    checked = validate_workflow('run-example', collaboration=True)
    assert not checked['valid'] and checked['promoted_pages'] == {}
    assert 'candidate_missing:drafts/takeaway.md' in checked['errors']


def test_finalize_requires_real_handoffs_and_saves_incomplete(workflow):
    root, result, _ = workflow
    # Extraction claims complete, but no communication has taken place.
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-example"])
    assert called.exit_code == 2, called.output
    checked = json.loads(called.output)
    assert checked["workflow_status"] == "incomplete"
    assert "message_not_visible:review_request" in checked["errors"]
    saved = json.loads((root / ".oks/runs/run-example/result.json").read_text("utf-8"))
    assert saved["status"] == "complete"
    assert saved["workflow_mode"] == "collaboration"
    assert saved["workflow_validation"] == checked
    assert saved["review_status"] == "pending"
    assert not (root / "mail").exists()


def test_finalize_real_handoff_is_idempotent_and_only_updates_run_state(workflow):
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    before = {p: p.read_bytes() for bucket in ["raw", "drafts", "wiki", "mail"]
              for p in (root / bucket).rglob("*") if p.is_file()}
    first = finalize_workflow("run-example")
    path = root / ".oks/runs/run-example/result.json"
    first_bytes = path.read_bytes()
    second = finalize_workflow("run-example")
    assert first == second and first["valid"]
    assert path.read_bytes() == first_bytes
    saved = json.loads(first_bytes)
    assert saved["workflow_status"] == "awaiting_human_review"
    assert saved["status"] == "complete" and saved["review_status"] == "pending"
    assert before == {p: p.read_bytes() for bucket in ["raw", "drafts", "wiki", "mail"]
                      for p in (root / bucket).rglob("*") if p.is_file()}


@pytest.mark.parametrize("status", ["complete", "partial", "failed", "skipped"])
def test_standalone_finalization_preserves_extraction_state_without_mail(workflow, status):
    root, result, save = workflow
    result.update(status=status, intake_grade="B", candidate_path=None, review_status=None)
    save()
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-example", "--source-only"])
    assert called.exit_code == (0 if status in {"complete", "partial"} else 2), called.output
    checked = json.loads(called.output)
    saved = json.loads((root / ".oks/runs/run-example/result.json").read_text("utf-8"))
    assert saved["status"] == checked["extraction_status"] == status
    assert saved["workflow_status"] == ("source_only" if checked["valid"] else "incomplete")
    assert not checked["collaboration_checked"]
    assert not (root / "mail").exists()


@pytest.mark.parametrize("declaration", ["mode", "recorded", "awaiting_authorization", "previous_attempt"])
def test_collaborative_run_cannot_downgrade_to_skip_handoffs(workflow, declaration):
    root, result, save = workflow
    if declaration == "mode":
        result["workflow_mode"] = "collaboration"
    elif declaration == "previous_attempt":
        finalize_workflow("run-example")
    else:
        result["collaboration"] = {"status": declaration}
    if declaration != "previous_attempt":
        save()
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-example", "--source-only"])
    assert called.exit_code == 2, called.output
    assert "collaboration_downgrade_not_allowed" in json.loads(called.output)["errors"]
    saved = json.loads((root / ".oks/runs/run-example/result.json").read_text("utf-8"))
    assert saved["workflow_mode"] == "collaboration"
    assert saved["workflow_status"] == "incomplete"
    assert not validate_workflow("run-example")["valid"]


def test_finalize_rechecks_evidence_instead_of_trusting_old_validation(workflow):
    root, result, save = workflow
    record_handoffs(root, result)
    save()
    assert finalize_workflow("run-example")["valid"]
    (root / result["candidate_path"]).unlink()
    checked = finalize_workflow("run-example")
    assert not checked["valid"]
    assert "candidate_missing:drafts/takeaway.md" in checked["errors"]
    assert checked["workflow_status"] == "incomplete"


def test_finalize_custom_review_owner_is_not_replaced_by_default(workflow):
    _, result, save = workflow
    record_handoffs(workflow[0], result, recipient="owner")
    save()
    assert not finalize_workflow("run-example")["valid"]
    assert finalize_workflow("run-example", review_owner="owner")["valid"]


@pytest.mark.parametrize("relative", ["result.json", ".result.lock"])
def test_finalize_rejects_linked_runtime_files_without_writing_target(workflow, tmp_path, relative):
    root, _, _ = workflow
    path = root / ".oks/runs/run-example" / relative
    target = tmp_path / "external.json"
    target.write_bytes(path.read_bytes() if path.is_file() else b"private")
    path.unlink(missing_ok=True)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks unavailable")
    before = target.read_bytes()
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-example"])
    assert called.exit_code == 2, called.output
    assert json.loads(called.output)["workflow_status"] == "incomplete"
    assert target.read_bytes() == before


@pytest.mark.parametrize("value", [[], "not-a-mode"])
def test_finalize_malformed_mode_is_a_structured_error_without_result_rewrite(workflow, value):
    root, result, save = workflow
    result["workflow_mode"] = value
    save()
    path = root / ".oks/runs/run-example/result.json"
    before = path.read_bytes()
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-example"])
    assert called.exit_code == 2, called.output
    assert json.loads(called.output)["valid"] is False
    assert path.read_bytes() == before


def test_finalize_missing_run_does_not_create_workspace(workflow):
    root, _, _ = workflow
    called = CliRunner().invoke(app, ["ingest", "finalize", "run-missing"])
    assert called.exit_code == 2
    assert not (root / ".oks/runs/run-missing").exists()
