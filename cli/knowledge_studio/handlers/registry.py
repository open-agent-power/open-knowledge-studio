"""Handler registry — discovers and manages available modality handlers.

Loads handler configuration from settings/handlers.json. Supports both built-in
Python handlers (this package) and external CLI handlers (registered via config).

Usage:
    registry = HandlerRegistry()
    registry.load()
    handler = registry.get_handler("video")
    all_handlers = registry.list_handlers()
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from knowledge_studio.handlers.base import BaseHandler, HandlerError


_BUILTIN_HANDLERS: dict[str, str] = {
    "web": "knowledge_studio.handlers.web:WebHandler",
    "pdf": "knowledge_studio.handlers.pdf:PDFHandler",
    "video": "knowledge_studio.handlers.video:VideoHandler",
    "audio": "knowledge_studio.handlers.audio:AudioHandler",
    "image": "knowledge_studio.handlers.image:ImageHandler",
    "repo": "knowledge_studio.handlers.repo:RepoHandler",
}


class HandlerRegistry:
    """Manages available handlers and their configuration."""

    def __init__(self):
        self._handlers: dict[str, BaseHandler] = {}
        self._config: list[dict[str, Any]] = []
        self._loaded = False

    def load(self) -> None:
        """Load handlers from settings/handlers.json and instantiate built-in ones."""
        config_path = self._find_config()
        if config_path and config_path.exists():
            with open(config_path) as f:
                self._config = json.load(f)
        else:
            self._config = self._default_config()

        for entry in self._config:
            if not entry.get("enabled", True):
                continue
            name = entry["name"]
            handler = self._instantiate(name, entry)
            if handler and handler.is_available():
                self._handlers[name] = handler

        self._loaded = True

    def get_handler(self, name: str) -> BaseHandler | None:
        """Get a handler by name. Returns None if not found or not available."""
        if not self._loaded:
            self.load()
        return self._handlers.get(name)

    def find_handler(self, input_path: str) -> BaseHandler | None:
        """Find the first handler that claims it can process the input."""
        if not self._loaded:
            self.load()
        for handler in self._handlers.values():
            try:
                if handler.detect(input_path):
                    return handler
            except Exception:
                continue
        return None

    def list_handlers(self) -> list[dict[str, Any]]:
        """Return handler info for all registered handlers."""
        if not self._loaded:
            self.load()
        result = []
        for entry in self._config:
            name = entry["name"]
            handler = self._handlers.get(name)
            result.append({
                "name": name,
                "modalities": entry.get("modalities", []),
                "description": entry.get("description", ""),
                "enabled": entry.get("enabled", True),
                "available": handler is not None,
                "is_builtin": name in _BUILTIN_HANDLERS,
            })
        return result

    def enable(self, name: str) -> bool:
        """Enable a handler in the config file."""
        return self._set_enabled(name, True)

    def disable(self, name: str) -> bool:
        """Disable a handler in the config file."""
        return self._set_enabled(name, False)

    def _instantiate(self, name: str, entry: dict) -> BaseHandler | None:
        builtin = _BUILTIN_HANDLERS.get(name)
        if builtin:
            module_path, class_name = builtin.split(":")
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                return cls()
            except Exception:
                return None
        return None

    def _set_enabled(self, name: str, enabled: bool) -> bool:
        config_path = self._find_config()
        if not config_path or not config_path.exists():
            return False
        with open(config_path) as f:
            config = json.load(f)
        for entry in config:
            if entry["name"] == name:
                entry["enabled"] = enabled
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                self._loaded = False
                return True
        return False

    def _find_config(self) -> Path | None:
        """Find settings/handlers.json relative to the repo root."""
        try:
            from knowledge_studio.store import repo_root
            root = repo_root()
            return root / "settings" / "handlers.json"
        except Exception:
            return None

    def _default_config(self) -> list[dict[str, Any]]:
        return [
            {"name": "web", "modalities": ["url:http", "url:https"], "enabled": True,
             "description": "Web article fetch + Readability extraction"},
            {"name": "pdf", "modalities": ["pdf"], "enabled": True,
             "description": "PDF parse → text + structure"},
            {"name": "video", "modalities": ["mp4", "mov", "avi", "mkv", "url:youtube", "url:bilibili"], "enabled": False,
             "description": "Video: ffmpeg frame extraction + Whisper subtitle + Vision analysis"},
            {"name": "audio", "modalities": ["mp3", "wav", "m4a", "flac"], "enabled": False,
             "description": "Audio: Whisper STT → transcript"},
            {"name": "image", "modalities": ["png", "jpg", "jpeg", "webp", "screenshot"], "enabled": False,
             "description": "Image: Vision model / OCR → structured description"},
            {"name": "repo", "modalities": ["directory"], "enabled": True,
             "description": "Code repo: structure scan + README + key patterns"},
        ]
