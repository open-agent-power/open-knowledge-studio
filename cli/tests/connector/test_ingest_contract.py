import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from oks_connector import raw_bundle_adapter as adapter


def _args(source: str, output: Path, *, mode: str = "quick") -> argparse.Namespace:
    return argparse.Namespace(
        source=source,
        output=output,
        mode=mode,
        subtitle_langs="zh,en",
        timeout_seconds=30,
        progress=False,
        title=None,
        overwrite=False,
    )


def test_quick_local_video_keeps_local_asr_available(tmp_path):
    args = _args(str(tmp_path / "clip.mp4"), tmp_path / "bundle")
    plan = {"extractor": "watch", "source_type": "video"}

    command = adapter.ingest_child_argv(args, plan, args.output, Path("python"))

    assert "--transcript-only" in command
    assert "--no-local-whisper" not in command


def test_quick_platform_video_can_remain_caption_only(tmp_path):
    args = _args("https://www.youtube.com/watch?v=example", tmp_path / "bundle")
    plan = {"extractor": "watch", "source_type": "video"}

    command = adapter.ingest_child_argv(args, plan, args.output, Path("python"))

    assert "--no-local-whisper" in command


def test_run_ingest_rejects_child_bundle_marked_failed(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "metadata.json").write_text(
        json.dumps({"processing_status": "failed"}), encoding="utf-8"
    )
    args = _args(str(source), output)

    monkeypatch.setattr(
        adapter,
        "route_plan",
        lambda _source: {"extractor": "watch", "source_type": "video", "platform": "local"},
    )
    monkeypatch.setattr(adapter, "_extractor_python", lambda _extractor: Path("python"))
    monkeypatch.setattr(adapter, "_ffprobe_preflight", lambda *_args: None)
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    with pytest.raises(RuntimeError, match="processing_status=failed"):
        adapter.run_ingest(args)


def test_run_ingest_accepts_partial_child_bundle(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "metadata.json").write_text(
        json.dumps({"processing_status": "partial"}), encoding="utf-8"
    )
    args = _args(str(source), output)

    monkeypatch.setattr(
        adapter,
        "route_plan",
        lambda _source: {"extractor": "watch", "source_type": "video", "platform": "local"},
    )
    monkeypatch.setattr(adapter, "_extractor_python", lambda _extractor: Path("python"))
    monkeypatch.setattr(adapter, "_ffprobe_preflight", lambda *_args: None)
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    assert adapter.run_ingest(args) == 0


def test_run_ingest_timeout_preserves_partial_result(tmp_path, monkeypatch, capsys):
    source = tmp_path / "notes.md"
    source.write_text("Source text", encoding="utf-8")
    args = _args(str(source), tmp_path / "bundle")
    monkeypatch.setattr(adapter, "_extractor_python", lambda extractor: Path("python"))

    def timeout(command, **kwargs):
        assert kwargs["timeout"] == 30
        raise adapter.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(adapter.subprocess, "run", timeout)

    assert adapter.run_ingest(args) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "partial"
    assert result["error"]["code"] == "EXTRACTION_TIMEOUT"


def test_ingest_parser_preserves_connector_defaults_and_mode_aliases():
    for mode in ("quick", "forensic", "fast", "full"):
        args = adapter.build_parser().parse_args(["ingest", "paper.pdf", "--mode", mode])
        assert args.progress is False
        assert args.formula_secondary is False
        assert args.formula_max_regions == 20
        assert args.timeout_seconds is None
        assert adapter.ingest_timeout_seconds(args, "mineru") == 900
