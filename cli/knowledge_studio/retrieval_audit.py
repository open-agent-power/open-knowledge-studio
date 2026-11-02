"""Read-only inventory of retrieval policies and their fallback boundaries.

This module describes declared routing only. It never runs a search, probes an
index, imports a backend, or inspects Wiki/Skill content.
"""
from __future__ import annotations

import copy
from pathlib import Path
import re
from typing import Any

import yaml


_ENTRIES: tuple[dict[str, Any], ...] = (
    {
        "id": "cli-recall",
        "title": "oks recall",
        "configuration": "settings/recall.yaml search_backend (default fts5); --search-backend overrides it; legacy OKS_SEARCH_BACKEND may override at runtime",
        "empty": "No Native retry for an ordinary empty result. Optional embedding fallback runs only when enabled and results are below its threshold; an empty embedding result preserves the original hits.",
        "error": "Unknown/unavailable backend raises an error; no Native fallback. Optional embedding fallback errors are recorded while original hits remain.",
        "native_condition": "Configured/selected native or legacy runs Native directly. Fusion invokes Native for reranking and uses Native results when FTS5 returns no hits.",
        "sources": [
            {"file": "cli/knowledge_studio/cli.py", "function": "recall_cmd"},
            {"file": "cli/knowledge_studio/recall.py", "function": "recall"},
            {"file": "cli/knowledge_studio/recall.py", "function": "_recall_knowledge_via_backend"},
        ],
    },
    {
        "id": "skill-search",
        "title": "oks skills search",
        "configuration": "Forced fts5 backend, independent of recall.yaml; capability metadata search may retry the original query against Skill body when no metadata match is found.",
        "empty": "After the optional body-search retry, returns no hits; no Native retry.",
        "error": "Backend/configuration errors propagate through the command wrapper; no Native retry.",
        "native_condition": "Never selected by this entry point. FTS5 runtime unavailability may use LIKE, not Native.",
        "sources": [
            {"file": "cli/knowledge_studio/skills_cli.py", "function": "search_cmd"},
            {"file": "cli/knowledge_studio/skills.py", "function": "search"},
        ],
    },
    {
        "id": "prompt-hook",
        "title": "UserPromptSubmit recall hook",
        "configuration": "Uses recall settings (default fts5; legacy environment override may apply); shares recall backend routing.",
        "empty": "Returns the hook empty/no_match status when no eligible memories remain; it does not switch to Native because of emptiness.",
        "error": "Recall errors become a hook error status. The CLI bridge reports bridge failures; neither layer chooses Native as an error recovery backend.",
        "native_condition": "Configured Native/legacy, or fusion's internal Native calls, as in CLI recall.",
        "sources": [
            {"file": "cli/knowledge_studio/_assets/hooks/user-prompt-recall.py", "function": "main"},
            {"file": "cli/knowledge_studio/cli.py", "function": "_run_hook_recall"},
        ],
    },
    {
        "id": "workspace-query",
        "title": "Workspace query operation",
        "configuration": "Calls recall without a backend override; settings/recall.yaml applies, default fts5; legacy environment override may apply.",
        "empty": "Returns the ordinary recall result; no separate Native retry.",
        "error": "Returns the worker's structured error; it does not change backend.",
        "native_condition": "Configured Native/legacy, or fusion's internal Native calls, as in CLI recall.",
        "sources": [
            {"file": "cli/knowledge_studio/workspace_worker.py", "function": "dispatch(query)"},
            {"file": "cli/knowledge_studio/recall.py", "function": "recall"},
        ],
    },
    {
        "id": "vfs-find",
        "title": "oks fs find",
        "configuration": "No retrieval backend; recursively checks path and text for a literal case-insensitive substring.",
        "empty": "Returns matches=[] (with skipped_count/truncated metadata); no backend fallback.",
        "error": "Unreadable, non-UTF-8, or binary-like files are counted as skipped; invalid scope/query raises a VFS error.",
        "native_condition": "Never; this is literal VFS search, not Wiki recall.",
        "sources": [
            {"file": "cli/knowledge_studio/cli.py", "function": "fs_find"},
            {"file": "cli/knowledge_studio/vfs.py", "function": "VFS.find"},
        ],
    },
    {
        "id": "fts5-runtime",
        "title": "FTS5 runtime fallback",
        "configuration": "Selected when fts5 is requested; SQLite FTS5 availability is checked by the backend at runtime.",
        "empty": "An FTS5 empty result is not by itself changed to Native; fusion and optional embedding fallback are separate policies.",
        "error": "When SQLite FTS5 is unavailable, the FTS5 backend searches with LIKE and reports actual backend like.",
        "native_condition": "FTS5 unavailability alone does not run Native.",
        "sources": [
            {"file": "cli/knowledge_studio/search/fts5.py", "function": "FTS5Backend.search"},
            {"file": "cli/knowledge_studio/search/fts5.py", "function": "FTS5Backend.actual_backend"},
        ],
    },
    {
        "id": "fusion-native",
        "title": "Fusion internal Native calls",
        "configuration": "Only when fusion is explicitly selected/configured.",
        "empty": "If FTS5 returns no hits, fusion returns Native hits; otherwise Native scores rerank FTS5 candidates.",
        "error": "Backend exceptions propagate to the caller; no general error-to-Native recovery contract.",
        "native_condition": "Always called during fusion search, including the FTS5-empty branch.",
        "sources": [{"file": "cli/knowledge_studio/search/fusion.py", "function": "FusionBackend.search"}],
    },
)


