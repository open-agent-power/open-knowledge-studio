#!/usr/bin/env python3
"""Auto-provision a Feishu Base, table, and form for the OKS knowledge loop.

Creates:
  1. A Base (or reuses an existing one via --base-token)
  2. A "每日知识采集" table with 28 fields (6 user-visible + 22 worker control)
  3. A form view exposing only the 6 user-visible fields

Uses ``lark-cli`` under the hood.  Requires a working ``lark-cli auth`` session.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from feishu_worker.states import (  # noqa: E402
    CAPTURE_MODE_OPTIONS,
    KNOWLEDGE_DOMAIN_OPTIONS,
    QUALITY_STATUS_OPTIONS,
    RATING_OPTIONS,
    REVIEW_ACTION_OPTIONS,
    RUN_STATUS_OPTIONS,
    WIKI_STATUS_OPTIONS,
)


def _options(values: tuple[str, ...]) -> list[dict[str, str]]:
    """Render a states.py tuple as lark-cli select options."""
    return [{"name": value} for value in values]


# ── lark-cli helper ──────────────────────────────────────────────

_LARK_CLI: str | None = None


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


def _lark(args: list[str], *, timeout: float = 60.0, redact_token: str | None = None) -> dict[str, Any]:
    """Run a lark-cli JSON command and return the parsed result."""
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

# User-visible backing fields, in the exact order used by the reference form.
USER_FIELDS: list[dict[str, Any]] = [
    {"name": "内容", "type": "text"},
    {"name": "附件", "type": "attachment"},
    {"name": "思考", "type": "text"},
    {"name": "重点问题（可选）", "type": "text"},
    {"name": "评级", "type": "select", "options": _options(RATING_OPTIONS)},
    {
        "name": "知识域",
        "type": "select",
        "multiple": True,
        "options": _options(KNOWLEDGE_DOMAIN_OPTIONS),
    },
]

FORM_NAME = "OKS Daily Knowledge Intake"
FORM_DESCRIPTION = (
    "记录今天值得留下的内容。文字、链接、图片、视频、语音和文件都可以；"
    "处理状态由后续自动化维护。"
)
FORM_QUESTIONS: list[dict[str, Any]] = [
    {
        "source_name": "内容", "title": "内容", "required": True,
        "description": "粘贴今天看到或想到的原始内容；网址也可以直接粘贴。",
    },
    {
        "source_name": "附件", "title": "附件", "required": False,
        "description": "可选：图片、截图、视频、语音、PDF 或其他文件。",
    },
    {
        "source_name": "思考", "title": "思考", "required": False,
        "description": "可选：你的判断、疑问、联想、可复用模式或行动想法。",
    },
    {
        "source_name": "重点问题（可选）", "legacy_name": "希望解决的问题",
        "title": "重点问题（可选）", "required": False,
        "description": "可选：希望 Agent 重点回答、判断或验证什么？",
    },
    {
        "source_name": "评级", "title": "评级", "required": False,
        "description": "可选：A=高价值优先处理，B=可保留，C=低优先级或可跳过。",
        "option_display_mode": 2,
    },
    {
        "source_name": "知识域", "title": "知识域", "required": False,
        "description": "可选多选；不确定就留空，Agent 后续判断。",
        "option_display_mode": 1,
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
    {"name": "状态", "type": "select", "options": [
        {"name": "active"}, {"name": "archived"},
    ]},
]


def _items(result: Any, *keys: str) -> list[dict[str, Any]]:
    """Normalize list responses returned by different lark-cli versions."""
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if not isinstance(result, dict):
        return []
    for container in (result.get("data"), result):
        if not isinstance(container, dict):
            continue
        for key in keys:
            value = container.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _question_title(question: dict[str, Any]) -> str:
    return str(
        question.get("title")
        or question.get("name")
        or question.get("field_name")
        or ""
    )


def _list_form_questions(base_token: str, table_id: str, form_id: str) -> list[dict[str, Any]]:
    return _items(_lark([
        "base", "+form-questions-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--form-id", form_id,
        "--format", "json",
    ], redact_token=base_token), "items", "questions")


def _find_form(base_token: str, table_id: str, names: tuple[str, ...]) -> str:
    result = _lark([
        "base", "+form-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--format", "json",
    ], redact_token=base_token)
    for form in _items(result, "forms", "items"):
        if form.get("name") in names:
            return str(form.get("id") or form.get("form_id") or "")
    return ""


def _read_form_questions(base_token: str, table_id: str, form_id: str) -> list[dict[str, Any]]:
    """Read through Feishu's short propagation window without hiding failures."""
    for attempt in range(5):
        try:
            questions = _list_form_questions(base_token, table_id, form_id)
        except RuntimeError as exc:
            if "not_found" not in str(exc).lower() or attempt == 4:
                raise
            questions = []
        if questions:
            return questions
        if attempt < 4:
            time.sleep(attempt + 1)
    return []


