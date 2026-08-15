"""Feishu worker configuration -- WorkerConfig, load_config, and Lark CLI resolver.

Extracted from feishu_base_worker.py (Round 3 Phase 1A).  This is a TRUE leaf
module: it never imports feishu_base_worker, directly or lazily.  The original
module provides legacy one-argument wrappers that supply ROOT automatically.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class WorkerConfig:
    base_token: str
    table_id: str
    lark_cli: Path
    output_root: Path
    identity: str = "user"
    lease_seconds: int = 3600
    review_recipient_user_id: str | None = None
    review_message_identity: str = "bot"
    knowledge_root: Path | None = None


def resolve_lark_cli() -> Path:
    from _lark_cli import resolve_lark_cli as _shared_resolve

    return _shared_resolve()


def load_config(args: argparse.Namespace, *, root: Path) -> WorkerConfig:
    base_token = args.base_token or os.environ.get("OKS_FEISHU_BASE_TOKEN")
    table_id = args.table_id or os.environ.get("OKS_FEISHU_TABLE_ID")
    if not base_token or not table_id:
        raise RuntimeError(
            "Base coordinates are required via --base-token/--table-id or "
            "OKS_FEISHU_BASE_TOKEN/OKS_FEISHU_TABLE_ID"
        )
    knowledge_root = Path(
        args.knowledge_root
        or os.environ.get("OKS_KNOWLEDGE_ROOT")
        or root
    ).expanduser().resolve()
    return WorkerConfig(
        base_token=base_token,
        table_id=table_id,
        lark_cli=resolve_lark_cli(),
        output_root=Path(
            args.output_root or knowledge_root / "raw" / "feishu-intake"
        ).expanduser().resolve(),
        lease_seconds=int(args.lease_seconds),
        review_recipient_user_id=(
            args.review_recipient_user_id
            or os.environ.get("OKS_FEISHU_REVIEW_USER_ID")
            or None
        ),
        review_message_identity=(
            args.review_message_identity
            or os.environ.get("OKS_FEISHU_REVIEW_MESSAGE_IDENTITY")
            or "bot"
        ),
        knowledge_root=knowledge_root,
    )


def configured_knowledge_root(config: WorkerConfig, *, root: Path) -> Path:
    return (config.knowledge_root or root).expanduser().resolve()
