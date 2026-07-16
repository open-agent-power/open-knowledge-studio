#!/usr/bin/env python3
"""Run an explicitly selected extractor and emit an OKS Raw bundle.

The Agent remains the orchestrator: it selects a subcommand before invoking
this Level-1 capability.  The adapter may call mature external extractors, but
it never summarizes, corrects, grades, or promotes source content to Draft or
Wiki.  Its contract is faithful extraction plus provenance and evidence.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA_VERSION = "raw-multimodal/v0.1"
PLUGIN_VERSION = "0.1.0"
_WATCH_OVERRIDE_LOCK = threading.Lock()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"oks-raw-bundle {PLUGIN_VERSION}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    mineru = subparsers.add_parser(
        "mineru", help="Package an existing MinerU result directory."
    )
    mineru.add_argument("result_dir", type=Path)
    mineru.add_argument("--source", type=Path, required=True)
    mineru.add_argument("--output", type=Path, required=True)
    mineru.add_argument("--title")
    mineru.add_argument("--extractor-version", default="unknown")
    mineru.add_argument("--formula-candidates", type=Path)
    mineru.add_argument("--warning", action="append", default=[])
    mineru.add_argument("--benchmark", action="store_true")
    mineru.add_argument("--overwrite", action="store_true")

    markitdown = subparsers.add_parser(
        "markitdown",
        help="Run MarkItDown or package an existing MarkItDown Markdown result.",
    )
    markitdown.add_argument("source", type=Path)
    markitdown.add_argument("--markdown", type=Path)
    markitdown.add_argument("--output", type=Path, required=True)
    markitdown.add_argument("--title")
    markitdown.add_argument("--extractor-version", default="unknown")
    markitdown.add_argument("--warning", action="append", default=[])
    markitdown.add_argument("--benchmark", action="store_true")
    markitdown.add_argument("--overwrite", action="store_true")

    watch = subparsers.add_parser(
        "watch", help="Run Watch Skill and package its evidence as Raw."
    )
    watch.add_argument("source")
    watch.add_argument("--source-file", type=Path)
    watch.add_argument("--output", type=Path, required=True)
    watch.add_argument("--title")
    watch.add_argument("--extractor-version", default="unknown")
    watch.add_argument("--max-frames", type=int, default=12)
    watch.add_argument("--hotwords")
    watch.add_argument("--initial-prompt")
    watch.add_argument("--asr-model", default="auto")
    watch.add_argument("--asr-language")
    watch.add_argument(
        "--video-profile", choices=("auto", "speech", "shots", "screen"), default="auto"
    )
    watch.add_argument("--ocr-roi")
    watch.add_argument("--screen-change-threshold", type=float, default=6.0)
    watch.add_argument("--screen-sample-seconds", type=float, default=1.0)
    watch.add_argument("--transcript-only", action="store_true")
    watch.add_argument("--no-local-whisper", action="store_true")
    watch.add_argument(
        "--subtitle-langs",
        default="zh.*,ai-zh,en.*",
        help="Caption language patterns passed to Watch/yt-dlp.",
    )
    watch.add_argument("--warning", action="append", default=[])
    watch.add_argument("--benchmark", action="store_true")
    watch.add_argument("--overwrite", action="store_true")

    watch_result = subparsers.add_parser(
        "watch-result", help="Package an exported Watch Skill JSON result."
    )
    watch_result.add_argument("result", type=Path)
    watch_result.add_argument("--source", required=True)
    watch_result.add_argument("--source-file", type=Path)
    watch_result.add_argument("--output", type=Path, required=True)
    watch_result.add_argument("--title")
    watch_result.add_argument("--extractor-version", default="unknown")
    watch_result.add_argument("--warning", action="append", default=[])
    watch_result.add_argument("--benchmark", action="store_true")
    watch_result.add_argument("--overwrite", action="store_true")

    image = subparsers.add_parser(
        "image", help="Run RapidOCR and package one image as Raw."
    )
    image.add_argument("source", type=Path)
    image.add_argument("--output", type=Path, required=True)
    image.add_argument("--title")
    image.add_argument("--extractor-version", default="unknown")
    image.add_argument("--min-confidence", type=float, default=0.5)
    image.add_argument("--ocr-roi", help="OCR region x1,y1,x2,y2 in source pixels.")
    image.add_argument("--warning", action="append", default=[])
    image.add_argument("--benchmark", action="store_true")
    image.add_argument("--overwrite", action="store_true")

    route = subparsers.add_parser(
        "route", help="Inspect a local source or URL and print the Raw route plan."
    )
    route.add_argument("source")

    validate = subparsers.add_parser(
        "validate", help="Validate an existing Raw bundle without modifying it."
    )
    validate.add_argument("bundle", type=Path)
    return parser


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")
            count += 1
    return count


def exactly_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {pattern!r} under {root}, found {len(matches)}"
        )
    return matches[0]


def prepare_output(path: Path, overwrite: bool) -> Path:
    path = path.expanduser().resolve()
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def source_identity(
    source: str,
    source_file: Path | None = None,
    content_file: Path | None = None,
) -> dict[str, Any]:
    local = source_file
    if local is None:
        candidate = Path(source).expanduser()
        if candidate.is_file():
            local = candidate
    if local is not None:
        local = local.expanduser().resolve()
        if not local.is_file():
            raise FileNotFoundError(local)
        identity = {
            "local_path": str(local),
            "url": None if source == str(local) else source if is_url(source) else None,
            "platform": platform_for(source),
            "content_sha256": sha256_file(local),
            "content_hash_status": "verified",
        }
        if is_url(source):
            identity["source_url_sha256"] = hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()
        return identity
    if not is_url(source):
        raise FileNotFoundError(source)
    verified_content = None
    if content_file is not None:
        candidate_content = content_file.expanduser().resolve()
        if candidate_content.is_file():
            verified_content = sha256_file(candidate_content)
    return {
        "local_path": None,
        "url": source,
        "platform": platform_for(source),
        "source_url_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "content_sha256": verified_content,
        "content_hash_status": "verified" if verified_content else "unavailable",
    }


def is_url(value: str) -> bool:
    return urlparse(value).scheme.lower() in {"http", "https"}


def platform_for(source: str) -> str:
    if not is_url(source):
        return "local"
    host = (urlparse(source).hostname or "").lower()
    if "bilibili.com" in host or host == "b23.tv":
        return "bilibili"
    if "douyin.com" in host:
        return "douyin"
    if "youtube.com" in host or host == "youtu.be":
        return "youtube"
    return host or "web"


def route_plan(source: str) -> dict[str, Any]:
    parsed = urlparse(source)
    suffix = Path(parsed.path if is_url(source) else source).suffix.lower()
    platform = platform_for(source)
    video_suffixes = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
    audio_suffixes = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
    office_suffixes = {".pptx", ".docx", ".xlsx", ".html", ".htm", ".txt", ".csv"}
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
    if is_url(source) and platform in {"bilibili", "douyin", "youtube"}:
        return {
            "source_type": "video",
            "platform": platform,
            "modalities": ["speech", "video", "on_screen_text"],
            "extractor": "watch",
            "route": ["platform_caption", "media_acquire", "asr", "keyframe", "ocr"],
        }
    if suffix in video_suffixes:
        return {
            "source_type": "video",
            "platform": platform,
            "modalities": ["speech", "video", "on_screen_text"],
            "extractor": "watch",
            "route": ["embedded_caption", "asr", "keyframe", "ocr"],
        }
    if suffix in audio_suffixes:
        return {
            "source_type": "audio",
            "platform": platform,
            "modalities": ["speech"],
            "extractor": "watch",
            "route": ["embedded_transcript", "asr"],
        }
    if suffix == ".pdf":
        return {
            "source_type": "document",
            "platform": platform,
            "modalities": ["text", "layout", "image", "formula"],
            "extractor": "mineru",
            "route": ["text_layer", "layout", "ocr", "formula", "asset_copy"],
        }
    if suffix in office_suffixes:
        return {
            "source_type": "document",
            "platform": platform,
            "modalities": ["text", "layout", "image"],
            "extractor": "markitdown",
            "route": ["native_structure", "markdown", "embedded_media"],
        }
    if suffix in image_suffixes:
        return {
            "source_type": "image",
            "platform": platform,
            "modalities": ["image", "on_screen_text"],
            "extractor": "rapidocr",
            "route": ["ocr", "bbox", "original_asset"],
        }
    return {
        "source_type": "unknown",
        "platform": platform,
        "modalities": [],
        "extractor": None,
        "route": ["human_fallback"],
        "implementation_status": "unsupported",
    }


def common_metadata(
    *,
    capture_id: str,
    identity: dict[str, Any],
    title: str,
    source_type: str,
    modalities: list[str],
    route: list[str],
    extractor_name: str,
    extractor_version: str,
    processing_status: str,
    benchmark: bool,
) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "capture_id": capture_id,
        "source": {
            **identity,
            "title": title,
            "author": None,
            "collected_at": generated_at,
        },
        "source_type": source_type,
        "modalities": modalities,
        "route": route,
        "extractors": [{"name": extractor_name, "version": extractor_version}],
        "processing_status": processing_status,
        "review_status": "pending",
        "benchmark": bool(benchmark),
        "human_context": "omitted" if benchmark else "required",
        "purpose": "multimodal_pipeline_evaluation" if benchmark else None,
    }


def coverage_report(
    checks: dict[str, tuple[int | None, int]],
) -> tuple[dict[str, dict[str, Any]], str]:
    report: dict[str, dict[str, Any]] = {}
    statuses: list[str] = []
    for name, (expected, observed) in checks.items():
        if expected is None:
            status = "unknown"
        elif observed == expected:
            status = "passed"
        else:
            status = "partial"
        report[name] = {
            "expected": expected,
            "observed": observed,
            "status": status,
        }
        statuses.append(status)
    if "partial" in statuses:
        overall = "partial"
    elif statuses and all(status == "passed" for status in statuses):
        overall = "passed"
    else:
        overall = "unknown"
    return report, overall


def markdown_asset_references(markdown: str) -> list[str]:
    values = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    values.extend(re.findall(r'<img\s+[^>]*src=["\']([^"\']+)', markdown))
    return [value.strip().split()[0].strip("<>") for value in values]


def neutralize_unresolved_images(markdown: str, unresolved: set[str]) -> str:
    def replace_markdown(match: re.Match[str]) -> str:
        alt, target = match.group(1), match.group(2).strip().split()[0].strip("<>")
        if target not in unresolved:
            return match.group(0)
        return f"> 未映射图片引用：`{target}`（原alt：{alt or '无'}）"

    value = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_markdown, markdown)

    def replace_html(match: re.Match[str]) -> str:
        target = match.group(1)
        if target not in unresolved:
            return match.group(0)
        return f"<!-- 未映射图片引用：{target} -->"

    return re.sub(r'<img\s+[^>]*src=["\']([^"\']+)["\'][^>]*>', replace_html, value)


def mineru_evidence(
    entries: list[dict[str, Any]], image_map: dict[str, str]
) -> Iterable[dict[str, Any]]:
    for index, entry in enumerate(entries):
        kind = str(entry.get("type", "unknown"))
        evidence: dict[str, Any] = {
            "id": f"mineru-{index + 1:06d}",
            "kind": kind,
            "method": "mineru",
            "locator": {
                "page": int(entry.get("page_idx", 0)) + 1,
            },
        }
        if entry.get("bbox") is not None:
            evidence["locator"]["bbox"] = entry["bbox"]
        text = entry.get("text")
        if text:
            evidence["text"] = text
        image_path = entry.get("img_path")
        if image_path:
            normalized = Path(str(image_path)).name
            evidence["locator"]["asset"] = image_map.get(
                normalized, f"assets/images/{normalized}"
            )
        table_body = entry.get("table_body")
        if table_body:
            evidence["text"] = table_body
        yield evidence


def rewrite_mineru_images(markdown: str) -> str:
    return re.sub(
        r'(?P<prefix>(?:!\[[^\]]*\]\(|src=["\']))images/',
        r"\g<prefix>assets/images/",
        markdown,
    )


def package_mineru(args: argparse.Namespace) -> Path:
    result_dir = args.result_dir.expanduser().resolve()
    source = args.source.expanduser().resolve()
    if not result_dir.is_dir():
        raise NotADirectoryError(result_dir)
    if not source.is_file():
        raise FileNotFoundError(source)

    markdown_path = exactly_one(result_dir, "*.md")
    content_list_path = exactly_one(result_dir, "*_content_list.json")
    entries = json.loads(content_list_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("MinerU content list must be a JSON array")

    output = prepare_output(args.output, args.overwrite)
    assets_dir = output / "assets" / "images"
    assets_dir.mkdir(parents=True)

    source_images = markdown_path.parent / "images"
    image_map: dict[str, str] = {}
    if source_images.is_dir():
        for image in sorted(source_images.iterdir()):
            if not image.is_file():
                continue
            destination = assets_dir / image.name
            shutil.copy2(image, destination)
            image_map[image.name] = f"assets/images/{image.name}"

    document = rewrite_mineru_images(markdown_path.read_text(encoding="utf-8"))
    (output / "document.md").write_text(document, encoding="utf-8", newline="\n")
    (output / "content.md").write_text(document, encoding="utf-8", newline="\n")
    evidence_count = write_jsonl(
        output / "evidence.jsonl", mineru_evidence(entries, image_map)
    )
    formula_candidate_count = 0
    formula_candidates_path = getattr(args, "formula_candidates", None)
    if formula_candidates_path is not None:
        formula_candidates_path = formula_candidates_path.expanduser().resolve()
        formula_payload = json.loads(formula_candidates_path.read_text(encoding="utf-8"))
        formula_candidate_count = int(formula_payload.get("region_count", 0))
        write_json(output / "formula-candidates.json", formula_payload)

    warnings = list(args.warning)
    warnings.extend(
        [
            "MinerU文本、OCR和公式结果未经人工逐项校对",
            "公式、上下标、矢量和复杂表格可能误识别；以原PDF页面为准",
        ]
    )
    if formula_candidate_count:
        warnings.append(
            f"{formula_candidate_count}个独立公式块有第二提取候选；未自动选择或覆盖MinerU结果"
        )
    image_references = len(re.findall(r"(?:!\[|<img\s)", document))
    expected_image_assets = {
        Path(str(item["img_path"])).name
        for item in entries
        if item.get("img_path")
    }
    observed_image_assets = sum(
        1 for name in expected_image_assets if name in image_map
    )
    coverage_checks, coverage_status = coverage_report(
        {
            "extractor_entries": (len(entries), evidence_count),
            "extractor_image_assets": (
                len(expected_image_assets),
                observed_image_assets,
            ),
        }
    )
    if coverage_status == "partial":
        warnings.append("MinerU提取结果未被完整打包；详见coverage_checks")
    processing_status = "partial" if warnings else "complete"
    digest = sha256_file(source)
    title = args.title or source.stem
    capture_id = f"{datetime.now():%Y%m%d}-document-{digest[:12]}"
    metadata = common_metadata(
        capture_id=capture_id,
        identity=source_identity(str(source)),
        title=title,
        source_type="document",
        modalities=["text", "layout", "formula", "image"],
        route=["mineru", "markdown", "page_evidence", "asset_copy"],
        extractor_name="MinerU",
        extractor_version=args.extractor_version,
        processing_status=processing_status,
        benchmark=args.benchmark,
    )
    write_json(output / "metadata.json", metadata)

    quality = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": processing_status,
        "review_status": "pending",
        "evidence_count": evidence_count,
        "page_count": max(
            (int(item.get("page_idx", 0)) + 1 for item in entries), default=0
        ),
        "asset_count": len(image_map),
        "markdown_image_references": image_references,
        "unresolved_asset_references": max(0, image_references - len(image_map)),
        "formula_candidate_region_count": formula_candidate_count,
        "coverage_status": coverage_status,
        "coverage_checks": coverage_checks,
        "warnings": warnings,
        "human_fallback": "抽样核对每页正文；逐项核对将进入Draft或Wiki的公式",
    }
    write_json(output / "quality-report.json", quality)

    raw_markdown = f"""---
