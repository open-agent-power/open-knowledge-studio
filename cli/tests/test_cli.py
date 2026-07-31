"""Tests for CLI platform compatibility helpers."""

from datetime import date
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
