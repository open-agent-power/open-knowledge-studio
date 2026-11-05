"""Tests for optional editor hook installation."""

import json
import os

import pytest
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from knowledge_studio import hooks as hook_service, resources
from knowledge_studio.cli import app


runner = CliRunner()


def _init_instance(tmp_path):
    target = tmp_path / "kb"
    result = runner.invoke(
        app,
        ["init", str(target), "--no-git", "--no-set-default"],
    )
    assert result.exit_code == 0, result.output
    return target


def _load_codex_hooks(target):
    return json.loads((target / ".codex" / "hooks.json").read_text(encoding="utf-8"))


def _codex_commands(hooks, event):
    return [
        handler["command"]
        for group in hooks.get("hooks", {}).get(event, [])
        for handler in group.get("hooks", [])
        if handler.get("type") == "command"
    ]


def _collaboration_handlers(target, editor, event):
    rel = ".claude/settings.json" if editor == "claude" else ".codex/hooks.json"
    hooks = json.loads((target / rel).read_text(encoding="utf-8"))
    return [
        handler
        for group in hooks.get("hooks", {}).get(event, [])
        for handler in group.get("hooks", [])
        if hook_service._hook_handler_matches_script(
            handler, "subagent-collaboration.py"
        )
    ]


def _bash_command():
    r"""Resolve a working bash on Windows.

    CreateProcess searches System32 before PATH, so a bare ``"bash"`` fallback
    resolves to the WSL stub (``C:\Windows\System32\bash.exe``) when Git
    Bash is installed outside the default directory — every .sh hook test then
    fails with ``execvpe(/bin/bash) failed``. Enumerate real Git Bash
    candidates explicitly and never silently accept the WSL stub.
    """
    if os.name != "nt":
        return "bash"
    candidates = []
    git = shutil.which("git.exe") or shutil.which("git")
    if git:
        root = Path(git).resolve()
        for base in (root.parent.parent, root.parent.parent.parent):
            candidates.append(base / "bin" / "bash.exe")
            candidates.append(base / "usr" / "bin" / "bash.exe")
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        program_files = os.environ.get(variable)
        if program_files:
            candidates.append(Path(program_files) / "Git" / "bin" / "bash.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    which = shutil.which("bash")
    if which and "system32" not in which.lower():
        return which
    return "bash"


def _run_hook(script, payload, cwd, env_overrides=None):
    env = os.environ.copy()
    env["OKS_ROOT"] = str(cwd)
    if env_overrides:
        env.update(env_overrides)
    cli_root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join(
        [str(cli_root), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    command = (
        [_bash_command(), str(script)]
        if script.suffix == ".sh"
        else [sys.executable, str(script)]
    )
    return subprocess.run(
        command,
        input=json.dumps(payload),
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=str(cwd),
        env=env,
        check=False,
    )


@pytest.mark.parametrize("backend", ["native", "fts5"])
def test_prompt_hook_inactive_pages_never_enter_context_or_trace(tmp_path, backend):
    target = _init_instance(tmp_path)
    wiki = target / "wiki" / "computing" / "concepts"
    wiki.mkdir(parents=True, exist_ok=True)
    states = [
        ("dropped", "status: dropped\n"),
        ("superseded", "status: superseded\n"),
        ("archived", "status: active\narchived: true\n"),
        ("active", "status: active\n"),
        ("provisional", "status: provisional\n"),
        ("legacy", ""),
    ]
    for slug, state in states:
        (wiki / f"{slug}.md").write_text(
            f"---\ntitle: Quasar ledger {slug}\narea: computing\ntype: concept\n{state}---\nquasar ledger policy\n",
            encoding="utf-8",
        )
    # BM25 and Native do not share a score range. A low floor isolates admission
    # policy from that separate product boundary.
    (target / "settings" / "recall.yaml").write_text(
        f"search_backend: {backend}\nrecall:\n  floor: 0\n  topn: 3\n", encoding="utf-8",
    )
    result = _run_hook(
        target / ".codex/hooks/user-prompt-recall.py",
        {"prompt": "quasar ledger policy", "session_id": "state-policy", "cwd": str(target)},
        target, {"OKS_HOOK_OUTPUT": "json", "OKS_SEARCH_BACKEND": backend,
                 "OKS_RECALL_FLOOR": "0", "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert set(envelope["trace"]["matches"]) == {"active", "provisional", "legacy"}
    for slug in ("dropped", "superseded", "archived"):
        assert f"({slug})" not in envelope["context"]
    records = [json.loads(line) for line in (target / "records/inject.jsonl").read_text(encoding="utf-8").splitlines()]
    assert set(records[-1]["slugs"]) == {"active", "provisional", "legacy"}


def test_prompt_hook_rejects_inactive_hits_from_a_faulty_recall_result(tmp_path):
    target = _init_instance(tmp_path)
    hook = target / ".codex/hooks/user-prompt-recall.py"
    wrapper = tmp_path / "fake-recall-hook.py"
    wrapper.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(hook.parent)!r})\n"
        "import knowledge_studio.recall as module\n"
        "def fake_recall(**kwargs):\n"
        "    return {'knowledge': [\n"
        "        {'slug': 'dropped', 'title': 'Dropped', 'status': 'dropped', 'relevance': 9},\n"
        "        {'slug': 'archived', 'title': 'Archived', 'status': 'active', 'archived': True, 'relevance': 8},\n"
        "        {'slug': 'active', 'title': 'Active', 'status': 'active', 'archived': False, 'relevance': 7},\n"
        "    ]}\n"
        "module.recall = fake_recall\n"
        f"runpy.run_path({str(hook)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    result = _run_hook(
        wrapper,
        {"prompt": "quasar ledger policy", "session_id": "faulty-recall", "cwd": str(target)},
        target, {"OKS_HOOK_OUTPUT": "json", "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["trace"]["matches"] == ["active"]
    assert "(dropped)" not in payload["context"]
    assert "(archived)" not in payload["context"]
    injected = [json.loads(line) for line in (target / "records/inject.jsonl").read_text(encoding="utf-8").splitlines()]
    assert injected[-1]["slugs"] == ["active"]


def test_hook_install_wires_codex_prompt_recall(tmp_path):
    target = _init_instance(tmp_path)

    result = runner.invoke(app, ["hook", "install", "--editor", "codex", "--path", str(target)])

    assert result.exit_code == 0, result.output
    hooks = _load_codex_hooks(target)
    commands = _codex_commands(hooks, "UserPromptSubmit")
    assert len(commands) == 1
    if os.name == "nt":
        # Native Windows wires the .py engine directly (no bash dependency);
        # the command may carry a 2>NUL stdout suppressor.
        assert "user-prompt-recall.py" in commands[0]
    else:
        assert commands[0].endswith("/.codex/hooks/user-prompt-recall.sh")
    assert (target / ".codex" / "hooks" / "user-prompt-recall.sh").is_file()
    assert (target / ".codex" / "hooks" / "user-prompt-recall.py").is_file()

    # Existing Codex hooks remain intact.
    assert _codex_commands(hooks, "SessionStart")
    assert _codex_commands(hooks, "PreCompact")

    post_commands = _codex_commands(hooks, "PostToolUse")
    assert len(post_commands) == 1
    if os.name == "nt":
        assert "post-tool-edit.py" in post_commands[0]
    else:
        assert post_commands[0].endswith("/.codex/hooks/post-tool-edit.sh")
    wrapper = target / ".codex" / "hooks" / "post-tool-edit.sh"
    if os.name != "nt":
        # POSIX wiring uses the .sh wrapper, so its interpreter must be baked.
        assert f'${{OKS_PYTHON:-{sys.executable}}}' in wrapper.read_text(encoding="utf-8")
    assert "/hooks" in result.output


@pytest.mark.parametrize("editor", ["claude", "codex"])
def test_subagent_collaboration_install_is_opt_in_and_idempotent(tmp_path, editor):
    target = _init_instance(tmp_path)
    settings_path = target / (
        ".claude/settings.json" if editor == "claude" else ".codex/hooks.json"
    )

    # Ordinary hook installation must not widen event collection.
    result = runner.invoke(app, ["hook", "install", "--editor", editor, "--path", str(target)])
    assert result.exit_code == 0, result.output
    assert not _collaboration_handlers(target, editor, "SubagentStart")
    assert not _collaboration_handlers(target, editor, "SubagentStop")

    # Preserve user permissions and event handlers while adding the opt-in hook.
    current = json.loads(settings_path.read_text(encoding="utf-8"))
    current["permissions"] = {"allow": ["Bash(git status *)"]}
    current.setdefault("hooks", {}).setdefault("SubagentStart", []).append(
        {"matcher": "Explore", "hooks": [{"type": "command", "command": "user-start-hook"}]}
    )
    settings_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")

    args = ["hook", "install", "--collaboration", "--editor", editor, "--path", str(target)]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    installed = json.loads(settings_path.read_text(encoding="utf-8"))
    assert installed["permissions"] == {"allow": ["Bash(git status *)"]}
    assert any(
        handler.get("command") == "user-start-hook"
        for group in installed["hooks"]["SubagentStart"]
        for handler in group["hooks"]
    )
    for event in ("SubagentStart", "SubagentStop"):
        handlers = _collaboration_handlers(target, editor, event)
        assert len(handlers) == 1
        assert "subagent-collaboration.py" in " ".join(
            [handlers[0].get("command", ""), *handlers[0].get("args", [])]
        )
        if editor == "codex" and os.name == "nt":
            assert "2>NUL" not in handlers[0].get("command", "")
        # No matcher: all actual agent types are observed.
        assert all(
            "matcher" not in group
            for group in installed["hooks"][event]
            if any(
                hook_service._hook_handler_matches_script(
                    handler, "subagent-collaboration.py"
                )
                for handler in group.get("hooks", [])
            )
        )

    status = runner.invoke(app, ["hook", "status", "--path", str(target)])
    assert status.exit_code == 0, status.output
    assert f"{editor} collaboration SubagentStart: wired" in status.output
    assert f"{editor} collaboration SubagentStop: wired" in status.output
    assert "captured" not in status.output.lower()
    assert "triggered" not in status.output.lower()

    # Run the installed Python asset directly with an event lacking a child ID;
    # the handler should import cleanly and leave unknown identity unclaimed.
    script = target / (".claude/hooks" if editor == "claude" else ".codex/hooks") / "subagent-collaboration.py"
    probe = _run_hook(
        script,
        {"hook_event_name": "SubagentStart", "session_id": "parent-session", "cwd": str(target)},
        target,
    )
    assert probe.returncode == 0, probe.stderr


@pytest.mark.parametrize("editor", ["qoder", "both"])
def test_collaboration_install_rejects_unsupported_editor_without_mutation(tmp_path, editor):
    target = _init_instance(tmp_path)
    before = {
        str(path.relative_to(target)): path.read_bytes()
        for directory in (".claude", ".codex", ".qoder")
        for path in (target / directory).rglob("*")
        if path.is_file()
    }

    result = runner.invoke(
        app,
        ["hook", "install", "--collaboration", "--editor", editor, "--path", str(target)],
    )

    assert result.exit_code == 1
    assert "--collaboration" in result.output
    assert "exactly one supported editor" in result.output
    after = {
        str(path.relative_to(target)): path.read_bytes()
        for directory in (".claude", ".codex", ".qoder")
        for path in (target / directory).rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("editor", ["claude", "codex"])
def test_collaboration_opt_in_survives_instance_upgrade(tmp_path, editor):
    target = _init_instance(tmp_path)
    result = runner.invoke(
        app,
        ["hook", "install", "--collaboration", "--editor", editor, "--path", str(target)],
    )
    assert result.exit_code == 0, result.output

    settings_path = target / (
        ".claude/settings.json" if editor == "claude" else ".codex/hooks.json"
    )
    before = json.loads(settings_path.read_text(encoding="utf-8"))
    script_path = target / (".claude/hooks" if editor == "claude" else ".codex/hooks") / "subagent-collaboration.py"
    assert script_path.is_file()

    upgraded = runner.invoke(app, ["init", str(target), "--upgrade", "--no-git", "--no-set-default"])

    assert upgraded.exit_code == 0, upgraded.output
    after = json.loads(settings_path.read_text(encoding="utf-8"))
    assert after == before
    bundled = resources.asset_root() / "hooks" / "subagent-collaboration.py"
    assert script_path.read_bytes() == bundled.read_bytes()
    for event in ("SubagentStart", "SubagentStop"):
        assert len(_collaboration_handlers(target, editor, event)) == 1


def test_hook_install_codex_is_idempotent_and_status_reports_wired(tmp_path):
    target = _init_instance(tmp_path)
    args = ["hook", "install", "--editor", "codex", "--path", str(target)]

    first = runner.invoke(app, args)
    second = runner.invoke(app, args)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    hooks = _load_codex_hooks(target)
    commands = _codex_commands(hooks, "UserPromptSubmit")
    assert len(commands) == 1

    status = runner.invoke(app, ["hook", "status", "--path", str(target)])
    assert status.exit_code == 0, status.output
    assert "codex: wired" in status.output
    assert "codex PostToolUse: wired" in status.output
    assert "codex trust: review with `/hooks`" in status.output


def test_hook_install_migrates_codex_relative_lifecycle_paths(tmp_path):
    target = _init_instance(tmp_path)
    hooks_path = target / ".codex" / "hooks.json"
    hooks = _load_codex_hooks(target)
    legacy_commands = {
        "PreToolUse": "validate-wiki-write.sh",
        "PreCompact": "pre-compact.sh",
        "SessionStart": "session-start.sh",
    }
    for event, script_name in legacy_commands.items():
        hooks["hooks"][event][0]["hooks"][0]["command"] = f".codex/hooks/{script_name}"
    hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["hook", "install", "--editor", "codex", "--path", str(target)],
    )

    assert result.exit_code == 0, result.output
    migrated = _load_codex_hooks(target)
    for event, script_name in legacy_commands.items():
        command = _codex_commands(migrated, event)[0]
        assert Path(command).resolve() == (target / ".codex" / "hooks" / script_name).resolve()


def test_codex_session_start_emits_structured_json_context(tmp_path):
    """Codex 必须收到标准 SessionStart JSON，不能直接收到纯文本。"""
    target = _init_instance(tmp_path)
    domain = target / "wiki" / "computing"
    domain.mkdir()
    (domain / "hooks.md").write_text("# Hooks\n", encoding="utf-8")
    script = target / ".codex" / "hooks" / "session-start.sh"

    result = _run_hook(
        script,
        {
            "hook_event_name": "SessionStart",
            "session_id": "codex-session",
            "source": "startup",
            "cwd": str(target),
        },
        target,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "SessionStart"
    assert "[Knowledge Studio]" in hook_output["additionalContext"]


def test_codex_session_start_handles_an_empty_wiki(tmp_path):
    """空 Wiki 尚无 domain 时，SessionStart 也必须成功并返回合法 JSON。"""
    target = _init_instance(tmp_path)
    script = target / ".codex" / "hooks" / "session-start.sh"

    result = _run_hook(
        script,
        {
            "hook_event_name": "SessionStart",
            "session_id": "codex-session",
            "source": "startup",
            "cwd": str(target),
        },
        target,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "0 wiki pages" in context
    assert "Domains: none" in context


def test_codex_posttool_apply_patch_records_files_and_emits_json_context(tmp_path):
    target = _init_instance(tmp_path)
    script = target / ".codex" / "hooks" / "post-tool-edit.py"
    edited = target / "wiki" / "architecture.md"
    added = target / "docs" / "codex.md"
    target_records = target / "records" / "file-edits.jsonl"
    target_records.parent.mkdir(parents=True, exist_ok=True)
    target_records.write_text(
        json.dumps(
            {
                "agent_id": "other-agent",
                "file_path": str(edited),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    patch_command = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: wiki/architecture.md",
            "@@",
            "+updated",
            "*** Add File: docs/codex.md",
            "+new",
            "*** End Patch",
        ]
    )
    result = _run_hook(
        script,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": patch_command},
            "tool_response": {"status": "completed"},
            "session_id": "codex-session",
            "cwd": str(target),
            "agent_id": "codex-agent",
            "model": "gpt-5",
        },
        target,
        {"PYTHONIOENCODING": "cp1252"},
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "文件冲突" in output["hookSpecificOutput"]["additionalContext"]
    records = [
        json.loads(line)
        for line in target_records.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {record["file_path"] for record in records[-2:]} == {
        str(edited),
        str(added),
    }


def test_codex_pretooluse_blocks_invalid_added_wiki_patch(tmp_path):
    target = _init_instance(tmp_path)
    script = target / ".codex" / "hooks" / "validate-wiki-write.sh"
    shell_python = sys.executable.replace("\\", "/")
    baked_python = f'${{OKS_PYTHON:-{shell_python}}}'
    assert baked_python in script.read_text(encoding="utf-8")
    invalid_patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: wiki/invalid.md",
            "+# Missing frontmatter",
            "*** End Patch",
        ]
    )
    blocked = _run_hook(
        script,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": invalid_patch},
            "cwd": str(target),
        },
        target,
    )
    assert blocked.returncode == 2
    assert "frontmatter" in blocked.stderr

    valid_patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: wiki/valid.md",
            "+---",
            "+title: Valid",
            "+type: concept",
            "+area: computing",
            "+---",
            "+",
            "+# Valid",
            "*** End Patch",
        ]
    )
    allowed = _run_hook(
        script,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": valid_patch},
            "cwd": str(target),
        },
        target,
    )
    assert allowed.returncode == 0, allowed.stderr

    legacy = _run_hook(
        script,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "wiki/legacy.md",
                "content": "# Missing frontmatter",
            },
            "cwd": str(target),
        },
        target,
    )
    assert legacy.returncode == 2
    assert "frontmatter" in legacy.stderr

    existing = target / "wiki" / "updated.md"
    existing.write_text(
        "---\ntitle: Existing\ntype: concept\narea: computing\n---\n\n# Existing\n",
        encoding="utf-8",
    )
    invalid_update = _run_hook(
        script,
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "\n".join(
                    [
                        "*** Begin Patch",
                        "*** Update File: wiki/updated.md",
                        "@@",
                        "-title: Existing",
                        "+type: concept",
                        "*** End Patch",
                    ]
                )
            },
            "cwd": str(target),
        },
        target,
    )
    assert invalid_update.returncode == 2
    assert "title" in invalid_update.stderr