schema_version: {SCHEMA_VERSION}
capture_id: {capture_id}
source_type: document
processing_status: {processing_status}
review_status: pending
benchmark: {str(bool(args.benchmark)).lower()}
---

# {title}

## 来源

- 本地文件：`{source}`
- SHA-256：`{digest}`
- 提取器：MinerU {args.extractor_version}

## Raw提取物

- [可读Raw正文](content.md)
- [文档正文](document.md)
""" + (
        f"- [公式候选](formula-candidates.json)：{formula_candidate_count}个独立公式块\n"
        if formula_candidate_count else ""
    ) + f"""
- [原子证据](evidence.jsonl)：{evidence_count}条，保留页码和可用坐标
- [元数据](metadata.json)
- [质量报告](quality-report.json)
- `assets/images/`：{len(image_map)}个图片证据

## 已知限制

""" + "".join(f"- {warning}\n" for warning in warnings)
    (output / "raw.md").write_text(raw_markdown, encoding="utf-8", newline="\n")
    return output


def markitdown_text(source: Path, markdown: Path | None) -> str:
    if markdown is not None:
        markdown = markdown.expanduser().resolve()
        if not markdown.is_file():
            raise FileNotFoundError(markdown)
        return markdown.read_text(encoding="utf-8")
    try:
        from markitdown import MarkItDown, StreamInfo
    except ImportError as exc:
        raise RuntimeError(
            "MarkItDown is not installed in this interpreter; install it or pass --markdown"
        ) from exc
    stream_info = None
    if source.suffix.lower() in {".html", ".htm"}:
        header = source.read_bytes()[:8192].decode("ascii", errors="ignore")
        charset_match = re.search(
            r"charset\s*=\s*[\"']?([a-zA-Z0-9._-]+)", header, re.IGNORECASE
        )
        stream_info = StreamInfo(
            mimetype="text/html",
            extension=source.suffix.lower(),
            charset=charset_match.group(1) if charset_match else "utf-8",
            filename=source.name,
            local_path=str(source),
        )
    result = MarkItDown().convert(str(source), stream_info=stream_info)
    return result.text_content


def extract_pptx_media(source: Path, assets_dir: Path) -> list[str]:
    if source.suffix.lower() != ".pptx":
        return []
    copied: list[str] = []
    with zipfile.ZipFile(source) as archive:
        for member in sorted(archive.namelist()):
            if not member.startswith("ppt/media/") or member.endswith("/"):
                continue
            name = Path(member).name
            destination = assets_dir / "ppt-media" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as input_handle, destination.open("wb") as output_handle:
                shutil.copyfileobj(input_handle, output_handle)
            copied.append(f"assets/ppt-media/{name}")
    return copied


def extract_docx_media(source: Path, assets_dir: Path) -> list[str]:
    if source.suffix.lower() != ".docx":
        return []
    copied: list[str] = []
    with zipfile.ZipFile(source) as archive:
        for member in sorted(archive.namelist()):
            if not member.startswith("word/media/") or member.endswith("/"):
                continue
            name = Path(member).name
            destination = assets_dir / "docx-media" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as input_handle, destination.open("wb") as output_handle:
                shutil.copyfileobj(input_handle, output_handle)
            copied.append(f"assets/docx-media/{name}")
    return copied


def docx_document_images(source: Path) -> list[str]:
    """Resolve DOCX image occurrence order through document relationships."""
    if source.suffix.lower() != ".docx":
        return []
    relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    office_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(source) as archive:
        members = set(archive.namelist())
        rel_path = "word/_rels/document.xml.rels"
        document_path = "word/document.xml"
        if rel_path not in members or document_path not in members:
            return []
        rel_root = ET.fromstring(archive.read(rel_path))
        relationships: dict[str, str] = {}
        for relationship in rel_root.findall(f"{{{relationship_ns}}}Relationship"):
            if not str(relationship.get("Type", "")).endswith("/image"):
                continue
            target = str(relationship.get("Target", ""))
            if relationship.get("TargetMode") == "External" or not target:
                continue
            relationships[str(relationship.get("Id", ""))] = (
                f"assets/docx-media/{Path(target).name}"
            )
        document_root = ET.fromstring(archive.read(document_path))
        images: list[str] = []
        for blip in document_root.findall(f".//{{{drawing_ns}}}blip"):
            relationship_id = blip.get(f"{{{office_rel_ns}}}embed")
            asset = relationships.get(str(relationship_id))
            if asset:
                images.append(asset)
        return images


def map_markitdown_docx_images(markdown: str, images: list[str]) -> tuple[str, int]:
    if not images:
        return markdown, 0
    available = iter(images)
    mapped_count = 0
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

    def replace_image(match: re.Match[str]) -> str:
        nonlocal mapped_count
        target = match.group(2).strip().split()[0].strip("<>")
        if is_url(target):
            return match.group(0)
        asset = next(available, None)
        if asset is None:
            return match.group(0)
        mapped_count += 1
        return f"![{match.group(1)}]({asset})"

    return image_pattern.sub(replace_image, markdown), mapped_count


def pptx_slide_images(source: Path) -> dict[int, list[dict[str, str]]]:
    """Resolve each PPTX picture to its packaged media asset via OOXML rels."""
    if source.suffix.lower() != ".pptx":
        return {}
    relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    presentation_ns = (
        "http://schemas.openxmlformats.org/presentationml/2006/main"
    )
    drawing_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    office_rel_ns = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    )
    mapping: dict[int, list[dict[str, str]]] = {}
    with zipfile.ZipFile(source) as archive:
        slide_members: list[tuple[int, str]] = []
        for member in archive.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", member)
            if match:
                slide_members.append((int(match.group(1)), member))
        for slide_number, slide_member in sorted(slide_members):
            rel_member = (
                f"ppt/slides/_rels/slide{slide_number}.xml.rels"
            )
            if rel_member not in archive.namelist():
                continue
            rel_root = ET.fromstring(archive.read(rel_member))
            relationships: dict[str, str] = {}
            for relationship in rel_root.findall(
                f"{{{relationship_ns}}}Relationship"
            ):
                if not str(relationship.get("Type", "")).endswith("/image"):
                    continue
                target = str(relationship.get("Target", ""))
                if relationship.get("TargetMode") == "External" or not target:
                    continue
                relationships[str(relationship.get("Id", ""))] = (
                    f"assets/ppt-media/{Path(target).name}"
                )
            slide_root = ET.fromstring(archive.read(slide_member))
            images: list[dict[str, str]] = []
            for picture in slide_root.findall(
                f".//{{{presentation_ns}}}pic"
            ):
                metadata = picture.find(
                    f".//{{{presentation_ns}}}cNvPr"
                )
                blip = picture.find(f".//{{{drawing_ns}}}blip")
                relationship_id = (
                    blip.get(f"{{{office_rel_ns}}}embed")
                    if blip is not None
                    else None
                )
                asset = relationships.get(str(relationship_id))
                if not asset:
                    continue
                images.append(
                    {
                        "asset": asset,
                        "alt": (
                            str(metadata.get("descr") or metadata.get("name") or "")
                            if metadata is not None
                            else ""
                        ),
                    }
                )
            if images:
                mapping[slide_number] = images
    return mapping


def map_markitdown_ppt_images(
    markdown: str, slide_images: dict[int, list[dict[str, str]]]
) -> tuple[str, int]:
    """Replace MarkItDown placeholders with OOXML-resolved slide media."""
    marker = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->", re.IGNORECASE)
    matches = list(marker.finditer(markdown))
    if not matches or not slide_images:
        return markdown, 0
    pieces: list[str] = [markdown[: matches[0].start()]]
    mapped_count = 0
    image_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        section = markdown[match.start() : end]
        available = iter(slide_images.get(int(match.group(1)), []))

        def replace_image(image_match: re.Match[str]) -> str:
            nonlocal mapped_count
            target = image_match.group(2).strip().split()[0].strip("<>")
            if is_url(target):
                return image_match.group(0)
            image = next(available, None)
            if image is None:
                return image_match.group(0)
            mapped_count += 1
            alt = image_match.group(1) or image.get("alt") or ""
            return f"![{alt}]({image['asset']})"

        pieces.append(image_pattern.sub(replace_image, section))
    return "".join(pieces), mapped_count


def extract_markdown_data_images(
    markdown: str, assets_dir: Path
) -> tuple[str, list[Path], int]:
    """Persist extractor-provided data URI images without interpreting them."""
    pattern = re.compile(
        r"(!\[[^\]]*\]\()data:image/([a-zA-Z0-9.+-]+);base64,([^\s)]+)(\))"
    )
    extension_map = {"jpeg": "jpg", "svg+xml": "svg"}
    extracted: list[Path] = []
    failed = 0
    embedded_dir = assets_dir / "embedded"

    def replace(match: re.Match[str]) -> str:
        nonlocal failed
        subtype = match.group(2).lower()
        extension = extension_map.get(subtype, subtype)
        try:
            payload = base64.b64decode(match.group(3), validate=True)
        except (ValueError, TypeError):
            failed += 1
            return match.group(0)
        embedded_dir.mkdir(parents=True, exist_ok=True)
        destination = embedded_dir / f"image-{len(extracted) + 1:04d}.{extension}"
        destination.write_bytes(payload)
        extracted.append(destination)
        return f"{match.group(1)}assets/embedded/{destination.name}{match.group(4)}"

    return pattern.sub(replace, markdown), extracted, failed


def markitdown_evidence(markdown: str) -> Iterable[dict[str, Any]]:
    if not markdown.strip():
        return
    marker = re.compile(r"<!--\s*Slide number:\s*(\d+)\s*-->", re.IGNORECASE)
    matches = list(marker.finditer(markdown))
    if matches:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            text = markdown[match.end() : end].strip()
            yield {
                "id": f"markitdown-slide-{int(match.group(1)):04d}",
                "kind": "slide_text",
                "text": text,
                "method": "markitdown",
                "locator": {"slide": int(match.group(1))},
            }
        return
    yield {
        "id": "markitdown-document-0001",
        "kind": "document_text",
        "text": markdown,
        "method": "markitdown",
        "locator": {"document": 1},
    }


def package_markitdown(args: argparse.Namespace) -> Path:
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    document = markitdown_text(source, args.markdown)
    output = prepare_output(args.output, args.overwrite)
    assets_dir = output / "assets"
    original_dir = assets_dir / "original"
    original_dir.mkdir(parents=True)
    shutil.copy2(source, original_dir / source.name)
    ppt_media_assets = extract_pptx_media(source, assets_dir)
    docx_media_assets = extract_docx_media(source, assets_dir)

    original_references = markdown_asset_references(document)
    slide_images = pptx_slide_images(source)
    mapped_document, mapped_reference_count = map_markitdown_ppt_images(
        document, slide_images
    )
    mapped_document, docx_mapped_reference_count = map_markitdown_docx_images(
        mapped_document, docx_document_images(source)
    )
    mapped_reference_count += docx_mapped_reference_count
    mapped_document, data_image_assets, failed_data_images = extract_markdown_data_images(
        mapped_document, assets_dir
    )
    references = markdown_asset_references(mapped_document)
    unresolved = [
        reference
        for reference in references
        if not is_url(reference) and not (output / reference).is_file()
    ]
    packaged_document = neutralize_unresolved_images(
        mapped_document, set(unresolved)
    )
    (output / "extractor-output.md").write_text(
        document, encoding="utf-8", newline="\n"
    )
    (output / "document.md").write_text(
        packaged_document, encoding="utf-8", newline="\n"
    )
    (output / "content.md").write_text(
        packaged_document, encoding="utf-8", newline="\n"
    )
    evidence_count = write_jsonl(
        output / "evidence.jsonl", markitdown_evidence(packaged_document)
    )
    warnings = list(args.warning)
    warnings.append("MarkItDown正文和结构未经人工校对")
    empty_document = not packaged_document.strip()
    if empty_document:
        warnings.append("MarkItDown未提取到可见正文；仅保留原始文件和失败现场")
    if unresolved:
        warnings.append(
            f"Markdown含{len(unresolved)}个未映射图片引用；原文件和内嵌媒体已保留供回查"
        )
    if failed_data_images:
        warnings.append(
            f"{failed_data_images}个内嵌data URI图片未能解码；原始引用保留在extractor-output.md"
        )
    if source.suffix.lower() != ".pptx":
        warnings.append("当前格式缺少稳定的页码或段落级定位，证据定位仅到文档级")
    slide_count = len(
        re.findall(r"<!--\s*Slide number:", document, re.IGNORECASE)
    )
    expected_evidence = slide_count or 1
    coverage_checks, coverage_status = coverage_report(
        {
            "document_units": (expected_evidence, evidence_count),
            "original_asset": (1, int((original_dir / source.name).is_file())),
            "markdown_asset_references": (
                len(original_references),
                len(references) - len(unresolved),
            ),
            "embedded_media": (
                len(ppt_media_assets) + len(docx_media_assets) + len(data_image_assets),
                len(ppt_media_assets) + len(docx_media_assets) + len(data_image_assets),
            ),
        }
    )
    if coverage_status == "partial":
        warnings.append("MarkItDown提取结果未被完整打包；详见coverage_checks")
    processing_status = "failed" if empty_document else ("partial" if warnings else "complete")
    digest = sha256_file(source)
    title = args.title or source.stem
    capture_id = f"{datetime.now():%Y%m%d}-document-{digest[:12]}"
    metadata = common_metadata(
        capture_id=capture_id,
        identity=source_identity(str(source)),
        title=title,
        source_type="document",
        modalities=["text", "layout", "image"],
        route=["markitdown", "markdown", "embedded_media", "original_asset"],
        extractor_name="MarkItDown",
        extractor_version=args.extractor_version,
        processing_status=processing_status,
        benchmark=args.benchmark,
    )
    write_json(output / "metadata.json", metadata)
    quality = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": processing_status,
        "review_status": "pending",
        "evidence_count": evidence_count,
        "slide_count": slide_count,
        "asset_count": 1 + len(ppt_media_assets) + len(docx_media_assets) + len(data_image_assets),
        "embedded_media_count": len(ppt_media_assets) + len(docx_media_assets) + len(data_image_assets),
        "ppt_media_count": len(ppt_media_assets),
        "docx_media_count": len(docx_media_assets),
        "data_uri_image_count": len(data_image_assets),
        "failed_data_uri_image_count": failed_data_images,
        "markdown_asset_references": len(original_references),
        "mapped_asset_references": mapped_reference_count,
        "unresolved_asset_references": len(unresolved),
        "coverage_status": coverage_status,
        "coverage_checks": coverage_checks,
        "warnings": warnings,
        "human_fallback": (
            "通过原PPT和assets/ppt-media核对正文、图片、图表与排版"
            if source.suffix.lower() == ".pptx"
            else "通过原Word和assets/docx-media核对正文、图片、图表与排版"
            if source.suffix.lower() == ".docx"
            else "通过原始文档核对提取正文、链接与结构"
        ),
    }
    write_json(output / "quality-report.json", quality)
    raw_markdown = f"""---
