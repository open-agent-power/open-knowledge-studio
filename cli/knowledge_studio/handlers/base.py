"""Base handler interface for multi-modal raw material intake.

All modality handlers (web, pdf, video, audio, image, repo) implement this interface.
The ingest orchestrator calls detect() to check if a handler can process an input,
then process() to produce structured markdown with maximum fidelity preservation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HandlerResult:
    """Unified output from any handler — what gets written to raw/."""

    markdown: str
    title: str = ""
    source: str = ""
    modality: str = ""
    handler_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_subdir(self) -> str:
        """Which raw/ subdirectory this material belongs to."""
        return _MODALITY_TO_SUBDIR.get(self.modality, "misc")

    def to_raw_file_content(self) -> str:
        """Render the full markdown file with frontmatter for raw/."""
        from datetime import date

        today = date.today().isoformat()
        tags = self.metadata.get("tags", [])
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)

        fm_lines = [
            "---",
            f'title: "{self.title}"',
            f"source: {self.source}",
            f"date: {today}",
            f"type: {self.modality}",
            f"modality: {self.modality}",
        ]
        if tags_str:
            fm_lines.append(f"tags: [{tags_str}]")
        for key, val in self.metadata.items():
            if key == "tags":
                continue
            fm_lines.append(f"{key}: {val}")
        fm_lines.append("---")
        fm_lines.append("")
        fm_lines.append(self.markdown)
        return "\n".join(fm_lines)


class BaseHandler(ABC):
    """Abstract base for all modality handlers.

    A handler is responsible for:
    1. Detecting whether it can process a given input (URL, file path, etc.)
    2. Processing the input into structured markdown with maximum fidelity
    3. Returning a HandlerResult with content + metadata

    Handlers may use AI models (vision, STT, etc.) via API keys from global config.
    """

    name: str = "base"
    modalities: list[str] = []
    description: str = ""

    @abstractmethod
    def detect(self, input_path: str) -> bool:
        """Return True if this handler can process the given input."""
        ...

    @abstractmethod
    def process(self, input_path: str, config: dict[str, Any] | None = None) -> HandlerResult:
        """Process the input and return structured markdown."""
        ...

    def is_available(self) -> bool:
        """Check if this handler's dependencies are installed."""
        return True


class HandlerError(Exception):
    """Raised when a handler fails to process input."""

    def __init__(self, handler_name: str, message: str, *, hint: str = ""):
        self.handler_name = handler_name
        self.hint = hint
        super().__init__(f"[{handler_name}] {message}")


_MODALITY_TO_SUBDIR: dict[str, str] = {
    "article": "articles",
    "web": "articles",
    "paper": "papers",
    "pdf": "papers",
    "repo": "repos",
    "video": "misc",
    "audio": "misc",
    "image": "misc",
    "conversation": "misc",
    "note": "misc",
}
