import importlib.util
import io
import json
import sys
import tomllib
import zipfile
import subprocess
from argparse import Namespace
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

import pytest


import os
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[1])
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

MODULE_PATH = Path(__file__).parents[1] / "raw_bundle_adapter.py"
SPEC = importlib.util.spec_from_file_location("raw_bundle_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)

IMAGE_PATH = Path(__file__).parents[1] / "extractors" / "image.py"
_IMG_SPEC = importlib.util.spec_from_file_location("extractors.image", IMAGE_PATH)
assert _IMG_SPEC and _IMG_SPEC.loader
image_module = importlib.util.module_from_spec(_IMG_SPEC)
_IMG_SPEC.loader.exec_module(image_module)

MINERU_PATH = Path(__file__).parents[1] / "extractors" / "mineru.py"
_MIN_SPEC = importlib.util.spec_from_file_location("extractors.mineru", MINERU_PATH)
assert _MIN_SPEC and _MIN_SPEC.loader
mineru_module = importlib.util.module_from_spec(_MIN_SPEC)
_MIN_SPEC.loader.exec_module(mineru_module)

MD_PATH = Path(__file__).parents[1] / "extractors" / "markitdown.py"
_MD_SPEC = importlib.util.spec_from_file_location("extractors.markitdown", MD_PATH)
assert _MD_SPEC and _MD_SPEC.loader
markitdown_module = importlib.util.module_from_spec(_MD_SPEC)
_MD_SPEC.loader.exec_module(markitdown_module)

WATCH_PATH = Path(__file__).parents[1] / "extractors" / "watch.py"
_W_SPEC = importlib.util.spec_from_file_location("extractors.watch", WATCH_PATH)
assert _W_SPEC and _W_SPEC.loader
watch_module = importlib.util.module_from_spec(_W_SPEC)
_W_SPEC.loader.exec_module(watch_module)


def test_watch_prepends_active_interpreter_bin_to_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/local/bin")
    monkeypatch.setattr(watch_module.sys, "executable", "/isolated/venv/bin/python")

    previous = watch_module.prepend_interpreter_bin_to_path()

    assert previous == "/usr/local/bin"
    assert watch_module.os.environ["PATH"].split(watch_module.os.pathsep)[0] == str(
        Path(watch_module.sys.executable).parent
    )


def test_watch_payload_serializes_dataclass_metadata_and_ocr_blocks(tmp_path):
    @dataclass
    class Metadata:
        title: str

    @dataclass
    class OcrBlock:
        text: str

    frame = SimpleNamespace(
        index=0, timestamp_seconds=0.0, path=tmp_path / "frame.png",
        scene_id="scene-1", phash="abc", reason="sample", ocr_blocks=[OcrBlock("hello")],
    )
    result = SimpleNamespace(
        perception=SimpleNamespace(
            frames=[frame], source="local", engine="test", scene_count=1,
            candidate_count=1, deduped_count=1, focused=False,
            start_seconds=0.0, end_seconds=1.0,
        ),
        acquisition=SimpleNamespace(
            source="sample.mp4", kind="video", video_path=None, subtitle_path=None,
            info={}, from_cache=False, acquirer="local",
        ),
        metadata=Metadata("sample"),
        transcript=SimpleNamespace(source="none", segments=[]),
        start_seconds=0.0,
        end_seconds=1.0,
    )

    payload = watch_module.watch_payload(result)

    assert payload["metadata"] == {"title": "sample"}
    assert payload["perception"]["frames"][0]["ocr_blocks"] == [{"text": "hello"}]

NET_PATH = Path(__file__).parents[1] / "network.py"
_NET_SPEC = importlib.util.spec_from_file_location("network", NET_PATH)
assert _NET_SPEC and _NET_SPEC.loader
network_module = importlib.util.module_from_spec(_NET_SPEC)
_NET_SPEC.loader.exec_module(network_module)

VAL_PATH = Path(__file__).parents[1] / "validator.py"
_VAL_SPEC = importlib.util.spec_from_file_location("validator", VAL_PATH)
assert _VAL_SPEC and _VAL_SPEC.loader
validator_module = importlib.util.module_from_spec(_VAL_SPEC)
_VAL_SPEC.loader.exec_module(validator_module)


def test_default_ingest_output_uses_oks_root_raw(tmp_path, monkeypatch):
    kb = tmp_path / "kb"
    (kb / "wiki").mkdir(parents=True)
    source = tmp_path / "source.txt"
    source.write_text("hello", encoding="utf-8")
    monkeypatch.setenv("OKS_ROOT", str(kb))
    monkeypatch.chdir(tmp_path)

    output = adapter.default_ingest_output(str(source))

    assert output.parent == (kb / "raw").resolve()


def test_default_ingest_output_prefers_current_kb_before_config(tmp_path, monkeypatch):
    configured = tmp_path / "configured"
    current = tmp_path / "current"
    (configured / "wiki").mkdir(parents=True)
    (current / "wiki").mkdir(parents=True)
    config_dir = tmp_path / "home" / ".oks"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps({"knowledge_base_path": str(configured)}),
        encoding="utf-8",
    )
    monkeypatch.delenv("OKS_ROOT", raising=False)
    monkeypatch.setattr(adapter.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(current)

    output = adapter.default_ingest_output("note.txt")

    assert output.parent == (current / "raw").resolve()


def test_capability_env_python_must_import_required_module(tmp_path, monkeypatch):
    import capability_check

    fake_python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("OKS_DOCUMENT_PYTHON", str(fake_python))
    monkeypatch.setattr(capability_check.importlib.util, "find_spec", lambda _module: None)
    monkeypatch.setattr(
        capability_check.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(_args[0], 1),
    )

    assert capability_check.is_capability_available("document") == (False, None)


def test_capability_env_python_is_available_only_after_import_probe(tmp_path, monkeypatch):
    import capability_check

    fake_python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setenv("OKS_DOCUMENT_PYTHON", str(fake_python))
    monkeypatch.setattr(capability_check.importlib.util, "find_spec", lambda _module: None)
    monkeypatch.setattr(
        capability_check.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(_args[0], 0),
    )

    assert capability_check.is_capability_available("document") == (True, fake_python.resolve())


class FakeProbeResponse:
    def __init__(
        self,
        body,
        *,
        url="https://example.com/article",
        content_type="text/html",
        status=200,
    ):
        self._body = io.BytesIO(body)
        self._url = url
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body.read(size)


class FakeProbeOpener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.response


def test_probe_rejects_non_http_and_private_targets():
    invalid = network_module.probe_url("file:///etc/passwd")
    assert invalid["status"] == "failed_final"
    assert invalid["error"]["code"] == "INVALID_URL"

    try:
        network_module.assert_public_network_target("http://127.0.0.1/admin")
    except network_module.ProbeError as exc:
        assert exc.code == "INVALID_URL"
        assert "non-public" in str(exc)
    else:
        raise AssertionError("private target was accepted")


def test_probe_public_html_emits_fetch_receipt():
    body = (
        "<html><body><article>"
        + "Public article text. " * 10
        + "</article></body></html>"
    ).encode()
    opener = FakeProbeOpener(FakeProbeResponse(body))

    receipt = network_module.probe_url(
        "https://example.com/article#section",
        opener=opener,
        resolved_addresses=["93.184.216.34"],
    )

    assert receipt["schema_version"] == adapter.FETCH_RECEIPT_VERSION
    assert receipt["status"] == "ok"
    assert receipt["normalized_url"] == "https://example.com/article"
    assert receipt["next_action"] == "direct_http_snapshot"
    assert receipt["http_status"] == 200
    assert receipt["robots"]["checked"] is False
    assert opener.requests[0][1] == 15.0


def test_probe_delegates_known_platform_without_generic_dns_or_http():
    opener = FakeProbeOpener(FakeProbeResponse(b"must not be read"))

    receipt = network_module.probe_url(
        "https://www.youtube.com/watch?v=abc123",
        opener=opener,
    )

    assert receipt["status"] == "ok"
    assert receipt["fetch_mode"] == "platform_route"
    assert receipt["next_action"] == "platform_extractor"
    assert receipt["route_plan"]["extractor"] == "watch"
    assert receipt["resolved_addresses"] == []
    assert opener.requests == []


def test_platform_detection_requires_exact_domain_boundary():
    assert adapter.platform_for("https://youtube.com/watch?v=abc") == "youtube"
    assert adapter.platform_for("https://www.youtube.com/watch?v=abc") == "youtube"
    assert adapter.platform_for("https://evil-youtube.com/watch?v=abc") == "evil-youtube.com"


def test_probe_script_only_page_requires_browser_without_claiming_failure():
    body = b"<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    receipt = network_module.probe_url(
        "https://example.com/app",
        opener=FakeProbeOpener(
            FakeProbeResponse(body, url="https://example.com/app")
        ),
        resolved_addresses=["93.184.216.34"],
    )

    assert receipt["status"] == "ok"
    assert receipt["error"]["code"] == "JS_RENDER_REQUIRED"
    assert receipt["next_action"] == "browser_public"


