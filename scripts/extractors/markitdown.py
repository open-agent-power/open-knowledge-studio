"""Office documents + HTML + text  ->  MarkItDown  ->  Raw Bundle."""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from route import is_url
from _shared import prepare_output, sha256_file, write_json, write_jsonl
from constants import SCHEMA_VERSION
from _shared import common_metadata, coverage_report, source_identity


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
    suffix = source.suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        stream_info = StreamInfo(
            mimetype="text/plain",
            extension=suffix,
            charset="utf-8",
            filename=source.name,
            local_path=str(source),
        )
    elif suffix in {".html", ".htm"}:
        header = source.read_bytes()[:8192].decode("ascii", errors="ignore")
        charset_match = re.search(
            r"charset\s*=\s*[\"']?([a-zA-Z0-9._-]+)", header, re.IGNORECASE
        )
        stream_info = StreamInfo(
            mimetype="text/html",
            extension=suffix,
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
