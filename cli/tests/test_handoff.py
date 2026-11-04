"""Synthetic handoff contracts; no claims about human or model task success."""
import copy
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from knowledge_studio import handoff, mail, store, trace

GOAL = "profiles/goals/report.md"
SCOPE = "project:report"
OPTIONS = [
    {"id": "local", "chosen": True, "rationale": "Keep the report offline", "conditions": ["private materials"]},
    {"id": "upload", "chosen": False, "rejected_because": "Do not upload private input"},
    {"id": "length", "status": "unresolved", "question": "Confirm the audience before choosing length"},
]


@pytest.fixture
def kb(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    goal = tmp_path / GOAL
    goal.parent.mkdir(parents=True)
    goal.write_text("---\ntitle: Report\ntype: goal\nstatus: active\n---\nUse cited sources. Stay offline.\n", encoding="utf-8")
    draft = tmp_path / "drafts/report.md"
    draft.parent.mkdir()
    draft.write_text("---\n" + yaml.safe_dump({"title": "Report policy", "draft_type": "strategy",
        "draft_area": "computing", "options": OPTIONS}, allow_unicode=True) + "---\nUse evidence in the report.\n", encoding="utf-8")
    slug = store.promote_draft("report")
    path = Path(store.get_wiki_page(slug)["file_path"]).relative_to(tmp_path).as_posix()
    return tmp_path, path, slug


CASES = json.loads((Path(__file__).parent / "fixtures/handoff-cases.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_frozen_handoff_contract_cases(kb, case):
    root, path, _ = kb
    snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    assert snapshot["knowledge"][0]["options"] == OPTIONS
    operation = case["operation"]
    if operation in {"change_goal", "refresh_goal"}:
        (root / GOAL).write_text((root / GOAL).read_text(encoding="utf-8") + "New human constraint: use only public examples.\n", encoding="utf-8")
        if operation == "refresh_goal":
            snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    elif operation == "resolve_refresh":
        options = copy.deepcopy(OPTIONS)
        options[2] = {"id": "length", "chosen": True, "rationale": "Audience confirmed"}
        store._update_frontmatter_field(root / path, "options", options)
        snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
        assert snapshot["knowledge"][0]["options"][2]["chosen"] is True
    elif operation == "delete_source":
        (root / path).unlink()
    elif operation == "withdraw":
        store._update_frontmatter_field(root / path, "status", "superseded")
    result = handoff.check(root, snapshot, "other-project" if operation == "wrong_scope" else SCOPE)
    assert result["status"] == case["status"]
    assert result["execution_verified"] is False
    if "issue" in case:
        assert case["issue"] in {issue["code"] for issue in result["issues"]}
    if operation == "assert_rejected":
        assert snapshot["knowledge"][0]["options"][1]["rejected_because"]
    if operation == "assert_unresolved":
        assert "chosen" not in snapshot["knowledge"][0]["options"][2]


def test_mail_session_receipts_preserve_snapshot_and_trace(kb):
    root, path, _ = kb
    snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    sent = mail.delegate_message(root, task="Continue report", sender="sender", recipients="receiver",
                                 origin_session_id="first", agreement=snapshot)
    message = mail.parse_message(sent["path"])
    restored = handoff.decode(message["meta"]["handoff_agreement_b64"])
    assert restored == snapshot
    assert "Do not upload private input" in message["body"]
    assert "unresolved" in message["body"]
    receipt = mail.record_delivery(root, "second", message)
    assert receipt["session_id"] == "second"
    trace.start_trace("report", "report-run")
    from knowledge_studio.cli import app
    result = CliRunner().invoke(app, ["handoff", "check", sent["message_id"], "--scope", SCOPE, "--run-id", "report-run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["trace_event_id"] == "report-run:2"
    event = trace.show_trace("report-run")["events"][-1]
    assert event["event_type"] == "tool_observation"
    assert event["payload"]["handoff_check"]["agreement_sha256"] == snapshot["sha256"]


def test_cli_prepare_delegate_check_and_stale_result(kb):
    root, _, slug = kb
    from knowledge_studio.cli import app
    runner = CliRunner()
    output = root / "snapshot.json"
    result = runner.invoke(app, ["handoff", "prepare", "--goal", GOAL, "--scope", SCOPE,
                                "--wiki", slug, "--output", str(output)])
    assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["handoff", "prepare", "--goal", GOAL, "--scope", SCOPE,
                                "--output", str(output)]).exit_code == 2
    result = runner.invoke(app, ["mail", "delegate", "--task", "Continue report", "--to", "receiver",
                                "--agreement", str(output), "--path", str(root), "--format", "json"])
    assert result.exit_code == 0, result.output
    message_id = json.loads(result.output)["message_id"]
    assert runner.invoke(app, ["handoff", "check", message_id, "--scope", SCOPE]).exit_code == 0
    (root / GOAL).write_text("---\ntype: goal\n---\nChanged scope", encoding="utf-8")
    result = runner.invoke(app, ["handoff", "check", message_id, "--scope", SCOPE])
    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "needs_review"
    assert runner.invoke(app, ["mail", "delegate", "--task", "Continue", "--to", "receiver",
                               "--agreement", str(output), "--format", "json"]).exit_code == 2


@pytest.mark.parametrize("path", ["../outside.md", "wiki/../outside.md", "C:/secret.md", "wiki//x.md", "wiki/./x.md", "wiki/x\\y.md"])
def test_paths_cannot_escape_knowledge_bucket(kb, path):
    root, _, _ = kb
    with pytest.raises(ValueError):
        handoff.prepare(root, GOAL, [path], SCOPE)


def test_scope_mismatch_does_not_read_sources(kb, monkeypatch):
    root, path, _ = kb
    snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    def unexpected_read(*args):
        pytest.fail("Scope mismatch read source data")
    monkeypatch.setattr(handoff, "_read", unexpected_read)
    assert handoff.check(root, snapshot, "another")["issues"] == [{"code": "scope_mismatch"}]


def test_tamper_and_forged_decisions_are_detected(kb):
    root, path, _ = kb
    snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    snapshot["knowledge"][0]["options"][0]["rationale"] = "Changed without source"
    with pytest.raises(ValueError, match="digest"):
        handoff.validate(snapshot)
    # A digest is not a signature. Even if recomputed, compare to actual source.
    snapshot["sha256"] = handoff.digest(snapshot)
    result = handoff.check(root, snapshot, SCOPE)
    assert "decision_snapshot_mismatch" in {x["code"] for x in result["issues"]}


def test_unreviewed_or_secret_sources_rejected(kb):
    root, path, _ = kb
    store._update_frontmatter_field(root / path, "human_reviewed_at", None)
    with pytest.raises(ValueError, match="human-reviewed"):
        handoff.prepare(root, GOAL, [path], SCOPE)
    (root / GOAL).write_text("---\ntype: goal\n---\nBearer abcdefghijklmnopqrstuvwxyz", encoding="utf-8")
    with pytest.raises(ValueError, match="Credential"):
        handoff.prepare(root, GOAL, [], SCOPE)


def test_legacy_handoff_remains_readable(kb):
    root, _, _ = kb
    sent = mail.delegate_message(root, task="Old task", sender="a", recipients="b")
    assert "handoff_agreement_b64" not in mail.parse_message(sent["path"])["meta"]
    from knowledge_studio.cli import app
    result = CliRunner().invoke(app, ["handoff", "check", sent["message_id"], "--scope", SCOPE])
    assert result.exit_code == 2
    assert "legacy" in result.output


def test_wrong_trace_goal_does_not_append(kb):
    root, path, _ = kb
    sent = mail.delegate_message(root, task="Report", sender="a", recipients="b",
                                 agreement=handoff.prepare(root, GOAL, [path], SCOPE))
    trace.start_trace("another-goal", "wrong-goal")
    from knowledge_studio.cli import app
    result = CliRunner().invoke(app, ["handoff", "check", sent["message_id"], "--scope", SCOPE, "--run-id", "wrong-goal"])
    assert result.exit_code == 2
    assert trace.show_trace("wrong-goal")["manifest"]["event_count"] == 1


def test_changed_invalid_utf8_source_reports_both_change_and_read_failure(kb):
    root, path, _ = kb
    snapshot = handoff.prepare(root, GOAL, [path], SCOPE)
    (root / path).write_bytes(b"\xffinvalid")
    result = handoff.check(root, snapshot, SCOPE)
    assert {x["code"] for x in result["issues"]} == {"source_changed", "source_unreadable"}


def test_oversized_or_duplicate_sources_rejected(kb):
    root, path, _ = kb
    with pytest.raises(ValueError, match="Duplicate"):
        handoff.prepare(root, GOAL, [path, path], SCOPE)
    (root / path).write_bytes(b"x" * (handoff.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="size limit"):
        handoff.prepare(root, GOAL, [path], SCOPE)


def test_symlink_source_cannot_escape_bucket(kb):
    root, _, _ = kb
    outside = root / "private.md"
    outside.write_text("---\ntitle: Private\n---\nDo not read", encoding="utf-8")
    link = root / "wiki/escape.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This platform/user cannot create a symlink")
    with pytest.raises(ValueError, match="escapes"):
        handoff.prepare(root, GOAL, ["wiki/escape.md"], SCOPE)


def test_cli_does_not_parse_unbounded_wiki_and_rejects_ambiguous_slug(kb, monkeypatch):
    root, path, slug = kb
    from knowledge_studio.cli import app
    monkeypatch.setattr(store, "get_wiki_page", lambda *a: pytest.fail("Unbounded Wiki read"))
    duplicate = root / "wiki/science" / Path(path).name
    duplicate.parent.mkdir()
    duplicate.write_bytes((root / path).read_bytes())
    result = CliRunner().invoke(app, ["handoff", "prepare", "--goal", GOAL, "--scope", SCOPE,
                                    "--wiki", slug, "--output", str(root / "snapshot.json")])
    assert result.exit_code == 2
    assert "exactly one" in result.output
    assert not (root / "snapshot.json").exists()
