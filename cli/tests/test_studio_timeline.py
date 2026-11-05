import hashlib
import json
from datetime import datetime
import pytest
from knowledge_studio import studio, studio_history as history, layout


def write(root, path, text):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_migration_preserves_bytes_and_old_paths_are_read_aliases(tmp_path):
    doc = "---\ntype: goal\n---\n# Plan\n## [ ] Task\n"
    write(tmp_path, "goal/2026/11/04/a.md", doc)
    write(tmp_path, "skill/oh-my-test/SKILL.md", "# Method")
    result = layout.migrate(tmp_path)
    assert result["status"] == "completed"
    assert (tmp_path / "profiles/goals/2026/11/04/a.md").read_text() == doc
    assert (
        studio.read_file(tmp_path, "goal/2026/11/04/a.md")["path"]
        == "profiles/goals/2026/11/04/a.md"
    )
    assert not (tmp_path / "goal").exists() and not (tmp_path / "skill").exists()
    assert (
        studio.local_skills(tmp_path)["skills"][0]["path"]
        == "skills/oh-my-test/SKILL.md"
    )
    assert layout.migrate(tmp_path)["status"] == "unchanged"


def test_conflict_preflight_moves_nothing(tmp_path):
    write(tmp_path, "skill/a/SKILL.md", "# one")
    write(tmp_path, "skills/a/SKILL.md", "# two")
    with pytest.raises(ValueError, match="Conflicting"):
        layout.migrate(tmp_path)
    assert (tmp_path / "skill/a/SKILL.md").read_text() == "# one"


def test_real_edit_records_revision_and_history_is_read_only(tmp_path):
    today = datetime.now().astimezone().date().isoformat()
    relative = "profiles/goals/" + today.replace("-", "/") + "/plan.md"
    write(tmp_path, relative, "# Plan\n\n## [ ] first\n")
    before = studio.read_file(tmp_path, relative)
    studio.save_file(
        tmp_path,
        {
            "path": relative,
            "text": "# Plan\n\n## [x] first\n### [ ] next\n",
            "expected_sha256": before["sha256"],
        },
    )
    events = history.events(tmp_path, today, "goal")
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "edit" and event["status"] == "complete"
    assert "before" not in event
    revision = studio.revision_view(tmp_path, event["id"])
    assert (
        revision["read_only"] is True
        and revision["revision"]["before"] == before["text"]
    )
    day = studio.day_view(tmp_path, "goal", today)
    assert day["entries"] == [relative] and len(day["timeline"]) == 1
    assert studio.document_date(relative) == today


def test_external_changes_are_observations_not_invented_past_times(tmp_path):
    p = write(tmp_path, "profiles/goals/2020/01/01/old.md", "# Old\n## [ ] A\n")
    watcher = history.Watcher(tmp_path)
    watcher.scan()
    today = datetime.now().astimezone().date().isoformat()
    events = history.events(tmp_path, today, "goal")
    assert events[0]["action"] == "baseline"
    assert not history.events(tmp_path, "2020-01-01")
    p.write_text("# Old\n## [x] A\n")
    watcher.scan()
    watcher.scan()
    events = history.events(tmp_path, today, "goal")
    assert len(events) == 2 and events[-1]["action"] == "observed_change"
    assert studio.day_view(tmp_path, "goal", today)["entries"] == [
        "profiles/goals/2020/01/01/old.md"
    ]


def test_onboarding_skip_does_not_fake_completion_and_resume_is_explicit(tmp_path):
    assert history.onboarding(tmp_path)["status"] == "not_started"
    state = history.onboarding(tmp_path, {"action": "skip"})
    assert state["status"] == "skipped" and not any(state["steps"].values())
    history.onboarding(tmp_path, {"action": "reset"})
    for step in ["discuss", "goals", "learning"]:
        state = history.onboarding(tmp_path, {"action": "complete_step", "step": step})
    assert state["status"] == "completed"


def test_vfs_canonical_skills_and_old_alias_share_one_file(tmp_path):
    from knowledge_studio.vfs import VfsResolver, VfsService

    p = write(tmp_path, "skills/oh-my-test/SKILL.md", "# Test")
    write(tmp_path, ".agents/skills/query/SKILL.md", "# Host")
    resolver = VfsResolver(tmp_path)
    assert resolver.resolve("oks://skills/oh-my-test/SKILL.md").path == p
    assert resolver.resolve("oks://skill/oh-my-test/SKILL.md").path == p
    assert (
        resolver.resolve("oks://host-skills/query/SKILL.md").path
        == tmp_path / ".agents/skills/query/SKILL.md"
    )
    assert "skill" not in [
        e["name"] for e in VfsService(resolver).ls("oks://")["entries"]
    ]


def test_day_replay_keeps_other_known_goals_and_never_includes_future_revision(tmp_path):
    a=history.record(tmp_path,'profiles/goals/2026/11/05/a.md',None,'# A\n## [ ] first\n',action='create')
    b=history.record(tmp_path,'profiles/goals/2026/11/05/b.md',None,'# B\n',action='create')
    history.record(tmp_path,a['path'],a['after'],'# A\n## [x] first\n',action='edit')
    frame=studio.revision_view(tmp_path,b['id'])
    assert set(frame['files'])=={a['path'],b['path']}
    assert '[ ] first' in frame['files'][a['path']]['text']
    assert frame['read_only']
