"""Ingest orchestrator — the universal intake pipeline.

Detects input modality → dispatches to the appropriate handler → writes
unified markdown to raw/ with maximum fidelity preservation.

Usage:
    from knowledge_studio.ingest import ingest
    result = ingest("https://example.com/article")
    result = ingest("~/Downloads/paper.pdf")
    result = ingest("~/Movies/demo.mp4")
    result = ingest("~/projects/my-repo")
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerResult, HandlerError
from knowledge_studio.handlers.registry import HandlerRegistry
from knowledge_studio.handlers.detect import detect_modality
from knowledge_studio.config import get_handler_config, get_api_key, get_kb_root


def ingest(
    input_path: str,
    *,
    handler_name: str | None = None,
    dry_run: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Process an input through the universal intake pipeline.

    Args:
        input_path: URL, file path, or directory path
        handler_name: Force a specific handler (e.g., "video"). Auto-detect if None.
        dry_run: If True, detect modality and handler but don't write to raw/
        config: Override config (for testing)

    Returns:
        {
            "modality": str,
            "handler": str,
            "raw_path": str | None,     # None if dry_run
            "title": str,
            "metadata": dict,
        }
    """
    input_path = os.path.expanduser(input_path)

    modality = detect_modality(input_path)

    registry = HandlerRegistry()
    registry.load()

    if handler_name:
        handler = registry.get_handler(handler_name)
        if not handler:
            return {
                "modality": modality,
                "handler": handler_name,
                "raw_path": None,
                "title": "",
                "metadata": {},
                "error": f"Handler '{handler_name}' not available or not enabled",
            }
    else:
        handler = registry.find_handler(input_path)
        if not handler:
            return {
                "modality": modality,
                "handler": "none",
                "raw_path": None,
                "title": "",
                "metadata": {},
                "error": f"No handler available for input: {input_path} (detected: {modality})",
            }

    if dry_run:
        return {
            "modality": modality,
            "handler": handler.name,
            "raw_path": None,
            "title": "",
            "metadata": {"dry_run": True},
        }

    handler_config = config or get_handler_config(handler.name)
    api_key = get_api_key("openai")
    if api_key:
        handler_config.setdefault("openai_api_key", api_key)

    try:
        result = handler.process(input_path, handler_config)
    except HandlerError as e:
        return {
            "modality": modality,
            "handler": handler.name,
            "raw_path": None,
            "title": "",
            "metadata": {},
            "error": str(e),
            "hint": e.hint,
        }

    raw_path = _write_raw(result)

    return {
        "modality": result.modality,
        "handler": handler.name,
        "raw_path": str(raw_path),
        "title": result.title,
        "metadata": result.metadata,
    }


def _write_raw(result: HandlerResult) -> Path:
    """Write HandlerResult to raw/ subdirectory with atomic write."""
    raw_root = get_kb_root() / "raw"
    subdir = raw_root / result.raw_subdir
    subdir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(result.title or "untitled")
    filename = f"{slug}.md"
    file_path = subdir / filename

    if file_path.exists():
        counter = 1
        while (subdir / f"{slug}-{counter}.md").exists():
            counter += 1
        filename = f"{slug}-{counter}.md"
        file_path = subdir / filename

    content = result.to_raw_file_content()

    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(subdir), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, file_path)
    except Exception:
        os.unlink(tmp)
        raise

    return file_path


def _slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text or "untitled"