def _question_create_payload(start: int) -> list[dict[str, Any]]:
    payload = []
    for field, desired in zip(USER_FIELDS[start:], FORM_QUESTIONS[start:]):
        question = dict(field)
        question["title"] = desired["title"]
        question.pop("name", None)
        question["description"] = desired["description"]
        question["required"] = desired["required"]
        if "option_display_mode" in desired:
            question["option_display_mode"] = desired["option_display_mode"]
        payload.append(question)
    return payload


def _complete_user_form(base_token: str, table_id: str, form_id: str) -> None:
    """Only append questions when the current form is a safe ordered prefix."""
    questions = _read_form_questions(base_token, table_id, form_id)
    actual = [_question_title(item) for item in questions]
    accepted_prefix = [
        {
            question["source_name"],
            question["title"],
            str(question.get("legacy_name") or question["source_name"]),
        }
        for question in FORM_QUESTIONS[:len(actual)]
    ]
    if not questions:
        raise RuntimeError(
            "新建表单未返回引导问题，拒绝盲目创建字段；请稍后重试 setup"
        )
    if len(actual) > len(FORM_QUESTIONS) or any(
        title not in accepted_prefix[index] for index, title in enumerate(actual)
    ):
        raise RuntimeError(
            "现有表单包含额外字段或顺序异常，拒绝自动修改："
            f"{actual}。setup 不会删除底层字段或表单问题；请新建表单后再迁移。"
        )
    if len(actual) == len(FORM_QUESTIONS):
        return
    _lark([
        "base", "+form-questions-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--form-id", form_id,
        "--questions", json.dumps(_question_create_payload(len(actual)), ensure_ascii=False),
        "--format", "json",
    ], redact_token=base_token)

    # The create call may return before all questions are visible to the read
    # endpoint. Wait for the expected count, while still rejecting any shape
    # that stops being a safe ordered prefix.
    for attempt in range(5):
        questions = _list_form_questions(base_token, table_id, form_id)
        actual = [_question_title(item) for item in questions]
        accepted_prefix = [
            {
                question["source_name"],
                question["title"],
                str(question.get("legacy_name") or question["source_name"]),
            }
            for question in FORM_QUESTIONS[:len(actual)]
        ]
        if len(actual) == len(FORM_QUESTIONS):
            return
        if len(actual) > len(FORM_QUESTIONS) or any(
            title not in accepted_prefix[index] for index, title in enumerate(actual)
        ):
            raise RuntimeError(
                "新增表单问题后出现额外字段或顺序异常，拒绝继续："
                f"{actual}。setup 不会删除底层字段或表单问题。"
            )
        if attempt < 4:
            time.sleep(attempt + 1)
    raise RuntimeError(
        "新增表单问题后未能在传播窗口内读取完整六字段，拒绝报告配置成功"
    )


