"""``oks capability`` — inspect available providers and diagnose environment.

``capability list`` reads ``providers/*/provider.yaml`` and shows what
actions are available.  ``capability doctor`` checks the local environment
(command existence, env vars, Python imports) and reports what's ready,
what's missing, and how to fix it.

Per CONSTITUTION P4, doctor performs only LOCAL checks — no MCP handshake,
no HTTP requests, no API authentication tests.  Remote capability
availability is verified by each Provider's own ``probe.py``.

Also exposes ``_provider_status``, ``_build_capability_summary``, and
``print_capability_summary`` so ``oks init`` can show a user-facing
capability overview without duplicating grouping logic.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any

from rich.console import Console

from knowledge_studio.i18n import t


def _providers_root() -> Path:
    """Return the providers/ resource directory inside the installed package."""
    return Path(str(files("knowledge_studio.providers")))


def _parse_yaml_lines(lines: list[str]) -> dict[str, Any]:
    """Parse simple indented YAML into nested dicts.  Handles up to 3 levels
    of nesting — sufficient for provider.yaml.  No anchors, no lists-of-dicts,
    no multi-line strings."""
    result: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        indent = len(line) - len(line.lstrip())
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if not value:
            # Section header — collect all indented lines that follow
            sub_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                nxt_stripped = nxt.strip()
                if not nxt_stripped or nxt_stripped.startswith("#"):
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip())
                if nxt_indent <= indent:
                    break  # dedented — end of section
                sub_lines.append(nxt)
                j += 1
            # Detect YAML block-list: all items start with "- "
            if sub_lines and all(s.strip().startswith("- ") for s in sub_lines):
                result[key] = [s.strip()[2:].strip().strip('"').strip("'") for s in sub_lines]
            else:
                result[key] = _parse_yaml_lines(sub_lines)
            i = j
        else:
            # Scalar value
            if value.startswith("[") and value.endswith("]"):
                value = [
                    v.strip().strip('"').strip("'")
                    for v in value[1:-1].split(",") if v.strip()
                ]
            result[key] = value
            i += 1
    return result


def _load_provider_yaml(path: Path) -> dict[str, Any] | None:
    """Load a provider.yaml as a plain nested dict. Returns None on failure."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    result = _parse_yaml_lines(lines)
    return result if result else None


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
        data = _load_provider_yaml(yaml_path)
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
    root = root or _providers_root()
    providers = _scan_providers(root)

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
    root = root or _providers_root()
    providers = _scan_providers(root)

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
    from importlib.resources import files

    actions_yaml = files("knowledge_studio.capabilities").joinpath("actions.yaml")
    if not actions_yaml.is_file():
        return {}
    lines = actions_yaml.read_text(encoding="utf-8").splitlines()
    parsed = _parse_yaml_lines(lines)
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
    root = root or _providers_root()
    catalog = capability_list(root)
    doctor = capability_doctor(root)
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
    for raw_p in _scan_providers(root):
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


# ── Init-time capability summary ────────────────────────────────────

_ALWAYS_AVAILABLE = frozenset({"agent-runtime", "human", "text-read"})


def _remote_setup_hint(provider_id: str) -> str:
    """Return a one-line configuration hint for a remote provider."""
    if provider_id == "firecrawl":
        return t("firecrawl_setup_hint")
    if provider_id == "agentkey":
        return t("agentkey_setup_hint")
    if provider_id == "mediacrawler":
        return t("mediacrawler_setup_hint")
    return ""