def test_probe_challenge_stops_for_user_action():
    body = b"<html><body><div class='cf-chl-widget'>Cloudflare challenge CAPTCHA</div></body></html>"
    receipt = network_module.probe_url(
        "https://example.com/protected",
        opener=FakeProbeOpener(
            FakeProbeResponse(body, url="https://example.com/protected")
        ),
        resolved_addresses=["93.184.216.34"],
    )

    assert receipt["status"] == "needs_user_action"
    assert receipt["error"]["code"] == "CHALLENGE_REQUIRED"
    assert receipt["next_action"] == "visible_browser_or_manual_snapshot"


def test_fetch_public_binary_is_atomic_and_hashed(tmp_path):
    body = b"%PDF-1.7\npublic fixture\n"
    opener = FakeProbeOpener(
        FakeProbeResponse(
            body,
            url="https://example.com/paper.pdf",
            content_type="application/pdf",
        )
    )
    output = tmp_path / "paper.pdf"

    receipt = network_module.fetch_url(
        "https://example.com/paper.pdf",
        output,
        opener=opener,
        resolved_addresses=["93.184.216.34"],
    )

    assert receipt["status"] == "ok"
    assert receipt["fetch_mode"] == "http_snapshot"
    assert receipt["content_sha256"] == adapter.sha256_file(output)
    assert receipt["downloaded_bytes"] == len(body)
    assert output.read_bytes() == body


def test_fetch_rejects_oversize_without_leaving_partial_file(tmp_path):
    body = b"x" * 20
    output = tmp_path / "too-large.bin"
    receipt = network_module.fetch_url(
        "https://example.com/too-large.bin",
        output,
        max_bytes=10,
        opener=FakeProbeOpener(
            FakeProbeResponse(body, content_type="application/octet-stream")
        ),
        resolved_addresses=["93.184.216.34"],
    )

    assert receipt["status"] == "failed_final"
    assert receipt["error"]["code"] == "RESPONSE_TOO_LARGE"
    assert not output.exists()


def test_emit_json_writes_unicode_as_utf8_bytes(monkeypatch):
    class BinaryStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

    stdout = BinaryStdout()
    monkeypatch.setattr(sys, "stdout", stdout)

    adapter.emit_json({"formula": "x₀ + 中文"})

    payload = stdout.buffer.getvalue()
    assert payload.endswith(b"\n")
    assert json.loads(payload.decode("utf-8")) == {"formula": "x₀ + 中文"}


def test_watch_extra_declares_perception_dependencies():
    pyproject = MODULE_PATH.parents[1] / "cli" / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = config["project"]["optional-dependencies"]["watch"]

    assert any(item.lower().startswith("scenedetect") for item in dependencies)
    assert any(item.lower().startswith("imagehash") for item in dependencies)


def test_document_extra_declares_docx_and_pptx_dependencies():
    pyproject = MODULE_PATH.parents[1] / "cli" / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = config["project"]["optional-dependencies"]["document"]
    requirements = (
        MODULE_PATH.parents[1] / "scripts" / "raw_extract_requirements.txt"
    ).read_text(encoding="utf-8")

    assert any("markitdown[docx,pptx]" in item.lower() for item in dependencies)
    assert "markitdown[docx,pptx]" in requirements.lower()


def test_markitdown_text_reads_utf8_plain_text(tmp_path):
    source = tmp_path / "chapter.txt"
    source.write_text("Chapter 20\nMental labour: caf\u00e9.\n", encoding="utf-8")

    text = markitdown_module.markitdown_text(source, None)

    assert "Mental labour: caf\u00e9." in text


