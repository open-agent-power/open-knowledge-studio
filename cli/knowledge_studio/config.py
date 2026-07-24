"""Global configuration — ~/.oks/config.json

Enables cross-project access: any project can find the knowledge base
via the global config, without being inside the OKS repo.

Config structure:
{
    "knowledge_base_path": "/path/to/open-knowledge-studio",
    "api_keys": {
        "openai": "",
        "anthropic": ""
    },
    "handlers": {
        "video": {"frame_interval": 30, "frames_per_batch": 9, "whisper_model": "base"},
        "audio": {"whisper_model": "base"},
        "image": {"vision_model": "gpt-4o", "max_tokens": 1000}
    }
}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "knowledge_base_path": "",
    "api_keys": {
        "openai": "",
        "anthropic": "",
    },
    "handlers": {
        "video": {
            "frame_interval": 30,
            "frames_per_batch": 9,
            "whisper_model": "base",
        },
        "audio": {
            "whisper_model": "base",
        },
        "image": {
            "vision_model": "gpt-4o",
            "max_tokens": 1000,
        },
    },
}


def config_dir() -> Path:
    return Path.home() / ".oks"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict[str, Any]:
    """Load global config, creating default if missing."""
    path = config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{path} is corrupt ({e}). Fix the JSON manually, or delete it and "
            f"re-run `oks config init` / `oks init <path>`."
        ) from e


def save_config(config: dict[str, Any]) -> None:
    """Save config with atomic write."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    import contextlib
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def init_config(kb_path: str | None = None) -> Path:
    """Initialize global config. Returns the config path.

    Raises ValueError when no kb_path is given and the existing config has
    no knowledge_base_path — we never silently default to cwd.
    """
    config = load_config()

    if kb_path:
        config["knowledge_base_path"] = str(Path(kb_path).expanduser().resolve())
    elif not config.get("knowledge_base_path"):
        raise ValueError(
            "knowledge_base_path required: pass --kb-path or run `oks init <path>`"
        )

    save_config(config)
    return config_path()


# Warn at most once per process when the configured root lacks wiki/.
_warned_missing_wiki = False


def _warn_if_not_kb(root: Path) -> None:
    global _warned_missing_wiki
    if _warned_missing_wiki:
        return
    if not (root / "wiki").is_dir():
        _warned_missing_wiki = True
        import sys
        print(
            f"oks: warning: configured KB path {root} does not look like a "
            f"knowledge base (missing wiki/); run `oks init <path>` or "
            f"`oks config set knowledge_base_path <path>`",
            file=sys.stderr,
        )


def get_kb_root() -> Path:
    """Get the knowledge base root path (single source of truth).

    Priority:
    1. OKS_ROOT env var
    2. ~/.oks/config.json → knowledge_base_path
    3. Current working directory

    A corrupt config warns on stderr and falls back to cwd instead of
    raising, matching the historical store.repo_root() behavior.
    """
    env_root = os.environ.get("OKS_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        _warn_if_not_kb(root)
        return root

    try:
        config = load_config()
    except Exception as e:
        import sys
        print(
            f"oks: warning: could not read {config_path()} ({e}); "
            f"falling back to current directory as KB root",
            file=sys.stderr,
        )
        return Path.cwd()

    kb_path = config.get("knowledge_base_path")
    if kb_path:
        root = Path(kb_path).expanduser().resolve()
        _warn_if_not_kb(root)
        return root

    return Path.cwd()