def _verify_user_form(base_token: str, table_id: str, form_id: str) -> None:
    """Configure and verify exactly six questions; otherwise fail closed."""
    questions = _read_form_questions(base_token, table_id, form_id)
    if not questions:
        raise RuntimeError("无法读取表单问题列表，拒绝报告配置成功")
    actual = [_question_title(item) for item in questions]
    expected_sources = [
        {
            question["source_name"],
            question["title"],
            str(question.get("legacy_name") or question["source_name"]),
        }
        for question in FORM_QUESTIONS
    ]
    if len(actual) != len(FORM_QUESTIONS) or any(
        title not in expected_sources[index] for index, title in enumerate(actual)
    ):
        raise RuntimeError(
            "表单字段校验失败：期望按顺序仅包含 "
            f"{[item['title'] for item in FORM_QUESTIONS]}，实际为 {actual}。"
            "setup 不会自动删除底层字段或表单问题。"
        )
    updates = []
    for question, desired in zip(questions, FORM_QUESTIONS):
        question_id = question.get("id") or question.get("field_id")
        if not question_id:
            raise RuntimeError("表单问题缺少 ID，无法安全配置表单")
        update = {
            "id": question_id,
            "title": desired["title"],
            "description": desired["description"],
            "required": desired["required"],
        }
        if "option_display_mode" in desired:
            update["option_display_mode"] = desired["option_display_mode"]
        updates.append(update)
    _lark([
        "base", "+form-update", "--base-token", base_token,
        "--table-id", table_id, "--form-id", form_id,
        "--name", FORM_NAME, "--description", FORM_DESCRIPTION,
        "--format", "json",
    ], redact_token=base_token)
    _lark([
        "base", "+form-questions-update", "--base-token", base_token,
        "--table-id", table_id, "--form-id", form_id,
        "--questions", json.dumps(updates, ensure_ascii=False),
        "--format", "json",
    ], redact_token=base_token)

    # Read back after writes. A successful update response is not proof that
    # Feishu persisted the exact public form schema.
    expected_required = [bool(item["required"]) for item in FORM_QUESTIONS]
    expected_titles = [item["title"] for item in FORM_QUESTIONS]
    verified_titles: list[str] = []
    verified_required: list[bool] = []
    for attempt in range(5):
        verified = _list_form_questions(base_token, table_id, form_id)
        verified_titles = [_question_title(item) for item in verified]
        verified_required = [bool(item.get("required")) for item in verified]
        if verified_titles == expected_titles and verified_required == expected_required:
            break
        if attempt < 4:
            time.sleep(attempt + 1)
    if verified_titles != expected_titles or verified_required != expected_required:
        raise RuntimeError(
            "表单写入后校验失败："
            f"titles={verified_titles}, required={verified_required}。拒绝报告配置成功。"
        )


def _ensure_fields(
    base_token: str,
    table_id: str,
    fields: list[dict[str, Any]],
    existing_names: set[str],
) -> int:
    created = 0
    for field in fields:
        if field["name"] in existing_names:
            continue
        _lark([
            "base", "+field-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(field, ensure_ascii=False),
        ], redact_token=base_token)
        existing_names.add(field["name"])
        created += 1
    return created


def _validate_existing_user_fields(field_list: list[dict[str, Any]]) -> None:
    """Reject field shapes that cannot implement the reference form safely."""
    by_name = {
        str(field.get("name") or field.get("field_name") or ""): field
        for field in field_list
    }
    problems = []
    for expected in USER_FIELDS:
        actual = by_name.get(expected["name"])
        if not actual and expected.get("name") == "重点问题（可选）":
            actual = by_name.get("希望解决的问题")
        if not actual or "type" not in actual:
            continue
        if actual.get("type") != expected["type"]:
            problems.append(
                f"{expected['name']} 类型应为 {expected['type']}，实际为 {actual.get('type')}"
            )
            continue
        if expected["type"] != "select":
            continue
        if "multiple" in actual and bool(actual.get("multiple")) != bool(expected.get("multiple")):
            problems.append(f"{expected['name']} 的单选/多选配置不匹配")
        actual_options = [
            str(option.get("name") or "") for option in actual.get("options", [])
            if isinstance(option, dict)
        ]
        expected_options = [str(option["name"]) for option in expected.get("options", [])]
        if actual_options and actual_options != expected_options:
            problems.append(f"{expected['name']} 的选项不匹配")
    if problems:
        raise RuntimeError(
            "现有表字段结构与 OKS 参考表单不兼容："
            + "；".join(problems)
            + "。为避免破坏已有数据，setup 不自动转换字段类型；请使用新的表名重新执行。"
        )


# ── main setup logic ──────────────────────────────────────────────

