"""Install editor hook assets, manage their wiring, and bridge hook records."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Optional

from . import resources, store


_RECALL_HOOK_SCRIPT_NAME = "user-prompt-recall.sh"

_RECALL_HOOK_SCRIPT_NAMES = ("user-prompt-recall.sh", "user-prompt-recall.py")

_RECALL_HOOK_SCRIPTS = ("user-prompt-recall.py", "user-prompt-recall.sh", "post-tool-edit.py", "post-tool-edit.sh")

_HOOK_SUPPORT_FILES = ("_persistence.py", "_hook_runner.py")

_POST_TOOL_SCRIPT_NAME = "post-tool-edit.sh"

_POST_TOOL_SCRIPT_NAMES = ("post-tool-edit.sh", "post-tool-edit.py")

_HOOK_EDITORS = {
    "claude": ".claude/settings.json",
    "qoder": ".qoder/settings.json",
    "codex": ".codex/hooks.json",
}

_HOOK_SCRIPT_DIRS = {
    "claude": ".claude/hooks",
    "qoder": ".claude/hooks",
    "codex": ".codex/hooks",
}

_CODEX_LIFECYCLE_SCRIPTS = (
    "validate-wiki-write.sh",
    "pre-compact.sh",
    "session-start.sh",
)

def _bake_codex_lifecycle_hooks(root: Path) -> None:
    """Bake the active Python interpreter into Codex lifecycle hooks.

    Codex invokes these hooks through Bash. On Windows/Git Bash, resolving
    ``python3`` at runtime can select a launcher that exits successfully for
    a probe but cannot execute the hook payload. The absolute interpreter used
    to run ``oks init`` is already known to import the package, so use it as
    the hook fallback just like the recall wrappers do.
    """
    import sys

    hooks_dir = root / ".codex" / "hooks"
    shell_python = sys.executable.replace("\\", "/")
    baked = f'"${{OKS_PYTHON:-{shell_python}}}"'
    markers = (
        '"${OKS_PYTHON:-python3}"',
        '"${OKS_PYTHON:-}"',
    )
    for name in _CODEX_LIFECYCLE_SCRIPTS:
        dest = hooks_dir / name
        if not dest.is_file():
            continue
        try:
            text = dest.read_text(encoding="utf-8")
        except OSError:
            continue
        updated = text
        for marker in markers:
            updated = updated.replace(marker, baked)
        if updated != text:
            dest.write_text(updated, encoding="utf-8")

def _hook_command_matches_script(
    command: str, script_name: str | tuple[str, ...]
) -> bool:
    """Match bare, quoted, or runner-wrapped hook commands by script name."""
    names = (script_name,) if isinstance(script_name, str) else tuple(script_name)
    command = str(command or "").strip().rstrip("\"' ")
    # Native Windows commands may include ``2>NUL`` to keep hook stdout clean.
    command = command.split(" 2>", 1)[0].rstrip()
    return any(
        command.endswith(name)
        or re.search(rf"(?:^|[\\/]){re.escape(name)}(?=$|[\"'\s])", command)
        for name in names
    )

def _codex_python_hook_command(
    hooks_dir: Path,
    python_script_name: str,
    *,
    native_windows: bool | None = None,
    suppress_stderr: bool = True,
) -> str:
    """Return a Codex command that works without Bash on native Windows."""
    if native_windows is None:
        native_windows = os.name == "nt"
    script = (hooks_dir / python_script_name).resolve()
    if native_windows:
        # Existing recall hooks suppress dependency chatter by default. Hooks
        # that report diagnostics can opt out and keep stderr visible.
        # Use native separators even when tests simulate Windows on POSIX.
        # Preserve the host's directory spelling while using a Windows
        # separator between the directory and script name. This also makes
        # native-Windows formatting deterministic in cross-platform tests.
        script_text = str(script.parent) + "\\" + script.name
        command = subprocess.list2cmdline([sys.executable, script_text])
        return command + " 2>NUL" if suppress_stderr else command
    return script.as_posix()

def _windows_python_hook_exec(hooks_dir: Path, python_script_name: str) -> tuple[str, list[str]]:
    """Return a direct-exec hook command for native Windows Claude Code."""
    runner = (hooks_dir / "_hook_runner.py").resolve()
    script = (hooks_dir / python_script_name).resolve()
    package_root = str(Path(__file__).resolve().parents[1])
    return sys.executable, [str(runner), str(script), package_root]

def _workflow_hook_command(
    hooks_dir: Path, script_name: str, kb_root: Path, host: str
) -> tuple[str, list[str] | None]:
    """Run a copied hook through the Python runner with an explicit KB root."""
    runner = (hooks_dir / "_hook_runner.py").resolve()
    script = (hooks_dir / script_name).resolve()
    package_root = str(Path(__file__).resolve().parents[1])
    argv = [sys.executable, str(runner), str(script), package_root, "--kb", str(kb_root)]
    if os.name == "nt" and host == "claude":
        return argv[0], argv[1:]
    if os.name == "nt":
        return subprocess.list2cmdline(argv), None
    return shlex.join(argv), None

def _hook_handler_matches_script(
    handler: dict, script_name: str | tuple[str, ...]
) -> bool:
    """Match a shell-form or direct-exec hook handler by script name."""
    if _hook_command_matches_script(handler.get("command", ""), script_name):
        return True
    args = handler.get("args", [])
    return isinstance(args, list) and any(
        _hook_command_matches_script(str(arg), script_name) for arg in args
    )

def _write_hook_handler(handler: dict, command: str, args: list[str] | None) -> None:
    """Update one owned hook handler without touching its unrelated fields."""
    handler["command"] = command
    if args is None:
        handler.pop("args", None)
    else:
        handler["args"] = args

def _migrate_codex_hook_paths(settings_path: Path, root: Path) -> bool:
    """Rewrite legacy relative Codex lifecycle commands to repo-root paths."""
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as e:
        raise ValueError(f"{settings_path} is not valid JSON: {e}") from e

    changed = False
    hooks = data.get("hooks", {})
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            for handler in group.get("hooks", []):
                command = str(handler.get("command", "") or "").strip().strip("\"' ")
                for script_name in _CODEX_LIFECYCLE_SCRIPTS:
                    legacy_paths = {
                        f".codex/hooks/{script_name}",
                        f"$(git rev-parse --show-toplevel)/.codex/hooks/{script_name}",
                    }
                    if command in legacy_paths:
                        handler["command"] = (
                            root / ".codex" / "hooks" / script_name
                        ).resolve().as_posix()
                        changed = True
                        break

    if not changed:
        return False
    shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return True

def _ensure_recall_scripts(root: Path, hooks_dir: Path | None = None) -> list[str]:
    """Copy/refresh the recall hook scripts into an agent's hooks directory.

    The .sh wrapper gets the current interpreter baked into its OKS_PYTHON
    fallback. If an existing .sh lacks the current bake (fresh copy still on
    `python3`, or baked against a stale interpreter), it is re-copied from
    the asset source and re-baked. Existing hook engines are refreshed when
    their bundled source has changed, so protocol updates reach installed
    instances too: hook engines are baked runtime, not a customization
    surface.
    """
    import shutil
    import stat
    import sys

    hooks_dir = hooks_dir or (root / ".claude" / "hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)

    base = resources.asset_source()
    src_dir = None
    if base is not None:
        src_dir = base / "hooks"

    # The fallback is consumed by a POSIX shell, including Git Bash on
    # Windows.  Keep the drive letter but use forward slashes; a backslash in
    # ``C:\\Users\\...`` is parsed as an escape by Bash.
    shell_python = sys.executable.replace("\\", "/")
    baked = f'"${{OKS_PYTHON:-{shell_python}}}"'
    created: list[str] = []
    for name in _HOOK_SUPPORT_FILES:
        dest = hooks_dir / name
        if dest.exists():
            continue
        if src_dir is None or not (src_dir / name).is_file():
            raise FileNotFoundError(
                f"bundled hook support file not found: {name} (asset source: {src_dir})"
            )
        shutil.copy2(src_dir / name, dest)
        created.append(name)

    for name in _RECALL_HOOK_SCRIPTS:
        dest = hooks_dir / name
        if dest.exists():
            try:
                dest_text = dest.read_text(encoding="utf-8")
                if src_dir is not None and (src_dir / name).is_file():
                    bundled = (src_dir / name).read_text(encoding="utf-8")
                    expected = bundled
                    if name.endswith(".sh"):
                        # A matching bake must not shield an outdated wrapper
                        # body from an upstream fix: compare against the
                        # bundled template re-baked for this interpreter.
                        expected = bundled.replace('"${OKS_PYTHON:-python3}"', baked)
                    if dest_text == expected:
                        continue
            except OSError:
                pass
            # Stale interpreter bake — fall through to re-copy + re-bake.
        if src_dir is None or not (src_dir / name).is_file():
            raise FileNotFoundError(
                f"bundled hook script not found: {name} (asset source: {src_dir})"
            )
        shutil.copy2(src_dir / name, dest)
        if name.endswith(".sh"):
            text = dest.read_text(encoding="utf-8").replace(
                '"${OKS_PYTHON:-python3}"', baked
            )
            dest.write_text(text, encoding="utf-8")
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        created.append(name)
    return created

def _stale_hook_engines(hooks_dir: Path) -> list[str]:
    """Return installed Python hook engines that differ from bundled assets."""
    base = resources.asset_source()
    if base is None:
        return []
    stale: list[str] = []
    for name in (*_HOOK_SUPPORT_FILES, *_RECALL_HOOK_SCRIPTS):
        if not name.endswith(".py"):
            continue
        src, dest = base / "hooks" / name, hooks_dir / name
        if not src.is_file() or not dest.is_file():
            continue
        try:
            if src.read_bytes() != dest.read_bytes():
                stale.append(name)
        except OSError:
            continue
    return stale

def _wire_userpromptsubmit(
    settings_path: Path, command: str, args: list[str] | None = None
) -> str:
    """Idempotently add a UserPromptSubmit command hook. Returns 'wired'|'exists'.

    Recognizes previously wired entries (old relative or stale absolute
    paths) by script name and rewrites them in place instead of duplicating.
    """
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    ups = hooks.setdefault("UserPromptSubmit", [])
    stale: dict | None = None
    for group in ups:
        for h in group.get("hooks", []):
            cmd = h.get("command", "")
            if cmd == command and h.get("args") == args:
                return "exists"
            if _hook_handler_matches_script(h, _RECALL_HOOK_SCRIPT_NAMES):
                stale = h
    if stale is not None:
        _write_hook_handler(stale, command, args)
    else:
        handler = {"type": "command", "command": command}
        _write_hook_handler(handler, command, args)
        ups.append({"hooks": [handler]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    # This file belongs to the user's editor and holds permissions, other hooks
    # and MCP servers. Keep a backup and write atomically (CONSTITUTION P2/A5)
    # so a torn write can never destroy configuration we do not own.
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return "wired"

def _wire_posttooluse(
    settings_path: Path, command: str, args: list[str] | None = None
) -> str:
    """Idempotently add a PostToolUse command hook (file conflict detection)."""
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    ptu = hooks.setdefault("PostToolUse", [])
    stale: dict | None = None
    for group in ptu:
        for h in group.get("hooks", []):
            cmd = h.get("command", "")
            if cmd == command and h.get("args") == args:
                return "exists"
            if _hook_handler_matches_script(h, _POST_TOOL_SCRIPT_NAMES):
                stale = h
    if stale is not None:
        _write_hook_handler(stale, command, args)
    else:
        handler = {"type": "command", "command": command}
        _write_hook_handler(handler, command, args)
        ptu.append({"hooks": [handler]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return "wired"

_SUBAGENT_COLLABORATION_SCRIPT = "subagent-collaboration.py"

_WORKFLOW_CONFIG_RELATIVE_PATH = Path("settings") / "task-workflow.json"

_WORKFLOW_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "Stop",
    "SubagentStart",
    "SubagentStop",
)

def _read_task_workflow_config(path: Path) -> dict:
    """Read the opt-in workflow config without masking malformed user state."""
    if not path.exists():
        return {"schema_version": "task-workflow/v1", "enabled": True, "hosts": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} cannot be read as valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if value.get("schema_version") != "task-workflow/v1":
        raise ValueError(f"{path} has an unsupported schema_version")
    if not isinstance(value.get("enabled"), bool):
        raise ValueError(f"{path} must contain a boolean enabled field")
    if not isinstance(value.get("hosts"), list) or any(
        not isinstance(host, str) for host in value["hosts"]
    ):
        raise ValueError(f"{path} must contain a string-list hosts field")
    return value

def _enable_task_workflow(path: Path, host: str) -> None:
    """Atomically enable workflow and union its host without dropping settings."""
    config = _read_task_workflow_config(path)
    config["enabled"] = True
    hosts = config["hosts"]
    if host not in hosts:
        hosts.append(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    store._atomic_write(path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")

def _wire_subagent_collaboration(
    settings_path: Path, event: str, command: str, args: list[str] | None = None
) -> str:
    """Idempotently wire one owned Claude/Codex subagent lifecycle hook."""
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as e:
            raise ValueError(f"{settings_path} is not valid JSON: {e}") from e
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault(event, [])
    stale: dict | None = None
    for group in groups:
        for handler in group.get("hooks", []):
            if handler.get("type") != "command":
                continue
            if handler.get("command") == command and handler.get("args") == args:
                return "exists"
            if _hook_handler_matches_script(handler, _SUBAGENT_COLLABORATION_SCRIPT):
                stale = handler
    if stale is not None:
        _write_hook_handler(stale, command, args)
    else:
        handler = {"type": "command", "command": command}
        _write_hook_handler(handler, command, args)
        # No matcher: capture all subagent types, including custom agents.
        groups.append({"hooks": [handler]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if settings_path.is_file():
        shutil.copy2(settings_path, settings_path.with_suffix(".json.oks-bak"))
    store._atomic_write(
        settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    )
    return "wired"

def _ensure_subagent_collaboration_script(hooks_dir: Path) -> bool:
    """Install or refresh the opt-in collaboration event recorder asset."""
    import stat

    base = resources.asset_source()
    source = base / "hooks" / _SUBAGENT_COLLABORATION_SCRIPT if base else None
    if source is None or not source.is_file():
        raise FileNotFoundError(
            f"bundled hook script not found: {_SUBAGENT_COLLABORATION_SCRIPT}"
        )
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / _SUBAGENT_COLLABORATION_SCRIPT
    source_bytes = source.read_bytes()
    if target.is_file() and target.read_bytes() == source_bytes:
        return False
    shutil.copy2(source, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True

def _hook_event_is_wired(
    settings_path: Path, event: str, script_name: str | tuple[str, ...]
) -> bool:
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError:
        return False
    for group in data.get("hooks", {}).get(event, []):
        for h in group.get("hooks", []):
            if _hook_handler_matches_script(h, script_name):
                return True
    return False

def _hook_is_wired(settings_path: Path) -> bool:
    return _hook_event_is_wired(
        settings_path, "UserPromptSubmit", _RECALL_HOOK_SCRIPT_NAMES
    )

_HOOK_RECALL_SCHEMA = "hook-recall-response/v1"

_HOOK_HISTORY_SCHEMA = "hook-recall-history/v1"

_HOOK_RECALL_STATUSES = {
    "skipped_minlen",
    "skipped_cooldown",
    "empty",
    "injected",
    "error",
}

def _hook_recall_error(reason: str, diagnostic: str = "") -> dict:
    result = {
        "schema": _HOOK_RECALL_SCHEMA,
        "status": "error",
        "context": "",
        "trace": {
            "candidate_count": 0,
            "matches": [],
            "top_relevance": None,
            "threshold": None,
        },
        "reason": reason,
    }
    # Diagnostics are opt-in: the failure detail can carry host paths and
    # stderr from the child, so it stays out of the default envelope.
    if diagnostic and os.environ.get("OKS_HOOK_DIAGNOSTICS", "").lower() in {"1", "true", "yes"}:
        result["diagnostic"] = diagnostic[-1000:]
    return result

def _valid_hook_number(value: object, *, allow_none: bool = False) -> bool:
    return (allow_none and value is None) or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )

def _validate_hook_recall_response(data: object) -> Optional[dict]:
    """Accept only the documented hook bridge envelope, never arbitrary fields."""
    if not isinstance(data, dict):
        return None
    trace = data.get("trace")
    if (
        data.get("schema") != _HOOK_RECALL_SCHEMA
        or data.get("status") not in _HOOK_RECALL_STATUSES
        or not isinstance(data.get("context"), str)
        or not isinstance(trace, dict)
        or not _valid_hook_number(trace.get("candidate_count"))
        or int(trace["candidate_count"]) < 0
        or not isinstance(trace.get("matches"), list)
        or not all(isinstance(match, str) for match in trace["matches"])
        or not _valid_hook_number(trace.get("top_relevance"), allow_none=True)
        or not _valid_hook_number(trace.get("threshold"), allow_none=True)
    ):
        return None
    result = {
        "schema": _HOOK_RECALL_SCHEMA,
        "status": data["status"],
        "context": data["context"],
        "trace": {
            "candidate_count": int(trace["candidate_count"]),
            "matches": trace["matches"],
            "top_relevance": trace["top_relevance"],
            "threshold": trace["threshold"],
        },
    }
    if isinstance(data.get("reason"), str):
        result["reason"] = data["reason"]
    return result

def _run_hook_recall(
    root: Path,
    prompt: str,
    session_id: str,
    cwd: str,
    agent_id: str,
) -> dict:
    """Run the resolved prompt hook in its structured bridge mode."""
    assets = resources.asset_source()
    if assets is None:
        return _hook_recall_error("hook_script_unavailable")
    script = assets / "hooks" / "user-prompt-recall.py"
    if not script.is_file():
        return _hook_recall_error("hook_script_unavailable")
    env = os.environ.copy()
    env["OKS_ROOT"] = str(root)
    env["OKS_HOOK_OUTPUT"] = "json"
    # The Hook Bridge exchanges JSON with a Python child process. Force UTF-8
    # instead of inheriting a Windows console code page that cannot round-trip
    # Chinese prompts or recall context.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    package_root = str(Path(__file__).resolve().parents[1])
    inherited_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([package_root, inherited_pythonpath]).rstrip(os.pathsep)
    payload = {"prompt": prompt, "session_id": session_id, "cwd": cwd, "agent_id": agent_id}
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            cwd=str(root),
            env=env,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            detail = f"hook exited {completed.returncode}"
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            if stderr:
                detail += f": {stderr[-1000:]}"
            raise RuntimeError(detail)
        data = _validate_hook_recall_response(json.loads(completed.stdout))
        if data is None:
            raise ValueError("invalid hook response")
        return data
    except Exception as exc:
        return _hook_recall_error(
            "hook_bridge_failed",
            diagnostic=f"{type(exc).__name__}: {exc}",
        )

def _read_hook_history(root: Path, limit: int, session_id: str, cwd: str) -> dict:
    """Expose existing hook injection records without prompts, paths, or a new store."""
    path = root / "records" / "inject.jsonl"
    items: list[dict] = []
    if path.is_file():
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if session_id and record.get("session_id") != session_id:
                    continue
                if cwd and record.get("cwd") != cwd:
                    continue
                slugs = [str(value).strip() for value in record.get("slugs", []) if str(value).strip()]
                rels = [float(value) for value in record.get("rels", []) if isinstance(value, (int, float))]
                fingerprint = json.dumps(record, sort_keys=True, ensure_ascii=True)
                items.append({
                    "id": "inject-" + hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12],
                    "at": str(record.get("injected_at", "")),
                    "phase": "pre-step",
                    "status": "ok",
                    "candidate_count": len(slugs),
                    "matches": slugs[:12],
                    "top_relevance": max(rels) if rels else None,
                    "threshold": None,
                })
        except OSError:
            pass
    items.sort(key=lambda item: item["at"], reverse=True)
    return {"schema": _HOOK_HISTORY_SCHEMA, "items": items[:limit], "truncated": len(items) > limit}
