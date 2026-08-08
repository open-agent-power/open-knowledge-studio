"""Tests for CLI platform compatibility helpers and config commands."""

from pathlib import Path
import sys

import pytest
from typer.testing import CliRunner


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
        ("paper.pdf", "pdf"),
    ],
)
def test_recommended_capability_routes_supported_local_files(source, capability):
    from knowledge_studio import cli

    assert cli._recommended_capability(source) == capability


# ?? Strategy config round-trip ????????????????????????????????????

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
    """Set strategy ? config show displays it ? set invalid ? rejected."""
    from knowledge_studio import cli

    r1 = CliRunner().invoke(cli.app, ["config", "set", "strategy", "privacy"])
    assert r1.exit_code == 0

    r2 = CliRunner().invoke(cli.app, ["config", "show"])
    assert r2.exit_code == 0
    assert "privacy" in r2.stdout

    r3 = CliRunner().invoke(cli.app, ["config", "set", "strategy", "invalid_strategy"])
    assert r3.exit_code != 0

    assert _MOCK_STRATEGY_STORE.get("strategy") == "privacy"