schema_version: {SCHEMA_VERSION}
capture_id: {capture_id}
source_type: document
processing_status: {processing_status}
review_status: pending
benchmark: {str(bool(args.benchmark)).lower()}
---

# {title}

## 来源

- 本地文件：`{source}`
- SHA-256：`{digest}`
- 提取器：MarkItDown {args.extractor_version}

## Raw提取物

- [可读Raw正文](content.md)
- [文档正文](document.md)
- [提取器原始Markdown](extractor-output.md)
- [原子证据](evidence.jsonl)：{evidence_count}条
- [元数据](metadata.json)
- [质量报告](quality-report.json)
- `assets/original/`：原始文件
- `assets/ppt-media/`：{len(ppt_media_assets)}个PPT内嵌媒体
- `assets/docx-media/`：{len(docx_media_assets)}个Word内嵌媒体
- `assets/embedded/`：{len(data_image_assets)}个提取器内嵌图片

## 已知限制

""" + "".join(f"- {warning}\n" for warning in warnings)
    (output / "raw.md").write_text(raw_markdown, encoding="utf-8", newline="\n")
    return output


def watch_payload(result: Any) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    if result.perception is not None:
        for frame in result.perception.frames:
            frames.append(
                {
                    "index": frame.index,
                    "timestamp_seconds": frame.timestamp_seconds,
                    "path": str(frame.path),
                    "scene_id": frame.scene_id,
                    "phash": frame.phash,
                    "reason": frame.reason,
                    "ocr_blocks": [asdict(block) for block in frame.ocr_blocks],
                }
            )
    acquisition = result.acquisition
    return {
        "acquisition": {
            "source": acquisition.source,
            "kind": str(acquisition.kind),
            "video_path": str(acquisition.video_path) if acquisition.video_path else None,
            "subtitle_path": str(acquisition.subtitle_path) if acquisition.subtitle_path else None,
            "info": acquisition.info,
            "from_cache": acquisition.from_cache,
            "acquirer": acquisition.acquirer,
        },
        "metadata": asdict(result.metadata),
        "transcript": {
            "source": result.transcript.source,
            "segments": [segment.to_dict() for segment in result.transcript.segments],
        },
        "perception": None
        if result.perception is None
        else {
            "source": result.perception.source,
            "engine": result.perception.engine,
            "scene_count": result.perception.scene_count,
            "candidate_count": result.perception.candidate_count,
            "deduped_count": result.perception.deduped_count,
            "focused": result.perception.focused,
            "start_seconds": result.perception.start_seconds,
            "end_seconds": result.perception.end_seconds,
            "frames": frames,
        },
        "start_seconds": result.start_seconds,
        "end_seconds": result.end_seconds,
    }


def render_transcript(payload: dict[str, Any]) -> str:
    lines = ["# 未校对逐字稿", ""]
    for segment in payload.get("transcript", {}).get("segments", []):
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        speaker = f"{segment['speaker']}: " if segment.get("speaker") else ""
        lines.append(f"[{start:.3f}–{end:.3f}] {speaker}{segment.get('text', '').strip()}")
    return "\n".join(lines).rstrip() + "\n"


def format_media_time(seconds: float) -> str:
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def group_transcript_segments(
    segments: list[dict[str, Any]], max_chars: int = 220, max_gap: float = 1.5
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for index, segment in enumerate(segments):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        evidence_id = f"watch-speech-{index + 1:06d}"
        speaker = segment.get("speaker")
        can_merge = bool(
            current
            and start - float(current["end"]) <= max_gap
            and len(str(current["text"])) + len(text) <= max_chars
            and current.get("speaker") == speaker
        )
        if can_merge and current is not None:
            current["end"] = end
            current["text"] = f"{current['text']} {text}"
            current["evidence_ids"].append(evidence_id)
        else:
            current = {
                "start": start,
                "end": end,
                "text": text,
                "speaker": speaker,
                "evidence_ids": [evidence_id],
            }
            groups.append(current)
    return groups


def normalize_ocr_text(value: str) -> str:
    return re.sub(r"\W+", "", value, flags=re.UNICODE).lower()


def order_ocr_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restore basic top-to-bottom, left-to-right order from OCR bboxes.

    This changes only presentation order. Text, confidence and coordinates are
    copied unchanged, and ``source_index`` preserves the extractor order.
    """
    positioned: list[dict[str, Any]] = []
    unpositioned: list[dict[str, Any]] = []
    for index, original in enumerate(blocks):
        block = dict(original)
        block.setdefault("source_index", index)
        bbox = block.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            unpositioned.append(block)
            continue
        left, top, right, bottom = (float(value) for value in bbox)
        block["_layout"] = {
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
            "center": (top + bottom) / 2,
            "height": max(1.0, bottom - top),
        }
        positioned.append(block)

    positioned.sort(
        key=lambda item: (
            item["_layout"]["top"],
            item["_layout"]["left"],
            item["source_index"],
        )
    )
    lines: list[dict[str, Any]] = []
    for block in positioned:
        layout = block["_layout"]
        best_line: dict[str, Any] | None = None
        best_distance = float("inf")
        for line in lines:
            overlap = max(
                0.0,
                min(layout["bottom"], line["bottom"])
                - max(layout["top"], line["top"]),
            )
            overlap_ratio = overlap / min(layout["height"], line["height"])
            distance = abs(layout["center"] - line["center"])
            tolerance = max(layout["height"], line["height"]) * 0.6
            if (overlap_ratio >= 0.4 or distance <= tolerance) and distance < best_distance:
                best_line = line
                best_distance = distance
        if best_line is None:
            lines.append(
                {
                    "top": layout["top"],
                    "bottom": layout["bottom"],
                    "center": layout["center"],
                    "height": layout["height"],
                    "blocks": [block],
                }
            )
            continue
        best_line["blocks"].append(block)
        best_line["top"] = min(best_line["top"], layout["top"])
        best_line["bottom"] = max(best_line["bottom"], layout["bottom"])
        best_line["center"] = (best_line["top"] + best_line["bottom"]) / 2
        best_line["height"] = max(1.0, best_line["bottom"] - best_line["top"])

    ordered: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: (item["top"], item["center"])):
        for block in sorted(
            line["blocks"],
            key=lambda item: (item["_layout"]["left"], item["source_index"]),
        ):
            block.pop("_layout", None)
            ordered.append(block)
    ordered.extend(unpositioned)
    return ordered


