#!/usr/bin/env python3
"""Run PaddleOCR's PP-FormulaNet on MinerU equation crops.

The script preserves MinerU's original LaTeX and adds a second candidate.  It
does not choose a winner or rewrite the Raw document.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="PP-FormulaNet_plus-M")
    parser.add_argument("--max-regions", type=int, default=20)
    return parser


def exactly_one(root: Path, pattern: str) -> Path:
    values = sorted(root.rglob(pattern))
    if len(values) != 1:
        raise RuntimeError(f"expected one {pattern} under {root}, found {len(values)}")
    return values[0]


def candidate_regions(result_dir: Path, maximum: int) -> list[dict]:
    content_list = exactly_one(result_dir, "*_content_list.json")
    items = json.loads(content_list.read_text(encoding="utf-8"))
    regions = []
    for index, item in enumerate(items):
        if item.get("type") != "equation" or not item.get("img_path"):
            continue
        image = content_list.parent / str(item["img_path"])
        if not image.is_file():
            continue
        regions.append(
            {
                "source_index": index,
                "page": int(item.get("page_idx", 0)) + 1,
                "bbox": item.get("bbox"),
                "image": image,
                "mineru_latex": str(item.get("text", "")).strip(),
            }
        )
        if len(regions) >= maximum:
            break
    return regions


def main() -> int:
    args = build_parser().parse_args()
    if args.max_regions <= 0:
        raise ValueError("max-regions must be positive")
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "BOS")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import FormulaRecognition

    result_dir = args.result_dir.expanduser().resolve()
    regions = candidate_regions(result_dir, args.max_regions)
    model = FormulaRecognition(model_name=args.model)
    started = time.perf_counter()
    candidates = []
    errors = []
    for region in regions:
        try:
            predictions = list(model.predict(input=str(region["image"]), batch_size=1))
            payload = predictions[0].json["res"] if predictions else {}
        except Exception as exc:
            errors.append(
                {
                    "source_index": region["source_index"],
                    "page": region["page"],
                    "image": str(region["image"]),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        candidates.append(
            {
                "source_index": region["source_index"],
                "page": region["page"],
                "bbox": region["bbox"],
                "image": str(region["image"].relative_to(result_dir)).replace("\\", "/"),
                "candidates": [
                    {"method": "mineru", "latex": region["mineru_latex"]},
                    {"method": args.model, "latex": str(payload.get("rec_formula", ""))},
                ],
            }
        )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": "raw-formula-candidates/v0.1",
                "model": args.model,
                "region_count": len(candidates),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "selection_policy": "none",
                "error_count": len(errors),
                "errors": errors,
                "regions": candidates,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
