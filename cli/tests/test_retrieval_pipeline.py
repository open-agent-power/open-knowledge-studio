"""Fixed synthetic cases for retrieval -> agreement -> Hook -> Debug contracts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from urllib.request import urlopen

import pytest
import yaml

from knowledge_studio import handoff, skills, store
from knowledge_studio.recall import recall, load_recall_params
from knowledge_studio.retrieval_debug import overview, read_records, record
from knowledge_studio.search.fts5 import FTS5Backend


@pytest.fixture
def kb(tmp_path, monkeypatch):
    root = tmp_path / "kb"
    (root / "wiki/computing/concepts").mkdir(parents=True)
    (root / "profiles/goals").mkdir(parents=True)
    (root / "settings").mkdir()
    (root / "mail").mkdir()
    (root / "profiles/goals/retrieval.md").write_text("---\ntitle: Retrieval\ntype: goal\nstatus: active\nkeywords: [nebula]\n---\nKeep source citations.\n", encoding="utf-8")
    monkeypatch.setenv("OKS_ROOT", str(root))
    monkeypatch.delenv("OKS_SEARCH_BACKEND", raising=False)
    write_page(root, "wiki/computing/concepts/nebula.md")
    return root


def write_page(root, path, **overrides):
    meta = dict(title="Nebula retrieval", area="computing", type="concept", status="active",
                human_reviewed_at="2026-10-27", options=[{"id": "local", "chosen": True, "reason": "offline"},
                                                        {"id": "remote", "chosen": False, "reason": "no network"}])
    meta.update(overrides)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + yaml.safe_dump(meta) + "---\n\n## Evidence\nnebula source citations\n", encoding="utf-8")
    return target


def skill(root, name="retrieve", description="Nebula retrieval", body="Special operation quasar-protocol"):
    source = root.parent / name
    source.mkdir(exist_ok=True)
    (source / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")
    imported = skills.import_skill(source, category="knowledge/retrieval")
    return store.get_wiki_page(store.promote_draft(imported["entry"]["slug"]))


def test_default_and_skill_use_same_persistent_index(kb):
    page = skill(kb)
    assert load_recall_params()["search_backend"] == "fts5"
    result = recall("nebula", goal="none", knowledge_only=True)
    assert result["diagnostics"]["actual_backends"] == ["fts5"]
    assert all(h["relevance"] > 0 for h in result["knowledge"])
    hit = skills.search("nebula")[0]
    assert hit["skill_version"] == page["skill_version"]
    assert hit["backend"] == "fts5"
    assert "--version " + page["skill_version"] in hit["load_command"]
    backend = FTS5Backend(root=str(kb))
    try:
        assert backend._conn.execute("SELECT count(*) FROM wiki_fts").fetchone()[0] >= 2
        assert backend._conn.execute("SELECT count(*) FROM skill_fts").fetchone()[0] == 1
    finally:
        backend.close()


def test_query_hit_loads_exact_wiki_skill_without_host_deployment(kb):
    page = skill(kb)
    assert all(h.get("artifact_kind") != "skill" for h in recall("nebula", goal="none")["knowledge"])
    hit = skills.search("nebula")[0]
    assert hit["load_command"] == f"oks skills load {page['skill_id']} --version {page['skill_version']}"
    assert not (kb / ".oks/skill-loads.json").exists()
    loaded = skills.load(hit["skill_id"], version=hit["skill_version"])
    assert loaded["executed"] is False
    assert "quasar-protocol" in loaded["instructions"]
    assert Path(loaded["assets_root"]).is_relative_to(kb / ".oks/skill-cache")
    assert not (kb / ".oks/skill-loads.json").exists()


def test_metadata_routing_beats_incidental_body_without_execution_fallback(kb):
    skill(kb, "extract", "document extraction", "anything")
    skill(kb, "mail", "mail collaboration", "document extraction " * 100)
    assert skills.search("文档提取", limit=1)[0]["skill_id"] == "extract"
    skill(kb, "special", "unrelated utility")
    assert skills.search("quasar-protocol", debug_record=True) == []
    diagnostics = read_records(kb)["records"][0]["diagnostics"]
    assert diagnostics["strategy"] == "capability"
    assert "capability_fallback" not in diagnostics


@pytest.mark.parametrize("state", [{"status": "dropped"}, {"archived": True}, {"human_reviewed_at": None}])
def test_changed_skill_admission_is_refreshed_before_top_k(kb, state):
    bad = skill(kb, "bad", "nebula " * 30)
    skill(kb, "good", "nebula")
    assert skills.search("nebula")
    path = Path(bad["file_path"])
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    meta.update(state)
    path.write_text("---\n" + yaml.safe_dump(meta) + "---" + body, encoding="utf-8")
    assert [h["skill_id"] for h in skills.search("nebula", limit=1)] == ["good"]


def test_like_degradation_is_truthful_and_filters_before_limit(kb, monkeypatch):
    import knowledge_studio.search.fts5 as module
    skill(kb)
    write_page(kb, "wiki/computing/concepts/aaa.md", status="dropped")
    monkeypatch.setattr(module, "_check_fts5", lambda: False)
    result = recall("nebula", goal="none", limit=1, knowledge_only=True)
    assert result["knowledge"][0]["backend"] == "like"
    assert result["diagnostics"]["fallback_reason"] == "sqlite_fts5_unavailable"
    assert skills.search("nebula", limit=1)[0]["skill_id"] == "retrieve"


def test_native_is_explicit_observable_control(kb):
    result = recall("nebula", goal="none", search_backend="native", knowledge_only=True)
    assert result["diagnostics"]["experimental"] is True
    assert result["diagnostics"]["actual_backends"] == ["native"]


def test_fts_recovery_rebuilds_metadata_only_cache(kb, monkeypatch):
    import knowledge_studio.search.fts5 as module
    real_check = module._check_fts5
    if not real_check():
        pytest.skip("SQLite lacks FTS5")
    monkeypatch.setattr(module, "_check_fts5", lambda: False)
    assert recall("nebula", knowledge_only=True)["diagnostics"]["actual_backends"] == ["like"]
    skill(kb)
    assert skills.search("nebula")[0]["backend"] == "like"
    monkeypatch.setattr(module, "_check_fts5", real_check)
    assert skills.search("nebula")[0]["backend"] == "fts5"
    assert recall("nebula", knowledge_only=True)["knowledge"]


def test_agreement_versions_scope_and_decision_evidence(kb):
    agreement = handoff.prepare(kb, "profiles/goals/retrieval.md", ["wiki/computing/concepts/nebula.md"], "project-a")
    result = recall("nebula", goal="active", agreement=agreement, task_scope="project-a", debug_record=True)
    assert result["diagnostics"]["task"]["goal_sha256"] == agreement["goal"]["sha256"]
    hit = result["knowledge"][0]
    assert hit["source_sha256"] == hashlib.sha256((kb / hit["source_path"]).read_bytes()).hexdigest()
    assert hit["options"][1]["chosen"] is False
    with pytest.raises(ValueError, match="scope_mismatch"):
        recall("nebula", agreement=agreement, task_scope="project-b")
    with pytest.raises(ValueError, match="differs"):
        recall("nebula", agreement=agreement, task_scope="project-a", goal="other")
    (kb / "profiles/goals/retrieval.md").write_text("Changed", encoding="utf-8")
    with pytest.raises(ValueError, match="source_changed"):
        skills.search("nebula", agreement=agreement, task_scope="project-a")


def test_debug_opt_in_privacy_and_corruption_preservation(kb):
    result = recall("secret task text nebula", goal="none")
    assert read_records(kb)["status"] == "empty"
    record(kb, "secret task text nebula", result["diagnostics"], result["knowledge"])
    path = kb / ".oks/retrieval-debug.json"
    assert "secret task text" not in path.read_text(encoding="utf-8")
    assert "body_preview" not in path.read_text(encoding="utf-8")
    assert overview(kb)["records"][0]["host_consumed"] == "unknown"
    path.write_text("corrupt", encoding="utf-8")
    with pytest.raises(ValueError, match="preserved"):
        record(kb, "new", {}, [])
    assert path.read_text(encoding="utf-8") == "corrupt"


def test_hook_emits_catalog_once_and_keeps_asset_cooldown_on_card_edits(kb):
    page = skill(kb)
    (kb / "settings/recall.yaml").write_text("debug_record: true\nrecall:\n  topn: 3\n  cooldown: 10\n", encoding="utf-8")
    hook = Path(__file__).resolve().parents[2] / "assets/hooks/user-prompt-recall.py"
    env = {**os.environ, "OKS_ROOT": str(kb), "OKS_HOOK_OUTPUT": "json", "PYTHONIOENCODING": "utf-8"}
    def invoke():
        done = subprocess.run([sys.executable, "-X", "utf8", str(hook)], input=json.dumps({"prompt": "nebula retrieval task", "session_id": "pipeline", "cwd": str(kb)}),
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        assert done.returncode == 0, done.stderr
        return done.stdout
    first = invoke()
    assert "oks skills load retrieve --version" in first
    assert "quasar-protocol" not in first
    second = invoke()
    assert "oks skills load retrieve --version" not in second
    path = Path(page["file_path"])
    # The asset version is unchanged, so editing the card must not reload the package.
    path.write_text(path.read_text(encoding="utf-8") + "\nadditional note\n", encoding="utf-8")
    assert "oks skills load retrieve --version" not in invoke()
    records = read_records(kb)["records"]
    assert records[-1]["stage"] == "hook_emitted"
    assert any(e["content"] == "skill_catalog" for e in records[-1]["emitted"])
    assert records[0]["skipped"][page["slug"]] == "cooldown"


def test_skill_routing_failure_does_not_discard_wiki_hook_results(kb):
    (kb / "settings/recall.yaml").write_text("debug_record: true\n", encoding="utf-8")
    hook = Path(__file__).resolve().parents[2] / "assets/hooks/user-prompt-recall.py"
    wrapper = kb.parent / "faulty_skill.py"
    wrapper.write_text("import runpy, sys\n" + f"sys.path.insert(0, {str(hook.parent)!r})\n" + "import knowledge_studio.skills as skills\n"
                       "def fail(*args, **kwargs):\n    raise RuntimeError('broken capability index')\n"
                       "skills.search = fail\n" + f"runpy.run_path({str(hook)!r}, run_name='__main__')\n", encoding="utf-8")
    done = subprocess.run([sys.executable, "-X", "utf8", str(wrapper)],
                          input=json.dumps({"prompt": "nebula source citations", "session_id": "skill-failure", "cwd": str(kb)}),
                          env={**os.environ, "OKS_HOOK_OUTPUT": "json"}, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    assert "nebula" in json.loads(done.stdout)["trace"]["matches"]
    assert read_records(kb)["records"][0]["diagnostics"]["skill_error"] == "RuntimeError"


def test_malformed_debug_items_are_reported_without_overwrite(kb):
    path = kb / ".oks/retrieval-debug.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text('[{"stage":"retrieved","diagnostics":{},"hits":[null],"emitted":[]}]', encoding="utf-8")
    assert read_records(kb)["status"] == "error"


def test_read_only_debug_http_api_and_assets(kb):
    from knowledge_studio.mail_web import create_server
    recall("nebula", debug_record=True)
    server = create_server(kb, port=0)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urlopen(base + "/api/retrieval/debug", timeout=5) as response:
            assert json.load(response)["records"][0]["stage"] == "retrieved"
        for route in ("/debug", "/debug.js", "/debug.css"):
            with urlopen(base + route, timeout=5) as response:
                assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
