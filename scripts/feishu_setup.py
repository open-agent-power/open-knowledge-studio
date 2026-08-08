#!/usr/bin/env python3
"""Auto-provision a Feishu Base, table, and form for the OKS knowledge loop.

Creates:
  1. A Base (or reuses an existing one via --base-token)
  2. A "每日知识采集" table with 27 fields (6 user-visible + 21 worker control)
  3. A form view exposing only the 6 user-visible fields

Uses ``lark-cli`` under the hood.  Requires a working ``lark-cli auth`` session.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from feishu_worker.states import (  # noqa: E402
    CAPTURE_MODE_OPTIONS,
    CAPTURE_STATUS_OPTIONS,
    QUALITY_STATUS_OPTIONS,
    REVIEW_ACTION_OPTIONS,
    RUN_STATUS_OPTIONS,
    WIKI_STATUS_OPTIONS,
)


def _options(values: tuple[str, ...]) -> list[dict[str, str]]:
    """Render a states.py tuple as lark-cli select options."""
    return [{"name": value} for value in values]


# ── lark-cli helper ──────────────────────────────────────────────

_LARK_CLI: str | None = None
_WRITE_COUNT = 0
_WRITE_COMMANDS = {
    "+base-create", "+table-create", "+field-create", "+field-update",
    "+form-create", "+form-update", "+form-questions-create",
    "+form-questions-update", "+form-questions-delete", "+view-create",
    "+view-rename", "+view-set-visible-fields",
}

FEISHU_CONFIG_SCHEMA = "oks-feishu-config/v1"
_CONFIG_DIR_NAME = ".oks"
_CONFIG_FILE_NAME = "config.json"


def _get_lark_cli() -> str:
    """Lazily resolve and cache the lark-cli path. Never fails at import time."""
    global _LARK_CLI
    if _LARK_CLI is not None:
        return _LARK_CLI
    from _lark_cli import resolve_lark_cli

    _LARK_CLI = str(resolve_lark_cli())
    return _LARK_CLI


def _redact_token(token: str) -> str:
    """Show only the first 6 and last 4 characters of a Base token."""
    if len(token) <= 12:
        return token[:2] + "***" + token[-2:]
    return token[:6] + "***" + token[-4:]


def _redact_text(text: str, token: str | None) -> str:
    """Replace every occurrence of *token* in *text* with its redacted form."""
    if not token:
        return text
    return text.replace(token, _redact_token(token))


def _oks_config_path() -> Path:
    """Return the shared OKS config path without creating it."""
    return Path.home() / _CONFIG_DIR_NAME / _CONFIG_FILE_NAME


def _load_oks_config() -> dict[str, Any]:
    """Load the shared config while preserving unrelated OKS settings."""
    path = _oks_config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"OKS 配置文件损坏: {path}；请先修复 JSON，再重试飞书初始化"
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"OKS 配置文件必须是 JSON 对象: {path}")
    return value


def _save_oks_config(config: dict[str, Any]) -> bool:
    """Atomically persist config and report whether its content changed."""
    path = _oks_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == encoded:
        return False
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix="config.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        with contextlib.suppress(OSError):
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return True


def _saved_feishu_config() -> dict[str, Any]:
    """Read the persisted Feishu coordinates, if any."""
    config = _load_oks_config()
    section = config.get("feishu", {})
    return section if isinstance(section, dict) else {}


def _persist_feishu_config(
    *,
    base_token: str,
    table_id: str,
    table_name: str,
    form_id: str,
    view_id: str,
) -> bool:
    config = _load_oks_config()
    config["feishu"] = {
        "schema_version": FEISHU_CONFIG_SCHEMA,
        "base_token": base_token,
        "table_id": table_id,
        "table_name": table_name,
        "form_id": form_id,
        "view_id": view_id,
    }
    return _save_oks_config(config)


def _lark(args: list[str], *, timeout: float = 60.0, redact_token: str | None = None) -> dict[str, Any]:
    """Run a lark-cli JSON command and return the parsed result."""
    global _WRITE_COUNT
    if len(args) > 1 and args[1] in _WRITE_COMMANDS:
        _WRITE_COUNT += 1
    cmd = [_get_lark_cli(), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        detail = _redact_text(detail, redact_token)
        raise RuntimeError(
            f"lark-cli {' '.join(args[:2])} 失败 (exit {result.returncode})\n{detail[-2000:]}"
        )
    try:
        return json.loads(result.stdout)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {"_raw": result.stdout}


def _lark_text(args: list[str], *, timeout: float = 60.0, redact_token: str | None = None) -> str:
    """Run a lark-cli command and return raw stdout text."""
    cmd = [_get_lark_cli(), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        detail = _redact_text(detail, redact_token)
        raise RuntimeError(
            f"lark-cli {' '.join(args[:2])} 失败 (exit {result.returncode})\n{detail[-2000:]}"
        )
    return result.stdout


# ── field schema ──────────────────────────────────────────────────

# User-visible fields (shown in the form). Keep this list intentionally small:
# the Base table also contains worker control fields, but those must never leak
# into the daily capture form.
_KNOWLEDGE_DOMAIN_OPTIONS = [
    {"name": name}
    for name in (
        "management", "transport", "finance", "production", "repair",
        "engineering", "construction", "science", "agriculture", "social",
        "administration", "legal", "sales", "education", "personal", "media",
        "healthcare", "care", "maintenance", "food", "security", "computing",
    )
]

FORM_DESCRIPTION = (
    "记录今天值得留下的内容。文字、链接、图片、视频、语音和文件都可以；"
    "处理状态由后续自动化维护。"
)

VIEW_NAME = "采集总览"
# Keep the grid focused on the capture and processing summary, matching the
# reference "每天学了什么 - 列表" view. Worker lease/review internals remain
# available to the pipeline but should not dominate the daily user view.
VIEW_VISIBLE_FIELDS = [
    "内容",
    "附件",
    "思考",
    "状态",
    "评级",
    "知识域",
    "总结",
]

USER_FIELDS: list[dict[str, Any]] = [
    {
        "name": "内容",
        "type": "text",
        "description": "粘贴今天看到或想到的原始内容；网址也可以直接粘贴。",
        "required": True,
    },
    {
        "name": "附件",
        "type": "attachment",
        "description": "可选：图片、截图、视频、语音、PDF 或其他文件。",
    },
    {
        "name": "思考",
        "type": "text",
        "description": "可选：你的判断、疑问、联想、可复用模式或行动想法。",
    },
    {
        "name": "希望解决的问题",
        "form_title": "重点问题（可选）",
        "type": "text",
        "description": "可选：希望 Agent 重点回答、判断或验证什么？",
    },
    {
        "name": "评级",
        "type": "select",
        "multiple": False,
        "option_display_mode": 2,
        "options": [
            {"name": "A"}, {"name": "B"}, {"name": "C"},
        ],
        "description": "可选：A=高价值优先处理，B=可保留，C=低优先级或可跳过。",
    },
    {
        "name": "知识域",
        "type": "select",
        "multiple": True,
        "option_display_mode": 0,
        "options": _KNOWLEDGE_DOMAIN_OPTIONS,
        "description": "可选多选；不确定就留空，Agent 后续判断。",
    },
]

# Worker control fields (hidden from the form)
WORKER_FIELDS: list[dict[str, Any]] = [
    {"name": "运行状态", "type": "select", "options": _options(RUN_STATUS_OPTIONS)},
    {"name": "运行ID", "type": "text"},
    {"name": "来源哈希", "type": "text"},
    {"name": "重试", "type": "number"},
    {"name": "租约所有者", "type": "text"},
    {"name": "租约到期", "type": "text"},
    {"name": "Raw Bundle", "type": "text"},
    {"name": "Wiki状态", "type": "select", "options": _options(WIKI_STATUS_OPTIONS)},
    {"name": "候选ID", "type": "text"},
    {"name": "候选内容", "type": "text"},
    {"name": "审核动作", "type": "select", "options": _options(REVIEW_ACTION_OPTIONS)},
    {"name": "审核意见", "type": "text"},
    {"name": "修改类型", "type": "text"},
    {"name": "审核时间", "type": "text"},
    {"name": "Wiki路径", "type": "text"},
    {"name": "错误码", "type": "text"},
    {"name": "错误说明", "type": "text"},
    {"name": "采集模式", "type": "select", "options": _options(CAPTURE_MODE_OPTIONS)},
    {"name": "质量状态", "type": "select", "options": _options(QUALITY_STATUS_OPTIONS)},
    {"name": "总结", "type": "text"},
    {"name": "状态", "type": "select", "options": _options(CAPTURE_STATUS_OPTIONS)},
]


_FORM_ONLY_FIELD_KEYS = {"form_title", "required", "option_display_mode"}


def _base_field(field: dict[str, Any]) -> dict[str, Any]:
    """Return only properties accepted by Base field create/update APIs."""
    return {
        key: value
        for key, value in field.items()
        if key not in _FORM_ONLY_FIELD_KEYS
    }


def _base_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_base_field(field) for field in fields]


def _permission_preflight(base_token: str | None) -> None:
    """Check user auth and, when supplied, resource access before writes."""
    print("[preflight] 检查飞书用户授权和资源权限...")
    auth = _lark(
        ["auth", "status", "--json", "--verify"],
        redact_token=base_token,
    )
    # A small empty response is accepted for isolated unit mocks. The real
    # lark-cli always returns the structured envelope below or raises.
    if not auth:
        return
    if auth.get("verified") is not True:
        raise RuntimeError(
            "飞书用户授权预检失败：请先完成 lark-cli auth login；"
            "不要在 setup 中重复创建 Base。"
        )
    user = auth.get("identities", {}).get("user", {})
    if user.get("status") != "ready" or user.get("tokenStatus") != "valid":
        raise RuntimeError(
            "飞书用户授权已过期或未完成：请刷新 user OAuth 后再运行 setup。"
        )
    if base_token:
        try:
            _lark([
                "base", "+base-get", "--base-token", base_token,
                "--as", "user",
            ], redact_token=base_token)
        except RuntimeError as exc:
            raise RuntimeError(
                "飞书 Base 资源权限预检失败：当前用户或应用没有访问该 Base 的权限；"
                "请检查 Base 分享权限和应用 scope，再重试。\n"
                + _redact_text(str(exc), base_token)
            ) from exc


def _option_names(options: Any) -> list[str]:
    if not isinstance(options, list):
        return []
    return [
        str(item.get("name", ""))
        for item in options
        if isinstance(item, dict)
    ]


def _field_diff(expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return semantic schema differences while ignoring server-generated IDs/styles."""
    differences: list[str] = []
    for key in ("name", "type", "multiple", "description"):
        if key in current and key in expected and current.get(key) != expected.get(key):
            differences.append(key)
    if "options" in current and "options" in expected:
        if _option_names(current.get("options")) != _option_names(expected.get("options")):
            differences.append("options")
    return differences


