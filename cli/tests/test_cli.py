"""Tests for CLI platform compatibility helpers and config commands."""

from datetime import date
import json
from pathlib import Path
import subprocess
import sys

import pytest
from typer.testing import CliRunner


def test_cli_version_defers_unused_command_dependencies():
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", "-c", """
import sys
from typer.testing import CliRunner
from knowledge_studio.cli import app

result = CliRunner().invoke(app, ["--version"])
assert result.exit_code == 0, result.output
assert result.output.startswith("oks ")
unused = {"rich.markdown", "oks_connector.raw_bundle_adapter",
          "knowledge_studio.recall", "knowledge_studio.workbuddy"}
assert not unused.intersection(sys.modules), unused.intersection(sys.modules)
"""],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_recall_command_reads_parameters_once_and_preserves_legacy_warning(tmp_path, monkeypatch):
    from knowledge_studio import recall as engine
    from knowledge_studio.cli import app

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    monkeypatch.setenv("OKS_RECALL_TOPN", "5")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "policy.md").write_text(
        "---\ntitle: Quasar\ntype: concept\narea: computing\n---\nquasar policy",
        encoding="utf-8",
    )
    load = engine.load_recall_params
    reads = []

    def load_params(*args, **kwargs):
        reads.append(None)
        return load(*args, **kwargs)

    load_params._warned = False
    monkeypatch.setattr(engine, "load_recall_params", load_params)
    result = CliRunner().invoke(app, [
        "recall", "quasar", "--goal", "none", "--no-task", "--knowledge-only",
        "--search-backend", "native", "--format", "json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["knowledge"]
    assert len(reads) == 1
    assert result.stderr.count("OKS_RECALL_TOPN") == 1


def _make_vfs_instance(root: Path) -> None:
    (root / "wiki").mkdir()
    (root / "wiki/page.md").write_text("# Page\nneedle here\n", encoding="utf-8")


def test_fs_ls_json_contract(tmp_path, monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _make_vfs_instance(tmp_path)

    result = CliRunner().invoke(
        cli.app, ["fs", "ls", "oks://wiki/", "--format", "json"]
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["schema_version"] == "oks-fs-response/v1"
    assert payload["operation"] == "ls"
    assert payload["uri"] == "oks://wiki/"
    assert payload["result"]["entries"][0]["uri"] == "oks://wiki/page.md"


@pytest.mark.parametrize(
    ("command", "args", "result_key"),
    [
        ("tree", ["oks://wiki/", "--depth", "1"], "entries"),
        ("stat", ["oks://wiki/page.md"], "type"),
        ("read", ["oks://wiki/page.md", "--limit", "4"], "content"),
        ("overview", ["oks://wiki/"], "counts"),
        ("find", ["needle", "--under", "oks://wiki/"], "matches"),
    ],
)
def test_fs_commands_share_json_envelope(
    tmp_path, monkeypatch, command, args, result_key
):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _make_vfs_instance(tmp_path)

    result = CliRunner().invoke(cli.app, ["fs", command, *args, "--format", "json"])
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["schema_version"] == "oks-fs-response/v1"
    assert payload["operation"] == command
    assert payload["uri"].startswith("oks://wiki/")
    assert result_key in payload["result"]


def test_fs_read_many_json_contract(tmp_path, monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _make_vfs_instance(tmp_path)
    (tmp_path / "wiki/second.md").write_text("second", encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        [
            "fs",
            "read-many",
            "oks://wiki/page.md",
            "oks://wiki/second.md",
            "--limit",
            "6",
            "--max-total-chars",
            "9",
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 0
    assert payload["operation"] == "read-many"
    assert payload["uri"] == "oks://"
    assert [item["uri"] for item in payload["result"]["items"]] == [
        "oks://wiki/page.md",
        "oks://wiki/second.md",
    ]
    assert payload["result"]["returned_chars"] == 9
    assert payload["result"]["truncated"] is True


def test_fs_error_json_hides_physical_path(tmp_path, monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    result = CliRunner().invoke(
        cli.app,
        ["fs", "read", "oks://settings/recall.yaml", "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert result.exit_code == 2
    assert payload["error"]["code"] == "UNSUPPORTED_SCOPE"
    assert str(tmp_path) not in result.stdout


def test_fs_text_output_includes_uri_and_truncation(tmp_path, monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    _make_vfs_instance(tmp_path)
    result = CliRunner().invoke(
        cli.app,
        ["fs", "read", "oks://wiki/page.md", "--limit", "4"],
    )

    assert result.exit_code == 0
    assert "oks://wiki/page.md" in result.stdout
    assert "truncated" in result.stdout.lower()


@pytest.mark.parametrize("command", ["write", "mkdir", "mv", "rm", "cp"])
def test_fs_has_no_mutating_commands(tmp_path, monkeypatch, command):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    sentinel = tmp_path / "sentinel.md"
    sentinel.write_text("unchanged", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["fs", command])

    assert result.exit_code != 0
    assert "No such command" in result.output
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


class _FakeStream:
    encoding = "gbk"

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_configure_utf8_stdio_on_windows(monkeypatch):
    from knowledge_studio import cli

    stdout = _FakeStream()
    stderr = _FakeStream()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    cli._configure_utf8_stdio()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


@pytest.mark.parametrize(
    ("source", "capability"),
    [
        ("notes.md", "document"),
        ("notes.txt", "document"),
        ("video.mp4", "watch"),
        ("paper.pdf", "pdf-lite"),
    ],
)
def test_recommended_capability_routes_supported_local_files(source, capability):
    from knowledge_studio import cli

    assert cli._recommended_capability(source) == capability


def test_drafts_list_renders_yaml_date(monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setattr(
        cli.store,
        "list_drafts",
        lambda: [
            {
                "slug": "dated-draft",
                "title": "Dated draft",
                "draft_type": "strategy",
                "draft_area": "computing",
                "drafted_at": date(2026, 7, 28),
            }
        ],
    )

    result = CliRunner().invoke(cli.app, ["drafts", "list"])

    assert result.exit_code == 0
    assert "dated-draft" in result.stdout
    assert "2026-07-28" in result.stdout


def test_drafts_get_prints_exact_candidate_markdown(tmp_path, monkeypatch):
    from knowledge_studio import cli

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "candidate-one.md"
    draft.parent.mkdir()
    source = """---