def _build_capability_summary(
    doctor_result: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    """Group provider statuses for human-readable init output.

    Pure function — receives a ``capability_doctor()`` result, returns
    grouped lists keyed by ``local_ready``, ``local_missing``,
    ``remote_ready``, ``remote_not_configured``, ``remote_runtime_only``,
    ``blocked_experimental``.

    Providers that are always available (agent-runtime, human, text-read)
    are excluded — they would only add noise for a first-time user.
    """
    empty: dict[str, list[dict[str, Any]]] = {
        "local_ready": [],
        "local_missing": [],
        "remote_ready": [],
        "remote_not_configured": [],
        "remote_runtime_only": [],
        "blocked_experimental": [],
    }
    if doctor_result is None:
        return empty

    for p in doctor_result.get("providers", []):
        pid = p.get("id", "")
        if pid in _ALWAYS_AVAILABLE:
            continue
        status = p.get("status", "unavailable")
        execution = p.get("execution", "")

        if status in ("blocked", "experimental"):
            empty["blocked_experimental"].append(p)
        elif execution == "external":
            if status == "ready":
                empty["remote_ready"].append(p)
            elif status == "not_configured":
                empty["remote_not_configured"].append(p)
            elif status == "runtime_only":
                empty["remote_runtime_only"].append(p)
            else:
                empty["remote_not_configured"].append(p)
        else:
            if status == "ready":
                empty["local_ready"].append(p)
            else:
                empty["local_missing"].append(p)

    return empty


# ── User-facing capability descriptions ──────────────────────────────

# Maps provider IDs to user-facing capability names shown during init.
# Internal provider IDs are hidden from default user view.
# Each entry: (user_facing_label, category)
# Categories: "document" | "web" | "media" | "social" | "platform"
_USER_CAPABILITY_LABELS: dict[str, tuple[str, str]] = {
    "pdf-lite": ("PDF 文本提取", "pdf"),
    "markitdown": ("Office 文档提取", "pdf"),
    "mineru": ("PDF 深度提取（含排版还原）", "pdf"),
    "rapidocr": ("图片文字识别（OCR）", "image"),
    "trafilatura": ("网页正文提取（静态页面）", "web"),
    "http-fetch": ("网页原始获取", "web"),
    "firecrawl": ("动态网页内容抓取", "web"),
    "browser": ("浏览器登录态页面", "web"),
    "yt-dlp": ("视频/音频下载", "media"),
    "ffmpeg": ("媒体格式转换", "media"),
    "local-asr": ("本地语音转写", "media"),
    "remote-asr": ("远程语音转写", "media"),
    "mediacrawler": ("社交平台公开内容采集", "platform"),
    "agentkey": ("受限平台内容获取（知乎/微信/B站）", "platform"),
}


def _describe_ready_capabilities(
    summary: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    """Derive user-facing capability lists from provider status.

    Returns (can_do_now, can_enable_later) — each is a list of
    human-readable Chinese capability descriptions.
    """
    can_do: list[str] = []
    can_enable: list[str] = []

    def _label(pid: str) -> str:
        return _USER_CAPABILITY_LABELS.get(pid, (pid, "other"))[0]

    # Local ready
    for p in summary.get("local_ready", []):
        can_do.append(_label(p["id"]))
    # Remote ready
    for p in summary.get("remote_ready", []):
        can_do.append(_label(p["id"]))
    # Remote runtime_only — depends on the Agent model; not guaranteed
    for p in summary.get("remote_runtime_only", []):
        can_enable.append(f"{_label(p['id'])}（取决于 Agent 模型和 MCP 配置）")

    # Local missing (installable)
    for p in summary.get("local_missing", []):
        hint = ""
        pid = p["id"]
        if pid == "pdf-lite":
            hint = " — oks capability install pdf-lite"
        elif pid == "rapidocr":
            hint = " — pip install rapidocr"
        elif pid == "markitdown":
            hint = " — pip install markitdown"
        can_enable.append(_label(pid) + hint)

    # Remote not configured
    for p in summary.get("remote_not_configured", []):
        hint = _remote_setup_hint(p["id"])
        entry = _label(p["id"])
        if hint:
            entry += f" — {hint}"
        can_enable.append(entry)

    # Blocked/experimental — shown as unavailable
    for p in summary.get("blocked_experimental", []):
        can_enable.append(f"{_label(p['id'])}（当前不可用）")

    return can_do, can_enable


def _derive_first_prompts(
    can_do: list[str],
) -> list[str]:
    """Generate first-use prompt suggestions based on available capabilities."""
    prompts: list[str] = []
    has_doc = any("PDF" in c or "Office" in c or "Markdown" in c for c in can_do)
    has_web = any("网页" in c for c in can_do)

    prompts.append(t("init_prompt_local_only"))
    if has_doc:
        prompts.append(t("init_prompt_with_pdf"))
    if has_web:
        prompts.append(t("init_prompt_with_web"))
    return prompts


# ── R4-4: Category-level capability view ────────────────────────────

# Six user-facing capability categories.  Provider names are hidden from
# the default view — users see WHAT they can do, not WHICH providers exist.
_CATEGORY_DEFINITIONS: dict[str, dict[str, Any]] = {
    "text": {
        "label": "文本与 Markdown",
        "description": "Markdown / 纯文本直接读取，本地处理，无需额外依赖",
        "always_available": True,
    },
    "web": {
        "label": "网页读取",
        "description": "网页抓取与正文提取，支持静态页面与动态渲染",
    },
    "pdf": {
        "label": "PDF 文档处理",
        "description": "PDF 文本提取、结构解析、扫描件 OCR",
    },
    "image": {
        "label": "图片理解",
        "description": "图片文字识别（OCR）与语义内容理解",
    },
    "media": {
        "label": "音视频处理",
        "description": "媒体下载、语音转写、字幕提取",
    },
    "platform": {
        "label": "平台内容",
        "description": "社交平台与受限平台内容获取",
    },
}


def _category_status(
    key: str, doctor_result: dict[str, Any] | None
) -> str:
    """Derive a simple status for a capability category.

    Returns one of: "ready" (always-available or has working providers),
    "available" (has providers, some may need config), "unavailable".
    """
    cat = _CATEGORY_DEFINITIONS.get(key, {})
    if cat.get("always_available"):
        return "ready"

    if doctor_result is None:
        return "unavailable"

    # Check if any provider in this category has a useful status
    # (aggregation is informal — we just check if anything exists)
    provider_map = {p["id"]: p for p in doctor_result.get("providers", [])}

    # Map category to its relevant providers via _USER_CAPABILITY_LABELS
    relevant_pids = {
        pid for pid, (label, cat_name) in _USER_CAPABILITY_LABELS.items()
        if cat_name == key
    }

    has_ready = False
    has_any = False
    for pid in relevant_pids:
        p = provider_map.get(pid, {})
        status = p.get("status", "unavailable")
        if status == "ready":
            has_ready = True
        if status not in ("unavailable",):
            has_any = True

    if has_ready:
        return "ready"
    elif has_any:
        return "available"
    return "unavailable"


def _build_category_summary(
    doctor_result: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return a simple capability category list for user-facing display.

    No provider IDs, no counts, no weight/latency — just status + name +
    description.
    """
    categories: list[dict[str, Any]] = []
    for key, cat in _CATEGORY_DEFINITIONS.items():
        status = _category_status(key, doctor_result)
        categories.append({
            "key": key,
            "label": cat["label"],
            "description": cat["description"],
            "status": status,
        })
    return categories


def _status_indicator(status: str) -> str:
    """Return a display character for a category status."""
    if status == "ready":
        return "✓"
    elif status == "available":
        return "○"
    else:
        return "✗"


def print_capability_summary(
    console: Console,
    doctor_result: dict[str, Any] | None,
) -> None:
    """Print a user-facing capability summary after ``oks init``.

    Shows 6 capability categories — no provider IDs, no counts, no
    weight/latency.  Provider details are available via
    ``oks capability doctor --verbose``.
    """
    categories = _build_category_summary(doctor_result)

    console.print(f"\n[bold]{t('init_ready')}[/bold]")

    # ── Category list (6 rows, one per capability family) ──
    if categories:
        for cat in categories:
            indicator = _status_indicator(cat["status"])
            status_map = {"ready": "green", "available": "yellow", "unavailable": "red"}
            color = status_map.get(cat["status"], "dim")
            console.print(
                f"  [{color}]{indicator}[/{color}] "
                f"[bold]{cat['label']}[/bold]"
            )
            console.print(f"    {cat['description']}")

    # ── First-use prompts ──
    can_do_labels = [cat["label"] for cat in categories if cat["status"] in ("ready", "available")]
    prompts = _derive_first_prompts(can_do_labels)
    if prompts:
        console.print(f"\n[bold]{t('init_first_prompt')}[/bold]")
        for prompt in prompts:
            console.print(f'  [cyan]"{prompt}"[/cyan]')
