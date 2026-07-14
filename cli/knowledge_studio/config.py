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
    with open(path) as f:
        return json.load(f)


def save_config(config: dict[str, Any]) -> None:
    """Save config with atomic write."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def init_config(kb_path: str | None = None) -> Path:
    """Initialize global config. Returns the config path."""
    config = load_config()

    if kb_path:
        config["knowledge_base_path"] = kb_path
    elif not config.get("knowledge_base_path"):
        try:
            from knowledge_studio.store import repo_root
            config["knowledge_base_path"] = str(repo_root())
        except Exception:
            config["knowledge_base_path"] = str(Path.cwd())

    save_config(config)
    return config_path()


def get_kb_root() -> Path:
    """Get the knowledge base root path.

    Priority:
    1. OKS_ROOT env var
    2. ~/.oks/config.json → knowledge_base_path
    3. Current working directory
    """
    env_root = os.environ.get("OKS_ROOT")
    if env_root:
        return Path(env_root)

    config = load_config()
    kb_path = config.get("knowledge_base_path")
    if kb_path:
        return Path(kb_path)

    return Path.cwd()


def get_handler_config(handler_name: str) -> dict[str, Any]:
    """Get handler-specific config from global config."""
    config = load_config()
    return config.get("handlers", {}).get(handler_name, {})


def get_api_key(provider: str = "openai") -> str:
    """Get API key for a provider.

    Priority:
    1. Environment variable (OPENAI_API_KEY, ANTHROPIC_API_KEY)
    2. ~/.oks/config.json → api_keys.<provider>
    """
    env_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
    env_var = env_map.get(provider, f"{provider.upper()}_API_KEY")
    env_val = os.environ.get(env_var)
    if env_val:
        return env_val

    config = load_config()
    return config.get("api_keys", {}).get(provider, "")