title: Candidate one
draft_type: concept
draft_area: computing
status: pending
source_bundle: raw/example
---

# Candidate body

Keep the provenance visible during review.
"""
    draft.write_text(source, encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["drafts", "get", "candidate-one"])

    assert result.exit_code == 0
    assert result.stdout == source


def test_drafts_promote_accepts_review_overrides(tmp_path, monkeypatch):
    from knowledge_studio import cli
    from knowledge_studio import store

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "candidate-one.md"
    draft.parent.mkdir()
    draft.write_text(
        """---
title: Candidate one 待审核
draft_type: concept
draft_area: computing
status: pending
---

Reviewed body.
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli.app,
        [
            "drafts",
            "promote",
            "candidate-one",
            "--title",
            "Candidate one",
            "--type",
            "strategy",
            "--area",
            "computing",
            "--slug-hint",
            "candidate-one-reviewed",
            "--tag",
            "kimi",
            "--tag",
            "reviewed",
        ],
    )

    assert result.exit_code == 0, result.stdout
    pages = store.list_wiki_pages()
    assert len(pages) == 1
    page = pages[0]
    assert page is not None
    assert page["title"] == "Candidate one"
    assert page["type"] == "strategy"
    assert page["area"] == "computing"
    assert page["tags"] == "kimi, reviewed"
    assert page["human_reviewed_at"]


# ── Strategy config round-trip ────────────────────────────────────

_MOCK_STRATEGY_STORE: dict = {}


@pytest.fixture
def _isolate_config(monkeypatch):
    """Prevent strategy config tests from touching the real ~/.oks/config.json."""
    import knowledge_studio.config as _cfg

    _MOCK_STRATEGY_STORE.clear()
    monkeypatch.setattr(_cfg, "config_path", lambda: Path("/tmp/__oks_test_config__.json"))
    monkeypatch.setattr(_cfg, "load_config", lambda: dict(_cfg.DEFAULT_CONFIG, **_MOCK_STRATEGY_STORE))

    def _mock_save(config_dict):
        _MOCK_STRATEGY_STORE.clear()
        _MOCK_STRATEGY_STORE.update(config_dict)

    monkeypatch.setattr(_cfg, "save_config", _mock_save)


def test_config_show_displays_strategy(_isolate_config):
    from knowledge_studio import cli

    _MOCK_STRATEGY_STORE["strategy"] = "lightweight"
    result = CliRunner().invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    assert "lightweight" in result.stdout
    assert "Strategy" in result.stdout


def test_config_show_strategy_unset(_isolate_config):
    from knowledge_studio import cli

    _MOCK_STRATEGY_STORE.pop("strategy", None)
    result = CliRunner().invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0
    assert "(not set)" in result.stdout


def test_config_set_strategy_valid(_isolate_config):
    from knowledge_studio import cli

    result = CliRunner().invoke(cli.app, ["config", "set", "strategy", "lightweight"])
    assert result.exit_code == 0
    assert "lightweight" in result.stdout
    assert _MOCK_STRATEGY_STORE.get("strategy") == "lightweight"


def test_config_set_strategy_invalid_rejected(_isolate_config):
    from knowledge_studio import cli

    result = CliRunner().invoke(cli.app, ["config", "set", "strategy", "nonsense"])
    assert result.exit_code != 0
    assert "nonsense" not in _MOCK_STRATEGY_STORE.get("strategy", "")


@pytest.mark.parametrize("value", ["lightweight", "quality", "privacy", "ask_each_time"])
def test_config_set_all_valid_strategies(_isolate_config, value):
    from knowledge_studio import cli

    result = CliRunner().invoke(cli.app, ["config", "set", "strategy", value])
    assert result.exit_code == 0
    assert _MOCK_STRATEGY_STORE.get("strategy") == value


def test_strategy_round_trip(_isolate_config):
    """Set strategy → config show displays it → set invalid → rejected."""
    from knowledge_studio import cli

    r1 = CliRunner().invoke(cli.app, ["config", "set", "strategy", "privacy"])
    assert r1.exit_code == 0

    r2 = CliRunner().invoke(cli.app, ["config", "show"])
    assert r2.exit_code == 0
    assert "privacy" in r2.stdout

    r3 = CliRunner().invoke(cli.app, ["config", "set", "strategy", "invalid_strategy"])
    assert r3.exit_code != 0

    # Value should still be 'privacy' after failed set
    assert _MOCK_STRATEGY_STORE.get("strategy") == "privacy"
