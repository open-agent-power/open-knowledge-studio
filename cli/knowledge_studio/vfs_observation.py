"""Measured VFS calls. Timings are real spans, never estimated model tokens."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from . import store, tasks
from .vfs import VfsResolver, VfsService, VfsError, _validate_slice


class Measurement:
    def __init__(self):
        self.start = perf_counter()
        self.spans = []
        self.stack = []

    @contextmanager
    def span(self, name):
        started = perf_counter()
        item = {
            "id": len(self.spans),
            "parent_id": self.stack[-1] if self.stack else None,
            "name": name,
            "start_ms": (started - self.start) * 1000,
            "status": "complete",
        }
        self.spans.append(item)
        self.stack.append(item["id"])
        try:
            yield
        except Exception:
            item["status"] = "failed"
            raise
        finally:
            self.stack.pop()
            item["duration_ms"] = (perf_counter() - started) * 1000


class MeasuredResolver(VfsResolver):
    def __init__(self, root, measurement):
        super().__init__(root)
        self.measurement = measurement

    def resolve(self, *args, **kwargs):
        with self.measurement.span("解析与边界检查"):
            return super().resolve(*args, **kwargs)


class MeasuredService(VfsService):
    def __init__(self, root, measurement):
        super().__init__(MeasuredResolver(root, measurement))
        self.measurement = measurement

    def read(self, uri, *, offset=0, limit=20000):
        _validate_slice(offset, limit)
        node = self.resolver.resolve(uri)
        if node.path is None or not node.path.is_file():
            raise VfsError("UNSUPPORTED_CONTENT", "Not a readable file")
        with self.measurement.span("读取与 UTF-8 解码"):
            try:
                content = node.path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise VfsError(
                    "UNSUPPORTED_CONTENT", "File is not readable UTF-8"
                ) from exc
            if "\x00" in content:
                raise VfsError("UNSUPPORTED_CONTENT", "File is not readable UTF-8 text")
        with self.measurement.span("内容裁剪"):
            page = content[offset : offset + limit]
            end = offset + len(page)
            return {
                "uri": node.uri.render(),
                "content": page,
                "offset": offset,
                "returned_chars": len(page),
                "total_chars": len(content),
                "truncated": end < len(content),
                "next_offset": end if end < len(content) else None,
            }


def history(root, kind="vfs"):
    if kind not in {"vfs", "recall"}:
        raise ValueError("Unsupported observation kind")
    path = tasks._inside(root, f"records/observability/{kind}.json")
    if not path.is_file():
        return {"records": []}
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("VFS observation history exceeds limit")
    rows = json.loads(path.read_text())
    if (
        not isinstance(rows, list)
        or len(rows) > 200
        or any(not isinstance(r, dict) for r in rows)
    ):
        raise ValueError("Invalid observation history; existing file preserved")
    return {"records": rows}


def _save(root, record):
    kind = record.get("kind", "vfs")
    if kind not in {"vfs", "recall"}:
        raise ValueError("Unsupported observation kind")
    path = tasks._inside(root, f"records/observability/{kind}.json")
    with store._file_lock(tasks._inside(root, ".oks/locks/vfs-observation.lock")):
        rows = history(root, kind)["records"]
        store._atomic_write(
            path, json.dumps((rows + [record])[-200:], ensure_ascii=False)
        )


def execute(root, operation, uri, *, query="", offset=0, limit=20000, persist=True):
    if operation not in {"ls", "stat", "read", "overview", "find", "compare"}:
        raise ValueError("Unsupported VFS operation")
    m = Measurement()
    record = {
        "id": uuid4().hex,
        "kind": "vfs",
        "operation": operation,
        "uri": uri,
        "at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "offset": offset,
        "limit": limit,
        "model_tokens": None,
        "query_sha256": hashlib.sha256(query.encode()).hexdigest() if query else None,
    }
    service = MeasuredService(root, m)
    try:
        with m.span(operation):
            if operation in {"read", "compare"}:
                with m.span("VFS 读取"):
                    result = service.read(uri, offset=offset, limit=limit)
                vfs_ms = m.spans[1]["duration_ms"]
                if operation == "compare":
                    # Same resolved file and character slice, no grep/read workload
                    # mismatch. VFS is deliberately first: cache/order is disclosed.
                    node = service.resolver.resolve(uri)
                    with m.span("直接读取（同文件与切片）"):
                        direct = node.path.read_text(encoding="utf-8")[
                            offset : offset + limit
                        ]
                    record["comparison"] = {
                        "equivalent": direct == result["content"],
                        "vfs_ms": vfs_ms,
                        "direct_ms": m.spans[-1]["duration_ms"],
                        "order": "vfs_then_direct",
                        "cache": "OS cache uncontrolled",
                        "scope": "one paired read; not evidence of general speedup",
                    }
            elif operation == "find":
                result = service.find(query, under=uri, max_results=50)
            else:
                with m.span("目录枚举" if operation == "ls" else "文件信息"):
                    result = getattr(service, operation)(uri)
            with m.span("结果序列化"):
                encoded = json.dumps(result, ensure_ascii=False).encode()
                record["output_bytes"] = len(encoded)
                record["output_sha256"] = hashlib.sha256(encoded).hexdigest()
                if "content" in result:
                    record["returned_chars"] = result["returned_chars"]
                    record["content_sha256"] = hashlib.sha256(
                        result["content"].encode()
                    ).hexdigest()
                    record["truncated"] = result["truncated"]
    except Exception as exc:
        record["status"] = "failed"
        record["error_code"] = getattr(exc, "code", type(exc).__name__)
        raise
    finally:
        record.update(
            total_ms=(perf_counter() - m.start) * 1000,
            spans=m.spans,
            timing_scope="server operation; excludes persistence, HTTP and model execution",
        )
        if persist:
            try:
                _save(root, record)
            except (OSError, ValueError):
                record["persistence_status"] = "failed"
    return {"result": result, "trace": record}


def observe_call(root, operation, uri, call):
    """Instrument ordinary CLI fs commands without changing their output schema."""
    m = Measurement()
    record = {
        "id": uuid4().hex,
        "kind": "vfs",
        "operation": operation,
        "uri": uri,
        "at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "model_tokens": None,
        "timing_scope": "CLI VFS operation; excludes persistence and terminal rendering",
    }
    try:
        with m.span(operation):
            result = call(MeasuredService(root, m))
            with m.span("结果序列化"):
                data = json.dumps(result, ensure_ascii=False).encode()
                record.update(
                    output_bytes=len(data),
                    output_sha256=hashlib.sha256(data).hexdigest(),
                )
        return result
    except Exception as exc:
        record.update(
            status="failed", error_code=getattr(exc, "code", type(exc).__name__)
        )
        raise
    finally:
        record.update(total_ms=(perf_counter() - m.start) * 1000, spans=m.spans)
        try:
            _save(root, record)
        except (OSError, ValueError):
            pass  # Observability failure never changes fs command correctness.
