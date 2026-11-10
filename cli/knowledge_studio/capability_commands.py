"""Provider inventory and local diagnostics for ``oks capability status``.

Per CONSTITUTION P4, doctor performs only LOCAL checks — no MCP handshake,
no HTTP requests, no API authentication tests.  Remote capability
availability is verified by each Provider's own ``probe.py``.
"""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml


def _providers_root() -> Path:
    """Return the providers/ resource directory inside the installed package."""
    return Path(str(files("knowledge_studio.providers")))


def _load_yaml_mapping(path: Path) -> dict[str, Any] | None:
    """Load catalog YAML while preserving its string-valued scalar contract."""
    try:
        result = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except (OSError, yaml.YAMLError):
        return None
    return result if isinstance(result, dict) and result else None


def _scan_providers(root: Path) -> list[dict[str, Any]]:
    """Scan providers/*/provider.yaml and return parsed entries."""
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        yaml_path = child / "provider.yaml"
        if not yaml_path.is_file():
            continue
        data = _load_yaml_mapping(yaml_path)
        if data:
            data["_dir"] = str(child.name)
            entries.append(data)
    return entries


# ── capability list ───────────────────────────────────────────────

def capability_list(root: Path | None = None) -> dict[str, Any]:
    """Return structured capability inventory.

    Returns a dict with keys: ``actions`` (set of action names),
    ``providers`` (list of {id, execution, provides, maturity, limits}),
    and ``by_action`` (action → list of provider ids).
    """
    return _catalog(_scan_providers(root or _providers_root()))


def _catalog(providers: list[dict[str, Any]]) -> dict[str, Any]:
    """Project one provider snapshot into the action inventory."""
    all_actions: set[str] = set()
    by_action: dict[str, list[str]] = {}
    provider_list: list[dict[str, Any]] = []

    for p in providers:
        pid = p.get("id", p["_dir"])
        execution = p.get("execution", "unknown")
        label = p.get("label", pid)
        entry = {
            "id": pid,
            "label": label,
            "execution": execution,
            "actions": [],
        }
        # Parse 'provides' section (simple key: maturity format)
        provides = p.get("provides", {})
        if isinstance(provides, dict):
            for action_name, action_info in provides.items():
                entry["actions"].append(action_name)
                all_actions.add(action_name)
                by_action.setdefault(action_name, []).append(pid)
        provider_list.append(entry)

    return {
        "actions": sorted(all_actions),
        "providers": provider_list,
        "by_action": {k: sorted(v) for k, v in sorted(by_action.items())},
    }


# ── capability doctor ─────────────────────────────────────────────

def _check_command(name: str) -> dict[str, Any]:
    """Check if a command exists on PATH."""
    found = shutil.which(name) is not None
    path = shutil.which(name) if found else None
    return {
        "type": "command",
        "name": name,
        "available": found,
        "path": str(path) if path else None,
        "suggestion": None if found else f"install '{name}' via your package manager",
    }


def _check_env_var(name: str) -> dict[str, Any]:
    """Check if an environment variable is set."""
    value = os.environ.get(name)
    available = bool(value)
    return {
        "type": "env_var",
        "name": name,
        "available": available,
        "value": "[set]" if available else None,
        "suggestion": (
            None if available
            else f"set {name}=<value> in your shell profile or .env"
        ),
    }


def _check_python_import(module_name: str, package_name: str | None = None) -> dict[str, Any]:
    """Check if a Python module can be imported."""
    pkg = package_name or module_name
    try:
        __import__(module_name)
        return {
            "type": "python_import",
            "name": pkg,
            "available": True,
            "suggestion": None,
        }
    except ImportError:
        return {
            "type": "python_import",
            "name": pkg,
            "available": False,
            "suggestion": f"pip install {pkg}",
        }