def format_evidence_refs(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return "无"
    if len(evidence_ids) == 1:
        return f"`{evidence_ids[0]}`"
    return f"`{evidence_ids[0]}`–`{evidence_ids[-1]}`（{len(evidence_ids)}条）"


def select_visual_summaries(
    frames: list[dict[str, Any]], similarity_threshold: float = 0.88
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    previous = ""
    for frame in frames:
        blocks = [
            str(block.get("text", "")).strip()
            for block in order_ocr_blocks(frame.get("ocr_blocks", []))
            if str(block.get("text", "")).strip()
        ]
        text = "\n".join(dict.fromkeys(blocks))
        normalized = normalize_ocr_text(text)
        similarity = (
            difflib.SequenceMatcher(None, previous, normalized).ratio()
            if previous and normalized
            else 0.0
        )
        if normalized and similarity >= similarity_threshold:
            continue
        selected.append({**frame, "ocr_text": text})
        if normalized:
            previous = normalized
    return selected


def render_watch_content(
    transcript_segments: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    image_map: dict[str, str],
    max_ocr_lines_per_frame: int = 6,
    max_ocr_chars_per_frame: int = 500,
    include_visual: bool = True,
) -> tuple[str, int, int, int]:
    groups = group_transcript_segments(transcript_segments)
    visual_summaries = select_visual_summaries(frames)
    lines = [
        "# Raw提取正文",
        "",
        "> 以下内容仅做机器提取结果的合段、去重和证据编排，未经总结、改写或概念抽取。",
        "",
        "## 语音内容",
        "",
    ]
    if not groups:
        lines.append("未取得字幕或ASR逐字稿。")
    for group in groups:
        start = format_media_time(float(group["start"]))
        end = format_media_time(float(group["end"]))
        evidence_ids = format_evidence_refs(group["evidence_ids"])
        speaker = f"{group['speaker']}：" if group.get("speaker") else ""
        lines.extend(
            [
                f"### {start}–{end}",
                "",
                f"{speaker}{group['text']}",
                "",
                f"证据：{evidence_ids}",
                "",
            ]
        )
    rendered_visuals = 0
    rendered_ocr_lines = 0
    if not include_visual:
        return (
            "\n".join(lines).rstrip() + "\n",
            len(groups),
            rendered_visuals,
            rendered_ocr_lines,
        )
    lines.extend(["## 视觉内容", ""])
    if not visual_summaries:
        lines.append("未取得可用视觉证据。")
    for frame in visual_summaries:
        source_frame = str(Path(frame["path"]).expanduser().resolve())
        asset = image_map.get(source_frame)
        if not asset:
            continue
        rendered_visuals += 1
        index = int(frame.get("index", 0))
        timestamp = float(frame.get("timestamp_seconds", 0))
        lines.extend(
            [
                f"### {format_media_time(timestamp)}",
                "",
                f"![]({asset})",
                "",
                f"证据：`watch-frame-{index + 1:06d}`",
                "",
            ]
        )
        if frame.get("ocr_text"):
            all_ocr_lines = frame["ocr_text"].splitlines()
            excerpt: list[str] = []
            excerpt_chars = 0
            for ocr_line in all_ocr_lines:
                if len(excerpt) >= max_ocr_lines_per_frame:
                    break
                if excerpt and excerpt_chars + len(ocr_line) > max_ocr_chars_per_frame:
                    break
                excerpt.append(ocr_line)
                excerpt_chars += len(ocr_line)
            rendered_ocr_lines += len(excerpt)
            lines.extend(["```text", "\n".join(excerpt), "```", ""])
            if len(excerpt) < len(all_ocr_lines):
                lines.extend(
                    [
                        f"OCR摘录：显示{len(excerpt)}/{len(all_ocr_lines)}行；完整OCR见 `evidence.jsonl`。",
                        "",
                    ]
                )
    return (
        "\n".join(lines).rstrip() + "\n",
        len(groups),
        rendered_visuals,
        rendered_ocr_lines,
    )


def transcript_route(payload: dict[str, Any]) -> str:
    transcript = payload.get("transcript", {})
    if not transcript.get("segments"):
        return "none"
    source = str(transcript.get("source", "")).lower()
    if "caption" in source or "subtitle" in source:
        return "platform_caption"
    if "whisper" in source or "asr" in source:
        return "asr"
    return "extractor_transcript"


def package_watch_payload(
    payload: dict[str, Any],
    *,
    source: str,
    source_file: Path | None,
    output_path: Path,
    title: str | None,
    extractor_version: str,
    warnings: list[str],
    benchmark: bool,
    overwrite: bool,
    frame_fallback_dir: Path | None = None,
) -> Path:
    output = prepare_output(output_path, overwrite)
    planned_route = route_plan(source)
    source_type = (
        planned_route["source_type"]
        if planned_route.get("source_type") in {"audio", "video"}
        else "video"
    )
    is_audio = source_type == "audio"
    acquired_value = payload.get("acquisition", {}).get("video_path")
    acquired_file = Path(acquired_value) if acquired_value else None
    identity = source_identity(source, source_file, acquired_file)
    digest = identity.get("content_sha256") or identity.get("source_url_sha256")
    if not digest:
        raise ValueError("无法为媒体来源生成稳定指纹")
    info = payload.get("acquisition", {}).get("info", {})
    resolved_title = title or info.get("title") or (
        source_file.stem
        if source_file
        else Path(urlparse(source).path).stem or source_type
    )
    capture_id = f"{datetime.now():%Y%m%d}-{source_type}-{digest[:12]}"
    frames_dir = output / "assets" / "frames"
    if not is_audio:
        frames_dir.mkdir(parents=True)
    transcript_segments = payload.get("transcript", {}).get("segments", [])
    perception = payload.get("perception") or {}
    frames = perception.get("frames", [])
    image_map: dict[str, str] = {}
    for frame in frames:
        payload_frame = Path(frame["path"]).expanduser().resolve()
        source_frame = payload_frame
        if not source_frame.is_file() and frame_fallback_dir is not None:
            candidates = sorted(
                frame_fallback_dir.glob(f"frame-{int(frame.get('index', 0)):04d}.*")
            )
            if candidates:
                source_frame = candidates[0].resolve()
        if not source_frame.is_file():
            warnings.append(f"证据帧不存在：{source_frame}")
            continue
        destination = frames_dir / f"frame-{int(frame.get('index', 0)):04d}{source_frame.suffix.lower()}"
        shutil.copy2(source_frame, destination)
        image_map[str(payload_frame)] = f"assets/frames/{destination.name}"

    evidence: list[dict[str, Any]] = []
    for index, segment in enumerate(transcript_segments):
        item = {
            "id": f"watch-speech-{index + 1:06d}",
            "kind": "speech",
            "text": str(segment.get("text", "")),
            "method": payload.get("transcript", {}).get("source", "watch-skill"),
            "locator": {
                "start": float(segment.get("start", 0)),
                "end": float(segment.get("end", segment.get("start", 0))),
            },
        }
        if segment.get("speaker"):
            item["speaker"] = segment["speaker"]
        evidence.append(item)
    visual_lines = ["# 视觉证据", ""]
    ocr_count = 0
    for frame in frames:
        frame_path = str(Path(frame["path"]).expanduser().resolve())
        asset = image_map.get(frame_path)
        if not asset:
            continue
        timestamp = float(frame.get("timestamp_seconds", 0))
        evidence.append(
            {
                "id": f"watch-frame-{int(frame.get('index', 0)) + 1:06d}",
                "kind": "video_frame",
                "method": "watch-skill",
                "locator": {
                    "start": timestamp,
                    "end": timestamp,
                    "asset": asset,
                    "scene_id": frame.get("scene_id"),
                    "reason": frame.get("reason"),
                    "phash": frame.get("phash"),
                },
            }
        )
        visual_lines.extend([f"## {timestamp:.3f}秒", "", f"![]({asset})", ""])
        for block_index, block in enumerate(
            order_ocr_blocks(frame.get("ocr_blocks", []))
        ):
            ocr_count += 1
            evidence.append(
                {
                    "id": f"watch-ocr-{int(frame.get('index', 0)) + 1:04d}-{block_index + 1:04d}",
                    "kind": "ocr",
                    "text": str(block.get("text", "")),
                    "method": "watch-skill/rapidocr",
                    "confidence": block.get("confidence"),
                    "locator": {
                        "start": timestamp,
                        "end": timestamp,
                        "asset": asset,
                        "bbox": block.get("bbox"),
                    },
                }
            )
            visual_lines.append(
                f"- OCR `{block.get('confidence', 'unknown')}`：{block.get('text', '')}"
            )
        visual_lines.append("")

    (
        content,
        transcript_group_count,
        content_visual_count,
        content_ocr_line_count,
    ) = render_watch_content(
        transcript_segments, frames, image_map, include_visual=not is_audio
    )
    (output / "content.md").write_text(
        content, encoding="utf-8", newline="\n"
    )
    (output / "transcript.md").write_text(
        render_transcript(payload), encoding="utf-8", newline="\n"
    )
    transcript_candidates = payload.get("transcript_candidates", [])
    if transcript_candidates:
        candidate_lines = [
            "# ASR候选逐字稿",
            "",
            "> 候选仅用于与主逐字稿对照；未经人工真值确认，不自动覆盖主结果。",
            "",
        ]
        for candidate in transcript_candidates:
            candidate_lines.extend([f"## {candidate.get('source', 'unknown')}", ""])
            for segment in candidate.get("segments", []):
                start = float(segment.get("start", 0))
                end = float(segment.get("end", start))
                candidate_lines.append(
                    f"[{start:.3f}–{end:.3f}] {str(segment.get('text', '')).strip()}"
                )
            candidate_lines.append("")
        (output / "transcript-candidates.md").write_text(
            "\n".join(candidate_lines).rstrip() + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if not is_audio:
        (output / "visual.md").write_text(
            "\n".join(visual_lines).rstrip() + "\n", encoding="utf-8", newline="\n"
        )
    write_json(output / "extractor-result.json", payload)
    evidence_count = write_jsonl(output / "evidence.jsonl", evidence)
    warning_values = list(warnings)
    resolved_transcript_route = transcript_route(payload)
    if not transcript_segments:
        warning_values.append("没有取得字幕或ASR逐字稿；不得据此生成语音内容")
    elif resolved_transcript_route == "platform_caption":
        warning_values.append("平台字幕未经人工校对")
    elif resolved_transcript_route == "asr":
        warning_values.append("ASR逐字稿未经人工校对")
    else:
        warning_values.append("提取器逐字稿未经人工校对")
    if frames and not ocr_count:
        warning_values.append("已保留证据帧，但没有取得可用OCR文字")
    missing_frames = max(0, len(frames) - len(image_map))
    if missing_frames:
        warning_values.append(f"{missing_frames}个证据帧未能打包")
    if frames and int(perception.get("scene_count", 0) or 0) == 0:
        warning_values.append(
            "场景检测未发现切换；当前证据帧可能来自均匀回退或候选筛选，需人工抽样确认视觉覆盖"
        )
    expected_ocr_blocks = sum(
        len(frame.get("ocr_blocks", [])) for frame in frames
    )
    coverage_checks, coverage_status = coverage_report(
        {
            "transcript_segments": (
                len(transcript_segments),
                sum(1 for item in evidence if item.get("kind") == "speech"),
            ),
            "evidence_frames": (len(frames), len(image_map)),
            "ocr_blocks": (expected_ocr_blocks, ocr_count),
            "evidence_records": (
                len(transcript_segments) + len(image_map) + ocr_count,
                evidence_count,
            ),
        }
    )
    if coverage_status == "partial":
        warning_values.append("Watch提取结果未被完整打包；详见coverage_checks")
    has_any_evidence = bool(transcript_segments or image_map)
    processing_status = "partial" if has_any_evidence else "failed"
    metadata = common_metadata(
        capture_id=capture_id,
        identity=identity,
        title=resolved_title,
        source_type=source_type,
        modalities=["speech"] if is_audio else ["speech", "video", "on_screen_text"],
        route=(
            [
                "watch-skill",
                payload.get("acquisition", {}).get("acquirer", "unknown"),
                payload.get("transcript", {}).get("source", "none"),
            ]
            if is_audio
            else [
                "watch-skill",
                payload.get("acquisition", {}).get("acquirer", "unknown"),
                payload.get("transcript", {}).get("source", "none"),
                perception.get("engine", "none"),
                "ocr",
            ]
        ),
        extractor_name="Watch Skill",
        extractor_version=extractor_version,
        processing_status=processing_status,
        benchmark=benchmark,
    )
    metadata["source"]["author"] = info.get("uploader") or info.get("channel")
    metadata["media"] = payload.get("metadata", {})
    metadata["transcript"] = {
        "route": resolved_transcript_route,
        "source": payload.get("transcript", {}).get("source", "none"),
        "subtitle_file": (
            Path(str(payload.get("acquisition", {}).get("subtitle_path"))).name
            if payload.get("acquisition", {}).get("subtitle_path")
            else None
        ),
        "segment_count": len(transcript_segments),
    }
    write_json(output / "metadata.json", metadata)
    quality = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": processing_status,
        "review_status": "pending",
        "duration_seconds": payload.get("metadata", {}).get("duration_seconds", 0),
        "transcript_source": payload.get("transcript", {}).get("source", "none"),
        "transcript_route": resolved_transcript_route,
        "transcript_segment_count": len(transcript_segments),
        "content_transcript_group_count": transcript_group_count,
        "frame_count": len(image_map),
        "content_visual_count": content_visual_count,
        "content_ocr_line_count": content_ocr_line_count,
        "ocr_block_count": ocr_count,
        "ocr_reading_order": "bbox_line_then_left",
        "scene_count": perception.get("scene_count", 0),
        "candidate_frame_count": perception.get("candidate_count", 0),
        "deduped_frame_count": perception.get("deduped_count", 0),
        "evidence_count": evidence_count,
        "missing_frame_count": missing_frames,
        "coverage_status": coverage_status,
        "coverage_checks": coverage_checks,
        "warnings": warning_values,
        "human_fallback": (
            "抽样校对逐字稿"
            if is_audio
            else "抽样校对逐字稿；逐帧核对将用于Draft或Wiki的屏幕文字"
        ),
    }
    write_json(output / "quality-report.json", quality)
    raw_markdown = f"""---
schema_version: {SCHEMA_VERSION}
capture_id: {capture_id}
source_type: {source_type}
processing_status: {processing_status}
review_status: pending
benchmark: {str(bool(benchmark)).lower()}
---

# {resolved_title}

## 来源

- 来源：`{source}`
- 来源指纹：`{digest}`（内容哈希状态：{identity.get('content_hash_status', 'unknown')}）
- 提取器：Watch Skill {extractor_version}

## Raw提取物

- [可读Raw正文](content.md)：{transcript_group_count}个语音段落""" + (
        "" if is_audio else f"，{content_visual_count}个视觉段落"
    ) + f"""
- [未校对逐字稿](transcript.md)：{len(transcript_segments)}段
""" + (
        f"- [ASR候选逐字稿](transcript-candidates.md)：{len(transcript_candidates)}路候选\n"
        if transcript_candidates else ""
    ) + f"""
""" + (
        "" if is_audio else f"- [视觉证据](visual.md)：{len(image_map)}帧，{ocr_count}个OCR块\n"
    ) + f"""- [原子证据](evidence.jsonl)：{evidence_count}条
- [提取器原始结果](extractor-result.json)
- [元数据](metadata.json)
- [质量报告](quality-report.json)

## 已知限制

""" + "".join(f"- {warning}\n" for warning in warning_values)
    (output / "raw.md").write_text(raw_markdown, encoding="utf-8", newline="\n")
    return output


def parse_ocr_roi(value: str | None) -> tuple[int, int, int, int] | None:
    """Parse an explicit pixel ROI without guessing the user's content area."""
    if not value:
        return None
    try:
        values = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise ValueError("OCR ROI must be x1,y1,x2,y2 integers") from exc
    if len(values) != 4:
        raise ValueError("OCR ROI must contain exactly four integers")
    x1, y1, x2, y2 = values
    if min(values) < 0 or x2 <= x1 or y2 <= y1:
        raise ValueError("OCR ROI must satisfy 0 <= x1 < x2 and 0 <= y1 < y2")
    return values


def _adaptive_scene_detector(video_path: Path, start: float | None, end: float | None):
    from scenedetect import AdaptiveDetector, detect

    kwargs: dict[str, Any] = {}
    if start is not None:
        kwargs["start_time"] = start
    if end is not None:
        kwargs["end_time"] = end
    scenes = detect(str(video_path), AdaptiveDetector(), **kwargs)
    return [(float(item[0].seconds), float(item[1].seconds)) for item in scenes]


def _screen_change_scenes(
    video_path: Path,
    start: float | None,
    end: float | None,
    *,
    threshold: float,
    sample_seconds: float,
    roi: tuple[int, int, int, int] | None,
) -> list[tuple[float, float]]:
    """Find material screen changes with OpenCV; return scene-like spans.

    This is intentionally a transparent sampler, not semantic understanding.
    It compares one frame every ``sample_seconds`` after resizing and optional
    content crop. It cannot observe changes shorter than that sampling window.
    """
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        return []
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if total_frames else 0.0
    lo = max(0.0, float(start or 0.0))
    hi = min(duration, float(end)) if end is not None and duration else duration
    boundaries = [lo]
    if sample_seconds <= 0:
        raise ValueError("screen sample interval must be positive")
    previous = None
    second = lo
    try:
        while second <= hi:
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000.0)
            ok, frame = capture.read()
            if not ok:
                second += sample_seconds
                continue
            if roi is not None:
                x1, y1, x2, y2 = roi
                height, width = frame.shape[:2]
                frame = frame[min(y1, height):min(y2, height), min(x1, width):min(x2, width)]
                if frame.size == 0:
                    raise ValueError(f"OCR ROI {roi} is outside video frame {width}x{height}")
            sample = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
            sample = cv2.GaussianBlur(sample, (3, 3), 0)
            if previous is not None:
                difference = float(cv2.absdiff(sample, previous).mean())
                if difference >= threshold and second - boundaries[-1] >= 1.0:
                    boundaries.append(round(second, 3))
            previous = sample
            second += sample_seconds
    finally:
        capture.release()
    if hi <= lo or len(boundaries) == 1:
        return []
    return list(zip(boundaries, [*boundaries[1:], hi]))


def run_watch(args: argparse.Namespace) -> Path:
    # Watch does not expose detector/OCR strategy injection yet. Serialize the
    # short-lived module override so concurrent calls in one process cannot
    # observe each other's strategy.
    with _WATCH_OVERRIDE_LOCK:
        return _run_watch_unlocked(args)


def _run_watch_unlocked(args: argparse.Namespace) -> Path:
    if args.output.expanduser().exists() and not args.overwrite:
        raise FileExistsError(f"output already exists: {args.output.expanduser().resolve()}")
    try:
        from watch_skill.watch import watch
    except ImportError as exc:
        raise RuntimeError(
            "Watch Skill is not installed in this interpreter; run this command with its Python environment"
        ) from exc
    from watch_skill.config import get_settings
    from watch_skill.perceive import ocr as watch_ocr
    from watch_skill.perceive import scenes as watch_scenes
    from watch_skill.transcribe.types import Segment, Transcript

    work_dir = Path(tempfile.mkdtemp(prefix="oks-watch-"))
    roi = parse_ocr_roi(args.ocr_roi)
    original_scene_detector = watch_scenes.detect_scenes
    original_ocr = watch_ocr.ocr_frame
    enhanced_transcribe = None
    if args.hotwords or args.initial_prompt:
        def enhanced_transcribe(audio_path, model_size="auto", language=None):
            from faster_whisper import WhisperModel
            from watch_skill.transcribe.local import has_cuda_gpu, pick_model_size

            size = pick_model_size() if args.asr_model == "auto" else args.asr_model
            device = "cuda" if has_cuda_gpu() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            model = WhisperModel(size, device=device, compute_type=compute)
            raw_segments, _ = model.transcribe(
                str(audio_path),
                language=language,
                vad_filter=True,
                hotwords=args.hotwords,
                initial_prompt=args.initial_prompt,
                word_timestamps=True,
            )
            segments = [
                Segment(round(item.start, 2), round(item.end, 2), item.text.strip())
                for item in raw_segments if item.text.strip()
            ]
            return Transcript(segments, source=f"whisper-local ({size};context)")

    if args.video_profile == "shots":
        watch_scenes.detect_scenes = _adaptive_scene_detector
    elif args.video_profile == "screen":
        def screen_detector(video_path, start_seconds=None, end_seconds=None):
            return _screen_change_scenes(
                video_path,
                start_seconds,
                end_seconds,
                threshold=args.screen_change_threshold,
                sample_seconds=args.screen_sample_seconds,
                roi=roi,
            )

        watch_scenes.detect_scenes = screen_detector

    if roi is not None:
        def roi_ocr(image_path, min_confidence=0.5, lang=None):
            from PIL import Image
            from watch_skill.perceive.types import OcrBlock

            with Image.open(image_path) as image:
                width, height = image.size
                x1, y1, x2, y2 = roi
                if x1 >= width or y1 >= height:
                    raise ValueError(f"OCR ROI {roi} is outside frame {width}x{height}")
                clipped = (x1, y1, min(x2, width), min(y2, height))
                crop_path = work_dir / f"roi-{Path(image_path).stem}.png"
                image.crop(clipped).save(crop_path)
            blocks = original_ocr(crop_path, min_confidence=min_confidence, lang=lang)
            return [
                OcrBlock(
                    block.text,
                    (
                        block.bbox[0] + clipped[0], block.bbox[1] + clipped[1],
                        block.bbox[2] + clipped[0], block.bbox[3] + clipped[1],
                    ),
                    block.confidence,
                )
                for block in blocks
            ]

        watch_ocr.ocr_frame = roi_ocr
    setting_name = "WATCHSKILL_SUBTITLE_LANGS"
    previous_subtitle_langs = os.environ.get(setting_name)
    if args.subtitle_langs:
        os.environ[setting_name] = args.subtitle_langs
    get_settings.cache_clear()
    try:
        result = watch(
            args.source,
            max_frames=args.max_frames,
            transcript_only=args.transcript_only,
            run_ocr=not args.transcript_only,
            allow_local_whisper=not args.no_local_whisper,
            allow_cloud_stt=False,
            out_dir=work_dir,
            use_cache=True,
            whisper_model=args.asr_model,
        )
        payload = watch_payload(result)
        if (
            enhanced_transcribe is not None
            and result.acquisition.video_path is not None
            and "whisper" in str(payload.get("transcript", {}).get("source", "")).lower()
        ):
            context_transcript = enhanced_transcribe(
                result.acquisition.video_path,
                model_size=args.asr_model,
                language=(args.asr_language or result.acquisition.info.get("language")),
            )
            payload["transcript_candidates"] = [
                {
                    "source": context_transcript.source,
                    "segments": [item.to_dict() for item in context_transcript.segments],
                }
            ]
        payload["extraction_options"] = {
            "hotwords": [item.strip() for item in (args.hotwords or "").split(",") if item.strip()],
            "initial_prompt_present": bool(args.initial_prompt),
            "asr_model": args.asr_model,
            "asr_language": args.asr_language,
            "video_profile": args.video_profile,
            "ocr_roi": roi,
            "screen_change_threshold": args.screen_change_threshold,
            "screen_sample_seconds": args.screen_sample_seconds,
        }
        return package_watch_payload(
            payload,
            source=args.source,
            source_file=args.source_file,
            output_path=args.output,
            title=args.title,
            extractor_version=args.extractor_version,
            warnings=args.warning,
            benchmark=args.benchmark,
            overwrite=args.overwrite,
            frame_fallback_dir=None,
        )
    finally:
        watch_scenes.detect_scenes = original_scene_detector
        watch_ocr.ocr_frame = original_ocr
        if previous_subtitle_langs is None:
            os.environ.pop(setting_name, None)
        else:
            os.environ[setting_name] = previous_subtitle_langs
        get_settings.cache_clear()
        shutil.rmtree(work_dir, ignore_errors=True)


def rapidocr_blocks(result: Any, min_confidence: float) -> tuple[list[dict[str, Any]], int]:
    raw_texts = getattr(result, "txts", None)
    raw_boxes = getattr(result, "boxes", None)
    raw_scores = getattr(result, "scores", None)
    texts = list(raw_texts) if raw_texts is not None else []
    boxes = list(raw_boxes) if raw_boxes is not None else []
    scores = list(raw_scores) if raw_scores is not None else []
    returned_count = max(len(texts), len(boxes), len(scores))
    blocks: list[dict[str, Any]] = []
    for text, box, score in zip(texts, boxes, scores):
        confidence = float(score)
        value = str(text).strip()
        if not value or confidence < min_confidence:
            continue
        points = box.tolist() if hasattr(box, "tolist") else list(box)
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        blocks.append(
            {
                "text": value,
                "confidence": confidence,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "polygon": points,
            }
        )
    return order_ocr_blocks(blocks), returned_count


def package_image_result(
    args: argparse.Namespace, result: Any, *, elapsed_seconds: float | None = None
) -> Path:
    source = args.source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    output = prepare_output(args.output, args.overwrite)
    original_dir = output / "assets" / "original"
    original_dir.mkdir(parents=True)
    original_asset = original_dir / f"source{source.suffix.lower()}"
    shutil.copy2(source, original_asset)
    asset_reference = f"assets/original/{original_asset.name}"

    blocks, extractor_block_count = rapidocr_blocks(result, args.min_confidence)
    roi = parse_ocr_roi(getattr(args, "ocr_roi", None))
    if roi is not None:
        x1, y1, _, _ = roi
        for block in blocks:
            block["bbox"] = [
                block["bbox"][0] + x1,
                block["bbox"][1] + y1,
                block["bbox"][2] + x1,
                block["bbox"][3] + y1,
            ]
            block["polygon"] = [
                [float(point[0]) + x1, float(point[1]) + y1]
                for point in block["polygon"]
            ]
    evidence: list[dict[str, Any]] = [
        {
            "id": "rapidocr-image-000001",
            "kind": "image",
            "method": "source-image",
            "locator": {"asset": asset_reference},
        }
    ]
    for index, block in enumerate(blocks, start=1):
        evidence.append(
            {
                "id": f"rapidocr-text-{index:06d}",
                "kind": "ocr",
                "text": block["text"],
                "method": "rapidocr",
                "confidence": block["confidence"],
                "locator": {
                    "asset": asset_reference,
                    "bbox": block["bbox"],
                    "polygon": block["polygon"],
                },
            }
        )
    evidence_count = write_jsonl(output / "evidence.jsonl", evidence)
    lines = [
        "# Raw提取正文",
        "",
        "> 以下文字由RapidOCR直接提取，未经总结、改写或概念抽取。",
        "",
        f"![]({asset_reference})",
        "",
        "## OCR文字",
        "",
    ]
    if blocks:
        for index, block in enumerate(blocks, start=1):
            lines.append(
                f"- {block['text']}  `rapidocr-text-{index:06d}` "
                f"（置信度 {block['confidence']:.3f}）"
            )
    else:
        lines.append("未识别到达到置信度阈值的文字。")
    content = "\n".join(lines).rstrip() + "\n"
    (output / "content.md").write_text(content, encoding="utf-8", newline="\n")
    (output / "visual.md").write_text(content, encoding="utf-8", newline="\n")
    write_json(
        output / "extractor-result.json",
        {
            "engine": "RapidOCR",
            "returned_block_count": extractor_block_count,
            "retained_block_count": len(blocks),
            "minimum_confidence": args.min_confidence,
            "reading_order": "bbox_line_then_left",
            "ocr_roi": roi,
            "elapsed_seconds": elapsed_seconds,
            "blocks": blocks,
        },
    )

    warnings = list(args.warning)
    warnings.append("OCR文字、顺序和坐标未经人工校对；以原图为准")
    if roi is not None:
        warnings.append(f"OCR只处理用户明确指定的像素区域{roi}；区域外内容仍保留在原图中")
    rejected = extractor_block_count - len(blocks)
    if rejected:
        warnings.append(
            f"{rejected}个OCR块为空或低于置信度阈值{args.min_confidence:.2f}，未写入Raw正文"
        )
    if not blocks:
        warnings.append("未取得可用OCR文字；仅保留原图证据")
    coverage_checks, coverage_status = coverage_report(
        {
            "original_asset": (1, int(original_asset.is_file())),
            "extractor_ocr_blocks": (extractor_block_count, len(blocks)),
            "evidence_records": (1 + len(blocks), evidence_count),
        }
    )
    processing_status = "partial" if blocks else "failed"
    digest = sha256_file(source)
    title = args.title or source.stem
    capture_id = f"{datetime.now():%Y%m%d}-image-{digest[:12]}"
    metadata = common_metadata(
        capture_id=capture_id,
        identity=source_identity(str(source)),
        title=title,
        source_type="image",
        modalities=["image", "on_screen_text"],
        route=["rapidocr", "bbox", "original_asset"],
        extractor_name="RapidOCR",
        extractor_version=args.extractor_version,
        processing_status=processing_status,
        benchmark=args.benchmark,
    )
    write_json(output / "metadata.json", metadata)
    quality = {
        "schema_version": SCHEMA_VERSION,
        "processing_status": processing_status,
        "review_status": "pending",
        "extractor_ocr_block_count": extractor_block_count,
        "ocr_block_count": len(blocks),
        "rejected_ocr_block_count": rejected,
        "ocr_reading_order": "bbox_line_then_left",
        "ocr_roi": roi,
        "evidence_count": evidence_count,
        "asset_count": 1,
        "elapsed_seconds": elapsed_seconds,
        "coverage_status": coverage_status,
        "coverage_checks": coverage_checks,
        "warnings": warnings,
        "human_fallback": "对照原图抽样核对OCR文字；进入Draft或Wiki前逐项核对关键表述",
    }
    write_json(output / "quality-report.json", quality)
    raw_markdown = f"""---
schema_version: {SCHEMA_VERSION}
capture_id: {capture_id}
source_type: image
processing_status: {processing_status}
review_status: pending
benchmark: {str(bool(args.benchmark)).lower()}
---

# {title}

## 来源

- 本地文件：`{source}`
- SHA-256：`{digest}`
- 提取器：RapidOCR {args.extractor_version}

## Raw提取物

- [可读Raw正文](content.md)：{len(blocks)}个OCR块
- [视觉证据](visual.md)
- [原子证据](evidence.jsonl)：{evidence_count}条
- [提取器原始结果](extractor-result.json)
- [元数据](metadata.json)
- [质量报告](quality-report.json)
- `{asset_reference}`：原始图片

## 已知限制

""" + "".join(f"- {warning}\n" for warning in warnings)
    (output / "raw.md").write_text(raw_markdown, encoding="utf-8", newline="\n")
    return output


def run_image(args: argparse.Namespace) -> Path:
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "RapidOCR is not installed in this interpreter; run this command with its Python environment"
        ) from exc
    source = args.source.expanduser().resolve()
    roi = parse_ocr_roi(getattr(args, "ocr_roi", None))
    temporary: Path | None = None
    target = source
    if roi is not None:
        from PIL import Image

        with Image.open(source) as image:
            width, height = image.size
            x1, y1, x2, y2 = roi
            if x1 >= width or y1 >= height:
                raise ValueError(f"OCR ROI {roi} is outside image {width}x{height}")
            clipped = (x1, y1, min(x2, width), min(y2, height))
            fd, name = tempfile.mkstemp(prefix="oks-ocr-roi-", suffix=".png")
            os.close(fd)
            temporary = Path(name)
            image.crop(clipped).save(temporary)
    started = datetime.now(timezone.utc)
    try:
        result = RapidOCR()(str(target if temporary is None else temporary))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return package_image_result(args, result, elapsed_seconds=elapsed)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_bundle(bundle: Path) -> dict[str, Any]:
    bundle = bundle.expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if not bundle.is_dir():
        return {"valid": False, "bundle": str(bundle), "errors": ["bundle目录不存在"]}
    required = [
        "raw.md",
        "content.md",
        "metadata.json",
        "evidence.jsonl",
        "quality-report.json",
    ]
    for name in required:
        if not (bundle / name).is_file():
            errors.append(f"缺少必需文件：{name}")
    metadata: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    for name, target in (("metadata.json", metadata), ("quality-report.json", quality)):
        path = bundle / name
        if not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                errors.append(f"{name}必须是JSON对象")
            else:
                target.update(value)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{name}无法解析：{exc}")
    if metadata and metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append("metadata.json schema_version不受支持")
    if metadata and metadata.get("processing_status") not in {"complete", "partial", "failed"}:
        errors.append("metadata.json processing_status无效")
    evidence_count = 0
    evidence_path = bundle / "evidence.jsonl"
    if evidence_path.is_file():
        for line_number, line in enumerate(
            evidence_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                evidence = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"evidence.jsonl第{line_number}行无法解析：{exc}")
                continue
            evidence_count += 1
            if not evidence.get("kind") or not evidence.get("method"):
                errors.append(f"evidence.jsonl第{line_number}行缺少kind或method")
            if not isinstance(evidence.get("locator"), dict):
                errors.append(f"evidence.jsonl第{line_number}行缺少locator")
            asset = evidence.get("locator", {}).get("asset")
            if asset and not (bundle / asset).is_file():
                errors.append(f"evidence.jsonl第{line_number}行引用不存在资产：{asset}")
    if quality:
        expected = quality.get("evidence_count")
        if expected is not None and int(expected) != evidence_count:
            errors.append(f"质量报告证据数{expected}与实际{evidence_count}不一致")
        quality_warnings = [str(item) for item in quality.get("warnings", [])]
        warnings.extend(quality_warnings)
        checks = quality.get("coverage_checks")
        if not isinstance(checks, dict) or not checks:
            errors.append("质量报告缺少coverage_checks")
        else:
            recomputed: list[str] = []
            for name, check in checks.items():
                if not isinstance(check, dict):
                    errors.append(f"coverage_checks.{name}必须是JSON对象")
                    continue
                expected_count = check.get("expected")
                observed_count = check.get("observed")
                declared = check.get("status")
                actual = (
                    "unknown"
                    if expected_count is None
                    else "passed"
                    if observed_count == expected_count
                    else "partial"
                )
                recomputed.append(actual)
                if declared != actual:
                    errors.append(
                        f"coverage_checks.{name}状态{declared}与计数推导结果{actual}不一致"
                    )
            actual_overall = (
                "partial"
                if "partial" in recomputed
                else "passed"
                if recomputed and all(item == "passed" for item in recomputed)
                else "unknown"
            )
            if quality.get("coverage_status") != actual_overall:
                errors.append("coverage_status与coverage_checks不一致")
            if actual_overall == "partial" and not quality_warnings:
                errors.append("覆盖不完整时必须在warnings中显式说明")
    for name in ("raw.md", "content.md", "document.md", "transcript.md", "visual.md"):
        markdown_path = bundle / name
        if not markdown_path.is_file():
            continue
        for reference in markdown_asset_references(markdown_path.read_text(encoding="utf-8")):
            if is_url(reference):
                continue
            if not (markdown_path.parent / reference).is_file():
                errors.append(f"{markdown_path.name}引用不存在资产：{reference}")
    return {
        "valid": not errors,
        "bundle": str(bundle),
        "schema_version": metadata.get("schema_version"),
        "processing_status": metadata.get("processing_status"),
        "evidence_count": evidence_count,
        "errors": errors,
        "warnings": warnings,
    }


