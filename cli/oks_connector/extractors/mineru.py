"""PDF → MinerU → Raw Bundle."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from oks_connector._shared import exactly_one, prepare_output, sha256_file, write_json, write_jsonl
from oks_connector.constants import SCHEMA_VERSION
from oks_connector._shared import common_metadata, coverage_report, source_identity


def mineru_evidence(
    entries: list[dict[str, Any]], image_map: dict[str, str]
) -> Iterable[dict[str, Any]]:
    for index, entry in enumerate(entries):
        kind = str(entry.get("type", "unknown"))
        evidence: dict[str, Any] = {
            "id": f"mineru-{index + 1:06d}",
            "kind": kind,
            "method": "mineru",
            "locator": {"page": int(entry.get("page_idx", 0)) + 1},
        }
        if entry.get("bbox") is not None:
            evidence["locator"]["bbox"] = entry["bbox"]
        text = entry.get("text")
        if text:
            evidence["text"] = text
        image_path = entry.get("img_path")
        if image_path:
            normalized = Path(str(image_path)).name
            evidence["locator"]["asset"] = image_map.get(normalized, f"assets/images/{normalized}")
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
    evidence_count = write_jsonl(output / "evidence.jsonl", mineru_evidence(entries, image_map))
    formula_candidate_count = 0
    formula_candidates_path = getattr(args, "formula_candidates", None)
    if formula_candidates_path is not None:
        formula_candidates_path = formula_candidates_path.expanduser().resolve()
        formula_payload = json.loads(formula_candidates_path.read_text(encoding="utf-8"))
        formula_candidate_count = int(formula_payload.get("region_count", 0))
        write_json(output / "formula-candidates.json", formula_payload)

    warnings = list(args.warning) + [
        "MinerU文本、OCR和公式结果未经人工逐项校对",
        "公式、上下标、矢量和复杂表格可能误识别；以原PDF页面为准",
    ]
    if formula_candidate_count:
        warnings.append(f"{formula_candidate_count}个独立公式块有第二提取候选；未自动选择或覆盖MinerU结果")
    image_references = len(re.findall(r"(?:!\[|<img\s)", document))
    expected_image_assets = {Path(str(item["img_path"])).name for item in entries if item.get("img_path")}
    observed_image_assets = sum(1 for name in expected_image_assets if name in image_map)
    coverage_checks, coverage_status = coverage_report({
        "extractor_entries": (len(entries), evidence_count),
        "extractor_image_assets": (len(expected_image_assets), observed_image_assets),
    })
    if coverage_status == "partial":
        warnings.append("MinerU提取结果未被完整打包；详见coverage_checks")
    processing_status = "partial" if warnings else "complete"
    digest = sha256_file(source)
    title = args.title or source.stem
    capture_id = f"{datetime.now():%Y%m%d}-document-{digest[:12]}"
    metadata = common_metadata(
        capture_id=capture_id, identity=source_identity(str(source)),
        title=title, source_type="document",
        modalities=["text", "layout", "formula", "image"],
        route=["mineru", "markdown", "page_evidence", "asset_copy"],
        extractor_name="MinerU", extractor_version=args.extractor_version,
        processing_status=processing_status, benchmark=args.benchmark,
    )
    write_json(output / "metadata.json", metadata)

    quality = {
        "schema_version": SCHEMA_VERSION, "processing_status": processing_status,
        "review_status": "pending", "evidence_count": evidence_count,
        "page_count": max((int(item.get("page_idx", 0)) + 1 for item in entries), default=0),
        "asset_count": len(image_map), "markdown_image_references": image_references,
        "unresolved_asset_references": max(0, image_references - len(image_map)),
        "formula_candidate_region_count": formula_candidate_count,
        "coverage_status": coverage_status, "coverage_checks": coverage_checks,
        "warnings": warnings,
        "human_fallback": "抽样核对每页正文；逐项核对将进入Draft或Wiki的公式",
    }
    write_json(output / "quality-report.json", quality)

    raw_md = (
        f"---\nschema_version: {SCHEMA_VERSION}\ncapture_id: {capture_id}\n"
        f"source_type: document\nprocessing_status: {processing_status}\n"
        f"review_status: pending\nbenchmark: {str(bool(args.benchmark)).lower()}\n---\n\n"
        f"# {title}\n\n## 来源\n\n- 本地文件：`{source}`\n- SHA-256：`{digest}`\n"
        f"- 提取器：MinerU {args.extractor_version}\n\n## Raw提取物\n\n"
        f"- [可读Raw正文](content.md)\n- [文档正文](document.md)\n"
        + (f"- [公式候选](formula-candidates.json)：{formula_candidate_count}个独立公式块\n" if formula_candidate_count else "")
        + f"- [原子证据](evidence.jsonl)：{evidence_count}条，保留页码和可用坐标\n"
        f"- [元数据](metadata.json)\n- [质量报告](quality-report.json)\n"
        f"- `assets/images/`：{len(image_map)}个图片证据\n\n## 已知限制\n\n"
        + "".join(f"- {w}\n" for w in warnings)
    )
    (output / "raw.md").write_text(raw_md, encoding="utf-8", newline="\n")
    return output
