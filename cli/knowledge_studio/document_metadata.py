"""Shared document fields for knowledge lists, readers and graphs."""
from datetime import date, datetime, time, timezone
from pathlib import Path
import re

TIME_KEYS = (
    "updated_at", "updated", "modified_at", "ingested_at",
    "human_reviewed_at", "created",
)


def plain(value: str, limit: int = 240) -> str:
    text = str(value or "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?(?:\[([^\]]+)\]\([^)]*\))", r"\1", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(raw), time.min)
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_time(meta: dict, path: Path) -> tuple[datetime, str]:
    for key in TIME_KEYS:
        parsed = parse_time(meta.get(key))
        if parsed is not None:
            return parsed, key
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc), "file_mtime"


def is_visible(meta: dict) -> bool:
    status = str(meta.get("status") or "active").strip().lower()
    archived = meta.get("archived") is True or str(meta.get("archived") or "").strip().lower() in {"1", "true", "yes"}
    return not archived and status not in {"dropped", "superseded", "retired", "archived"}


def title(meta: dict, body: str, path: Path) -> str:
    for key in ("title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return plain(value.strip(), 140)
    for line in body.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match and match.group(1).strip():
            return plain(match.group(1), 140)
    return plain(path.stem.replace("-", " ").replace("_", " "), 140) or "未命名知识"


def summary(meta: dict, body: str, *, skip_quotes: bool = False) -> str:
    for key in ("summary", "description", "abstract"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return plain(value)
    paragraph = []
    for line in body.splitlines():
        clean = line.strip()
        if not clean:
            if paragraph:
                break
            continue
        if clean.startswith(("#", "---")) or (skip_quotes and clean.startswith(">")):
            continue
        paragraph.append(clean)
    return plain(" ".join(paragraph)) or "这份知识还没有可显示的摘要，打开详情查看原文。"
