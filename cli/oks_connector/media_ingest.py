#!/usr/bin/env python3
"""Prepare local videos for human-approved Open Knowledge Studio intake.

The command has two explicit phases:

1. ``prepare`` writes an evidence bundle under ``.oks/intake/``.
2. ``approve`` writes the reviewed candidate to ``raw/misc/`` only after a
   human passes ``--confirm-human-review``.

It does not call an LLM, summarize content, write drafts, or write wiki pages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass
class Probe:
    duration_seconds: float
    file_size_bytes: int
    video_codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    subtitle_streams: int


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and approve oral-video Raw materials."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="Generate a review bundle under .oks/intake/."
    )
    prepare.add_argument("video", type=Path)
    prepare.add_argument("--title", required=True)
    prepare.add_argument("--source-url")
    prepare.add_argument("--source-author")
    prepare.add_argument("--save-reason", required=True)
    prepare.add_argument("--question")
    prepare.add_argument("--relation")
    prepare.add_argument("--tags", nargs="*", default=[])
    prepare.add_argument("--source-complete", action="store_true")
    prepare.add_argument("--model", default="small")
    prepare.add_argument("--device", default="cpu")
    prepare.add_argument("--compute-type", default="int8")
    prepare.add_argument(
        "--content-kind",
        choices=("oral", "screen"),
        default="oral",
        help="oral keeps sparse evidence; screen captures scene changes.",
    )
    prepare.add_argument(
        "--frame-strategy",
        choices=("auto", "periodic", "scene"),
        default="auto",
    )
    prepare.add_argument("--frame-interval", type=float, default=30.0)
    prepare.add_argument("--max-frames", type=int, default=12)
    prepare.add_argument("--overwrite", action="store_true")
    prepare.add_argument("--root", type=Path)

    approve = subparsers.add_parser(
        "approve", help="Promote a human-reviewed candidate into raw/misc/."
    )
    approve.add_argument("capture_id")
    approve.add_argument("--confirm-human-review", action="store_true")
    approve.add_argument("--review-note", required=True)
    approve.add_argument("--force", action="store_true")
    approve.add_argument("--root", type=Path)
    return parser


def repo_root(explicit: Path | None = None) -> Path:
    root = explicit or Path(os.environ.get("OKS_ROOT", Path.cwd()))
    root = root.expanduser().resolve()
    if not (root / "raw" / "misc").is_dir():
        raise ValueError(f"not an Open Knowledge Studio root: {root}")
    return root


def ensure_descendant(path: Path, parent: Path) -> None:
    resolved_path = path.resolve()
    resolved_parent = parent.resolve()
    if resolved_path == resolved_parent or resolved_parent not in resolved_path.parents:
        raise ValueError(f"unsafe path outside expected directory: {resolved_path}")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.stem, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.stem, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip().lower())
    return slug.strip("-")[:80] or "video-note"


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def format_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def probe_video(path: Path) -> Probe:
    try:
        import av
    except ImportError as exc:
        raise RuntimeError(
            "missing media dependencies; install scripts/media_ingest_requirements.txt"
        ) from exc

    with av.open(str(path)) as container:
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        video = next(iter(container.streams.video), None)
        audio = next(iter(container.streams.audio), None)
        fps = float(video.average_rate) if video and video.average_rate else None
        channels = None
        if audio and audio.codec_context.layout:
            channels = audio.codec_context.layout.nb_channels
        return Probe(
            duration_seconds=round(duration, 3),
            file_size_bytes=path.stat().st_size,
            video_codec=video.codec_context.name if video else None,
            width=video.codec_context.width if video else None,
            height=video.codec_context.height if video else None,
            fps=round(fps, 3) if fps else None,
            audio_codec=audio.codec_context.name if audio else None,
            audio_sample_rate=audio.codec_context.sample_rate if audio else None,
            audio_channels=channels,
            subtitle_streams=len(container.streams.subtitles),
        )


def transcribe_video(
    source: Path, model_name: str, device: str, compute_type: str
) -> tuple[dict[str, Any], float]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "missing ASR dependencies; install scripts/media_ingest_requirements.txt"
        ) from exc

    started = time.perf_counter()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    iterator, info = model.transcribe(
        str(source), language="zh", vad_filter=True, beam_size=5
    )
    segments = [
        {
            "id": segment.id,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
            "avg_logprob": round(segment.avg_logprob, 4),
            "no_speech_prob": round(segment.no_speech_prob, 4),
        }
        for segment in iterator
    ]
    result = {
        "engine": "faster-whisper",
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "language": info.language,
        "language_probability": round(info.language_probability, 4),
        "duration": round(info.duration, 3),
        "duration_after_vad": round(info.duration_after_vad, 3),
        "segments": segments,
    }
    return result, round(time.perf_counter() - started, 2)


def periodic_frame_times(duration: float, interval: float) -> list[float]:
    if interval <= 0:
        raise ValueError("frame interval must be positive")
    if duration <= 0:
        return []
    values = [min(5.0, duration / 2)]
    current = interval
    while current < duration - 2:
        values.append(current)
        current += interval
    if duration > 10:
        values.append(duration - 5)
    return dedupe_times(values)


def dedupe_times(values: Iterable[float], minimum_gap: float = 1.0) -> list[float]:
    result: list[float] = []
    for value in sorted(max(0.0, float(item)) for item in values):
        if not result or value - result[-1] >= minimum_gap:
            result.append(round(value, 3))
    return result


def _limit_evenly(values: list[float], maximum: int) -> list[float]:
    if maximum <= 0:
        raise ValueError("max frames must be positive")
    if len(values) <= maximum:
        return values
    if maximum == 1:
        return [values[len(values) // 2]]
    indexes = {
        round(index * (len(values) - 1) / (maximum - 1))
        for index in range(maximum)
    }
    return [values[index] for index in sorted(indexes)]


def scene_frame_times(
    source: Path,
    duration: float,
    interval: float,
    max_frames: int,
) -> list[float]:
    """Select visual evidence using PySceneDetect with periodic fallback.

    Screen recordings can contain long static stretches, so scene midpoints are
    supplemented with sparse periodic samples when too few transitions exist.
    """
    try:
        from scenedetect import AdaptiveDetector, detect
    except ImportError as exc:
        raise RuntimeError(
            "scene frame selection requires scenedetect; install "
            "scripts/media_ingest_requirements.txt"
        ) from exc

    scenes = detect(
        str(source),
        AdaptiveDetector(min_scene_len=1.5),
        show_progress=False,
        start_in_scene=True,
    )
    values = [
        (start.seconds + end.seconds) / 2
        for start, end in scenes
        if end.seconds > start.seconds
    ]
    if len(values) < min(4, max_frames):
        values.extend(periodic_frame_times(duration, interval))
    return _limit_evenly(dedupe_times(values), max_frames)


def select_frame_times(
    source: Path,
    duration: float,
    content_kind: str,
    strategy: str,
    interval: float,
    max_frames: int,
) -> tuple[str, list[float]]:
    resolved = strategy
    if resolved == "auto":
        resolved = "periodic"
    if resolved == "scene":
        return resolved, scene_frame_times(source, duration, interval, max_frames)
    return resolved, _limit_evenly(
        periodic_frame_times(duration, interval), max_frames
    )


def extract_frames(
    source: Path, timestamps: list[float], assets_dir: Path
) -> list[dict[str, Any]]:
    try:
        import av
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "missing frame dependencies; install scripts/media_ingest_requirements.txt"
        ) from exc

    frames: list[dict[str, Any]] = []
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        for requested in timestamps:
            container.seek(int(requested * av.time_base), any_frame=False, backward=True)
            chosen = None
            for frame in container.decode(stream):
                if float(frame.time or 0.0) >= requested:
                    chosen = frame
                    break
            if chosen is None:
                continue
            actual = round(float(chosen.time or requested), 3)
            filename = f"frame-{actual:010.3f}s.jpg"
            image = chosen.to_image()
            image.thumbnail((1600, 1000), Image.Resampling.LANCZOS)
            target = assets_dir / filename
            temporary = target.with_suffix(".writing.jpg")
            image.save(temporary, quality=88)
            atomic_write_bytes(target, temporary.read_bytes())
            temporary.unlink(missing_ok=True)
            frames.append(
                {
                    "requested_seconds": requested,
                    "actual_seconds": actual,
                    "path": f"assets/{filename}",
                }
            )
    return frames


def transcript_text(transcript: dict[str, Any]) -> str:
    return "\n".join(
        f"[{format_timestamp(segment['start'])} --> "
        f"{format_timestamp(segment['end'])}] {segment['text']}"
        for segment in transcript["segments"]
    ) + "\n"


def render_candidate(
    metadata: dict[str, Any],
    probe: Probe,
    transcript: dict[str, Any],
    frames: list[dict[str, Any]],
) -> str:
    tags = ["video", metadata["content_kind"], *metadata["tags"]]
    tag_text = ", ".join(yaml_scalar(tag) for tag in dict.fromkeys(tags))
    warnings = ["ASR未经人工逐字校对"]
    if metadata["content_kind"] == "screen":
        warnings.append("屏幕文字尚未OCR")
    else:
        warnings.append("烧录字幕尚未OCR")
    if not metadata["source_complete"]:
        warnings.append("输入只是原来源片段")
    yaml_lines = [
        "---",
        f"title: {yaml_scalar(metadata['title'])}",
        f"source: {yaml_scalar(metadata.get('source_url') or str(metadata['source_path']))}",
        f"date: {metadata['collected_date']}",
        "type: note",
        f"tags: [{tag_text}]",
        f"capture_id: {yaml_scalar(metadata['capture_id'])}",
        f"content_sha256: {yaml_scalar(metadata['content_sha256'])}",
        f"source_complete: {yaml_scalar(metadata['source_complete'])}",
        f"content_kind: {yaml_scalar(metadata['content_kind'])}",
        f"frame_strategy: {yaml_scalar(metadata['frame_strategy'])}",
        "processing_status: partial",
        "review_status: pending",
        "processing_warnings:",
        *(f"  - {yaml_scalar(warning)}" for warning in warnings),
        "---",
    ]
    frame_lines = "\n".join(
        f"- `{format_timestamp(frame['actual_seconds'])}`："
        f"[{frame['path']}]({frame['path']})"
        for frame in frames
    ) or "- 未抽取到关键帧"
    transcript_lines = transcript_text(transcript).rstrip()
    return f"""{chr(10).join(yaml_lines)}

