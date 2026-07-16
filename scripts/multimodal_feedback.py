#!/usr/bin/env python3
"""Record and summarize multimodal extraction development loops.

The log lives under .oks/ and is intentionally separate from Raw bundles. It
records whether a capability exists, the concrete gap, the attempted fix, and
the result of rerunning the same sample. It does not score source content.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = ("gap", "fix", "verified", "blocked")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(".oks/feedback/multimodal-loop.jsonl"),
        help="JSONL feedback log; defaults to ignored local .oks state.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Append one loop observation.")
    record.add_argument("--cycle", required=True)
    record.add_argument("--sample", required=True)
    record.add_argument("--capability", required=True)
    record.add_argument("--status", choices=STATUSES, required=True)
    record.add_argument("--observation", required=True)
    record.add_argument("--evidence")
    record.add_argument("--next-action")
    record.add_argument("--commit")

    report = subparsers.add_parser("report", help="Render the current loop summary.")
    report.add_argument("--output", type=Path)
    return parser


def append_record(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def load_records(path: Path) -> list[dict[str, Any]]:
    path = path.expanduser().resolve()
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"feedback log line {line_number} is invalid: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"feedback log line {line_number} must be an object")
        records.append(value)
    return records


def make_record(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "cycle": args.cycle,
        "sample": args.sample,
        "capability": args.capability,
        "status": args.status,
        "observation": args.observation,
        "evidence": args.evidence,
        "next_action": args.next_action,
        "commit": args.commit,
    }


def render_report(records: list[dict[str, Any]]) -> str:
    cycles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        cycles[str(record.get("cycle", "unknown"))].append(record)
    lines = [
        "# 多模态抽取反馈循环",
        "",
        "> 这里只记录能力、缺口、修复和同样本复跑结果，不评价内容价值。",
        "",
    ]
    if not cycles:
        lines.append("暂无反馈记录。")
        return "\n".join(lines).rstrip() + "\n"
    for cycle, items in cycles.items():
        latest = items[-1]
        lines.extend(
            [
                f"## {cycle}",
                "",
                f"- 样本：{latest.get('sample', '')}",
                f"- 能力：{latest.get('capability', '')}",
                f"- 当前状态：{latest.get('status', '')}",
                "",
            ]
        )
        for item in items:
            lines.append(
                f"- `{item.get('status', '')}` {item.get('observation', '')}"
            )
            if item.get("evidence"):
                lines.append(f"  - 证据：{item['evidence']}")
            if item.get("next_action"):
                lines.append(f"  - 下一步：{item['next_action']}")
            if item.get("commit"):
                lines.append(f"  - 提交：`{item['commit']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "record":
        append_record(args.log, make_record(args))
        print(args.log.expanduser().resolve())
        return 0
    if args.command == "report":
        report = render_report(load_records(args.log))
        if args.output:
            output = args.output.expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(report, encoding="utf-8", newline="\n")
            print(output)
        else:
            print(report, end="")
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