def _provider_status(checks: list[dict[str, Any]], provider_id: str, execution: str) -> str:
    """Derive a provider's readiness status from its health checks.

    Pure function — does no I/O.  Returns one of:

    * ``ready`` — all checks passed
    * ``not_configured`` — env var / API key missing (commands available)
    * ``unavailable`` — required command or package absent
    * ``runtime_only`` — can only be verified at Agent runtime (MCP, etc.)
    * ``blocked`` — known blockers prevent use
    * ``experimental`` — flagged as experimental, not for production
    """
    # ── blocked providers ──
    if provider_id in ("browser",):
        return "blocked"
    if provider_id in ("http-fetch", "remote-asr", "media-ingest"):
        return "experimental"

    # ── runtime-only (MCP / Agent-dependent) ──
    if provider_id in ("agentkey", "agent-runtime"):
        return "runtime_only"

    # ── external optional (user must install separately, not bundled) ──
    if provider_id in ("mediacrawler",):
        return "unavailable"

    # ── separate mandatory vs optional checks ──
    required_failures = [
        c for c in checks
        if c.get("available") is False
        and c.get("type") not in ("note", "env_var")
        and c.get("required") is not False
    ]
    env_failures = [
        c for c in checks
        if c.get("type") == "env_var" and c.get("available") is False
    ]

    if not required_failures and not env_failures:
        return "ready"
    if env_failures and not required_failures:
        return "not_configured"
    return "unavailable"


def _check_provider_health(provider: dict[str, Any]) -> list[dict[str, Any]]:
    """Run local health checks for one provider.  NO network calls."""
    checks: list[dict[str, Any]] = []
    pid = provider.get("id", provider.get("_dir", "unknown"))
    execution = provider.get("execution", "")

    requirements = provider.get("requirements", {})
    if isinstance(requirements, str):
        # YAML string — skip
        requirements = {}

    # Check commands
    commands = requirements.get("command", [])
    if isinstance(commands, str):
        commands = [commands]
    optional_commands = requirements.get("optional_commands", [])
    if isinstance(optional_commands, str):
        optional_commands = [optional_commands]

    for cmd in commands:
        checks.append(_check_command(cmd))
    for cmd in optional_commands:
        c = _check_command(cmd)
        c["required"] = False
        checks.append(c)

    managed_capabilities = {
        "markitdown": ("document", "document"),
        "pdf-lite": ("pdf-lite", "pdf-lite"),
        "mineru": ("pdf", "pdf"),
        "rapidocr": ("rapidocr", "watch"),
        "local-asr": ("watch", "watch"),
    }
    managed_capability = managed_capabilities.get(pid)

    # Check env vars. *_PYTHON selects an interpreter; it is not a credential
    # and must not make an already importable managed provider look unconfigured.
    env_vars = requirements.get("env", [])
    if isinstance(env_vars, str):
        env_vars = [env_vars]
    for env_var in env_vars:
        if not (managed_capability and env_var.endswith("_PYTHON")):
            checks.append(_check_env_var(env_var))

    # Check Python imports (for managed providers)
    pypi_pkg = requirements.get("python_package", "")
    if managed_capability:
        from oks_connector.capability_check import is_capability_available

        probe_name, install_name = managed_capability
        available, python_path = is_capability_available(probe_name)
        checks.append({
            "type": "python_import",
            "name": pypi_pkg or probe_name,
            "available": available,
            "interpreter": str(python_path) if python_path else None,
            "suggestion": None if available else f"oks capability install {install_name}",
        })
    elif pypi_pkg:
        checks.append(_check_python_import(pypi_pkg))

    # Special cases
    if pid == "agent-runtime":
        checks.append({
            "type": "note",
            "name": "agent-runtime",
            "available": None,
            "message": (
                "Agent native capability — depends on current model. "
                "Multimodal models support image/page understanding; "
                "text-only models can only use registered Providers."
            ),
        })
    elif pid == "human":
        checks.append({
            "type": "note",
            "name": "human",
            "available": True,
            "message": "Human provider — always available when human is present",
        })
    elif execution == "external":
        # External providers: we only check env vars / API keys, not connectivity
        checks.append({
            "type": "note",
            "name": f"{pid}-remote",
            "available": None,
            "message": (
                f"Remote provider ({execution}) — local env check only. "
                f"Verify connectivity with 'oks capability probe {pid}' "
                f"or the Provider's probe.py."
            ),
        })

    return checks


def capability_doctor(root: Path | None = None) -> dict[str, Any]:
    """Diagnose local environment and report provider health.

    Returns ``{overall, providers: [{id, label, execution, healthy, status, checks}]}``.
    ``status`` is one of: ready, not_configured, unavailable, runtime_only, blocked, experimental.
    PER CONSTITUTION P4: local checks only, no network calls.
    """
    return _diagnose_providers(_scan_providers(root or _providers_root()))


