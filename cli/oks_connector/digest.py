"""Auto-generate Agent-friendly digest and index after each ingest."""

from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

from oks_connector._shared import _atomic_write_text

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None


@contextlib.contextmanager
def _index_lock(index_path: Path):
    """Serialize the read-modify-write of raw/index.json across processes."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = index_path.with_suffix(".json.lock")
    handle = lock_path.open("a+b")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()


def _load_index(index_path: Path) -> list[dict]:
    """Read the index, quarantining a corrupt file instead of dropping history."""
    if not index_path.is_file():
        return []
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        quarantine = index_path.with_suffix(f".json.corrupt-{int(time.time())}")
        with contextlib.suppress(OSError):
            index_path.replace(quarantine)
        print(
            f"raw/index.json was unreadable and moved to {quarantine.name}; "
            "rebuilding the index from this ingest onward",
            file=sys.stderr,
        )
        return []
    return entries if isinstance(entries, list) else []


def write_digest(bundle: Path) -> None:
    """Generate digest.md inside the bundle for Agent quick-scan."""
    qr_path = bundle / "quality-report.json"
    meta_path = bundle / "metadata.json"
    if not qr_path.is_file() or not meta_path.is_file():
        return
    qr = json.loads(qr_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source_info = meta.get("source", {})
    title = source_info.get("title") or bundle.name
    source = source_info.get("url") or source_info.get("local_path", "unknown")
    modality = meta.get("source_type", "unknown")
    status = qr.get("processing_status", meta.get("processing_status", "unknown"))
    transcript_n = qr.get("transcript_segment_count", 0)
    frame_n = qr.get("frame_count", 0)
    ocr_n = qr.get("ocr_block_count", 0)
    evidence_n = qr.get("evidence_count", 0)
    warnings = [w for w in qr.get("warnings", []) if w]
    human = qr.get("human_fallback", "")
    lines = [
        f"# {title}",
        f"- 来源：{source}",
        f"- 模态：{modality}",
        f"- 状态：{status}",
        f"- 证据：字幕{transcript_n}段 / 帧{frame_n} / OCR{ocr_n}块 / 总计{evidence_n}条",
    ]
    if warnings:
        lines.append(f"- 警告：{'；'.join(warnings)}")
    if human:
        lines.append(f"- 人工核验建议：{human}")
    lines.append("")
    _atomic_write_text(bundle / "digest.md", "\n".join(lines))


def update_raw_index(bundle: Path) -> None:
    """Append this bundle's entry to raw/index.json."""
    raw_dir = bundle.parent
    index_path = raw_dir / "index.json"
    qr_path = bundle / "quality-report.json"
    meta_path = bundle / "metadata.json"
    if not qr_path.is_file() or not meta_path.is_file():
        return
    qr = json.loads(qr_path.read_text(encoding="utf-8"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    source_info = meta.get("source", {})
    bundle_id = bundle.name
    with _index_lock(index_path):
        entries = _load_index(index_path)
        if bundle_id in {e["id"] for e in entries if "id" in e}:
            return
        entries.append({
            "id": bundle_id,
            "source": source_info.get("url") or source_info.get("local_path", ""),
            "title": source_info.get("title", ""),
            "modality": meta.get("source_type", ""),
            "collected_at": source_info.get("collected_at", ""),
            "status": qr.get("processing_status", meta.get("processing_status", "")),
            "digest": f"raw/{bundle_id}/digest.md",
            "evidence_count": qr.get("evidence_count", 0),
            "warnings": [w for w in qr.get("warnings", []) if w],
        })
        _atomic_write_text(index_path, json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
