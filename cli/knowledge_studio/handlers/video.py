"""Video handler — multi-modal video processing pipeline.

Pipeline:
    Video → ffprobe metadata → ffmpeg frame extraction (9 frames/segment)
    → subtitle extraction (or Whisper STT if no subtitles)
    → Vision model analyzes frame batches
    → Merge: timeline + subtitles + frame descriptions → structured Markdown

Dependencies: ffmpeg (frames), whisper (STT), vision API key (frame analysis)

Config (from ~/.oks/config.json → handlers.video):
    frame_interval: seconds between frame extractions (default: 30)
    frames_per_batch: frames per vision API call (default: 9)
    whisper_model: whisper model size (default: "base")
    vision_api_key: API key for vision model
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError
from knowledge_studio.handlers.detect import VIDEO_EXTENSIONS, VIDEO_HOSTS


class VideoHandler(BaseHandler):
    name = "video"
    modalities = ["mp4", "mov", "avi", "mkv", "url:youtube", "url:bilibili"]
    description = "Video: ffmpeg frame extraction + Whisper subtitle + Vision analysis"

    def detect(self, input_path: str) -> bool:
        if input_path.startswith(("http://", "https://")):
            from urllib.parse import urlparse
            host = urlparse(input_path).hostname or ""
            return host in VIDEO_HOSTS
        return Path(input_path).suffix.lower() in VIDEO_EXTENSIONS

    def is_available(self) -> bool:
        return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        if not self.is_available():
            raise HandlerError(
                self.name, "ffmpeg not found",
                hint="Install: brew install ffmpeg",
            )

        cfg = config or {}
        frame_interval = cfg.get("frame_interval", 30)
        frames_per_batch = cfg.get("frames_per_batch", 9)
        whisper_model = cfg.get("whisper_model", "base")

        video_path = self._ensure_local(input_path, cfg)
        duration = self._get_duration(video_path)
        subtitle_text = self._extract_subtitles(video_path, whisper_model, cfg)
        frames = self._extract_frames(video_path, frame_interval, duration)
        frame_descriptions = self._analyze_frames(frames, frames_per_batch, cfg)

        markdown = self._build_markdown(video_path, duration, subtitle_text, frame_descriptions)

        return HandlerResult(
            markdown=markdown,
            title=Path(video_path).stem,
            source=input_path,
            modality="video",
            handler_name=self.name,
            metadata={
                "duration_seconds": duration,
                "frame_count": len(frames),
                "frame_interval": frame_interval,
                "frames_per_batch": frames_per_batch,
                "subtitle_extracted": bool(subtitle_text),
            },
        )

    def _ensure_local(self, input_path: str, cfg: dict) -> str:
        if not input_path.startswith(("http://", "https://")):
            return input_path
        raise HandlerError(
            self.name, "URL video download not yet implemented",
            hint="Download manually and pass local file path, or install yt-dlp",
        )

    def _get_duration(self, video_path: str) -> float:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            import json
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
        return 0.0

    def _extract_subtitles(self, video_path: str, whisper_model: str, cfg: dict) -> str:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams",
             "-select_streams", "s", video_path],
            capture_output=True, text=True,
        )
        has_subtitle = result.returncode == 0 and '"stream"' in result.stdout

        if has_subtitle:
            sub_result = subprocess.run(
                ["ffmpeg", "-i", video_path, "-map", "0:s:0", "-f", "srt", "-"],
                capture_output=True, text=True,
            )
            if sub_result.returncode == 0 and sub_result.stdout:
                return sub_result.stdout

        return self._whisper_stt(video_path, whisper_model, cfg)

    def _whisper_stt(self, audio_path: str, model_size: str, cfg: dict) -> str:
        try:
            import whisper
        except ImportError:
            raise HandlerError(
                self.name, "whisper not installed",
                hint="pip install openai-whisper",
            )
        model = whisper.load_model(model_size)
        result = model.transcribe(audio_path)
        return result.get("text", "")

    def _extract_frames(self, video_path: str, interval: int, duration: float) -> list[str]:
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="oks_frames_")
        fps = 1.0 / interval if interval > 0 else 0.033
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}",
             "-q:v", "2", f"{tmpdir}/frame_%04d.jpg"],
            capture_output=True,
        )
        frames = sorted(Path(tmpdir).glob("frame_*.jpg"))
        return [str(f) for f in frames]

    def _analyze_frames(self, frames: list[str], batch_size: int, cfg: dict) -> list[dict]:
        api_key = cfg.get("vision_api_key") or cfg.get("openai_api_key")
        if not api_key or not frames:
            return []

        descriptions = []
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i + batch_size]
            desc = self._vision_analyze_batch(batch, api_key, cfg)
            if desc:
                descriptions.append({
                    "batch_index": i // batch_size,
                    "frame_range": f"{i+1}-{i+len(batch)}",
                    "description": desc,
                })
        return descriptions

    def _vision_analyze_batch(self, frames: list[str], api_key: str, cfg: dict) -> str:
        raise HandlerError(
            self.name, "Vision API integration not yet implemented",
            hint="Implement with OpenAI Vision API or Claude Vision",
        )

    def _build_markdown(self, video_path: str, duration: float,
                        subtitle_text: str, frame_descriptions: list[dict]) -> str:
        sections = [f"# {Path(video_path).stem}\n"]

        mins = int(duration // 60)
        secs = int(duration % 60)
        sections.append(f"Duration: {mins}m {secs}s\n")

        if subtitle_text:
            sections.append("## Transcript\n")
            sections.append(subtitle_text.strip() + "\n")

        if frame_descriptions:
            sections.append("## Frame Analysis\n")
            for desc in frame_descriptions:
                sections.append(f"### Batch {desc['batch_index']} (frames {desc['frame_range']})")
                sections.append(desc["description"] + "\n")

        return "\n".join(sections)
