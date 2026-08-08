"""Shared utilities — hashing, atomic writes, Rich-safe rendering.

Historical / Removed in v0.4.0: raw_bundle_adapter and extractor modules
were permanently deleted. See Git tag v0.4.0-legacy-final.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


# ── I/O helpers ───────────────────────────────────────────────────

def emit_json(value: Any, *, indent: int | None = None) -> None:
    """Write UTF-8 JSON without depending on the Windows console code page."""
    payload = json.dumps(value, ensure_ascii=False, indent=indent) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(payload.encode("utf-8"))
        buffer.flush()
        return
    sys.stdout.write(payload)
    sys.stdout.flush()


def emit_progress(enabled: bool, phase: str, fraction: float, eta_seconds: int | None) -> None:
    """Emit machine-readable progress on stderr without corrupting CLI JSON output."""
    if not enabled:
        return
    payload = {
        "event": "progress",
        "phase": phase,
        "percent": round(max(0.0, min(1.0, fraction)) * 100, 1),
        "estimated_remaining_seconds": eta_seconds,
    }
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(path: Path) -> None:
    """Persist the rename itself, per CONSTITUTION A5."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write_text(path: Path, payload: str) -> None:
    """mkstemp + fsync + os.replace + dir fsync, per CONSTITUTION P2/A5.

    Raw Bundle artifacts are the only record of a long extraction run, so a
    torn metadata.json or evidence.jsonl means redoing all of that work.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> int:
    lines = []
    for value in values:
        lines.append(json.dumps(value, ensure_ascii=False) + "\n")
    _atomic_write_text(path, "".join(lines))
    return len(lines)


def exactly_one(root: Path, pattern: str) -> Path:
    matches = sorted(root.rglob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {pattern!r} under {root}, found {len(matches)}")
    return matches[0]


def prepare_output(path: Path, overwrite: bool) -> Path:
    path = path.expanduser().resolve()
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output already exists: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# ── OCR helpers ────────────────────────────────────────────────────

def normalize_ocr_text(value: str) -> str:
    return " ".join(value.split())


def order_ocr_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Restore basic top-to-bottom, left-to-right order from OCR bboxes."""
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
            "left": left, "top": top, "right": right, "bottom": bottom,
            "center": (top + bottom) / 2, "height": max(1.0, bottom - top),
        }
        positioned.append(block)
    positioned.sort(key=lambda item: (item["_layout"]["top"], item["_layout"]["left"], item["source_index"]))
    lines: list[dict[str, Any]] = []
    for block in positioned:
        layout = block["_layout"]
        best_line: dict[str, Any] | None = None
        best_distance = float("inf")
        for line in lines:
            overlap = max(0.0, min(layout["bottom"], line["bottom"]) - max(layout["top"], line["top"]))
            overlap_ratio = overlap / min(layout["height"], line["height"])
            distance = abs(layout["center"] - line["center"])
            tolerance = max(layout["height"], line["height"]) * 0.6
            if (overlap_ratio >= 0.4 or distance <= tolerance) and distance < best_distance:
                best_line = line
                best_distance = distance
        if best_line is None:
            lines.append({"top": layout["top"], "bottom": layout["bottom"], "center": layout["center"],
                          "height": layout["height"], "blocks": [block]})
            continue
        best_line["blocks"].append(block)
        best_line["top"] = min(best_line["top"], layout["top"])
        best_line["bottom"] = max(best_line["bottom"], layout["bottom"])
        best_line["center"] = (best_line["top"] + best_line["bottom"]) / 2
        best_line["height"] = max(1.0, best_line["bottom"] - best_line["top"])
    ordered: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: (item["top"], item["center"])):
        for block in sorted(line["blocks"], key=lambda item: (item["_layout"]["left"], item["source_index"])):
            block.pop("_layout", None)
            ordered.append(block)
    ordered.extend(unpositioned)
    return ordered


def parse_ocr_roi(raw: str | None) -> tuple[int, int, int, int] | None:
    """Parse an OCR ROI string ``x1,y1,x2,y2``, or return None."""
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(f"OCR ROI must be x1,y1,x2,y2, got: {raw!r}")
    coords = tuple(int(p) for p in parts)
    x1, y1, x2, y2 = coords
    if min(coords) < 0 or x2 <= x1 or y2 <= y1:
        raise ValueError(f"OCR ROI must satisfy 0 <= x1 < x2 and 0 <= y1 < y2, got: {raw!r}")
    return coords  # type: ignore[return-value]


def format_media_time(seconds: float) -> str:
    """Format seconds as mm:ss, or hh:mm:ss for durations >= 1 hour."""
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

from constants import SCHEMA_VERSION


def markdown_asset_references(markdown: str) -> list[str]:
    """Extract asset references (images) from a Markdown string.

    Returns a list of target paths found in ``![alt](target)`` and
    ``<img src="target">`` patterns.  Pure utility — no network, no filesystem.
    """
    import re as _re
    values = _re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    values.extend(_re.findall(r'<img\s+[^>]*src=["\']([^"\']+)', markdown))
    return [value.strip().split()[0].strip("<>") for value in values]


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


# ── source identity ────────────────────────────────────────────────

from route import is_url, platform_for

def source_identity(
    source: str,
    source_file: Path | None = None,
    content_file: Path | None = None,
) -> dict:
    """Build a content-addressable identity dict for one source."""
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