def test_codex_precompact_emits_json_system_message_and_saves_snapshot(tmp_path):
    target = _init_instance(tmp_path)
    script = target / ".codex" / "hooks" / "pre-compact.sh"
    shell_python = sys.executable.replace("\\", "/")
    baked_python = f'${{OKS_PYTHON:-{shell_python}}}'
    assert baked_python in script.read_text(encoding="utf-8")
    result = _run_hook(
        script,
        {
            "hook_event_name": "PreCompact",
            "session_id": "codex-session",
            "cwd": str(target),
            "model": "gpt-5",
        },
        target,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["systemMessage"].startswith("Snapshot saved:")
    assert list((target / ".oks" / "snapshots").glob("pre-compact-*.md"))

    legacy = _run_hook(
        script,
        {
            "hook_event_name": "PreCompact",
            "session_id": "claude-session",
            "cwd": str(target),
        },
        target,
    )
    assert legacy.returncode == 0, legacy.stderr
    assert legacy.stdout.startswith("Snapshot saved:")


def test_non_codex_posttool_keeps_plain_text_conflict_output(tmp_path):
    target = _init_instance(tmp_path)
    script = target / ".codex" / "hooks" / "post-tool-edit.py"
    edited = target / "wiki" / "legacy.md"
    records = target / "records" / "file-edits.jsonl"
    records.parent.mkdir(parents=True, exist_ok=True)
    records.write_text(
        json.dumps(
            {
                "agent_id": "other-agent",
                "file_path": str(edited),
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run_hook(
        script,
        {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(edited)},
            "session_id": "claude-session",
            "cwd": str(target),
            "agent_id": "claude-agent",
        },
        target,
        {"PYTHONIOENCODING": "cp1252"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("[oks] 文件冲突:")
    assert not result.stdout.startswith("{")


def test_hook_recall_cli_reuses_policy_and_history_without_prompt_leakage(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_HOOK_DIAGNOSTICS", "1")
    # Reproduce Windows runners whose child stdout defaults to a legacy
    # ``charmap`` encoding. The structured bridge must remain ASCII-safe.
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    target = _init_instance(tmp_path)
    page = target / "wiki" / "computing" / "concepts" / "recall-bridge.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "title: Recall bridge\n"
        "type: concept\n"
        "area: architecture\n"
        "status: active\n"
        "importance: 0.9\n"
        "confidence: 0.9\n"
        "created: 2026-08-20T00:00:00+00:00\n"
        "tags: recall, bridge, architecture\n"
        "pinned: false\n"
        "archived: false\n"
        "access_count: 0\n"
        "---\n\n"
        "The recall bridge keeps DSH as a thin adapter over OKS policy.\n",
        encoding="utf-8",
    )
    # The Hook contract is independent of an optional FTS index. Exercise the
    # deterministic native backend here; FTS lifecycle has its own test suite.
    recall_config = target / "settings" / "recall.yaml"
    recall_config.write_text(
        recall_config.read_text(encoding="utf-8").replace("search_backend: fts5", "search_backend: native"),
        encoding="utf-8",
    )
    args = [
        "hook", "recall", "recall bridge architecture", "--format", "json",
        "--path", str(target), "--session-id", "dsh-oks", "--cwd", "C:/dsh-host",
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    assert payload["schema"] == "hook-recall-response/v1"
    assert payload["status"] == "injected", {
        "reason": payload.get("reason"),
        "diagnostic": payload.get("diagnostic"),
    }
    assert payload["trace"]["matches"] == ["recall-bridge"], payload
    assert "recall bridge architecture" not in json.dumps(payload)

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["status"] == "skipped_cooldown"

    history = runner.invoke(
        app,
        [
            "hook", "history", "--format", "json", "--path", str(target),
            "--session-id", "dsh-oks", "--cwd", "C:/dsh-host",
        ],
    )
    assert history.exit_code == 0, history.output
    records = json.loads(history.output)
    assert records["schema"] == "hook-recall-history/v1"
    assert records["items"][0]["matches"] == ["recall-bridge"]
    assert "C:/dsh-host" not in history.output


def test_hook_recall_cli_forces_utf8_for_chinese_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv("PYTHONUTF8", "0")
    target = _init_instance(tmp_path)
    page = target / "wiki" / "computing" / "concepts" / "promotion-declaration.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\n"
        "title: 晋升技术申报书\n"
        "type: concept\n"
        "area: architecture\n"
        "status: active\n"
        "importance: 0.9\n"
        "confidence: 0.9\n"
        "created: 2026-08-20T00:00:00+00:00\n"
        "tags: 晋升, 技术申报书\n"
        "pinned: false\n"
        "archived: false\n"
        "access_count: 0\n"
        "---\n\n"
        "晋升 Wiki 可以帮助生成技术申报书。\n",
        encoding="utf-8",
    )
    recall_config = target / "settings" / "recall.yaml"
    recall_config.write_text(
        recall_config.read_text(encoding="utf-8").replace("search_backend: fts5", "search_backend: native"),
        encoding="utf-8",
    )

    result = hook_service._run_hook_recall(
        target,
        "请基于晋升 Wiki 生成技术申报书",
        "dsh-oks",
        "C:/dsh-host",
        "dsh-oks",
    )

    assert result["status"] == "injected", result
    assert result["trace"]["candidate_count"] >= 1, result
    assert "晋升技术申报书" in result["context"]


def test_hook_recall_cli_forces_utf8_child_environment(tmp_path, monkeypatch):
    target = _init_instance(tmp_path)
    captured = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({
            "schema": "hook-recall-response/v1",
            "status": "skipped_minlen",
            "context": "",
            "trace": {"candidate_count": 0, "matches": [], "top_relevance": None, "threshold": None},
        })

    def fake_run(*args, **kwargs):
        captured.update(kwargs["env"])
        return Completed()

    monkeypatch.setattr(hook_service.subprocess, "run", fake_run)
    result = hook_service._run_hook_recall(target, "中文提示", "session", "C:/host", "dsh-oks")

    assert result["status"] == "skipped_minlen"
    assert captured["PYTHONIOENCODING"] == "utf-8"
    assert captured["PYTHONUTF8"] == "1"


def test_hook_recall_cli_rejects_malformed_success_envelope(tmp_path, monkeypatch):
    target = _init_instance(tmp_path)

    class Completed:
        returncode = 0
        stdout = json.dumps({
            "schema": "hook-recall-response/v1",
            "status": "invalid",
            "context": 123,
            "trace": None,
        })

    monkeypatch.setattr(hook_service.subprocess, "run", lambda *args, **kwargs: Completed())
    result = hook_service._run_hook_recall(target, "safe prompt", "session", "C:/host", "dsh-oks")

    assert result == {
        "schema": "hook-recall-response/v1",
        "status": "error",
        "context": "",
        "trace": {"candidate_count": 0, "matches": [], "top_relevance": None, "threshold": None},
        "reason": "hook_bridge_failed",
    }


def test_hook_recall_diagnostics_are_opt_in(tmp_path, monkeypatch):
    target = _init_instance(tmp_path)

    class Completed:
        returncode = 7
        stdout = ""
        stderr = "child hook failed: import error"

    monkeypatch.setattr(hook_service.subprocess, "run", lambda *args, **kwargs: Completed())
    without_diagnostics = hook_service._run_hook_recall(
        target, "safe prompt", "session", "C:/host", "dsh-oks"
    )
    assert "diagnostic" not in without_diagnostics

    monkeypatch.setenv("OKS_HOOK_DIAGNOSTICS", "1")
    with_diagnostics = hook_service._run_hook_recall(
        target, "safe prompt", "session", "C:/host", "dsh-oks"
    )
    assert with_diagnostics["diagnostic"] == (
        "RuntimeError: hook exited 7: child hook failed: import error"
    )


def _selected_task_for_continue(target, workspace, monkeypatch, *, feedback_scope=None):
    from knowledge_studio import tasks

    monkeypatch.setenv("OKS_TASK_HOME", str(target.parent / "task-bindings"))
    tasks.start(target, "continue-report", "profiles/goals/report.md", [])
    if feedback_scope:
        tasks.select(target, workspace, "continue-report", feedback_scope["subject"], feedback_scope["project"])
    else:
        tasks.select(target, workspace, "continue-report")


def _private_feedback_for_continue(target, monkeypatch, *, operation):
    from knowledge_studio import feedback, handoff

    scope = {"subject": "reviewer-a", "project": "reporting", "task": "continue-report"}
    asset = target / "wiki/computing/strategies/continue-policy.md"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text(
        "---\ntitle: Continue policy\ntype: strategy\narea: computing\nstatus: active\n"
        "human_reviewed_at: '2026-10-27'\noptions: []\n---\nPolicy body.\n",
        encoding="utf-8",
    )
    agreement = handoff.prepare(target, "profiles/goals/report.md", [], scope["task"])
    monkeypatch.setenv("OKS_FEEDBACK_HOME", str(target.parent / "private-feedback"))
    request = {"scope": scope, "event_id": "adopted-1", "action": "adopted",
               "reason": "Private rationale", "agreement": agreement,
               "asset_path": "wiki/computing/strategies/continue-policy.md"}
    feedback.record(target, request)
    candidate = feedback.propose(target, {"scope": scope, "candidate_id": "candidate-1",
        "event_ids": ["adopted-1"], "title": "Private candidate title",
        "summary": "PRIVATE_REQUIREMENT_BODY"})
    feedback.review(target, {"scope": scope, "candidate_id": "candidate-1", "decision": "approve",
        "expected_revision": candidate["revision"], "comment": "Reviewed"})
    if operation == "withdraw":
        feedback.withdraw(target, {"scope": scope, "event_id": "adopted-1"})
    elif operation == "conflict":
        feedback.record(target, {**request, "event_id": "rejected-1", "action": "rejected",
                                  "reason": "Opposite choice"})
    return scope


def _continue_hook(target, monkeypatch, *, session, extra_env=None):
    config = target / "settings/recall.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\ndebug_record: true\n", encoding="utf-8")
    monkeypatch.delenv("OKS_FEEDBACK_SUBJECT", raising=False)
    monkeypatch.delenv("OKS_FEEDBACK_PROJECT", raising=False)
    monkeypatch.delenv("OKS_TASK_AGREEMENT", raising=False)
    monkeypatch.delenv("OKS_TASK_SCOPE", raising=False)
    env = {"OKS_HOOK_OUTPUT": "json", "OKS_HOOK_DIAGNOSTICS": "1",
           "OKS_TASK_HOME": os.environ["OKS_TASK_HOME"], "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if extra_env:
        env.update(extra_env)
    result = _run_hook(target / ".codex/hooks/user-prompt-recall.py",
        {"prompt": "继续", "session_id": session, "cwd": str(target)}, target, env)
    assert result.returncode == 0, result.stderr
    debug_path = target / ".oks/retrieval-debug.json"
    assert debug_path.is_file(), result.stdout + result.stderr
    return json.loads(result.stdout), json.loads(debug_path.read_text(encoding="utf-8"))


def test_short_continue_warns_on_stale_task_without_old_goal_or_private_text(tmp_path, monkeypatch):
    from knowledge_studio import tasks

    target = _init_instance(tmp_path)
    (target / "profiles/goals/report.md").write_text(
        "---\ntype: goal\ntitle: Private old goal\nstatus: active\n---\nPRIVATE_OLD_GOAL_BODY\n",
        encoding="utf-8",
    )
    _selected_task_for_continue(target, target, monkeypatch)
    goal = target / "profiles/goals/report.md"
    goal.write_text(goal.read_text(encoding="utf-8") + "Changed requirement.\n", encoding="utf-8")

    response, records = _continue_hook(target, monkeypatch, session="stale-continue")

    assert response["status"] == "injected"
    assert "needs_review" in response["context"]
    assert "source_changed" in response["context"]
    assert "profiles/goals/report.md" in response["context"]
    assert "oks task show --task-id continue-report" in response["context"]
    assert "PRIVATE_OLD_GOAL_BODY" not in response["context"]
    assert "Private old goal" not in response["context"]
    assert tasks.show(target, "continue-report")["revision"] == 1
    diagnostic = records[-1]["diagnostics"]["task_warning"]
    assert diagnostic["status"] == "needs_review"
    assert diagnostic["issues"] == [{"code": "source_changed", "path": "profiles/goals/report.md"}]


@pytest.mark.parametrize("operation,expected", [("withdraw", "invalidated"), ("conflict", "conflicting_feedback")])
def test_short_continue_aggregates_withdrawn_or_conflicting_feedback(tmp_path, monkeypatch, operation, expected):
    target = _init_instance(tmp_path)
    (target / "profiles/goals/report.md").write_text(
        "---\ntype: goal\ntitle: Report\nstatus: active\n---\nKeep citations.\n", encoding="utf-8")
    scope = _private_feedback_for_continue(target, monkeypatch, operation=operation)
    _selected_task_for_continue(target, target, monkeypatch, feedback_scope=scope)

    response, records = _continue_hook(target, monkeypatch, session=f"feedback-{operation}", extra_env={
        "OKS_FEEDBACK_HOME": os.environ["OKS_FEEDBACK_HOME"]})

    assert response["status"] == "injected"
    assert "本任务反馈提示" in response["context"]
    assert "PRIVATE_REQUIREMENT_BODY" not in response["context"]
    assert "Private candidate title" not in response["context"]
    assert expected in records[-1]["diagnostics"]["task_context"]["excluded_counts"]
    assert records[-1]["diagnostics"]["task_warning"]["status"] == "feedback_excluded"
    assert scope["subject"] not in response["context"]
    assert scope["project"] not in response["context"]


def test_short_continue_without_feedback_selection_emits_no_private_warning(tmp_path, monkeypatch):
    target = _init_instance(tmp_path)
    (target / "profiles/goals/report.md").write_text(
        "---\ntype: goal\ntitle: Report\nstatus: active\n---\nKeep citations.\n", encoding="utf-8")
    _private_feedback_for_continue(target, monkeypatch, operation="withdraw")
    _selected_task_for_continue(target, target, monkeypatch)
    monkeypatch.delenv("OKS_FEEDBACK_HOME", raising=False)

    response, records = _continue_hook(target, monkeypatch, session="unselected-feedback")

    assert response["status"] == "injected"
    assert "本任务反馈提示" not in response["context"]
    assert "PRIVATE_REQUIREMENT_BODY" not in response["context"]
    diagnostics = records[-1]["diagnostics"]
    assert diagnostics["task_context"]["status"] == "not_requested"
    assert "task_warning" not in diagnostics


@pytest.mark.skipif(os.name == "nt", reason="native Windows wires the .py engine; the .sh wrapper bake contract is POSIX-scoped")
def test_hook_install_refreshes_an_outdated_wrapper_body(tmp_path):
    """A correct bake must not shield an old wrapper body from an upstream fix."""
    target = _init_instance(tmp_path)
    args = ["hook", "install", "--editor", "codex", "--path", str(target)]
    assert runner.invoke(app, args).exit_code == 0
    wrapper = target / ".codex" / "hooks" / "user-prompt-recall.sh"
    baked = f'"${{OKS_PYTHON:-{sys.executable}}}"'
    wrapper.write_text(
        f"#!/usr/bin/env bash\nexec {baked} \"$(dirname \"$0\")\"/x.py 2>/dev/null\n",
        encoding="utf-8",
    )

    assert runner.invoke(app, args).exit_code == 0

    refreshed = wrapper.read_text(encoding="utf-8")
    assert "exec " not in refreshed
    assert baked in refreshed
    bundled = (resources.asset_root() / "hooks" / "user-prompt-recall.sh").read_text(
        encoding="utf-8"
    )
    assert refreshed == bundled.replace('"${OKS_PYTHON:-python3}"', baked)


def test_hook_install_refreshes_a_differing_engine(tmp_path):
    """Hook engines are baked runtime, not a customization surface.

    An installed engine that drifted from the bundled asset (stale protocol or
    local edit) is refreshed by the next `hook install`, and `hook status`
    then reports it as current — protocol fixes must reach old instances.
    """
    target = _init_instance(tmp_path)
    assert runner.invoke(
        app, ["hook", "install", "--editor", "codex", "--path", str(target)]
    ).exit_code == 0
    engine = target / ".codex" / "hooks" / "user-prompt-recall.py"
    engine.write_text(engine.read_text(encoding="utf-8") + "# local edit\n", encoding="utf-8")

    assert runner.invoke(
        app, ["hook", "install", "--editor", "codex", "--path", str(target)]
    ).exit_code == 0
    assert "# local edit" not in engine.read_text(encoding="utf-8")

    result = runner.invoke(app, ["hook", "status", "--path", str(target)])
    assert result.exit_code == 0, result.output
    assert "cannot inject context" not in result.output


def test_recall_wrapper_surfaces_engine_failure_and_still_exits_zero(tmp_path):
    """A crashed engine must be visible, and must never block the prompt."""
    target = _init_instance(tmp_path)
    script = target / ".claude" / "hooks" / "user-prompt-recall.sh"

    result = _run_hook(
        script,
        {"prompt": "wrapper failure probe", "session_id": "s1", "cwd": str(target)},
        target,
        env_overrides={"OKS_PYTHON": str(tmp_path / "no-such-python")},
    )

    assert result.returncode == 0
    assert "recall engine exited" in result.stderr
    assert "oks hook install" in result.stderr


def test_init_upgrade_refreshes_engines_without_unwiring_hooks(tmp_path):
    """`hook status` sends users to --upgrade, so it must not drop the wiring."""
    target = _init_instance(tmp_path)
    assert runner.invoke(
        app, ["hook", "install", "--editor", "codex", "--path", str(target)]
    ).exit_code == 0
    engine = target / ".codex" / "hooks" / "user-prompt-recall.py"
    engine.write_text("# stale\n", encoding="utf-8")
    before = (target / ".codex" / "hooks.json").read_text(encoding="utf-8")
    assert _codex_commands(_load_codex_hooks(target), "UserPromptSubmit")

    assert runner.invoke(
        app, ["init", str(target), "--no-git", "--no-set-default", "--upgrade"]
    ).exit_code == 0

    assert engine.read_text(encoding="utf-8") != "# stale\n"
    assert (target / ".codex" / "hooks.json").read_text(encoding="utf-8") == before
    assert _codex_commands(_load_codex_hooks(target), "UserPromptSubmit")


@pytest.mark.skipif(os.name == "nt", reason="native Windows wires the .py engine; the .sh wrapper bake contract is POSIX-scoped")
def test_init_upgrade_keeps_the_baked_interpreter(tmp_path):
    """Refreshing the wrapper body must not reset OKS_PYTHON to bare python3.

    `python3` cannot import knowledge_studio on a pipx/venv install, so losing
    the bake turns the upgrade into a silent hook outage.
    """
    target = _init_instance(tmp_path)
    assert runner.invoke(
        app, ["hook", "install", "--editor", "codex", "--path", str(target)]
    ).exit_code == 0
    baked = f"${{OKS_PYTHON:-{sys.executable}}}"
    wrappers = [
        target / ".codex" / "hooks" / name
        for name in ("user-prompt-recall.sh", "post-tool-edit.sh")
    ]
    for wrapper in wrappers:
        assert baked in wrapper.read_text(encoding="utf-8")
    # Force a body refresh so the copy actually happens.
    wrappers[0].write_text(f'#!/usr/bin/env bash\n"{baked}" old\n', encoding="utf-8")

    assert runner.invoke(
        app, ["init", str(target), "--no-git", "--no-set-default", "--upgrade"]
    ).exit_code == 0

    for wrapper in wrappers:
        body = wrapper.read_text(encoding="utf-8")
        assert baked in body, body
        assert "${OKS_PYTHON:-python3}" not in body