def bundle_protocol_result(bundle: Path) -> dict[str, Any]:
    """Return the Level-1 JSON envelope for one generated Raw bundle."""
    bundle = bundle.expanduser().resolve()
    validation = validate_bundle(bundle)
    metadata_path = bundle / "metadata.json"
    content_path = bundle / "content.md"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = metadata.get("source", {})
    if not isinstance(source, dict):
        source = {"value": source}
    return {
        "status": "ok" if validation["valid"] else "invalid",
        "contract": SCHEMA_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "bundle": str(bundle),
        "markdown": content_path.read_text(encoding="utf-8"),
        "markdown_path": str(content_path),
        "title": source.get("title"),
        "source": source.get("url") or source.get("path") or source.get("value"),
        "modality": metadata.get("source_type"),
        "metadata": metadata,
        "validation": validation,
    }


def emit_bundle(bundle: Path) -> int:
    result = bundle_protocol_result(bundle)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 2


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "mineru":
            return emit_bundle(package_mineru(args))
        if args.command == "markitdown":
            return emit_bundle(package_markitdown(args))
        if args.command == "watch":
            return emit_bundle(run_watch(args))
        if args.command == "watch-result":
            payload = json.loads(args.result.expanduser().resolve().read_text(encoding="utf-8"))
            return emit_bundle(
                package_watch_payload(
                    payload,
                    source=args.source,
                    source_file=args.source_file,
                    output_path=args.output,
                    title=args.title,
                    extractor_version=args.extractor_version,
                    warnings=args.warning,
                    benchmark=args.benchmark,
                    overwrite=args.overwrite,
                    frame_fallback_dir=args.result.expanduser().resolve().parent
                    / "assets"
                    / "frames",
                )
            )
        if args.command == "image":
            return emit_bundle(run_image(args))
        if args.command == "route":
            print(json.dumps(route_plan(args.source), ensure_ascii=False, indent=2))
            return 0
        if args.command == "validate":
            report = validate_bundle(args.bundle)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["valid"] else 2
        raise AssertionError(args.command)
    except Exception as exc:  # CLI boundary: failures must remain machine-readable.
        print(
            json.dumps(
                {
                    "status": "error",
                    "contract": SCHEMA_VERSION,
                    "plugin_version": PLUGIN_VERSION,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
