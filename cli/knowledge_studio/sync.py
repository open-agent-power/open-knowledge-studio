"""Git sync for the knowledge repo.

Extracted from autpilot-web/backend/app/services/knowledge_sync.py.
Removed asyncio, settings, and platform dependencies. Synchronous.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from knowledge_studio.store import repo_root

_logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 30


def sync_repo(pull: bool = False) -> bool:
    """Sync the knowledge repo via git.

    If pull=True: git pull --rebase (get latest from remote).
    Otherwise: git add + commit + push (push local changes).
    """
    root = repo_root()

    if not (root / ".git").is_dir():
        _logger.warning("Not a git repo: %s", root)
        return False

    if pull:
        return _pull(root)
    else:
        return _commit_and_push(root)


def _has_local_changes(dest: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(dest), "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _auto_commit(dest: Path) -> bool:
    try:
        paths_to_add = ["profiles/", "wiki/", "drafts/", "settings/", "_meta/", "*.md"]
        subprocess.run(
            ["git", "-C", str(dest), "add"] + paths_to_add,
            capture_output=True, timeout=10,
        )

        msg = f"auto-sync: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')}"
        result = subprocess.run(
            ["git", "-C", str(dest), "commit", "-m", msg],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            _logger.warning("auto-commit failed: %s", result.stderr)
            return False
        return True
    except Exception as exc:
        _logger.warning("auto-commit failed: %s", exc)
        return False


def _push(dest: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(dest), "push"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
        return result.returncode == 0
    except Exception as exc:
        _logger.warning("push failed: %s", exc)
        return False


def _pull(dest: Path) -> bool:
    if _has_local_changes(dest):
        _auto_commit(dest)

    try:
        result = subprocess.run(
            ["git", "-C", str(dest), "pull", "--rebase"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
        if result.returncode != 0:
            _logger.warning("pull failed: %s", result.stderr)
            return False
        return True
    except Exception as exc:
        _logger.warning("pull failed: %s", exc)
        return False


def _commit_and_push(dest: Path) -> bool:
    if not _has_local_changes(dest):
        _logger.info("No local changes to sync.")
        return True

    _auto_commit(dest)
    return _push(dest)