def _diagnose_providers(providers: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a provider snapshot without reading its catalog again."""
    results: list[dict[str, Any]] = []
    all_healthy = True

    for p in providers:
        pid = p.get("id", p.get("_dir", "unknown"))
        checks = _check_provider_health(p)
        has_required_failure = any(
            c.get("available") is False
            and c.get("type") != "note"
            and c.get("required") is not False
            for c in checks
        )
        if has_required_failure:
            all_healthy = False

        results.append({
            "id": pid,
            "label": p.get("label", pid),
            "execution": p.get("execution", "unknown"),
            "healthy": not has_required_failure,
            "status": _provider_status(checks, pid, p.get("execution", "unknown")),
            "checks": checks,
        })

    return {
        "overall": "healthy" if all_healthy else "issues_found",
        "providers": results,
    }


# ── capability status (combined catalog + doctor) ──────────────────


def _load_actions_metadata() -> dict[str, dict[str, str]]:
    """Load action labels and descriptions from actions.yaml."""
    actions_yaml = files("knowledge_studio.capabilities").joinpath("actions.yaml")
    if not actions_yaml.is_file():
        return {}
    parsed = _load_yaml_mapping(actions_yaml) or {}
    actions = parsed.get("actions", {})
    if not isinstance(actions, dict):
        return {}
    return {
        name: {"label": info.get("label", name), "description": info.get("description", "")}
        for name, info in actions.items()
        if isinstance(info, dict)
    }


def capability_status(root: Path | None = None) -> dict[str, Any]:
    """Return a combined capability + availability view for Agent consumption.

    Merges ``capability_list()`` (what actions exist, who provides them)
    with ``capability_doctor()`` (what's available right now).

    Returns a single dict the Agent can use to make Provider selection
    decisions without calling multiple commands:
    ``{actions, providers, by_action, overall}``

    Each action entry includes its Chinese label and description from
    actions.yaml.  Each provider entry includes availability status,
    health, known limits, and platform metadata.
    """
    providers = _scan_providers(root or _providers_root())
    catalog = _catalog(providers)
    doctor = _diagnose_providers(providers)
    actions_meta = _load_actions_metadata()

    # Index providers by id from doctor result
    provider_status: dict[str, dict[str, Any]] = {}
    for p in doctor.get("providers", []):
        provider_status[p["id"]] = p

    # Enrich each action with metadata
    enriched_actions: dict[str, dict[str, Any]] = {}
    for action_name in catalog["actions"]:
        meta = actions_meta.get(action_name, {})
        enriched_actions[action_name] = {
            "id": action_name,
            "label": meta.get("label", action_name),
            "description": meta.get("description", ""),
        }

    # Enrich each provider with availability and raw metadata
    enriched_providers: list[dict[str, Any]] = []
    for raw_p in providers:
        pid = raw_p.get("id", raw_p.get("_dir", "unknown"))
        status = provider_status.get(pid, {})
        caps: list[str] = []
        provides = raw_p.get("provides", {})
        if isinstance(provides, dict):
            caps = list(provides.keys())

        entry: dict[str, Any] = {
            "id": pid,
            "label": raw_p.get("label", pid),
            "execution": raw_p.get("execution", "unknown"),
            "description": raw_p.get("description", ""),
            "status": status.get("status", "unavailable"),
            "healthy": status.get("healthy", False),
            "capabilities": caps,
            "known_limits": raw_p.get("known_limits", []),
        }
        # Carry platform metadata for providers that declare it
        platforms = raw_p.get("platforms")
        if platforms and isinstance(platforms, list):
            entry["platforms"] = platforms
        # Include user_impact if declared (Guided Decision UX)
        user_impact = raw_p.get("user_impact")
        if user_impact and isinstance(user_impact, dict):
            entry["user_impact"] = user_impact
        # Include per-platform maturity if declared
        maturity_by_action = raw_p.get("maturity_by_action")
        if maturity_by_action and isinstance(maturity_by_action, dict):
            entry["maturity_by_action"] = maturity_by_action
        enriched_providers.append(entry)

    return {
        "actions": enriched_actions,
        "providers": enriched_providers,
        "by_action": catalog["by_action"],
        "overall": doctor.get("overall", "unknown"),
    }
