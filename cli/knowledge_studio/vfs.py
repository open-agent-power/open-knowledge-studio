from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from knowledge_studio.config import get_kb_root

FS_RESPONSE_SCHEMA = "oks-fs-response/v1"
MAX_READ_MANY_FILES = 250
MAX_READ_MANY_TOTAL_CHARS = 8 * 1024 * 1024


class VfsError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.public_message = message


@dataclass(frozen=True)
class Mount:
    scope: str
    relative_root: tuple[str, ...]
    excluded_prefixes: tuple[tuple[str, ...], ...] = ()


MOUNTS: dict[str, Mount] = {
    "goal": Mount("goal", ("goal",)),
    "discuss": Mount("discuss", ("discuss",)),
    "skill": Mount("skill", ("skill",)),
    "profiles": Mount("profiles", ("profiles",)),
    "raw": Mount("raw", ("raw",), (("executions",), (".logs",))),
    "wiki": Mount("wiki", ("wiki",)),
    "drafts": Mount("drafts", ("drafts",)),
    "mail": Mount("mail", ("mail",)),
    "skills": Mount("skills", (".agents", "skills")),
    "traces": Mount("traces", ("raw", "executions")),
}


@dataclass(frozen=True)
class OksUri:
    scope: str | None
    parts: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "OksUri":
        if value == "oks://":
            return cls(scope=None)
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as exc:
            raise VfsError("INVALID_URI", "URI contains an invalid port") from exc
        if (
            parsed.scheme != "oks"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
        ):
            raise VfsError(
                "INVALID_URI",
                "URI must use oks:// without credentials, port, query, or fragment",
            )
        scope = parsed.netloc
        if scope not in MOUNTS:
            raise VfsError("UNSUPPORTED_SCOPE", f"Unsupported OKS scope: {scope}")
        path_body = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
        if "//" in parsed.path:
            raise VfsError("INVALID_URI", "Empty URI path segments are not allowed")
        if path_body.endswith("/"):
            path_body = path_body[:-1]
        raw_parts = tuple(path_body.split("/")) if path_body else ()
        decoded: list[str] = []
        for raw_part in raw_parts:
            lowered = raw_part.lower()
            if "%2f" in lowered or "%5c" in lowered:
                raise VfsError("INVALID_URI", "Encoded path separators are not allowed")
            try:
                part = unquote(raw_part, encoding="utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise VfsError("INVALID_URI", "URI path is not valid UTF-8") from exc
            if part in {"", ".", ".."} or "\x00" in part or "\\" in part:
                raise VfsError("INVALID_URI", "Unsafe URI path segment")
            decoded.append(part)
        return cls(scope=scope, parts=tuple(decoded))

    def render(self) -> str:
        if self.scope is None:
            return "oks://"
        suffix = "/".join(quote(part, safe="-._~") for part in self.parts)
        return f"oks://{self.scope}/" + suffix if suffix else f"oks://{self.scope}/"


@dataclass(frozen=True)
class ResolvedNode:
    uri: OksUri
    path: Path | None
    mount: Mount | None
    synthetic_root: bool = False


class VfsResolver:
    def __init__(self, root: Path | None = None):
        self.root = (root or get_kb_root()).expanduser().resolve()

    def parse(self, value: str) -> OksUri:
        return OksUri.parse(value)

    @staticmethod
    def _reject_symlinks(root: Path, parts: tuple[str, ...]) -> None:
        current = root
        if current.is_symlink():
            raise VfsError("SYMLINK_NOT_ALLOWED", "Mount root is a symbolic link")
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise VfsError("SYMLINK_NOT_ALLOWED", "Symbolic links are not exposed")

    def resolve(self, value: str | OksUri, *, must_exist: bool = True) -> ResolvedNode:
        uri = value if isinstance(value, OksUri) else self.parse(value)
        if uri.scope is None:
            return ResolvedNode(uri=uri, path=None, mount=None, synthetic_root=True)
        mount = MOUNTS[uri.scope]
        if any(uri.parts[: len(prefix)] == prefix for prefix in mount.excluded_prefixes):
            raise VfsError("PATH_NOT_EXPOSED", f"Path is not exposed under oks://{uri.scope}/")
        mount_root = self.root.joinpath(*mount.relative_root)
        self._reject_symlinks(self.root, mount.relative_root + uri.parts)
        candidate = mount_root.joinpath(*uri.parts)
        resolved_root = mount_root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        if not resolved_candidate.is_relative_to(resolved_root):
            raise VfsError("INVALID_URI", "URI escapes its public scope")
        if must_exist and not candidate.exists():
            # Allow canonical URIs to omit the ``.md`` suffix so they do not
            # expose the on-disk file format: when the bare candidate is missing
            # and a ``.md`` sibling exists, transparently resolve to it.
            md_candidate = candidate.with_suffix(".md")
            if candidate.suffix == "" and md_candidate.exists():
                candidate = md_candidate
            else:
                raise VfsError("PATH_NOT_FOUND", f"Path not found: {uri.render()}")
        return ResolvedNode(uri=uri, path=candidate, mount=mount)

    def uri_for_path(self, path: Path) -> str:
        candidate = path.expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.absolute()
        try:
            raw_relative = candidate.relative_to(self.root.absolute())
        except ValueError:
            raise VfsError("PATH_NOT_EXPOSED", "Physical path is outside public OKS scopes")
        for part in raw_relative.parts:
            if part in {"", ".", ".."} or "\x00" in part or "\\" in part:
                raise VfsError("PATH_NOT_EXPOSED", "Physical path contains unsafe segments")
        self._reject_symlinks(self.root, raw_relative.parts)

        candidate = candidate.resolve(strict=False)
        ordered = [MOUNTS["traces"]] + [
            mount for scope, mount in MOUNTS.items() if scope != "traces"
        ]
        for mount in ordered:
            mount_root = self.root.joinpath(*mount.relative_root).resolve(strict=False)
            try:
                relative = candidate.relative_to(mount_root)
            except ValueError:
                continue
            parts = relative.parts
            if any(
                part in {"", ".", ".."} or "\x00" in part or "\\" in part
                for part in parts
            ):
                raise VfsError("PATH_NOT_EXPOSED", "Physical path contains unsafe segments")
            if any(parts[: len(prefix)] == prefix for prefix in mount.excluded_prefixes):
                continue
            self._reject_symlinks(self.root, mount.relative_root + parts)
            return OksUri(mount.scope, tuple(parts)).render()
        raise VfsError("PATH_NOT_EXPOSED", "Physical path is outside public OKS scopes")


def _node_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "special"


def _validate_slice(offset: int, limit: int) -> None:
    if offset < 0 or not 1 <= limit <= 1_000_000:
        raise VfsError(
            "INVALID_ARGUMENT",
            "offset must be non-negative and limit must be 1..1000000",
        )


def _validate_tree_limits(depth: int, max_entries: int) -> None:
    if not 0 <= depth <= 10 or not 1 <= max_entries <= 10_000:
        raise VfsError(
            "INVALID_ARGUMENT",
            "depth must be 0..10 and max_entries must be 1..10000",
        )


def _validate_find(query: str, max_results: int) -> str:
    normalized = query.casefold()
    if not normalized or not 1 <= max_results <= 200:
        raise VfsError(
            "INVALID_ARGUMENT",
            "query must be non-empty and max_results must be 1..200",
        )
    return normalized


class VfsService:
    def __init__(self, resolver: VfsResolver | None = None):
        self.resolver = resolver or VfsResolver()

    def _entry(self, path: Path) -> dict[str, str]:
        uri = self.resolver.uri_for_path(path)
        node_type = _node_type(path)
        if node_type == "directory" and not uri.endswith("/"):
            uri += "/"
        return {"name": path.name, "type": node_type, "uri": uri}

    def _visible_children(self, path: Path, mount: Mount) -> list[Path]:
        mount_root = self.resolver.root.joinpath(*mount.relative_root)
        children: list[Path] = []
        for child in path.iterdir():
            relative = child.relative_to(mount_root).parts
            if any(
                relative[: len(prefix)] == prefix
                for prefix in mount.excluded_prefixes
            ):
                continue
            children.append(child)
        return sorted(children, key=lambda child: (child.name.casefold(), child.name))

    def _existing_mount_root(self, scope: str) -> Path | None:
        node = self.resolver.resolve(f"oks://{scope}/", must_exist=False)
        assert node.path is not None
        return node.path if node.path.exists() else None

    def ls(self, uri: str) -> dict[str, object]:
        node = self.resolver.resolve(uri)
        if node.synthetic_root:
            return {
                "uri": node.uri.render(),
                "entries": [
                    {
                        "name": scope,
                        "type": "directory",
                        "uri": f"oks://{scope}/",
                    }
                    for scope in MOUNTS
                ],
            }
        assert node.path is not None and node.mount is not None
        if not node.path.is_dir():
            raise VfsError("NOT_DIRECTORY", f"Not a directory: {node.uri.render()}")

        entries: list[dict[str, str]] = []
        for child in self._visible_children(node.path, node.mount):
            entries.append(self._entry(child))
        return {"uri": node.uri.render(), "entries": entries}

    def stat(self, uri: str) -> dict[str, object]:
        node = self.resolver.resolve(uri)
        if node.synthetic_root:
            return {
                "uri": node.uri.render(),
                "type": "directory",
                "size": None,
                "modified_at": None,
                "mount": None,
            }
        assert node.path is not None and node.mount is not None
        node_type = _node_type(node.path)
        metadata = node.path.stat()
        canonical_uri = self.resolver.uri_for_path(node.path)
        if node_type == "directory" and not canonical_uri.endswith("/"):
            canonical_uri += "/"
        return {
            "uri": canonical_uri,
            "type": node_type,
            "size": metadata.st_size if node_type != "directory" else None,
            "modified_at": datetime.fromtimestamp(
                metadata.st_mtime, tz=timezone.utc
            ).isoformat(),
            "mount": node.mount.scope,
        }

    def read(
        self, uri: str, *, offset: int = 0, limit: int = 20_000
    ) -> dict[str, object]:
        _validate_slice(offset, limit)
        node = self.resolver.resolve(uri)
        if node.synthetic_root or node.path is None or not node.path.is_file():
            raise VfsError(
                "UNSUPPORTED_CONTENT", f"Not a readable file: {node.uri.render()}"
            )
        try:
            content = node.path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise VfsError(
                "UNSUPPORTED_CONTENT", f"File is not readable UTF-8: {node.uri.render()}"
            ) from exc
        if "\x00" in content:
            raise VfsError(
                "UNSUPPORTED_CONTENT",
                f"File is not readable UTF-8 text: {node.uri.render()}",
            )

        page = content[offset : offset + limit]
        next_offset = offset + len(page)
        truncated = next_offset < len(content)
        return {
            "uri": self.resolver.uri_for_path(node.path),
            "content": page,
            "offset": offset,
            "returned_chars": len(page),
            "total_chars": len(content),
            "truncated": truncated,
            "next_offset": next_offset if truncated else None,
        }

    def read_many(
        self,
        uris: list[str],
        *,
        limit: int = 20_000,
        max_total_chars: int = MAX_READ_MANY_TOTAL_CHARS,
    ) -> dict[str, object]:
        """Read several public UTF-8 files within per-file and total bounds."""
        _validate_slice(0, limit)
        if not uris or len(uris) > MAX_READ_MANY_FILES:
            raise VfsError(
                "INVALID_ARGUMENT",
                f"uris must contain 1..{MAX_READ_MANY_FILES} items",
            )
        if not 1 <= max_total_chars <= MAX_READ_MANY_TOTAL_CHARS:
            raise VfsError(
                "INVALID_ARGUMENT",
                f"max_total_chars must be 1..{MAX_READ_MANY_TOTAL_CHARS}",
            )

        items: list[dict[str, object]] = []
        remaining = max_total_chars
        truncated = False
        for uri in uris:
            if remaining <= 0:
                truncated = True
                break
            item = self.read(uri, limit=min(limit, remaining))
            items.append(item)
            remaining -= int(item["returned_chars"])
            truncated = truncated or bool(item["truncated"])

        return {
            "uri": "oks://",
            "items": items,
            "requested_count": len(uris),
            "returned_count": len(items),
            "returned_chars": max_total_chars - remaining,
            "truncated": truncated or len(items) < len(uris),
        }

    def tree(
        self, uri: str, *, depth: int = 3, max_entries: int = 1_000
    ) -> dict[str, object]:
        _validate_tree_limits(depth, max_entries)
        node = self.resolver.resolve(uri)

        def physical_entries(
            path: Path, mount: Mount, level: int
        ):
            if level > depth:
                return
            for child in self._visible_children(path, mount):
                entry = self._entry(child)
                yield entry
                if entry["type"] == "directory" and level < depth:
                    yield from physical_entries(child, mount, level + 1)

        def all_entries():
            if depth == 0:
                return
            if node.synthetic_root:
                for scope, mount in MOUNTS.items():
                    yield {
                        "name": scope,
                        "type": "directory",
                        "uri": f"oks://{scope}/",
                    }
                    mount_root = self._existing_mount_root(scope)
                    if depth > 1 and mount_root is not None:
                        yield from physical_entries(mount_root, mount, 2)
                return
            assert node.path is not None and node.mount is not None
            if not node.path.is_dir():
                raise VfsError(
                    "NOT_DIRECTORY", f"Not a directory: {node.uri.render()}"
                )
            yield from physical_entries(node.path, node.mount, 1)

        entries: list[dict[str, str]] = []
        truncated = False
        for entry in all_entries():
            if len(entries) == max_entries:
                truncated = True
                break
            entries.append(entry)
        return {
            "uri": node.uri.render(),
            "entries": entries,
            "depth": depth,
            "truncated": truncated,
        }

    def overview(self, uri: str) -> dict[str, object]:
        node = self.resolver.resolve(uri)
        if node.synthetic_root:
            children = self.ls(uri)["entries"]
        else:
            assert node.path is not None and node.mount is not None
            if not node.path.is_dir():
                raise VfsError(
                    "NOT_DIRECTORY", f"Not a directory: {node.uri.render()}"
                )
            children = [
                self._entry(child)
                for child in self._visible_children(node.path, node.mount)
            ]

        directories = [entry for entry in children if entry["type"] == "directory"]
        files = [entry for entry in children if entry["type"] == "file"]
        counts = {
            node_type: sum(entry["type"] == node_type for entry in children)
            for node_type in ("directory", "file", "special")
        }
        index_uri = next(
            (entry["uri"] for entry in files if entry["name"] == "INDEX.md"),
            None,
        )
        return {
            "uri": node.uri.render(),
            "directories": directories,
            "files": files,
            "counts": counts,
            "index_uri": index_uri,
        }

    @staticmethod
    def _snippet(content: str, match_index: int) -> str:
        start = max(0, match_index - 80)
        return content[start : start + 200]

    def find(
        self, query: str, *, under: str, max_results: int = 50
    ) -> dict[str, object]:
        normalized = _validate_find(query, max_results)
        node = self.resolver.resolve(under)
        if not node.synthetic_root and (node.path is None or not node.path.is_dir()):
            raise VfsError("NOT_DIRECTORY", f"Not a directory: {node.uri.render()}")

        def files_in(path: Path, mount: Mount):
            for child in self._visible_children(path, mount):
                entry = self._entry(child)
                if entry["type"] == "directory":
                    yield from files_in(child, mount)
                elif entry["type"] == "file":
                    yield child, entry

        def all_files():
            if node.synthetic_root:
                for scope, mount in MOUNTS.items():
                    mount_root = self._existing_mount_root(scope)
                    if mount_root is None:
                        continue
                    for path, entry in files_in(mount_root, mount):
                        relative = path.relative_to(mount_root).as_posix()
                        yield path, entry, f"{scope}/{relative}"
                return
            assert node.path is not None and node.mount is not None
            for path, entry in files_in(node.path, node.mount):
                yield path, entry, path.relative_to(node.path).as_posix()

        matches: list[dict[str, str]] = []
        skipped_count = 0
        truncated = False
        for path, entry, relative_path in all_files():
            match: dict[str, str] | None = None
            if normalized in relative_path.casefold():
                match = {
                    "uri": entry["uri"],
                    "match": "path",
                    "snippet": relative_path[:200],
                }
            else:
                try:
                    content = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    skipped_count += 1
                    continue
                if "\x00" in content:
                    skipped_count += 1
                    continue
                match_index = content.casefold().find(normalized)
                if match_index >= 0:
                    match = {
                        "uri": entry["uri"],
                        "match": "content",
                        "snippet": self._snippet(content, match_index),
                    }
            if match is None:
                continue
            if len(matches) == max_results:
                truncated = True
                break
            matches.append(match)

        return {
            "uri": node.uri.render(),
            "query": query,
            "matches": matches,
            "skipped_count": skipped_count,
            "truncated": truncated,
        }