# {metadata['title']}

## 来源事实

- 平台或链接：{metadata.get('source_url') or '本地文件'}
- 作者（提交者填写）：{metadata.get('source_author') or '未确认'}
- 输入方式：本地视频文件
- 内容类型：{metadata['content_kind']}
- 本地文件：`{metadata['source_path']}`
- 文件哈希：`{metadata['content_sha256']}`
- 录制时长：{probe.duration_seconds}秒
- 来源是否完整：{metadata['source_complete']}
- 视频：{probe.video_codec or '无'}，{probe.width or '?'}×{probe.height or '?'}，{probe.fps or '?'}fps
- 音频：{probe.audio_codec or '无'}，{probe.audio_sample_rate or '?'}Hz，{probe.audio_channels or '?'}声道
- 内嵌字幕流：{probe.subtitle_streams}

## 人类采集注释

- 保存原因：{metadata['save_reason']}
- 想解决的问题：{metadata.get('question') or '未提供'}
- 相关项目或学习目标：{metadata.get('relation') or '未提供'}

> 本节来自素材提交者，不代表原作者观点。

## 机器原始转写

```text
{transcript_lines}
```

该转写由`faster-whisper {transcript['model']}`生成，未经人工改写。

## 视觉证据

{frame_lines}

本阶段不对证据帧做视觉理解或OCR；截图用于保留画面证据并支撑后续纠错。