def setup(args: argparse.Namespace) -> int:
    base_token = args.base_token or os.environ.get("OKS_FEISHU_BASE_TOKEN")
    table_name = args.table_name or "每日知识采集"
    show_credentials = bool(args.show_credentials)

    # ── Step 1: create or reuse Base ──
    if base_token:
        print(f"[1/5] 使用已有 Base: {_redact_token(base_token)}")
        _existing = _lark(["base", "+base-get", "--base-token", base_token], redact_token=base_token)
        base_name = _existing.get("name", "OKS Base")
    else:
        base_name = args.base_name or "Open Knowledge Studio"
        print(f"[1/5] 创建 Base: {base_name}")
        result = _lark([
            "base", "+base-create",
            "--name", base_name,
            "--table-name", table_name,
            "--fields", json.dumps(USER_FIELDS[:1], ensure_ascii=False),
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
    print(f"[2/5] 定位/创建采集表: {table_name}")
    tables = _lark(["base", "+table-list", "--base-token", base_token], redact_token=base_token)
    table_list = tables if isinstance(tables, list) else (
        tables.get("data", {}).get("tables", []) or tables.get("items", [])
    )
    table_id = None
    for t in table_list:
        if isinstance(t, dict) and t.get("name") == table_name:
            table_id = t.get("id") or t.get("table_id")
            break

    if table_id:
        print(f"  表已存在: {table_id}")
        existing_fields = _lark([
            "base", "+field-list", "--base-token", base_token, "--table-id", table_id,
        ], redact_token=base_token)
        field_list = existing_fields if isinstance(existing_fields, list) else (
            existing_fields.get("data", {}).get("fields", []) or existing_fields.get("items", [])
        )
        _validate_existing_user_fields(field_list)
        existing_names = {
            f.get("name") or f.get("field_name", "")
            for f in field_list
        }
    else:
        # Bootstrap with one question. Remaining user questions are added to
        # the form before Worker fields exist, preventing implicit exposure.
        result = _lark([
            "base", "+table-create",
            "--base-token", base_token,
            "--name", table_name,
            "--fields", json.dumps(USER_FIELDS[:1], ensure_ascii=False),
            "--format", "json",
        ], redact_token=base_token)
        result_data = result.get("data", {}) if isinstance(result, dict) else {}
        result_table = result_data.get("table", {}) if isinstance(result_data, dict) else {}
        table_id = (
            result.get("table_id")
            or result_data.get("table_id")
            or result_table.get("id")
            or result_table.get("table_id")
        )
        if not table_id:
            raise RuntimeError(f"无法获取 table_id: {json.dumps(result, ensure_ascii=False)}")
        print(f"  表已创建: {table_id}")
        existing_names = {USER_FIELDS[0]["name"]}

    # ── Step 3: ensure only the bootstrap field exists before form creation ──
    print("[3/5] 确保表单引导字段...")
    _ensure_fields(base_token, table_id, USER_FIELDS[:1], existing_names)

    # ── Step 4: create or verify the public form before Worker fields ──
    print("[4/5] 创建/验证表单视图...")
    form_id = _find_form(
        base_token,
        table_id,
        (FORM_NAME, f"{table_name} - 采集表单"),
    )
    if not form_id:
        internal_fields = [
            field["name"] for field in WORKER_FIELDS if field["name"] in existing_names
        ]
        if internal_fields:
            raise RuntimeError(
                "已有表包含 Worker 字段但没有可验证的采集表单。"
                "为避免把内部字段暴露给用户，setup 拒绝创建表单；"
                "请使用新的 --table-name，或先手动建立干净表单。"
            )
        form_result = _lark([
            "base", "+form-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--name", FORM_NAME,
            "--description", FORM_DESCRIPTION,
            "--format", "json",
        ], redact_token=base_token)
        form_data = form_result.get("data", {}) or form_result
        form_id = form_data.get("form_id") or form_data.get("id") or form_result.get("form_id", "")
    if not form_id:
        raise RuntimeError("无法获取 form_id，无法验证表单字段")
    _complete_user_form(base_token, table_id, form_id)
    _verify_user_form(base_token, table_id, form_id)

    # Questions created above also create their backing fields.
    existing_names.update(field["name"] for field in USER_FIELDS)

    # ── Step 5: Worker fields are added only after the public form is fixed ──
    print(f"[5/5] 确保 {len(WORKER_FIELDS)} 个 Worker 字段...")
    created = _ensure_fields(base_token, table_id, WORKER_FIELDS, existing_names)
    print(f"  新增 {created} 个 Worker 字段" if created else "  Worker 字段已就绪")
    _verify_user_form(base_token, table_id, form_id)

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
    print()
    print("或写入 ~/.oks/config.json:")
    print(json.dumps({
        "feishu": {
            "base_token": display_token,
            "table_id": table_id,
            "table_name": table_name,
            "form_id": form_id,
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
    parser.add_argument("--base-name", default="Open Knowledge Studio", help="新建 Base 的名称")
    parser.add_argument("--table-name", default="每日知识采集", help="采集表名称")
    parser.add_argument("--time-zone", default="Asia/Shanghai")
    parser.add_argument(
        "--show-credentials",
        action="store_true",
        help="Display the full Base token in output instead of the default redacted form",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(setup(build_parser().parse_args()))
