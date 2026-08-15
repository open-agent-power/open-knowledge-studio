"""CLI argument parsing for the Feishu Base worker."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Feishu Base source adapter for the Open Knowledge Studio Raw pipeline."
    )
    parser.add_argument("--base-token")
    parser.add_argument("--table-id")
    parser.add_argument("--connector-repo")
    parser.add_argument("--connector-python")
    parser.add_argument("--output-root")
    parser.add_argument("--knowledge-root")
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--review-recipient-user-id")
    parser.add_argument(
        "--review-message-identity",
        choices=("bot", "user"),
        default=None,
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    enqueue = subcommands.add_parser("enqueue", help="Create one pending capture row.")
    enqueue.add_argument("content")
    enqueue.add_argument("--thought", default="")
    enqueue.add_argument(
        "--rating",
        choices=("A", "B", "C", "紧急核心", "重要", "普通参考", "暂不处理"),
    )
    once = subcommands.add_parser("run-once", help="Process at most one pending row.")
    once.add_argument("--limit", type=int, default=100)
    selected = subcommands.add_parser(
        "run-record",
        help="Process one explicitly selected pending Base record.",
    )
    selected.add_argument("--record-id", required=True)
    browser = subcommands.add_parser("complete-browser", help="Complete one JS-rendered record from a controlled browser snapshot.")
    browser.add_argument("--record-id", required=True)
    browser.add_argument("--snapshot-dir", type=Path, required=True)
    publish = subcommands.add_parser(
        "publish-candidate",
        help="Publish an Agent-authored Teach-back Candidate to its Base record.",
    )
    publish.add_argument("--record-id", required=True)
    publish.add_argument("--candidate-file", type=Path, required=True)
    review = subcommands.add_parser(
        "review-once",
        help="Consume at most one new accept/edit/reject/defer action from Base.",
    )
    review.add_argument("--limit", type=int, default=100)
    listen = subcommands.add_parser(
        "listen-reviews",
        help="Consume bounded Feishu personal replies and apply linked Candidate reviews.",
    )
    listen.add_argument("--max-events", type=int, default=1)
    listen.add_argument("--timeout", default="5m")
    reconcile = subcommands.add_parser(
        "reconcile-review",
        help="Recover one missed personal review reply from immutable message IDs.",
    )
    reconcile.add_argument("--prompt-message-id", required=True)
    reconcile.add_argument("--reply-message-id", required=True)
    pending = subcommands.add_parser(
        "pending",
        help="List pending Inbox records (Pull-mode entry point).",
    )
    pending.add_argument("--limit", type=int, default=200)
    return parser.parse_args()