## 人工纠错记录

| 时间 | 原始结果 | 修正结果 | 依据 |
|---|---|---|---|
| 尚未审查 | — | — | — |

## 未解决问题

- ASR中的同音词和断句尚未校对；
- 烧录字幕尚未提取；
- 输入不完整时，不能推断缺失部分；
- 未生成人工总结、知识结论或Wiki内容。
"""


def render_quality(
    metadata: dict[str, Any],
    probe: Probe,
    transcript: dict[str, Any],
    frames: list[dict[str, Any]],
    elapsed: float,
    total_elapsed: float,
) -> str:
    blockers = ["ASR未经人工校对"]
    blockers.append(
        "屏幕文字尚未OCR"
        if metadata["content_kind"] == "screen"
        else "烧录字幕尚未OCR"
    )
    if not metadata["source_complete"]:
        blockers.append("来源仅为片段")
    return f"""# 媒体录入质量报告

- Capture ID：`{metadata['capture_id']}`
- 处理状态：`partial`
- 审核状态：`pending`
- 自动写入Raw：否
- 阻断原因：{'；'.join(blockers)}

| 项目 | 结果 |
|---|---|
| 输入文件 | `{metadata['source_path']}` |
| SHA-256 | `{metadata['content_sha256']}` |
| 时长 | {probe.duration_seconds}秒 |
| ASR片段 | {len(transcript['segments'])} |
| ASR耗时 | {elapsed}秒 |
| 总处理耗时 | {total_elapsed}秒 |
| 取帧策略 | {metadata['frame_strategy']} |
| 关键帧 | {len(frames)}张 |
| OCR | 未执行 |
| 人工审查 | 未执行 |

## 审核要求