def _field_update_payload(current: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Build a full PUT payload from the current field plus expected safe settings."""
    allowed = {
        "name", "type", "multiple", "options", "description", "style",
        "default_value",
    }
    payload = {key: value for key, value in current.items() if key in allowed}
    for key in ("name", "type", "multiple", "options", "description", "style"):
        if key in expected:
            payload[key] = expected[key]
    return payload


def _reconcile_fields(
    *,
    base_token: str,
    table_id: str,
    all_fields: list[dict[str, Any]],
    repair_schema: bool,
    confirm_writes: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Create missing fields and optionally repair safe schema drift."""
    existing_result = _lark([
        "base", "+field-list", "--base-token", base_token,
        "--table-id", table_id, "--limit", "200",
    ], redact_token=base_token)
    field_list = _collection(existing_result, "fields")
    existing_by_name = {
        str(field.get("name") or field.get("field_name")): field
        for field in field_list
        if field.get("name") or field.get("field_name")
    }
    writes = 0
    diffs: list[dict[str, Any]] = []
    for expected_raw in all_fields:
        expected = _base_field(expected_raw)
        name = str(expected["name"])
        current = existing_by_name.get(name)
        if current is None:
            _lark([
                "base", "+field-create", "--base-token", base_token,
                "--table-id", table_id, "--json",
                json.dumps(expected, ensure_ascii=False),
            ], redact_token=base_token)
            writes += 1
            print(f"  + 新增字段: {name}")
            continue

        difference = _field_diff(expected, current)
        if not difference:
            continue
        entry = {"field": name, "changes": difference}
        diffs.append(entry)
        print(f"  ! schema drift: {name} ({', '.join(difference)})")
        if (
            repair_schema
            and current.get("type")
            and expected.get("type") != current.get("type")
        ):
            raise RuntimeError(
                f"字段 {name} 类型不一致（{current.get('type')} -> {expected.get('type')}）；"
                "为避免破坏历史数据，停止自动修复，请人工迁移。"
            )
        if not repair_schema:
            continue
        if not confirm_writes:
            raise RuntimeError(
                "检测到可修复的 Feishu schema drift；请同时指定 "
                "--repair-schema --yes 才执行高风险字段 PUT。"
            )
        payload = _field_update_payload(current, expected)
        _lark([
            "base", "+field-update", "--base-token", base_token,
            "--table-id", table_id, "--field-id", str(current.get("id") or name),
            "--json", json.dumps(payload, ensure_ascii=False), "--yes",
        ], redact_token=base_token)
        writes += 1
        # Keep setup output ASCII-safe on Windows GBK consoles.
        print(f"  OK 修复字段: {name}")
    return writes, diffs


def _form_title(field: dict[str, Any]) -> str:
    return str(field.get("form_title") or field["name"])


def _collection(result: dict[str, Any] | list[Any], key: str) -> list[dict[str, Any]]:
    """Read a list from either the current or legacy lark-cli envelope."""
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    data = result.get("data", {}) if isinstance(result, dict) else {}
    if isinstance(data, dict):
        items = data.get(key, [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    items = result.get(key, []) if isinstance(result, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _form_question_update(field: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    """Build the supported, user-facing portion of a form question update."""
    update: dict[str, Any] = {
        "id": question["id"],
        "required": bool(field.get("required", False)),
    }
    title = _form_title(field)
    if question.get("title") != title:
        update["title"] = title
    if field.get("description"):
        update["description"] = field["description"]
    if "option_display_mode" in field:
        update["option_display_mode"] = field["option_display_mode"]
    return update


def _form_question_needs_update(field: dict[str, Any], question: dict[str, Any]) -> bool:
    """Avoid lark-cli's error response for an idempotent question update."""
    if question.get("title") != _form_title(field):
        return True
    if bool(question.get("required", False)) != bool(field.get("required", False)):
        return True
    if field.get("description") and question.get("description") != field["description"]:
        return True
    if (
        "option_display_mode" in field
        and question.get("option_display_mode") != field["option_display_mode"]
    ):
        return True
    return False


def _form_question_create(field: dict[str, Any]) -> dict[str, Any]:
    """Build a form question for a table field missing from the form."""
    question: dict[str, Any] = {
        "title": _form_title(field),
        "type": field["type"],
        "required": bool(field.get("required", False)),
    }
    for key in ("description", "multiple", "option_display_mode", "options", "style"):
        if key in field:
            question[key] = field[key]
    return question


def _ensure_capture_form(base_token: str, table_id: str, table_name: str) -> str:
    """Reuse one clean capture form and keep worker fields out of it."""
    forms = _collection(_lark([
        "base", "+form-list", "--base-token", base_token, "--table-id", table_id,
    ], redact_token=base_token), "forms")
    preferred_names = (table_name, f"{table_name} - 采集表单")
    form = next((item for item in forms if item.get("name") == preferred_names[0]), None)
    if form is None:
        form = next((item for item in forms if item.get("name") == preferred_names[1]), None)

    if form is None:
        result = _lark([
            "base", "+form-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--name", table_name,
            "--description", FORM_DESCRIPTION,
            "--format", "json",
        ], redact_token=base_token)
        data = result.get("data", {}) if isinstance(result, dict) else {}
        form_id = (
            (data.get("form_id") if isinstance(data, dict) else None)
            or (data.get("id") if isinstance(data, dict) else None)
            or result.get("form_id", "")
        )
        if not form_id:
            raise RuntimeError("无法从 lark-cli 响应获取 form_id")
        print(f"  表单已创建: {form_id}")
    else:
        form_id = form.get("id") or form.get("form_id")
        if not form_id:
            raise RuntimeError("已有表单缺少 form_id")
        print(f"  复用已有表单: {form_id}")

    questions = _collection(_lark([
        "base", "+form-questions-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--form-id", form_id,
    ], redact_token=base_token), "questions")
    user_fields = {_form_title(field): field for field in USER_FIELDS}
    stale_ids = [
        question["id"]
        for question in questions
        if question.get("title") not in user_fields and question.get("id")
    ]
    if stale_ids:
        for start in range(0, len(stale_ids), 10):
            batch = stale_ids[start:start + 10]
            _lark([
                "base", "+form-questions-delete",
                "--base-token", base_token,
                "--table-id", table_id,
                "--form-id", form_id,
                "--question-ids", json.dumps(batch, ensure_ascii=False),
                "--yes",
            ], redact_token=base_token)
        print(f"  已从表单隐藏 {len(stale_ids)} 个内部控制题目")

    existing_titles = {question.get("title") for question in questions}
    creates = [
        _form_question_create(field)
        for field in USER_FIELDS
        if _form_title(field) not in existing_titles
    ]
    if creates:
        _lark([
            "base", "+form-questions-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
            "--questions", json.dumps(creates, ensure_ascii=False),
        ], redact_token=base_token)
        print(f"  已补齐 {len(creates)} 个缺失的采集题目")

    updates = [
        _form_question_update(user_fields[question["title"]], question)
        for question in questions
        if (
            question.get("title") in user_fields
            and question.get("id")
            and _form_question_needs_update(user_fields[question["title"]], question)
        )
    ]
    if updates:
        _lark([
            "base", "+form-questions-update",
            "--base-token", base_token,
            "--table-id", table_id,
            "--form-id", form_id,
            "--questions", json.dumps(updates, ensure_ascii=False),
        ], redact_token=base_token)

    return str(form_id)


def _ensure_capture_view(base_token: str, table_id: str) -> str:
    """Keep the default grid useful without exposing worker internals."""
    views = _collection(_lark([
        "base", "+view-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--format", "json",
    ], redact_token=base_token), "views")
    view = next((item for item in views if item.get("name") == VIEW_NAME), None)
    if view is None:
        view = next((item for item in views if item.get("type") == "grid"), None)
    if view is None:
        result = _lark([
            "base", "+view-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps({"name": VIEW_NAME, "type": "grid"}, ensure_ascii=False),
        ], redact_token=base_token)
        data = result.get("data", {}) if isinstance(result, dict) else {}
        candidates = data.get("views", []) if isinstance(data, dict) else []
        view = candidates[0] if candidates and isinstance(candidates[0], dict) else data.get("view", {})
    view_id = view.get("id") or view.get("view_id")
    if not view_id:
        print("  ! 未能确定采集总览网格视图，跳过网格列配置")
        return ""
    if view.get("name") != VIEW_NAME:
        _lark([
            "base", "+view-rename",
            "--base-token", base_token,
            "--table-id", table_id,
            "--view-id", str(view_id),
            "--name", VIEW_NAME,
        ], redact_token=base_token)

    current = _lark([
        "base", "+view-get-visible-fields",
        "--base-token", base_token,
        "--table-id", table_id,
        "--view-id", str(view_id),
        "--format", "json",
    ], redact_token=base_token)
    current_fields = (current.get("data", {}) or {}).get("visible_fields", [])
    if current_fields != VIEW_VISIBLE_FIELDS:
        _lark([
            "base", "+view-set-visible-fields",
            "--base-token", base_token,
            "--table-id", table_id,
            "--view-id", str(view_id),
            "--json", json.dumps({"visible_fields": VIEW_VISIBLE_FIELDS}, ensure_ascii=False),
        ], redact_token=base_token)
    return str(view_id)


# ── main setup logic ──────────────────────────────────────────────

def setup(args: argparse.Namespace) -> int:
    global _WRITE_COUNT
    _WRITE_COUNT = 0
    saved = _saved_feishu_config()
    explicit_base = args.base_token or os.environ.get("OKS_FEISHU_BASE_TOKEN")
    saved_base = saved.get("base_token")
    base_token = explicit_base or saved_base
    table_name = args.table_name or saved.get("table_name") or "每日知识采集"
    show_credentials = bool(args.show_credentials)

    _permission_preflight(base_token)

    # ── Step 1: create or reuse Base ──
    if base_token:
        print(f"[1/4] 使用已有 Base: {_redact_token(base_token)}")
        _existing = _lark(["base", "+base-get", "--base-token", base_token], redact_token=base_token)
        existing_data = _existing.get("data", {}) if isinstance(_existing, dict) else {}
        existing_base = existing_data.get("base", {}) if isinstance(existing_data, dict) else {}
        base_name = (
            existing_base.get("name")
            or _existing.get("name", "OKS Base")
            if isinstance(_existing, dict)
            else "OKS Base"
        )
    else:
        base_name = args.base_name or "Open Knowledge Studio"
        print(f"[1/4] 创建 Base: {base_name}")
        result = _lark([
            "base", "+base-create",
            "--name", base_name,
            "--table-name", table_name,
            "--fields", json.dumps(_base_fields(USER_FIELDS[:2]), ensure_ascii=False),
            "--time-zone", "Asia/Shanghai",
            "--format", "json",
        ])
        result_data = result.get("data", {}) if isinstance(result, dict) else {}
        base = result.get("base", {}) or result_data.get("base", {})
        base_token = result.get("base_token") or result_data.get("base_token") or base.get("base_token")
        if not base_token:
            raise RuntimeError("无法从 lark-cli 响应获取 Base token")
        permission = result.get("permission_grant", "") or result_data.get("permission_grant", "")
        if permission:
            print(f"  权限提示: {permission}")

    if not base_token:
        raise RuntimeError("无法确定 Base token")

    # ── Step 2: find or create the capture table ──
    print(f"[2/4] 定位/创建采集表: {table_name}")
    tables = _lark(["base", "+table-list", "--base-token", base_token], redact_token=base_token)
    table_list = tables if isinstance(tables, list) else (
        tables.get("data", {}).get("tables", []) or tables.get("items", [])
    )
    table_id = None
    preferred_table_id = (
        args.table_id
        or (
            saved.get("table_id")
            if saved_base and str(saved_base) == str(base_token)
            else None
        )
    )
    for t in table_list:
        if not isinstance(t, dict):
            continue
        candidate_id = t.get("id") or t.get("table_id")
        if candidate_id == preferred_table_id or (
            preferred_table_id is None and t.get("name") == table_name
        ):
            table_id = candidate_id
            break

    if preferred_table_id and not table_id:
        raise RuntimeError(
            f"配置中的 Feishu table_id 不存在于 Base {_redact_token(base_token)}；"
            "为避免误建新表，请先确认 table_id 或清理失效配置。"
        )

    if table_id:
        print(f"  表已存在: {table_id}")
    else:
        if args.table_id:
            raise RuntimeError(
                f"指定的 Feishu table_id 不存在: {args.table_id}；未创建替代表。"
            )
        # Create table with initial fields
        result = _lark([
            "base", "+table-create",
            "--base-token", base_token,
            "--name", table_name,
            "--fields", json.dumps(_base_fields(USER_FIELDS[:6]), ensure_ascii=False),
            "--format", "json",
        ], redact_token=base_token)
        table_id = result.get("table_id")
        if not table_id:
            raise RuntimeError(f"无法获取 table_id: {json.dumps(result, ensure_ascii=False)}")
        print(f"  表已创建: {table_id}")

    # ── Step 3: ensure all 27 fields exist ──
    print("[3/4] 确保 27 个字段...")
    all_fields = USER_FIELDS + WORKER_FIELDS
    field_writes, schema_diffs = _reconcile_fields(
        base_token=base_token,
        table_id=str(table_id),
        all_fields=all_fields,
        repair_schema=bool(args.repair_schema),
        confirm_writes=bool(args.yes),
    )
    if schema_diffs and not args.repair_schema:
        print("  [提示] 检测到 schema drift；本次只报告，使用 --repair-schema --yes 修复")
    elif not schema_diffs:
        print("  schema 与声明一致")

    # ── Step 4: reuse/create one clean form ──
    print("[4/4] 复用或创建每日知识采集表单...")
    view_id = _ensure_capture_view(base_token, table_id)
    if view_id:
        print(f"  采集总览视图已就绪: {view_id}")
    form_id = _ensure_capture_form(base_token, table_id, table_name)

    config_changed = _persist_feishu_config(
        base_token=base_token,
        table_id=str(table_id),
        table_name=table_name,
        form_id=form_id,
        view_id=view_id,
    )
    print(
        "  本地 Feishu 配置已保存: "
        f"{'更新' if config_changed else '无变化'} ({_oks_config_path()})"
    )
    print(f"  本次云端写入调用数: {_WRITE_COUNT}")

    # ── output configuration ──
    display_token = base_token if show_credentials else _redact_token(base_token)
    print()
    print("=" * 60)
    print("飞书配置完成。请将以下内容设置为环境变量：")
    print()
    print(f"  $env:OKS_FEISHU_BASE_TOKEN = \"{display_token}\"")
    print(f"  $env:OKS_FEISHU_TABLE_ID   = \"{table_id}\"")
    if form_id:
        print(f"  # Form ID: {form_id}")
    if view_id:
        print(f"  # View ID: {view_id}")
    print()
    print("或写入 ~/.oks/config.json:")
    print(json.dumps({
        "feishu": {
            "schema_version": FEISHU_CONFIG_SCHEMA,
            "base_token": display_token,
            "table_id": table_id,
            "table_name": table_name,
            "form_id": form_id,
            "view_id": view_id,
        }
    }, ensure_ascii=False, indent=2))
    if not show_credentials:
        print()
        print("  [提示] 使用 --show-credentials 查看完整 Base token。")
    print("=" * 60)

    return 0


# ── CLI ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oks feishu setup",
        description="自动创建飞书 Base、采集表和表单，用于 OKS 知识闭环。",
    )
    parser.add_argument("--base-token", help="已有 Base token（跳过创建 Base）")
    parser.add_argument("--table-id", help="指定已有采集表 ID；不传则按表名复用")
    parser.add_argument("--base-name", default="Open Knowledge Studio", help="新建 Base 的名称")
    parser.add_argument("--table-name", help="采集表名称；默认复用配置或使用每日知识采集")
    parser.add_argument("--time-zone", default="Asia/Shanghai")
    parser.add_argument(
        "--repair-schema",
        action="store_true",
        help="修复安全的字段 schema drift；必须同时指定 --yes",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认 schema 字段 PUT 等高风险写入",
    )
    parser.add_argument(
        "--show-credentials",
        action="store_true",
        help="Display the full Base token in output instead of the default redacted form",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(setup(build_parser().parse_args()))