def test_pdf_extra_declares_pipeline_backend_dependencies():
    pyproject = MODULE_PATH.parents[1] / "cli" / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = config["project"]["optional-dependencies"]["pdf"]
    requirements = (
        MODULE_PATH.parents[1] / "scripts" / "mineru_extract_requirements.txt"
    ).read_text(encoding="utf-8")

    assert any("mineru[pipeline]" in item.lower() for item in dependencies)
    assert any(item.lower().startswith("six==") for item in dependencies)
    assert "mineru[pipeline]" in requirements.lower()
    assert "six==" in requirements.lower()


def test_package_mineru_preserves_page_bbox_and_assets(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"fake-pdf")
    result = tmp_path / "mineru" / "source" / "ocr"
    images = result / "images"
    images.mkdir(parents=True)
    (images / "formula.jpg").write_bytes(b"image")
    (result / "source.md").write_text(
        "# 标题\n\n![](images/formula.jpg)\n", encoding="utf-8"
    )
    (result / "source_content_list.json").write_text(
        json.dumps(
            [
                {
                    "type": "text",
                    "text": "第一条证据",
                    "page_idx": 0,
                    "bbox": [1, 2, 3, 4],
                },
                {
                    "type": "image",
                    "img_path": "images/formula.jpg",
                    "page_idx": 1,
                    "bbox": [5, 6, 7, 8],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "bundle"
    formula_candidates = tmp_path / "formula-candidates.json"
    formula_candidates.write_text(
        json.dumps({"region_count": 1, "selection_policy": "none", "regions": []}),
        encoding="utf-8",
    )

    mineru_module.package_mineru(
        Namespace(
            result_dir=result.parent.parent,
            source=source,
            output=output,
            title="测试文档",
            extractor_version="3.4.4",
            formula_candidates=formula_candidates,
            warning=[],
            benchmark=True,
            overwrite=False,
        )
    )

    document = (output / "document.md").read_text(encoding="utf-8")
    assert "assets/images/formula.jpg" in document
    assert (output / "assets" / "images" / "formula.jpg").is_file()

    evidence = [
        json.loads(line)
        for line in (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert evidence[0]["locator"] == {"page": 1, "bbox": [1, 2, 3, 4]}
    assert evidence[1]["locator"]["asset"] == "assets/images/formula.jpg"

    quality = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
    assert quality["page_count"] == 2
    assert quality["evidence_count"] == 2
    assert quality["unresolved_asset_references"] == 0
    assert quality["processing_status"] == "partial"
    assert quality["coverage_status"] == "passed"
    assert quality["formula_candidate_region_count"] == 1
    assert (output / "formula-candidates.json").is_file()


def test_route_plan_selects_mature_extractors():
    assert adapter.route_plan("lesson.mp4")["extractor"] == "watch"
    assert adapter.route_plan("slides.pptx")["extractor"] == "markitdown"
    assert adapter.route_plan("paper.pdf")["extractor"] == "mineru"
    assert adapter.route_plan("screenshot.png")["extractor"] == "rapidocr"
    assert "implementation_status" not in adapter.route_plan("screenshot.png")
    url_plan = adapter.route_plan("https://www.bilibili.com/video/BV123")
    assert url_plan["extractor"] == "watch"
    assert url_plan["route"][0] == "platform_caption"


def test_ingest_defaults_to_quick_tier_and_unique_run_output(monkeypatch, tmp_path):
    monkeypatch.delenv("OKS_ROOT", raising=False)
    monkeypatch.setattr(adapter.Path, "home", lambda: tmp_path / "home")
    monkeypatch.chdir(tmp_path)
    args = adapter.build_parser().parse_args(
        ["ingest", "https://www.youtube.com/watch?v=abc123"]
    )

    first = adapter.default_ingest_output(args.source)
    second = adapter.default_ingest_output(args.source)

    assert args.mode == "quick"
    assert first != second
    assert first.parent == tmp_path / "raw"
    assert "-www.youtube.com-watch-" in first.name
    assert len(first.name.rsplit("-", 1)[-1]) == 8


def test_ingest_fast_video_uses_caption_only_child_command(tmp_path):
    args = Namespace(
        source="https://www.youtube.com/watch?v=abc123",
        output=None,
        title=None,
        mode="fast",
        subtitle_langs="zh.*,en.*",
        mineru_backend="pipeline",
        mineru_method="auto",
        overwrite=False,
    )
    output = tmp_path / "bundle"

    command = adapter.ingest_child_argv(
        args,
        adapter.route_plan(args.source),
        output,
        Path("watch-python"),
    )

    assert command[2:5] == ["watch", args.source, "--output"]
    assert "--transcript-only" in command
    assert "--no-local-whisper" in command
    assert command[command.index("--subtitle-langs"):command.index("--subtitle-langs") + 2] == ["--subtitle-langs", "zh.*,en.*"]
    assert "--evidence-tier" in command
    assert command[command.index("--evidence-tier") + 1] == "quick"


def test_ingest_fast_audio_keeps_local_asr_available(tmp_path):
    args = Namespace(
        source=str(tmp_path / "voice.mp3"),
        output=None,
        title=None,
        mode="fast",
        subtitle_langs="zh.*,en.*",
        mineru_backend="pipeline",
        mineru_method="auto",
        overwrite=False,
    )

    command = adapter.ingest_child_argv(
        args,
        adapter.route_plan(args.source),
        tmp_path / "bundle",
        Path("watch-python"),
    )

    assert "--transcript-only" in command
    assert "--no-local-whisper" not in command


def test_ingest_forensic_uses_subtitle_anchored_tier(tmp_path):
    args = Namespace(
        source="https://www.youtube.com/watch?v=abc123",
        output=None,
        title=None,
        mode="forensic",
        subtitle_langs="zh.*,en.*",
        mineru_backend="pipeline",
        mineru_method="auto",
        overwrite=False,
    )

    command = adapter.ingest_child_argv(
        args, adapter.route_plan(args.source), tmp_path / "bundle", Path("watch-python")
    )

    assert "--transcript-only" not in command
    assert command[command.index("--evidence-tier") + 1] == "forensic"


def test_subtitle_topic_anchors_are_bounded_and_gap_aware():
    segments = [
        {"start": 0, "end": 2, "text": "opening"},
        {"start": 8, "end": 10, "text": "next topic"},
        {"start": 15, "end": 16, "text": "detail"},
        {"start": 70, "end": 72, "text": "later topic"},
    ]

    assert watch_module.subtitle_topic_anchors(segments, 12) == [0.0, 8.0, 15.0, 70.0]
    assert watch_module.subtitle_topic_anchors(segments, 2) == [0.0, 70.0]


def test_ingest_rejects_generic_web_url_without_claiming_extraction():
    args = adapter.build_parser().parse_args(["ingest", "https://example.com/article"])

    with pytest.raises(RuntimeError, match=r"Raw"):
        adapter.run_ingest(args)


def test_migrated_route_matrix_covers_declared_modalities_and_platforms():
    cases = {
        "clip.mp4": ("video", "watch"),
        "clip.mkv": ("video", "watch"),
        "voice.mp3": ("audio", "watch"),
        "voice.flac": ("audio", "watch"),
        "paper.pdf": ("document", "mineru"),
        "slides.pptx": ("document", "markitdown"),
        "notes.docx": ("document", "markitdown"),
        "table.xlsx": ("document", "markitdown"),
        "page.html": ("document", "markitdown"),
        "plain.txt": ("document", "markitdown"),
        "rows.csv": ("document", "markitdown"),
        "scan.png": ("image", "rapidocr"),
        "photo.jpg": ("image", "rapidocr"),
        "photo.jpeg": ("image", "rapidocr"),
        "screen.webp": ("image", "rapidocr"),
        "scan.bmp": ("image", "rapidocr"),
        "scan.tiff": ("image", "rapidocr"),
    }
    for source, expected in cases.items():
        plan = adapter.route_plan(source)
        assert (plan["source_type"], plan["extractor"]) == expected

    platforms = {
        "https://www.bilibili.com/video/BV123": "bilibili",
        "https://www.douyin.com/video/123": "douyin",
        "https://youtu.be/abc123": "youtube",
    }
    for source, platform in platforms.items():
        plan = adapter.route_plan(source)
        assert plan["source_type"] == "video"
        assert plan["platform"] == platform
        assert plan["extractor"] == "watch"
        assert plan["route"][0] == "platform_caption"


def test_package_markitdown_preserves_slides_media_and_unresolved_refs(tmp_path):
    source = tmp_path / "deck.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/media/image1.png", b"png")
    markdown = tmp_path / "deck.md"
    markdown.write_text(
        "<!-- Slide number: 1 -->\n\n![cover](Image0.jpg)\n第一张\n\n"
        "<!-- Slide number: 2 -->\n\n第二张\n",
        encoding="utf-8",
    )
    output = tmp_path / "bundle"

    markitdown_module.package_markitdown(
        Namespace(
            source=source,
            markdown=markdown,
            output=output,
            title="测试演示",
            extractor_version="0.1.6",
            warning=[],
            benchmark=True,
            overwrite=False,
        )
    )

    assert (output / "assets" / "original" / "deck.pptx").is_file()
    assert (output / "assets" / "ppt-media" / "image1.png").is_file()
    assert "![cover](Image0.jpg)" in (output / "extractor-output.md").read_text(
        encoding="utf-8"
    )
    assert "未映射图片引用" in (output / "document.md").read_text(encoding="utf-8")
    evidence = [
        json.loads(line)
        for line in (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["locator"]["slide"] for item in evidence] == [1, 2]
    quality = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
    assert quality["embedded_media_count"] == 1
    assert quality["unresolved_asset_references"] == 1
    assert quality["coverage_status"] == "partial"
    assert validator_module.validate_bundle(output)["valid"] is True


def test_package_markitdown_maps_pptx_placeholders_via_ooxml_relationships(tmp_path):
    source = tmp_path / "mapped.pptx"
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/slide-image.png"/>
</Relationships>"""
    slide = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree><p:pic>
    <p:nvPicPr><p:cNvPr id="2" name="Image 0" descr="cover.png"/></p:nvPicPr>
    <p:blipFill><a:blip r:embed="rId1"/></p:blipFill>
  </p:pic></p:spTree></p:cSld>
</p:sld>"""
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/media/slide-image.png", b"png")
        archive.writestr("ppt/slides/slide1.xml", slide)
        archive.writestr("ppt/slides/_rels/slide1.xml.rels", relationships)
    markdown = tmp_path / "mapped.md"
    markdown.write_text(
        "<!-- Slide number: 1 -->\n\n![cover](Image0.jpg)\n正文\n",
        encoding="utf-8",
    )
    output = tmp_path / "mapped-bundle"

    markitdown_module.package_markitdown(
        Namespace(
            source=source,
            markdown=markdown,
            output=output,
            title="映射测试",
            extractor_version="0.1.6",
            warning=[],
            benchmark=True,
            overwrite=False,
        )
    )

    document = (output / "document.md").read_text(encoding="utf-8")
    quality = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
    assert "![cover](assets/ppt-media/slide-image.png)" in document
    assert quality["mapped_asset_references"] == 1
    assert quality["unresolved_asset_references"] == 0
    assert quality["coverage_status"] == "passed"
    assert validator_module.validate_bundle(output)["valid"] is True


def test_extract_markdown_data_images_persists_extractor_asset(tmp_path):
    markdown = "![图](data:image/png;base64,aW1hZ2U=)"

    mapped, assets, failed = markitdown_module.extract_markdown_data_images(markdown, tmp_path)

    assert mapped == "![图](assets/embedded/image-0001.png)"
    assert len(assets) == 1
    assert assets[0].read_bytes() == b"image"
    assert failed == 0


def test_package_markitdown_marks_empty_extraction_failed(tmp_path):
    source = tmp_path / "script-only.html"
    source.write_text("<script>run()</script>", encoding="utf-8")
    extracted = tmp_path / "empty.md"
    extracted.write_text("", encoding="utf-8")
    output = tmp_path / "empty-bundle"

    markitdown_module.package_markitdown(
        Namespace(
            source=source,
            markdown=extracted,
            output=output,
            title="空HTML",
            extractor_version="0.1.6",
            warning=[],
            benchmark=True,
            overwrite=False,
        )
    )

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    quality = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
    assert metadata["processing_status"] == "failed"
    assert quality["processing_status"] == "failed"
    assert quality["evidence_count"] == 0
    assert any("未提取到可见正文" in warning for warning in quality["warnings"])


def test_package_watch_payload_keeps_timestamps_ocr_bbox_and_frames(tmp_path):
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"video")
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg")
    payload = {
        "acquisition": {
            "source": str(source),
            "kind": "local",
            "video_path": str(source),
            "subtitle_path": None,
            "info": {"title": "课程", "uploader": "老师"},
            "from_cache": False,
            "acquirer": "local",
        },
        "metadata": {
            "duration_seconds": 12.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "codec": "h264",
            "has_audio": True,
            "size_bytes": 5,
        },
        "transcript": {
            "source": "whisper-local (small)",
            "segments": [{"start": 1.2, "end": 3.4, "text": "三元运算符"}],
        },
        "transcript_candidates": [
            {
                "source": "whisper-local (small;context)",
                "segments": [{"start": 1.2, "end": 3.4, "text": "键盘录入"}],
            }
        ],
        "perception": {
            "source": str(source),
            "engine": "scene",
            "scene_count": 1,
            "candidate_count": 3,
            "deduped_count": 2,
            "focused": False,
            "start_seconds": None,
            "end_seconds": None,
            "frames": [
                {
                    "index": 0,
                    "timestamp_seconds": 2.0,
                    "path": str(frame),
                    "scene_id": 0,
                    "phash": "abc",
                    "reason": "scene-mid",
                    "ocr_blocks": [
                        {
                            "text": "条件 ? 真值 : 假值",
                            "bbox": [1, 2, 30, 40],
                            "confidence": 0.93,
                        }
                    ],
                }
            ],
        },
        "start_seconds": None,
        "end_seconds": None,
    }
    output = tmp_path / "bundle"

    watch_module.package_watch_payload(
        payload,
        source=str(source),
        source_file=None,
        output_path=output,
        title=None,
        extractor_version="1.0.0",
        warnings=[],
        benchmark=True,
        overwrite=False,
    )

    evidence = [
        json.loads(line)
        for line in (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    speech = next(item for item in evidence if item["kind"] == "speech")
    ocr = next(item for item in evidence if item["kind"] == "ocr")
    assert speech["locator"] == {"start": 1.2, "end": 3.4}
    assert ocr["locator"]["bbox"] == [1, 2, 30, 40]
    assert (output / ocr["locator"]["asset"]).is_file()
    content = (output / "content.md").read_text(encoding="utf-8")
    assert "三元运算符" in content
    assert "watch-speech-000001" in content
    assert "watch-frame-000001" in content
    raw = (output / "raw.md").read_text(encoding="utf-8")
    assert "[未校对逐字稿](transcript.md)：1段" in raw
    assert "{len(transcript_segments)}" not in raw
    assert "[ASR候选逐字稿](transcript-candidates.md)：1路候选" in raw
    assert "键盘录入" in (output / "transcript-candidates.md").read_text(encoding="utf-8")
    assert validator_module.validate_bundle(output)["valid"] is True


def test_watch_transcript_route_distinguishes_captions_asr_and_none():
    assert watch_module.transcript_route(
        {"transcript": {"source": "captions", "segments": [{"text": "字幕"}]}}
    ) == "platform_caption"
    assert watch_module.transcript_route(
        {
            "transcript": {
                "source": "whisper-local (small)",
                "segments": [{"text": "转写"}],
            }
        }
    ) == "asr"
    assert watch_module.transcript_route(
        {"transcript": {"source": "none", "segments": []}}
    ) == "none"


def test_package_watch_audio_is_transcript_only_raw(tmp_path):
    source = tmp_path / "interview.mp3"
    source.write_bytes(b"audio")
    payload = {
        "acquisition": {
            "source": str(source),
            "kind": "local",
            "video_path": str(source),
            "subtitle_path": None,
            "info": {"title": "访谈音频"},
            "from_cache": False,
            "acquirer": "local",
        },
        "metadata": {"duration_seconds": 8.0, "has_audio": True, "size_bytes": 5},
        "transcript": {
            "source": "whisper-local (small)",
            "segments": [{"start": 0.2, "end": 2.4, "text": "这是音频内容"}],
        },
        "perception": {"engine": "none", "frames": []},
    }
    output = tmp_path / "audio-bundle"

    watch_module.package_watch_payload(
        payload,
        source=str(source),
        source_file=None,
        output_path=output,
        title=None,
        extractor_version="1.0.0",
        warnings=[],
        benchmark=True,
        overwrite=False,
    )

    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["source_type"] == "audio"
    assert metadata["modalities"] == ["speech"]
    assert "source_type: audio" in (output / "raw.md").read_text(encoding="utf-8")
    assert not (output / "visual.md").exists()
    assert not (output / "assets" / "frames").exists()
    assert validator_module.validate_bundle(output)["valid"] is True


def test_group_transcript_and_visual_dedupe_are_readability_only():
    groups = watch_module.group_transcript_segments(
        [
            {"start": 0.0, "end": 1.0, "text": "第一句"},
            {"start": 1.1, "end": 2.0, "text": "第二句"},
            {"start": 5.0, "end": 6.0, "text": "第三句"},
        ]
    )
    assert len(groups) == 2
    assert groups[0]["evidence_ids"] == [
        "watch-speech-000001",
        "watch-speech-000002",
    ]
    assert groups[0]["text"] == "第一句 第二句"
    frames = [
        {"ocr_blocks": [{"text": "相同屏幕内容"}]},
        {"ocr_blocks": [{"text": "相同屏幕内容"}]},
        {"ocr_blocks": [{"text": "新的屏幕内容"}]},
    ]
    selected = watch_module.select_visual_summaries(frames)
    assert len(selected) == 2


def test_order_ocr_blocks_uses_bbox_without_changing_text():
    blocks = [
        {"text": "右下", "bbox": [100, 100, 150, 120], "confidence": 0.8},
        {"text": "右上", "bbox": [100, 10, 150, 30], "confidence": 0.9},
        {"text": "左下", "bbox": [10, 102, 60, 122], "confidence": 0.7},
        {"text": "左上", "bbox": [10, 12, 60, 32], "confidence": 0.95},
    ]

    ordered = adapter.order_ocr_blocks(blocks)

    assert [item["text"] for item in ordered] == ["左上", "右上", "左下", "右下"]
    assert [item["confidence"] for item in ordered] == [0.95, 0.9, 0.7, 0.8]
    assert [item["source_index"] for item in ordered] == [3, 1, 2, 0]


def test_parse_ocr_roi_requires_explicit_valid_rectangle():
    assert adapter.parse_ocr_roi("10,20,300,400") == (10, 20, 300, 400)
    assert adapter.parse_ocr_roi("10, 20, 300, 400") == (10, 20, 300, 400)
    assert adapter.parse_ocr_roi(None) is None
    assert adapter.parse_ocr_roi("") is None
    for invalid in ("1,2,3", "10,20,5,30", "-1,2,3,4", "a,2,3,4"):
        try:
            adapter.parse_ocr_roi(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid ROI accepted: {invalid}")


def test_package_image_result_translates_roi_coordinates(tmp_path):
    source = tmp_path / "screen.png"
    source.write_bytes(b"png")
    result = SimpleNamespace(
        txts=("正文",),
        boxes=([[1, 2], [11, 2], [11, 12], [1, 12]],),
        scores=(0.98,),
    )
    output = tmp_path / "roi-bundle"
    args = Namespace(
        source=source,
        output=output,
        title="选区",
        extractor_version="3.9.1",
        min_confidence=0.5,
        ocr_roi="100,200,500,600",
        warning=[],
        benchmark=True,
        overwrite=False,
    )

    image_module.package_image_result(args, result, elapsed_seconds=0.1)

    evidence = [
        json.loads(line)
        for line in (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert evidence[1]["locator"]["bbox"] == [101.0, 202.0, 111.0, 212.0]
    extraction = json.loads((output / "extractor-result.json").read_text(encoding="utf-8"))
    assert extraction["ocr_roi"] == [100, 200, 500, 600]


def test_validate_bundle_reports_broken_evidence_asset(tmp_path):
    bundle = tmp_path / "broken"
    bundle.mkdir()
    (bundle / "raw.md").write_text("# Raw\n", encoding="utf-8")
    (bundle / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": validator_module.SCHEMA_VERSION,
                "processing_status": "partial",
            }
        ),
        encoding="utf-8",
    )
    (bundle / "quality-report.json").write_text(
        json.dumps(
            {
                "evidence_count": 1,
                "coverage_status": "passed",
                "coverage_checks": {
                    "evidence_records": {
                        "expected": 1,
                        "observed": 1,
                        "status": "passed",
                    }
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (bundle / "evidence.jsonl").write_text(
        json.dumps(
            {
                "kind": "video_frame",
                "method": "test",
                "locator": {"asset": "assets/missing.jpg"},
            }
        ),
        encoding="utf-8",
    )
    report = validator_module.validate_bundle(bundle)
    assert report["valid"] is False
    assert any("不存在资产" in error for error in report["errors"])


def test_url_identity_separates_url_and_content_hash(tmp_path):
    acquired = tmp_path / "downloaded.mp4"
    acquired.write_bytes(b"real-media")
    url = "https://www.bilibili.com/video/BV123"

    unavailable = adapter.source_identity(url)
    verified = adapter.source_identity(url, content_file=acquired)

    assert unavailable["content_sha256"] is None
    assert unavailable["content_hash_status"] == "unavailable"
    assert unavailable["source_url_sha256"]
    assert verified["content_hash_status"] == "verified"
    assert verified["content_sha256"] == adapter.sha256_file(acquired)
    assert verified["source_url_sha256"] == unavailable["source_url_sha256"]


def test_package_image_result_preserves_ocr_bbox_and_original(tmp_path):
    source = tmp_path / "screen.png"
    source.write_bytes(b"png")
    result = SimpleNamespace(
        txts=("知识复利", "低置信度"),
        boxes=(
            [[1, 2], [11, 2], [11, 12], [1, 12]],
            [[20, 30], [40, 30], [40, 50], [20, 50]],
        ),
        scores=(0.98, 0.2),
    )
    output = tmp_path / "image-bundle"
    args = Namespace(
        source=source,
        output=output,
        title="截图",
        extractor_version="3.4.2",
        min_confidence=0.5,
        warning=[],
        benchmark=True,
        overwrite=False,
    )

    image_module.package_image_result(args, result, elapsed_seconds=0.1)

    content = (output / "content.md").read_text(encoding="utf-8")
    assert "知识复利" in content
    assert "低置信度" not in content
    evidence = [
        json.loads(line)
        for line in (output / "evidence.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert evidence[1]["locator"]["bbox"] == [1.0, 2.0, 11.0, 12.0]
    assert (output / evidence[0]["locator"]["asset"]).is_file()
    quality = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
    assert quality["coverage_status"] == "partial"
    assert quality["rejected_ocr_block_count"] == 1
    assert validator_module.validate_bundle(output)["valid"] is True

    protocol = adapter.bundle_protocol_result(output)
    assert protocol["status"] == "ok"
    assert protocol["contract"] == validator_module.SCHEMA_VERSION
    assert protocol["plugin_version"] == adapter.PLUGIN_VERSION
    assert protocol["bundle"] == str(output.resolve())
    assert protocol["markdown_path"] == str((output / "content.md").resolve())
    assert "知识复利" in protocol["markdown"]
    assert protocol["title"] == "截图"
    assert protocol["modality"] == "image"


def test_cli_failure_is_machine_readable(monkeypatch, capsys, tmp_path):
    source = tmp_path / "screen.png"
    source.write_bytes(b"png")
    import extractors.image as _img_mod
    monkeypatch.setattr(_img_mod, "run_image", lambda _: (_ for _ in ()).throw(RuntimeError("ocr unavailable")))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "raw_bundle_adapter.py",
            "image",
            str(source),
            "--output",
            str(tmp_path / "bundle"),
        ],
    )

    exit_code = adapter.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["status"] == "error"
    assert payload["contract"] == validator_module.SCHEMA_VERSION
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "ocr unavailable"


def test_finalize_v2_preserves_legacy_content_and_adds_provenance(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "content.md").write_text("# Extracted\n", encoding="utf-8")
    (bundle / "evidence.jsonl").write_text('{"id":"e1"}\n', encoding="utf-8")
    (bundle / "assets" / "page.html").write_text("<html>source</html>", encoding="utf-8")
    (bundle / "metadata.json").write_text(
        json.dumps({"schema_version": validator_module.SCHEMA_VERSION, "source": {"content_type": "text/html"}}),
        encoding="utf-8",
    )
    (bundle / "quality-report.json").write_text(json.dumps({"warnings": ["partial images"]}), encoding="utf-8")
    capture = {
        "schema_version": "oks-capture-envelope/v0.2",
        "capture_id": "capture-1",
        "content_hash": "a" * 64,
    }
    run = {
        "schema_version": "oks-processing-run/v0.2",
        "run_id": "run-1",
        "capture_id": "capture-1",
        "recipe_version": "recipe-1",
        "status": "partial",
        "started_at": "2026-07-19T00:00:00+00:00",
        "finished_at": "2026-07-19T00:01:00+00:00",
        "job": {"name": "web", "version": "1.0", "capability": "web.trafilatura"},
    }
    capture_path = tmp_path / "capture.json"
    run_path = tmp_path / "run.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    run_path.write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(validator_module, "validate_bundle", lambda _: {"valid": True, "errors": []})

    report = validator_module.finalize_bundle_v2(bundle, capture_path, run_path, bundle / "assets" / "page.html")

    assert report["valid"] is True
    assert report["schema_version"] == validator_module.RAW_V2_VERSION
    assert (bundle / "content.md").read_text(encoding="utf-8") == "# Extracted\n"
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    assert manifest["content_hash"] == "a" * 64
    assert {item["type"] for item in manifest["provenance"]["relations"]} == {
        "used",
        "wasGeneratedBy",
        "wasDerivedFrom",
    }
    assert manifest["sources"][0]["snapshot_kind"] == "content"
    assert manifest["sources"][0]["content_hash_status"] == "verified"
    assert (bundle / "source" / "primary.html").is_file()


def test_default_validator_reports_v2_manifest_contract(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(
        validator_module,
        "validate_bundle_v2",
        lambda _: {
            "valid": True,
            "schema_version": validator_module.RAW_V2_VERSION,
            "bundle_id": "bundle-1",
            "processing_status": "partial",
            "errors": [],
            "warnings": ["v2 warning"],
        },
    )
    for name in ("raw.md", "content.md"):
        (bundle / name).write_text("# Raw\n", encoding="utf-8")
    (bundle / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": validator_module.SCHEMA_VERSION,
                "processing_status": "partial",
            }
        ),
        encoding="utf-8",
    )
    (bundle / "evidence.jsonl").write_text(
        '{"kind":"text","method":"fixture","locator":{}}\n',
        encoding="utf-8",
    )
    (bundle / "quality-report.json").write_text(
        json.dumps(
            {
                "evidence_count": 1,
                "coverage_status": "passed",
                "coverage_checks": {
                    "evidence": {"expected": 1, "observed": 1, "status": "passed"}
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (bundle / "bundle.json").write_text("{}", encoding="utf-8")

    report = validator_module.validate_bundle(bundle)

    assert report["valid"] is True
    assert report["schema_version"] == validator_module.RAW_V2_VERSION
    assert report["bundle_id"] == "bundle-1"
    assert report["warnings"] == ["v2 warning"]


def test_finalize_v2_marks_platform_reference_without_claiming_media_hash(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "content.md").write_text("# Platform evidence\n", encoding="utf-8")
    (bundle / "evidence.jsonl").write_text('{"kind":"video_frame","method":"watch","locator":{}}\n', encoding="utf-8")
    (bundle / "metadata.json").write_text(json.dumps({"schema_version": validator_module.SCHEMA_VERSION, "source": {}, "processing_status": "partial"}), encoding="utf-8")
    (bundle / "quality-report.json").write_text(json.dumps({"warnings": [], "evidence_count": 1, "coverage_status": "passed", "coverage_checks": {"evidence": {"expected": 1, "observed": 1, "status": "passed"}}}), encoding="utf-8")
    reference = tmp_path / "platform-source.json"
    reference.write_text(json.dumps({"source_url": "https://example.com/video", "original_media_retained": False}), encoding="utf-8")
    capture = {
        "schema_version": "oks-capture-envelope/v0.2",
        "capture_id": "capture-platform",
        "content_hash": "b" * 64,
        "source_snapshot": {"kind": "reference", "content_hash_status": "unavailable"},
    }
    run = {
        "schema_version": "oks-processing-run/v0.2", "run_id": "run-platform", "capture_id": "capture-platform",
        "recipe_version": "platform-v0.1", "status": "partial", "started_at": "2026-07-19T00:00:00+00:00",
        "finished_at": "2026-07-19T00:01:00+00:00", "job": {"name": "watch", "version": "1.0", "capability": "video.watch"},
    }
    capture_path = tmp_path / "capture.json"
    run_path = tmp_path / "run.json"
    capture_path.write_text(json.dumps(capture), encoding="utf-8")
    run_path.write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(validator_module, "validate_bundle", lambda _: {"valid": True, "errors": []})

    report = validator_module.finalize_bundle_v2(bundle, capture_path, run_path, reference)

    assert report["valid"] is True
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    assert manifest["sources"][0]["snapshot_kind"] == "reference"
    assert manifest["sources"][0]["content_hash_status"] == "unavailable"


# ── PDF: mineru CLI discovery ──────────────────────────────────────

def test_mineru_cli_raises_actionable_error_when_binary_not_found(monkeypatch, tmp_path):
    """If the mineru binary is missing from the selected environment, fail
    before extraction with an error naming the interpreter and remediation."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    plan = adapter.route_plan(str(source))
    assert plan["extractor"] == "mineru"

    # Simulate an extractor_python with no mineru binary next to it
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("fake")
    from unittest import mock
    with mock.patch.object(adapter, "_extractor_python", return_value=fake_python):
        args = adapter.build_parser().parse_args(["ingest", str(source), "--mode", "quick"])
        with pytest.raises(RuntimeError) as exc:
            adapter.run_ingest(args)
        msg = str(exc.value)
        assert "mineru" in msg.lower()
        assert "找不到" in msg or "OKS_MINERU_PYTHON" in msg
        assert "oks capability install pdf" in msg


def test_validate_extractor_python_preserves_venv_symlink(monkeypatch, tmp_path):
    """A pipx-style symlink must not resolve to the host interpreter."""
    host_python = tmp_path / "host-python"
    host_python.write_text("host")
    venv_python = tmp_path / "venv-python"
    try:
        venv_python.symlink_to(host_python)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    def fake_run(command, **_kwargs):
        result = type("Result", (), {})()
        result.returncode = 0
        result.stdout = "3.12\n"
        result.stderr = ""
        return result

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    assert adapter._validate_extractor_python(venv_python, "mineru") == venv_python.absolute()


def test_pdf_ingest_gets_cold_start_timeout_budget(tmp_path):
    args = adapter.build_parser().parse_args(["ingest", str(tmp_path / "paper.pdf")])
    assert adapter.ingest_timeout_seconds(args, "mineru") == 900.0


def test_mineru_cli_uses_scripts_dir_binary_when_present(monkeypatch, tmp_path):
    """When the mineru binary exists next to extractor_python, it is used
    without falling back to shutil.which."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    fake_python = tmp_path / "fake-python"
    fake_python.write_text("fake")
    mineru_bin = tmp_path / ("mineru.exe" if os.name == "nt" else "mineru")
    mineru_bin.write_text("fake-mineru")

    plan = adapter.route_plan(str(source))
    from unittest import mock
    with mock.patch.object(adapter, "_extractor_python", return_value=fake_python):
        # Mock subprocess.run for mineru CLI to succeed and return a fake result
        run_results = []

        def fake_run(cmd, **kwargs):
            run_results.append(cmd)
            if "mineru" in str(cmd[0]).lower():
                # mineru CLI — succeed
                result = mock.MagicMock()
                result.returncode = 0
                result.stderr = ""
                result.stdout = ""
                return result
            # packaging stage — succeed
            result = mock.MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = ""
            return result

        with mock.patch("subprocess.run", side_effect=fake_run):
            # We also need to mock _ffprobe_preflight and the temp directory
            with mock.patch.object(adapter, "_ffprobe_preflight", return_value=None):
                args = adapter.build_parser().parse_args(["ingest", str(source), "--mode", "quick"])
                adapter.run_ingest(args)
            # First subprocess.run call must use the selected environment binary.
            mineru_calls = [c for c in run_results if "mineru" in str(c[0]).lower()]
            assert len(mineru_calls) >= 1
            assert str(mineru_bin) in str(mineru_calls[0][0])


# ── Formula: --formula-secondary flag forwarding ────────────────────

def test_ingest_child_argv_forwards_formula_candidates_for_pdf(tmp_path):
    """When --formula-candidates is passed for a PDF ingest, it appears in
    the packaging command."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    mineru_result = tmp_path / "mineru-result"
    mineru_result.mkdir()
    output = tmp_path / "bundle"

    args = adapter.build_parser().parse_args(
        ["ingest", str(source), "--mode", "quick", "--formula-secondary",
         "--formula-max-regions", "10",
         "--output", str(output)]
    )

    plan = adapter.route_plan(str(source))
    command = adapter.ingest_child_argv(
        args, plan, output, Path("fake-python"), mineru_result=mineru_result,
    )

    assert "mineru" in command
    assert "--formula-candidates" not in command  # not in base command; added in run_ingest
    assert "--source" in command


def test_formula_secondary_requires_both_pdf_and_formula_capabilities(monkeypatch, tmp_path):
    """When --formula-secondary is set for a PDF, both pdf and formula
    capabilities must be checked."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")

    from unittest import mock
    # Simulate: pdf capability is available, formula is not
    cap_results = {"pdf": (True, Path(sys.executable)), "formula": (False, None)}

    def fake_cap_ok(name):
        return cap_results.get(name, (False, None))

    with mock.patch("capability_check.is_capability_available", side_effect=fake_cap_ok):
        args = adapter.build_parser().parse_args(
            ["ingest", str(source), "--mode", "quick", "--formula-secondary"]
        )
        assert getattr(args, "formula_secondary", False) is True


# ── Watch: ffprobe preflight ───────────────────────────────────────

def test_ffprobe_preflight_raises_for_local_video_without_ffprobe(monkeypatch, tmp_path):
    """Local video files require ffprobe; raise an actionable error when
    it is missing from the system."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"fake-mp4")

    monkeypatch.delenv("OKS_FFPROBE", raising=False)
    plan = adapter.route_plan(str(source))
    from unittest import mock
    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError) as exc:
            adapter._ffprobe_preflight(str(source), plan)
        msg = str(exc.value)
        assert "ffprobe" in msg.lower() or "ffmpeg" in msg.lower()
        assert "安装" in msg or "install" in msg.lower()


def test_ffprobe_preflight_respects_oks_ffprobe_env_var(monkeypatch, tmp_path):
    """When OKS_FFPROBE is set and the binary exists, preflight passes."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "lesson.mp4"
    source.write_bytes(b"fake-mp4")
    fake_ffprobe = tmp_path / "my-ffprobe"
    fake_ffprobe.write_text("fake")

    monkeypatch.setenv("OKS_FFPROBE", str(fake_ffprobe))
    plan = adapter.route_plan(str(source))
    from unittest import mock
    with mock.patch("shutil.which", return_value=str(fake_ffprobe)):
        adapter._ffprobe_preflight(str(source), plan)  # no exception


def test_ffprobe_preflight_skips_url_sources(monkeypatch):
    """URL sources (YouTube, Bilibili, etc.) skip the ffprobe preflight
    because yt-dlp handles media acquisition."""
    plan = adapter.route_plan("https://www.youtube.com/watch?v=abc123")
    from unittest import mock
    with mock.patch("shutil.which") as mock_which:
        adapter._ffprobe_preflight("https://www.youtube.com/watch?v=abc123", plan)
        mock_which.assert_not_called()


def test_ffprobe_preflight_skips_non_media_files(monkeypatch, tmp_path):
    """Non media files (PDF, images, office docs) skip the ffprobe preflight."""
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    plan = adapter.route_plan(str(source))
    from unittest import mock
    with mock.patch("shutil.which") as mock_which:
        adapter._ffprobe_preflight(str(source), plan)
        mock_which.assert_not_called()