- [ ] 来源、标题和作者正确
- [ ] 保存原因表达准确
- [ ] 抽查ASR主要观点没有严重偏差
- [ ] 不确定内容已标记
- [ ] 确认允许写入`raw/misc/`
"""


def prepare_capture(args: argparse.Namespace) -> Path:
    processing_started = time.perf_counter()
    root = repo_root(args.root)
    source = args.video.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = sha256_file(source)
    capture_id = f"{date.today():%Y%m%d}-video-{digest[:12]}"
    intake_dir = root / ".oks" / "intake"
    capture_dir = intake_dir / capture_id
    ensure_descendant(capture_dir, intake_dir)
    if capture_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"capture already exists: {capture_dir}; pass --overwrite"
            )
        shutil.rmtree(capture_dir)
    assets_dir = capture_dir / "assets"
    assets_dir.mkdir(parents=True)

    print(f"[{capture_id}] probe and hash", flush=True)
    probe = probe_video(source)
    print(f"[{capture_id}] transcribe", flush=True)
    transcript, elapsed = transcribe_video(
        source, args.model, args.device, args.compute_type
    )
    print(f"[{capture_id}] select and extract evidence frames", flush=True)
    frame_strategy, frame_times = select_frame_times(
        source,
        probe.duration_seconds,
        args.content_kind,
        args.frame_strategy,
        args.frame_interval,
        args.max_frames,
    )
    frames = extract_frames(
        source,
        frame_times,
        assets_dir,
    )
    total_elapsed = round(time.perf_counter() - processing_started, 2)

    metadata = {
        "capture_id": capture_id,
        "title": args.title,
        "slug": slugify(args.title),
        "source_path": str(source),
        "source_url": args.source_url,
        "source_author": args.source_author,
        "save_reason": args.save_reason,
        "question": args.question,
        "relation": args.relation,
        "tags": args.tags,
        "content_kind": args.content_kind,
        "frame_strategy": frame_strategy,
        "source_complete": args.source_complete,
        "collected_date": date.today().isoformat(),
        "content_sha256": digest,
    }
    atomic_write_text(
        capture_dir / "transcript.txt", transcript_text(transcript)
    )
    atomic_write_text(
        capture_dir / "transcript.json",
        json.dumps(transcript, ensure_ascii=False, indent=2),
    )
    atomic_write_text(
        capture_dir / "candidate.md",
        render_candidate(metadata, probe, transcript, frames),
    )
    atomic_write_text(
        capture_dir / "quality-report.md",
        render_quality(
            metadata, probe, transcript, frames, elapsed, total_elapsed
        ),
    )
    report = {
        **metadata,
        "probe": asdict(probe),
        "asr_elapsed_seconds": elapsed,
        "processing_elapsed_seconds": total_elapsed,
        "asr_segments": len(transcript["segments"]),
        "frames": frames,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_text(
        capture_dir / "manifest.json",
        json.dumps(report, ensure_ascii=False, indent=2),
    )
    print(f"prepared: {capture_dir}", flush=True)
    print(
        f"review candidate.md, then run approve {capture_id} "
        "--confirm-human-review --review-note <note>",
        flush=True,
    )
    return capture_dir


def _find_duplicate(raw_dir: Path, digest: str) -> Path | None:
    marker = f"content_sha256: {yaml_scalar(digest)}"
    for path in raw_dir.rglob("*.md"):
        try:
            if marker in path.read_text(encoding="utf-8"):
                return path
        except OSError:
            continue
    return None


def approve_capture(
    root: Path,
    capture_id: str,
    review_note: str,
    confirmed: bool,
    force: bool = False,
) -> Path:
    if not confirmed:
        raise PermissionError("approval requires --confirm-human-review")
    capture_dir = root / ".oks" / "intake" / capture_id
    manifest_path = capture_dir / "manifest.json"
    candidate_path = capture_dir / "candidate.md"
    quality_path = capture_dir / "quality-report.md"
    if (
        not manifest_path.is_file()
        or not candidate_path.is_file()
        or not quality_path.is_file()
    ):
        raise FileNotFoundError(f"incomplete capture bundle: {capture_dir}")
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_misc = root / "raw" / "misc"
    duplicate = _find_duplicate(raw_misc, metadata["content_sha256"])
    if duplicate and not force:
        raise FileExistsError(f"same source already approved: {duplicate}")

    destination = raw_misc / f"{metadata['collected_date']}-{metadata['slug']}.md"
    if destination.exists() and not force:
        raise FileExistsError(f"destination already exists: {destination}")
    content = candidate_path.read_text(encoding="utf-8")
    content = content.replace("review_status: pending", "review_status: approved", 1)
    content = content.replace(
        "](assets/", f"](assets/{capture_id}/"
    )
    content += (
        "\n\n## 人工审核\n\n"
        f"- 审核日期：{date.today().isoformat()}\n"
        f"- 审核说明：{review_note}\n"
        "- 操作：提交者显式确认后写入Raw。\n"
    )
    source_assets = capture_dir / "assets"
    destination_assets = raw_misc / "assets" / capture_id
    for source_asset in source_assets.glob("*"):
        if source_asset.is_file():
            atomic_write_bytes(
                destination_assets / source_asset.name, source_asset.read_bytes()
            )
    atomic_write_text(destination, content)
    return destination


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        prepare_capture(args)
        return 0
    root = repo_root(args.root)
    destination = approve_capture(
        root=root,
        capture_id=args.capture_id,
        review_note=args.review_note,
        confirmed=args.confirm_human_review,
        force=args.force,
    )
    print(f"approved raw material: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
