"""Image → RapidOCR → Raw Bundle."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oks_connector._shared import (
    order_ocr_blocks, parse_ocr_roi, prepare_output,
    sha256_file, write_json, write_jsonl, format_media_time,
)
# Import from sibling module — safe because this module is loaded lazily
from oks_connector.constants import SCHEMA_VERSION
from oks_connector._shared import common_metadata, coverage_report, source_identity


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
        blocks.append({
            "text": value, "confidence": confidence,
            "bbox": [min(xs), min(ys), max(xs), max(ys)], "polygon": points,
        })
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
                block["bbox"][0] + x1, block["bbox"][1] + y1,
                block["bbox"][2] + x1, block["bbox"][3] + y1,
            ]
            block["polygon"] = [
                [float(point[0]) + x1, float(point[1]) + y1] for point in block["polygon"]
            ]
    evidence: list[dict[str, Any]] = [
        {"id": "rapidocr-image-000001", "kind": "image", "method": "source-image",
         "locator": {"asset": asset_reference}},
    ]
    for index, block in enumerate(blocks, start=1):
        evidence.append({
            "id": f"rapidocr-text-{index:06d}", "kind": "ocr",
            "text": block["text"], "method": "rapidocr",
            "confidence": block["confidence"],
            "locator": {"asset": asset_reference, "bbox": block["bbox"], "polygon": block["polygon"]},
        })
    evidence_count = write_jsonl(output / "evidence.jsonl", evidence)
    lines = [
        "# Raw提取正文", "",
        "> 以下文字由RapidOCR直接提取，未经总结、改写或概念抽取。", "",
        f"![]({asset_reference})", "", "## OCR文字", "",
    ]
    if blocks:
        for index, block in enumerate(blocks, start=1):
            lines.append(
                f"- {block['text']}  `rapidocr-text-{index:06d}` （置信度 {block['confidence']:.3f}）"
            )
    else:
        lines.append("未识别到达到置信度阈值的文字。")
    content = "\n".join(lines).rstrip() + "\n"
    (output / "content.md").write_text(content, encoding="utf-8", newline="\n")
    (output / "visual.md").write_text(content, encoding="utf-8", newline="\n")
    write_json(output / "extractor-result.json", {
        "engine": "RapidOCR", "returned_block_count": extractor_block_count,
        "retained_block_count": len(blocks), "minimum_confidence": args.min_confidence,
        "reading_order": "bbox_line_then_left", "ocr_roi": roi,
        "elapsed_seconds": elapsed_seconds, "blocks": blocks,
    })
    warnings = list(args.warning)
    warnings.append("OCR文字、顺序和坐标未经人工校对；以原图为准")
    if roi is not None:
        warnings.append(f"OCR只处理用户明确指定的像素区域{roi}；区域外内容仍保留在原图中")
    rejected = extractor_block_count - len(blocks)
    if rejected:
        warnings.append(f"{rejected}个OCR块为空或低于置信度阈值{args.min_confidence:.2f}，未写入Raw正文")
    if not blocks:
        warnings.append("未取得可用OCR文字；仅保留原图证据")
    coverage_checks, coverage_status = coverage_report({
        "original_asset": (1, int(original_asset.is_file())),
        "extractor_ocr_blocks": (extractor_block_count, len(blocks)),
        "evidence_records": (1 + len(blocks), evidence_count),
    })
    processing_status = "partial" if blocks else "failed"
    digest = sha256_file(source)
    title = args.title or source.stem
    capture_id = f"{datetime.now():%Y%m%d}-image-{digest[:12]}"
    metadata = common_metadata(
        capture_id=capture_id, identity=source_identity(str(source)),
        title=title, source_type="image",
        modalities=["image", "on_screen_text"],
        route=["rapidocr", "bbox", "original_asset"],
        extractor_name="RapidOCR", extractor_version=args.extractor_version,
        processing_status=processing_status, benchmark=args.benchmark,
    )
    write_json(output / "metadata.json", metadata)
    quality = {
        "schema_version": SCHEMA_VERSION, "processing_status": processing_status,
        "review_status": "pending", "extractor_ocr_block_count": extractor_block_count,
        "ocr_block_count": len(blocks), "rejected_ocr_block_count": rejected,
        "ocr_reading_order": "bbox_line_then_left", "ocr_roi": roi,
        "evidence_count": evidence_count, "asset_count": 1,
        "elapsed_seconds": elapsed_seconds,
        "coverage_status": coverage_status, "coverage_checks": coverage_checks,
        "warnings": warnings,
        "human_fallback": "对照原图抽样核对OCR文字；进入Draft或Wiki前逐项核对关键表述",
    }
    write_json(output / "quality-report.json", quality)
    raw_md = (
        f"---\nschema_version: {SCHEMA_VERSION}\ncapture_id: {capture_id}\n"
        f"source_type: image\nprocessing_status: {processing_status}\n"
        f"review_status: pending\nbenchmark: {str(bool(args.benchmark)).lower()}\n---\n\n"
        f"# {title}\n\n## 来源\n\n- 本地文件：`{source}`\n- SHA-256：`{digest}`\n"
        f"- 提取器：RapidOCR {args.extractor_version}\n\n## Raw提取物\n\n"
        f"- [可读Raw正文](content.md)：{len(blocks)}个OCR块\n"
        f"- [视觉证据](visual.md)\n- [原子证据](evidence.jsonl)：{evidence_count}条\n"
        f"- [提取器原始结果](extractor-result.json)\n- [元数据](metadata.json)\n"
        f"- [质量报告](quality-report.json)\n- `{asset_reference}`：原始图片\n\n"
        f"## 已知限制\n\n" + "".join(f"- {w}\n" for w in warnings)
    )
    (output / "raw.md").write_text(raw_md, encoding="utf-8", newline="\n")
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
        result = RapidOCR()(str(source if temporary is None else temporary))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        return package_image_result(args, result, elapsed_seconds=elapsed)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
