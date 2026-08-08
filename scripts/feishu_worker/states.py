"""Single source of truth for Feishu Base select-field values.

`feishu_setup.py` builds table options from these constants and the worker
writes only these values, so a Base created by setup can never receive an
unknown option (which Bitable rejects with INVALID_ARGUMENT — a fatal,
non-retried error in this pipeline).
"""
from __future__ import annotations

# 运行状态 — worker lifecycle states (claim → probe → capture → review → done)
RUN_STATUS_PENDING = "待处理"
RUN_STATUS_CLAIMED = "已领取"
RUN_STATUS_PROBING = "探测中"
RUN_STATUS_RAW_READY = "Raw就绪"
RUN_STATUS_RETRYABLE = "可重试失败"
RUN_STATUS_FATAL = "最终失败"
RUN_STATUS_NEEDS_HUMAN = "需人工"
RUN_STATUS_NEEDS_AUTH = "需授权"
RUN_STATUS_CANDIDATE_REVIEW = "候选待审"
RUN_STATUS_PROMOTED = "已晋升"
RUN_STATUS_REJECTED = "已拒绝"

RUN_STATUS_OPTIONS: tuple[str, ...] = (
    RUN_STATUS_PENDING,
    RUN_STATUS_CLAIMED,
    RUN_STATUS_PROBING,
    RUN_STATUS_RAW_READY,
    RUN_STATUS_RETRYABLE,
    RUN_STATUS_FATAL,
    RUN_STATUS_NEEDS_HUMAN,
    RUN_STATUS_NEEDS_AUTH,
    RUN_STATUS_CANDIDATE_REVIEW,
    RUN_STATUS_PROMOTED,
    RUN_STATUS_REJECTED,
)

# States a claim query must fetch: fresh work, user-requested retries, and
# claimed records whose lease may have expired (is_candidate refines these).
CLAIMABLE_STATUSES: tuple[str, ...] = (
    RUN_STATUS_PENDING,
    RUN_STATUS_RETRYABLE,
    RUN_STATUS_FATAL,
    RUN_STATUS_CLAIMED,
)

# 采集模式 — capture routes actually written by pipeline.py
CAPTURE_MODE_OPTIONS: tuple[str, ...] = (
    "直接文本",
    "附件",
    "平台提取器",
    "HTTP",
    "登录浏览器",
    "公开浏览器",
)

# 质量状态 — mirrors Raw Bundle processing_status
QUALITY_STATUS_OPTIONS: tuple[str, ...] = ("complete", "partial", "failed")

# 状态 — compact user-facing capture status shown in the daily grid.
CAPTURE_STATUS_OPTIONS: tuple[str, ...] = (
    "未处理",
    "处理中",
    "已处理",
    "跳过",
    "失败",
)

# Wiki状态 — candidate/review lifecycle written by pipeline.py & review_events.py
WIKI_STATUS_OPTIONS: tuple[str, ...] = (
    "none",
    "candidate",
    "review_pending",
    "promoted",
    "rejected",
)

# 审核动作 — review actions accepted by review_events.py
REVIEW_ACTION_OPTIONS: tuple[str, ...] = ("accept", "edit", "reject", "defer")
