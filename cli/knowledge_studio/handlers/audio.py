"""Audio handler — speech-to-text via Whisper.

Pipeline: Audio → Whisper STT → transcript with timestamps → structured Markdown
Dependencies: whisper (pip install openai-whisper) or whisper.cpp

Config (from ~/.oks/config.json → handlers.audio):
    whisper_model: model size — tiny/base/small/medium/large (default: "base")
    language: language hint (default: auto-detect)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError
from knowledge_studio.handlers.detect import AUDIO_EXTENSIONS


class AudioHandler(BaseHandler):
    name = "audio"
    modalities = ["mp3", "wav", "m4a", "flac", "aac", "ogg"]
    description = "Audio: Whisper STT → transcript"

    def detect(self, input_path: str) -> bool:
        return Path(input_path).suffix.lower() in AUDIO_EXTENSIONS

    def is_available(self) -> bool:
        try:
            import whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        if not self.is_available():
            raise HandlerError(
                self.name, "whisper not installed",
                hint="pip install openai-whisper",
            )

        import whisper

        cfg = config or {}
        model_size = cfg.get("whisper_model", "base")
        language = cfg.get("language")

        path = Path(input_path)
        if not path.exists():
            raise HandlerError(self.name, f"File not found: {input_path}")

        model = whisper.load_model(model_size)
        result = model.transcribe(str(path), language=language)

        segments = result.get("segments", [])
        if segments:
            transcript_parts = []
            for seg in segments:
                start = seg.get("start", 0)
                text = seg.get("text", "").strip()
                mins = int(start // 60)
                secs = int(start % 60)
                transcript_parts.append(f"[{mins:02d}:{secs:02d}] {text}")
            markdown = "## Transcript\n\n" + "\n".join(transcript_parts)
        else:
            markdown = result.get("text", "")

        return HandlerResult(
            markdown=markdown,
            title=path.stem,
            source=str(path),
            modality="audio",
            handler_name=self.name,
            metadata={
                "model": model_size,
                "language": result.get("language", "unknown"),
                "segment_count": len(segments),
                "original_file": path.name,
            },
        )