def _configured_backend(root: Path) -> tuple[str, str]:
    """Read only this explicit root's YAML setting; do not consult global roots/env."""
    path = root / "settings" / "recall.yaml"
    if not path.is_file():
        return "fts5", "code_default"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(document, dict):
            return "fts5", "code_default_invalid_config"
        value = document.get("search_backend", "fts5")
        if not isinstance(value, str) or not value.strip():
            return "fts5", "code_default"
        return value.strip(), "settings/recall.yaml"
    except (OSError, UnicodeError, yaml.YAMLError):
        # Mirrors recall's best-effort settings loading without exposing file
        # contents or parse details in an audit response.
        return "fts5", "code_default_invalid_config"


def _safe_observation(observation: object) -> dict[str, Any] | None:
    """Keep explicitly supplied runtime evidence separate and non-sensitive."""
    if not isinstance(observation, dict):
        return None
    safe: dict[str, Any] = {}
    for key in ("requested_backend", "actual_backends", "fallback_reason"):
        value = observation.get(key)
        if key == "actual_backends" and isinstance(value, (list, tuple)):
            safe[key] = [item for item in value if isinstance(item, str)][:8]
        elif isinstance(value, str):
            safe[key] = value[:120]
    error = observation.get("fallback_error")
    if isinstance(error, str):
        # Diagnostics normally contain an exception class; discard arbitrary
        # messages that could carry query text or local paths.
        error_kind = error.split(":", 1)[0]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}", error_kind):
            safe["fallback_error"] = error_kind
    return safe or None


def report(root: str | Path, observation: object = None) -> dict[str, Any]:
    """Describe retrieval routing for an explicit KB root without probing it.

    `observation` is optional caller-supplied diagnostics from a real query;
    it is filtered and returned under `observed` and never changes the
    top-level `actual_backend`, which remains `not_probed` here.
    """
    kb_root = Path(root).expanduser().resolve()
    configured, source = _configured_backend(kb_root)
    result: dict[str, Any] = {
        "schema_version": "retrieval-audit/v1",
        "knowledge_base": str(kb_root),
        "configured_backend": configured,
        "configuration_source": source,
        "actual_backend": "not_probed",
        "entries": copy.deepcopy(_ENTRIES),
        "claim_boundary": "Declared routing policy only; no backend, index, Wiki, or Skill was queried.",
    }
    observed = _safe_observation(observation)
    if observed is not None:
        result["observed"] = observed
    return result


__all__ = ["report"]
