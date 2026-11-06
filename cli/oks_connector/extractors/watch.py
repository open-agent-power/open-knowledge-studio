"""Video / Audio -> Watch Skill -> Raw Bundle.

Handles platform captions, local ASR (faster-whisper), scene detection,
frame extraction, RapidOCR, and subtitle-anchored forensic evidence.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from oks_connector._shared import (
    emit_json, emit_progress, write_json, write_jsonl,
    order_ocr_blocks, parse_ocr_roi,
    format_media_time, sha256_file, prepare_output,
)
from oks_connector.route import is_url, platform_for, route_plan
from oks_connector.constants import SCHEMA_VERSION, PLUGIN_VERSION, _WATCH_OVERRIDE_LOCK
from oks_connector._shared import common_metadata, coverage_report, source_identity



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


def _normalize_ocr_strict(value: str) -> str:
    """Normalize OCR text for similarity comparison (strips non-word chars, lowercases)."""
    return re.sub(r"\W+", "", value, flags=re.UNICODE).lower()




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
        normalized = _normalize_ocr_strict(text)
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


def subtitle_topic_anchors(segments: list[dict[str, Any]], max_frames: int) -> list[float]:
    """Choose bounded visual anchors from subtitle topic shifts, without AI inference.

    A long subtitle pause or sufficiently distant new speech segment is a
    transparent topic boundary.  The cap is shared with the visual evidence
    budget, so this never widens into a whole-video frame sweep.
    """
    if max_frames <= 0:
        return []
    anchors: list[float] = []
    previous_end: float | None = None
    previous_anchor: float | None = None
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0.0))
        gap = previous_end is not None and start - previous_end >= 2.5
        distant = previous_anchor is None or start - previous_anchor >= 45.0
        if previous_anchor is None or gap or distant:
            anchors.append(round(start, 3))
            previous_anchor = start
        previous_end = float(segment.get("end", start))
    if len(anchors) <= max_frames:
        return anchors
    if max_frames == 1:
        return anchors[:1]
    return [anchors[round(index * (len(anchors) - 1) / (max_frames - 1))] for index in range(max_frames)]


def _watch_progress(
    enabled: bool,
    timeout_seconds: float | None,
    *,
    phase_remap: dict[str, str] | None = None,
):
    started = time.monotonic()
    remap = phase_remap or {}

    def report(phase: str, fraction: float) -> None:
        label = remap.get(phase, phase)
        if timeout_seconds is None:
            eta = None
        elif fraction <= 0:
            eta = int(timeout_seconds)
        else:
            elapsed = time.monotonic() - started
            eta = max(0, int(elapsed * (1 - fraction) / fraction))
        emit_progress(enabled, label, fraction, eta)

    return report


def run_watch(args: argparse.Namespace) -> Path:
    # Watch does not expose detector/OCR strategy injection yet. Serialize the
    # short-lived module override so concurrent calls in one process cannot
    # observe each other's strategy.
    with _WATCH_OVERRIDE_LOCK:
        return _run_watch_unlocked(args)


def prepend_interpreter_bin_to_path() -> str | None:
    """Make console scripts installed with this interpreter discoverable.

    ``oks capability install watch`` installs ``yt-dlp`` into the active
    pipx/venv interpreter's bin directory.  That directory is not guaranteed
    to be in the parent shell's PATH, while Watch Skill resolves yt-dlp as an
    executable rather than as an import.
    """
    previous = os.environ.get("PATH")
    interpreter_bin = str(Path(sys.executable).parent)
    entries = (previous or "").split(os.pathsep)
    if interpreter_bin not in entries:
        os.environ["PATH"] = interpreter_bin + os.pathsep + (previous or "")
    return previous


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

    # 验证 watch-skill 接口：monkey-patch 目标必须存在
    for target_name, target_obj in [
        ("perceive.scenes.detect_scenes", watch_scenes.detect_scenes),
        ("perceive.ocr.ocr_frame", watch_ocr.ocr_frame),
    ]:
        if not callable(target_obj):
            raise RuntimeError(
                f"watch-skill 缺少预期接口 {target_name}\n"
                "当前 watch-skill 版本与此 connector 不兼容，请更新后重试。"
            )

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
    previous_path = prepend_interpreter_bin_to_path()
    if args.subtitle_langs:
        os.environ[setting_name] = args.subtitle_langs
    get_settings.cache_clear()
    try:
        tier = getattr(args, "evidence_tier", "forensic")
        transcript_only = getattr(args, "transcript_only", False) or tier == "quick"
        if transcript_only:
            phase_remap = {
                "extracting frames (scenes, dedup, OCR)": "acquiring source",
                "transcribing (captions -> local whisper)": "transcribing (platform captions)",
            }
        else:
            phase_remap = None
        progress = _watch_progress(
            getattr(args, "progress", False), args.timeout_seconds, phase_remap=phase_remap
        )
        if tier == "forensic" and not args.transcript_only:
            emit_progress(getattr(args, "progress", False), "captions_preflight", 0.08, None)
            caption_result = watch(
                args.source,
                transcript_only=True,
                run_ocr=False,
                allow_local_whisper=False,
                allow_cloud_stt=False,
                out_dir=work_dir / "captions",
                use_cache=True,
                whisper_model=args.asr_model,
                on_progress=progress,
            )
            caption_payload = watch_payload(caption_result)
            captions = caption_payload.get("transcript", {})
            anchors = subtitle_topic_anchors(captions.get("segments", []), args.max_frames)
            has_captions = transcript_route(caption_payload) == "platform_caption"
            if has_captions and anchors:
                emit_progress(getattr(args, "progress", False), "subtitle_anchored_evidence", 0.35, None)
                # Watch's perception normally detects scenes across the whole video.
                # In this tier, reserve its entire frame budget for subtitle anchors.
                watch_scenes.detect_scenes = lambda *_args, **_kwargs: []
                result = watch(
                    args.source,
                    max_frames=len(anchors),
                    cue_timestamps=anchors,
                    transcript_only=False,
                    run_ocr=True,
                    allow_local_whisper=not args.no_local_whisper,
                    allow_cloud_stt=False,
                    out_dir=work_dir / "evidence",
                    use_cache=True,
                    whisper_model=args.asr_model,
                    on_progress=progress,
                )
            else:
                args.warning.append("未取得可用平台字幕主题点；完整取证回退为全片视觉采样")
                result = watch(
                    args.source,
                    max_frames=args.max_frames,
                    transcript_only=False,
                    run_ocr=True,
                    allow_local_whisper=not args.no_local_whisper,
                    allow_cloud_stt=False,
                    out_dir=work_dir,
                    use_cache=True,
                    whisper_model=args.asr_model,
                    on_progress=progress,
                )
        else:
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
                on_progress=progress,
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
            "evidence_tier": tier,
            "subtitle_topic_anchor_seconds": anchors if tier == "forensic" and not args.transcript_only else [],
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
        if previous_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = previous_path
        get_settings.cache_clear()
        shutil.rmtree(work_dir, ignore_errors=True)
