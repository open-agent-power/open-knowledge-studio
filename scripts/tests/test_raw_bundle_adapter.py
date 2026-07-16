import importlib.util
import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).parents[1] / "raw_bundle_adapter.py"
SPEC = importlib.util.spec_from_file_location("raw_bundle_adapter", MODULE_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


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

    adapter.package_mineru(
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

    adapter.package_markitdown(
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
    assert adapter.validate_bundle(output)["valid"] is True


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

    adapter.package_markitdown(
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
    assert adapter.validate_bundle(output)["valid"] is True


def test_extract_markdown_data_images_persists_extractor_asset(tmp_path):
    markdown = "![图](data:image/png;base64,aW1hZ2U=)"

    mapped, assets, failed = adapter.extract_markdown_data_images(markdown, tmp_path)

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

    adapter.package_markitdown(
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

    adapter.package_watch_payload(
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
    assert adapter.validate_bundle(output)["valid"] is True


def test_watch_transcript_route_distinguishes_captions_asr_and_none():
    assert adapter.transcript_route(
        {"transcript": {"source": "captions", "segments": [{"text": "字幕"}]}}
    ) == "platform_caption"
    assert adapter.transcript_route(
        {
            "transcript": {
                "source": "whisper-local (small)",
                "segments": [{"text": "转写"}],
            }
        }
    ) == "asr"
    assert adapter.transcript_route(
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

    adapter.package_watch_payload(
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
    assert adapter.validate_bundle(output)["valid"] is True


def test_group_transcript_and_visual_dedupe_are_readability_only():
    groups = adapter.group_transcript_segments(
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
    selected = adapter.select_visual_summaries(frames)
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

    adapter.package_image_result(args, result, elapsed_seconds=0.1)

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
                "schema_version": adapter.SCHEMA_VERSION,
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
    report = adapter.validate_bundle(bundle)
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

    adapter.package_image_result(args, result, elapsed_seconds=0.1)

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
    assert adapter.validate_bundle(output)["valid"] is True

    protocol = adapter.bundle_protocol_result(output)
    assert protocol["status"] == "ok"
    assert protocol["contract"] == adapter.SCHEMA_VERSION
    assert protocol["plugin_version"] == adapter.PLUGIN_VERSION
    assert protocol["bundle"] == str(output.resolve())
    assert protocol["markdown_path"] == str((output / "content.md").resolve())
    assert "知识复利" in protocol["markdown"]
    assert protocol["title"] == "截图"
    assert protocol["modality"] == "image"


def test_cli_failure_is_machine_readable(monkeypatch, capsys, tmp_path):
    source = tmp_path / "screen.png"
    source.write_bytes(b"png")
    monkeypatch.setattr(adapter, "run_image", lambda _: (_ for _ in ()).throw(RuntimeError("ocr unavailable")))
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
    assert payload["contract"] == adapter.SCHEMA_VERSION
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "ocr unavailable"
