"""Versioned Skill assets, reviewed Wiki cards, and bounded host loading.

No AI calls, automatic promotion, dependency installation, or code execution.
Skill knowledge lives under wiki/skills/<type>/<category> and uses normal
Draft review and recall scoring. Runtime receipts track only owned host copies.
"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import io
import json
import os
import difflib
from pathlib import Path, PurePosixPath
import re
import uuid
import zipfile

import yaml

from knowledge_studio import store

TYPE_DIRS = {"strategy": "strategies", "anti-pattern": "anti-patterns", "concept": "concepts"}
HOSTS = {"agents": ".agents", "claude": ".claude", "qoder": ".qoder", "codebuddy": ".codebuddy"}
SKILL_FIELDS = (
    "artifact_kind", "skill_id", "skill_version", "skill_category", "skill_description",
    "skill_package", "skill_package_sha256", "skill_manifest", "skill_manifest_sha256",
    "skill_dependencies", "raw_bundle", "skill_lineage", "skill_instruction_format",
)
MAX_FILES = 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_DIFF_FILE_BYTES = 64 * 1024
MAX_DIFF_TOTAL_BYTES = 256 * 1024
MAX_DIFF_FILES = 512
MAX_DIFF_LINES = 2000
_IGNORED = {".git", "__pycache__", "node_modules", ".venv", ".DS_Store", "Thumbs.db"}
_DEVICES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value) or value in _DEVICES:
        raise ValueError(f"Invalid Skill identifier: {value!r}")
    return value


def validate_skill_lineage(lineage: object, *, skill_id: str | None = None,
                           skill_version: str | None = None) -> dict:
    if not isinstance(lineage, dict) or set(lineage) != {
            "schema_version", "derived_from", "upstream_base", "parents"}:
        raise ValueError("Invalid Skill lineage shape")
    if lineage.get("schema_version") != "skill-lineage/v1":
        raise ValueError("Unsupported Skill lineage schema")

    def validate_ref(ref):
        if not isinstance(ref, dict) or set(ref) != {
                "id", "version", "package_sha256", "manifest_sha256"}:
            raise ValueError("Invalid Skill lineage reference")
        identity = _identifier(ref.get("id") if isinstance(ref.get("id"), str) else "")
        for field in ("version", "package_sha256", "manifest_sha256"):
            if not isinstance(ref.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", ref[field]):
                raise ValueError("Invalid Skill lineage reference digest")
        if skill_id == identity and skill_version == ref["version"]:
            raise ValueError("Skill lineage cannot refer to itself")
        return (identity, ref["version"], ref["package_sha256"], ref["manifest_sha256"])

    validate_ref(lineage["derived_from"])
    validate_ref(lineage["upstream_base"])
    parents = lineage["parents"]
    if not isinstance(parents, list) or not 1 <= len(parents) <= 2:
        raise ValueError("Skill lineage requires one or two parent references")
    normalized = [validate_ref(parent) for parent in parents]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Skill lineage contains duplicate parents")
    return lineage


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Expected a portable relative path")
    parts = value.split("/")
    if any(p in {"", ".", ".."} or re.search(r'[\x00-\x1f:*?"<>|]', p)
           or p.rstrip(" .") != p or p.split(".")[0].lower() in _DEVICES for p in parts):
        raise ValueError(f"Unsafe relative path: {value!r}")
    return value


def validate_category(value: str) -> str:
    _relative(value)
    if not all(re.fullmatch(r"[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff-]*", p) for p in value.split("/")):
        raise ValueError("Skill category must contain portable lowercase or Chinese path components")
    return value


def _inside(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    target = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"Symlink or junction is not allowed: {relative}")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes the knowledge instance")
    return target


def _root(explicit: Path | str | None = None) -> Path:
    root = Path(explicit).expanduser().resolve() if explicit is not None else store.repo_root().resolve()
    if not (root / "wiki").is_dir():
        raise ValueError("Select an OKS knowledge instance before managing Skills")
    return root


def _scan(directory: Path, *, ignore: bool = False) -> tuple[dict[str, bytes], list[str]]:
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("Skill source/target cannot be a symlink or junction")
    files: dict[str, bytes] = {}
    skipped: list[str] = []
    total = 0
    for parent, dirs, names in os.walk(directory, followlinks=False):
        for name in list(dirs):
            child = Path(parent) / name
            if child.is_symlink() or child.is_junction():
                raise ValueError(f"Symlink or junction in Skill: {child.name}")
            if ignore and name in _IGNORED:
                skipped.append(child.relative_to(directory).as_posix())
                dirs.remove(name)
        for name in names:
            child = Path(parent) / name
            relative = _relative(child.relative_to(directory).as_posix())
            if child.is_symlink() or not child.is_file():
                raise ValueError(f"Only regular files may be imported: {relative}")
            if ignore and name in _IGNORED:
                skipped.append(relative)
                continue
            total += child.stat().st_size
            if total > MAX_BYTES or len(files) >= MAX_FILES:
                raise ValueError("Skill package exceeds the file or byte limit")
            files[relative] = child.read_bytes()
    _portable_names(files)
    return files, sorted(skipped)


def _hashes(files: dict[str, bytes]) -> dict[str, str]:
    return {name: _digest(data) for name, data in sorted(files.items())}


def _portable_names(names) -> None:
    """Reject paths that collide on case-insensitive hosts or with directories."""
    identities = {}
    file_names = set(names)
    for name in file_names:
        path = PurePosixPath(_relative(name))
        for component in (path, *path.parents):
            if str(component) == ".":
                continue
            value = str(component)
            previous = identities.setdefault(value.casefold(), value)
            if previous != value:
                raise ValueError("Skill paths collide on a case-insensitive host")
        if any(str(parent) in file_names for parent in path.parents):
            raise ValueError("A Skill path is both a file and a directory")


def _unpack(meta: dict, root: Path | str | None = None) -> dict[str, bytes]:
    root = _root(root)
    package_path = _inside(root, str(meta.get("skill_package", "")))
    manifest_path = _inside(root, str(meta.get("skill_manifest", "")))
    if not package_path.is_relative_to(root / "raw") or not manifest_path.is_relative_to(root / "raw"):
        raise ValueError("Skill assets must be captured under raw/")
    if package_path.stat().st_size > MAX_BYTES or manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Skill snapshot exceeds size limits")
    payload, manifest_bytes = package_path.read_bytes(), manifest_path.read_bytes()
    if _digest(payload) != meta.get("skill_package_sha256") or _digest(manifest_bytes) != meta.get("skill_manifest_sha256"):
        raise ValueError("Skill snapshot was modified after import")
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("Invalid Skill package manifest")
    if manifest.get("skill_id") != meta.get("skill_id") or manifest.get("version") != meta.get("skill_version"):
        raise ValueError("Skill manifest does not match the reviewed identity/version")
    if manifest.get('instruction_card_format') != meta.get('skill_instruction_format'):
        raise ValueError('Skill instruction format does not match its immutable manifest')
    if ("lineage" in manifest) != ("skill_lineage" in meta):
        raise ValueError("Skill lineage does not match its immutable package manifest")
    if "lineage" in manifest:
        if manifest["lineage"] != meta["skill_lineage"]:
            raise ValueError("Skill lineage does not match its immutable package manifest")
        validate_skill_lineage(manifest["lineage"], skill_id=meta.get("skill_id"),
                               skill_version=meta.get("skill_version"))
    files = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_BYTES:
                raise ValueError("Skill archive exceeds size limits")
            for member in members:
                name = _relative(member.filename)
                if member.is_dir() or name in files or ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("Invalid or duplicate Skill archive member")
                files[name] = archive.read(member)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError(f"Invalid Skill archive: {exc}") from exc
    if "SKILL.md" not in files or _hashes(files) != manifest.get("files"):
        raise ValueError("Skill assets do not match their manifest")
    if _digest(_json(manifest["files"]).encode()) != manifest["version"]:
        raise ValueError("Skill version does not identify the captured files")
    return files


def _instruction_text(raw: bytes) -> str:
    try:
        text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeError as exc:
        raise ValueError('Skill instruction body is not valid UTF-8') from exc
    if text.startswith('---\n'):
        parts = text.split('---', 2)
        if len(parts) < 3:
            raise ValueError('Skill instruction frontmatter is invalid')
        frontmatter = yaml.safe_load(parts[1]) or {}
        if not isinstance(frontmatter, dict):
            raise ValueError('Skill instruction frontmatter is invalid')
        text = parts[2]
    return text.strip()


def _legacy_instruction_body_matches(meta: dict, actual: str, raw: bytes, root: Path) -> bool:
    """Accept exact historical Windows bytes, never a normalized blank-line edit."""
    path = meta.get('file_path')
    if not isinstance(path, str):
        return False
    try:
        card = _inside(root, Path(path).resolve().relative_to(root).as_posix()).read_bytes()
        text = card.decode('utf-8-sig')
        starts = list(re.finditer(r'(?m)^## Skill instructions[ \t]*\r*\n', text))
        ends = list(re.finditer(r'(?m)^## Asset provenance[ \t]*\r*$', text))
        if not starts or not ends or ends[-1].start() <= starts[0].end():
            return False
        captured = text[starts[0].end():ends[-1].start()].strip()
        source = raw.decode('utf-8-sig')
        if source.startswith(('---\n', '---\r\n')):
            source = source.split('---', 2)[2]
        old_draft = source.strip().replace('\n', '\r\n')
        old_wiki = old_draft.replace('\n', '\r\n')
        candidates = {old_draft, old_wiki} if '\r\r\n' in captured else set()
        # Old reviewed cards could also be read with universal newlines and
        # rewritten while superseding or updating metadata. They have no format
        # marker. Do not extend this lossy compatibility to new review candidates.
        if meta.get('human_reviewed_at') and not meta.get('skill_instruction_format'):
            for old in (old_draft, old_wiki):
                normalized_old = old.replace('\r\n', '\n').replace('\r', '\n')
                candidates.update((normalized_old, normalized_old.replace('\n', '\r\n')))
        normalized = captured.replace('\r\n', '\n').replace('\r', '\n')
        return captured in candidates and normalized == actual
    except (OSError, ValueError, UnicodeError, IndexError):
        return False


def validate_skill_instruction_body(meta: dict, body: str, *, root: Path | str | None = None,
                                    files: dict[str, bytes] | None = None) -> None:
    """Check the captured Skill wrapper, allowing only line-ending/edge whitespace changes."""
    root = _root(root)
    files = files if files is not None else _unpack(meta, root)
    if 'skill_instruction_format' in meta and meta['skill_instruction_format'] != 'exact/v1':
        raise ValueError('Unsupported Skill instruction card format')
    if not isinstance(body, str) or 'SKILL.md' not in files:
        raise ValueError('Skill instructions are unavailable for comparison')
    expected = _instruction_text(files['SKILL.md'])
    lines = body.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r'## Skill instructions[ \t]*', line)]
    if not starts:
        raise ValueError('Skill instructions differ from immutable package; re-import source as a new package')
    start = starts[0]
    ends = [i for i, line in enumerate(lines) if i > start and re.fullmatch(r'## Asset provenance[ \t]*', line)]
    if not ends:
        raise ValueError('Skill instructions differ from immutable package; re-import source as a new package')
    actual = '\n'.join(lines[start + 1:ends[-1]]).strip()
    if actual != expected:
        if meta.get('skill_instruction_format') or not _legacy_instruction_body_matches(meta, actual, files['SKILL.md'], root):
            raise ValueError('Skill instructions differ from immutable package; re-import source as a new package')


def validate_skill_metadata(meta: dict) -> None:
    _identifier(str(meta.get("skill_id", "")))
    if 'skill_instruction_format' in meta and meta['skill_instruction_format'] != 'exact/v1':
        raise ValueError('Unsupported Skill instruction card format')
    validate_category(str(meta.get("skill_category", "")))
    if not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("skill_version", ""))):
        raise ValueError("Skill version must be a SHA256 digest")
    if "skill_lineage" in meta:
        validate_skill_lineage(meta["skill_lineage"], skill_id=meta.get("skill_id"),
                               skill_version=meta.get("skill_version"))
    _unpack(meta)


def entries(*, include_drafts: bool = True, root: Path | str | None = None) -> list[dict]:
    root = _root(root)
    result = []
    wiki_skills = _inside(root, "wiki/skills")
    if wiki_skills.is_dir():
        for path in sorted(wiki_skills.rglob("*.md")):
            safe_path = _inside(root, path.relative_to(root).as_posix())
            if safe_path.is_symlink() or not safe_path.is_file():
                continue
            meta = store.parse_wiki_file(safe_path)
            if meta and meta.get("artifact_kind") == "skill" and meta.get("area") == "skills":
                result.append(meta)
    if include_drafts:
        drafts = _inside(root, "drafts")
        for path in sorted(drafts.glob("*.md")) if drafts.is_dir() else []:
            safe_path = _inside(root, path.relative_to(root).as_posix())
            if safe_path.is_symlink() or not safe_path.is_file():
                continue
            meta = store.parse_wiki_file(safe_path)
            if meta and meta.get("artifact_kind") == "skill":
                meta["type"] = meta.get("draft_type", "strategy")
                meta["area"] = "skills"
                result.append(meta)
    return result


def validate_skill_merge_parents(root: Path | str, lineage: dict) -> None:
    """Require both reviewed merge parents to remain the current active package refs."""
    root = _root(root)
    validate_skill_lineage(lineage)
    parents = lineage['parents']
    if len(parents) != 2:
        return
    reviewed = [meta for meta in entries(include_drafts=False, root=root)
                if meta.get('status') == 'active' and meta.get('human_reviewed_at')]
    for ref in parents:
        matches = [meta for meta in reviewed if
                   (meta.get('skill_id'), meta.get('skill_version'), meta.get('skill_package_sha256'),
                    meta.get('skill_manifest_sha256')) ==
                   (ref['id'], ref['version'], ref['package_sha256'], ref['manifest_sha256'])]
        if not matches:
            raise ValueError('Skill merge parent is no longer an active reviewed version')
        try:
            _unpack(matches[0], root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('Skill merge parent package is unavailable or changed') from exc


def _review_state(meta: dict) -> str:
    if meta.get("status") == "draft":
        return "pending_review"
    if meta.get("archived") or meta.get("status") in {"archived", "dropped"}:
        return "archived"
    if meta.get("status") == "superseded":
        return "superseded"
    if meta.get("human_reviewed_at"):
        return "reviewed"
    return "unreviewed"


def _loadable_reviewed(meta: dict) -> bool:
    return bool(meta.get("human_reviewed_at")) and not meta.get("archived") and meta.get("status") not in {"draft", "dropped", "rejected", "archived"}


def _safe_issue(exc: Exception) -> str:
    # Exception messages can contain attacker-controlled frontmatter paths or absolute local paths.
    if isinstance(exc, ValueError):
        message = str(exc)
        for needle, safe in (
            ("snapshot was modified", "Skill snapshot was modified after import"),
            ("manifest does not match", "Skill manifest does not match the card identity/version"),
            ("archive exceeds", "Skill archive exceeds size limits"),
            ("Invalid Skill archive", "Invalid Skill archive"),
            ("assets do not match", "Skill assets do not match their manifest"),
            ("Skill instructions differ from immutable package", "Skill instructions differ; re-import the source as a new package"),
            ("version does not identify", "Skill version does not identify captured files"),
            ("Unsafe relative path", "Unsafe path in Skill package metadata"),
            ("Symlink or junction", "Symlink or junction is not allowed in Skill assets"),
            ("Path escapes", "Skill asset path escapes the knowledge instance"),
            ("Skill assets must be captured", "Skill assets must be captured under raw/"),
            ("snapshot exceeds", "Skill snapshot exceeds size limits"),
        ):
            if needle in message:
                return safe
        return "Skill snapshot failed validation"
    return type(exc).__name__


def _public_card(meta: dict, root: Path) -> dict:
    result = summary(meta)
    try:
        result["file_path"] = Path(str(meta.get("file_path", ""))).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        result["file_path"] = ""
    return result


def _version_entries(root: Path, identity: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for meta in entries(root=root):
        if meta.get("skill_id") == identity:
            grouped.setdefault(str(meta.get("skill_version", "")), []).append(meta)
    return grouped


def list_versions(root: Path | str, identity: str) -> dict:
    """List immutable versions and their card/integrity states for an explicit KB root."""
    root = _root(root)
    identity = _identifier(identity)
    grouped = _version_entries(root, identity)
    versions = []
    for version, cards in sorted(grouped.items()):
        card_rows = []
        integrity = []
        for meta in cards:
            issue = None
            count = None
            try:
                files = _unpack(meta, root)
                if 'body' in meta:
                    validate_skill_instruction_body(meta, meta['body'], root=root, files=files)
                count = len(files)
            except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
                issue = _safe_issue(exc)
            integrity.append(issue)
            card_rows.append({"slug": meta.get("slug", ""), "status": meta.get("status", ""),
                "review_state": _review_state(meta), "human_reviewed_at": meta.get("human_reviewed_at"),
                "file_path": _public_card(meta, root)["file_path"], "integrity": "failed" if issue else "ok",
                "integrity_issue": issue, "file_count": count})
        states = {_review_state(c) for c in cards}
        review_state = next((state for state in ('reviewed', 'pending_review', 'superseded', 'archived', 'unreviewed') if state in states), 'inactive')
        versions.append({"version": version, "review_state": review_state,
                         "integrity": "failed" if all(integrity) else "ok", "cards": card_rows})
    return {"schema_version": "skill-versions/v1", "skill_id": identity, "versions": versions}


def _version_snapshot(root: Path, identity: str, version: str) -> tuple[dict, dict[str, bytes]]:
    if not re.fullmatch(r"[0-9a-f]{64}", version):
        raise ValueError("Use the full 64-character SHA256 version from oks skills versions")
    cards = _version_entries(root, identity).get(version, [])
    if not cards:
        raise ValueError(f"No Skill card found for {identity} version {version}")
    errors = []
    for meta in sorted(cards, key=lambda item: (bool(item.get("human_reviewed_at")), str(item.get("file_path", ""))), reverse=True):
        try:
            return meta, _unpack(meta, root)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{meta.get('slug', 'card')}: {_safe_issue(exc)}")
    raise ValueError("No intact Skill package for this version: " + "; ".join(errors)[:800])


def _task_impact(root: Path, identity: str, old_version: str, old_paths: set[str], new_version: str) -> list[dict]:
    try:
        folder = _inside(root, ".oks/tasks")
    except ValueError:
        return []
    if not folder.is_dir():
        return []
    from . import handoff, tasks
    impacts = []
    for path in sorted(folder.glob("*.json"))[:100]:
        try:
            if path.is_symlink() or not path.resolve().is_relative_to((root / ".oks/tasks").resolve()):
                continue
            value = tasks._load(root, path.stem)
        except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError):
            continue
        current_paths = {source.get("path") for source in value.get("agreement", {}).get("knowledge", []) if isinstance(source, dict)}
        current_matches = sorted(current_paths & old_paths)
        if not current_matches:
            continue
        uses = [use for use in value.get("uses", []) if isinstance(use, dict) and use.get("source_path") in old_paths and use.get("skill_version") == old_version]
        impacts.append({"task_id": value.get("task_id", path.stem), "revision": value.get("revision"),
            "task_status": handoff.check(root, value["agreement"], path.stem).get("status", "unknown"),
            "comparison_status": "needs_review", "binding": "bound_to_old_version",
            "source_paths": current_matches, "old_version": old_version, "compared_version": new_version,
            "uses": [{"source_path": u.get("source_path"), "skill_version": u.get("skill_version"),
                      "verification": u.get("verification"), "execution_verified": False} for u in uses]})
    return impacts


def compare_versions(root: Path | str, identity: str, from_version: str, to_version: str) -> dict:
    """Compare two immutable snapshots. Explicit root keeps API workers isolated from store globals."""
    root = _root(root)
    identity = _identifier(identity)
    old_meta, old_files = _version_snapshot(root, identity, from_version)
    new_meta, new_files = _version_snapshot(root, identity, to_version)
    changes = []
    total_bytes = 0
    all_paths = sorted(set(old_files) | set(new_files))
    truncated = max(0, len(all_paths) - MAX_DIFF_FILES)
    for name in all_paths[:MAX_DIFF_FILES]:
        before, after = old_files.get(name), new_files.get(name)
        if before == after:
            continue
        state = "added" if before is None else "deleted" if after is None else "modified"
        row = {"path": name, "status": state, "from_sha256": _digest(before) if before is not None else None,
               "to_sha256": _digest(after) if after is not None else None, "unified_diff": None}
        before_data, after_data = before or b"", after or b""
        if max(len(before_data), len(after_data)) > MAX_DIFF_FILE_BYTES:
            row["diff_omitted_reason"] = "one side exceeds 64 KiB text diff limit"
        elif b"\x00" in before_data or b"\x00" in after_data:
            row["diff_omitted_reason"] = "binary file"
        elif total_bytes >= MAX_DIFF_TOTAL_BYTES:
            row["diff_omitted_reason"] = "comparison exceeds 256 KiB total text diff limit"
        else:
            try:
                left = before_data.decode("utf-8").splitlines(keepends=True) if before is not None else []
                right = after_data.decode("utf-8").splitlines(keepends=True) if after is not None else []
                if max(len(left), len(right)) > MAX_DIFF_LINES:
                    row["diff_omitted_reason"] = f"one side exceeds {MAX_DIFF_LINES} line diff limit"
                    changes.append(row)
                    continue
                delta = "".join(difflib.unified_diff(left, right, fromfile=f"a/{name}", tofile=f"b/{name}"))
                size = len(delta.encode("utf-8"))
                if total_bytes + size > MAX_DIFF_TOTAL_BYTES:
                    row["diff_omitted_reason"] = "comparison exceeds 256 KiB total text diff limit"
                else:
                    row["unified_diff"] = delta
                    total_bytes += size
            except UnicodeDecodeError:
                row["diff_omitted_reason"] = "file is not UTF-8 text"
        changes.append(row)
    old_cards = _version_entries(root, identity).get(from_version, [])
    new_cards = _version_entries(root, identity).get(to_version, [])
    try:
        receipt_path, receipts = _receipts(root)
        host_states = []
        for host in HOSTS:
            key = f"{host}/{identity}"
            dest = _host_path(root, host, identity)
            prior = receipts.get(key)
            if not dest.exists():
                state = "not_loaded"
            elif not prior:
                state = "unmanaged_existing"
            else:
                try:
                    actual, _ = _scan(dest)
                    state = "unchanged_managed" if _hashes(actual) == prior.get("files") else "modified_managed"
                except (OSError, ValueError):
                    state = "modified_or_unreadable"
            recovery_commands = []
            if any(_loadable_reviewed(c) for c in old_cards):
                if state == "unchanged_managed":
                    recovery_commands = [f"oks skills unload {identity} --target {host}", f"oks skills load {identity} --version {from_version} --target {host}"]
                elif state == "not_loaded":
                    recovery_commands = [f"oks skills load {identity} --version {from_version} --target {host}"]
            host_states.append({"host": host, "state": state,
                "recovery_commands": recovery_commands,
                "note": "Local edits or unmanaged files are never overwritten; preserve them before any recovery." if state in {"modified_managed", "modified_or_unreadable", "unmanaged_existing"} else None})
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        host_states = [{"state": "unavailable", "integrity_issue": _safe_issue(exc), "recovery_commands": []}]
    return {"schema_version": "skill-diff/v1", "skill_id": identity,
        "from": {"version": from_version, "review_state": _review_state(old_meta), "card": _public_card(old_meta, root)},
        "to": {"version": to_version, "review_state": _review_state(new_meta), "card": _public_card(new_meta, root)},
        "changes": changes, "change_count": sum(1 for p in all_paths if old_files.get(p) != new_files.get(p)),
        "files_truncated": truncated, "diff_bytes_included": total_bytes,
        "affected_tasks": _task_impact(root, identity, from_version,
            {Path(str(c.get("file_path", ""))).resolve().relative_to(root.resolve()).as_posix() for c in old_cards}, to_version),
        "recovery": {"load_command": f"oks skills load {identity} --version {from_version}" if any(_loadable_reviewed(c) for c in old_cards) else None,
                     "hosts": host_states,
                     "note": "The exact version must have a human-reviewed, non-archived card. Default loading still selects the active version. Host copies with local edits are preserved and must not be overwritten."}}


def summary(meta: dict) -> dict:
    result = {key: meta.get(key, "") for key in (
        "skill_id", "skill_version", "title", "type", "skill_category", "status",
        "human_reviewed_at", "slug", "file_path", "skill_description", "skill_dependencies", "skill_lineage",
    )}
    result["type"] = meta.get("type", meta.get("draft_type", ""))
    return result


def bundled_diff(root: Path, identity: str, version: str) -> dict:
    """Compare the selected captured instructions to this installation's bundled Skill."""
    from .mail_setup import asset_root
    root = _root(root)
    identity = _identifier(identity)
    meta, old_files = _version_snapshot(root, identity, version)
    source = _inside(asset_root(), f'skills/{identity}')
    files, _ = _scan(source, ignore=True)
    if 'SKILL.md' not in files:
        raise ValueError('This installation has no bundled instructions for that Skill')
    before, after = old_files['SKILL.md'], files['SKILL.md']
    if max(len(before), len(after)) > MAX_DIFF_FILE_BYTES:
        raise ValueError('Instructions exceed the 64 KiB comparison limit')
    left, right = before.decode('utf-8-sig').splitlines(), after.decode('utf-8-sig').splitlines()
    if max(len(left), len(right)) > 2000:
        raise ValueError('Instructions exceed the comparison line limit')
    delta = '\n'.join(difflib.unified_diff(left, right, fromfile='selected/SKILL.md', tofile='bundled/SKILL.md', lineterm=''))
    if len(delta.encode('utf-8')) > MAX_DIFF_TOTAL_BYTES:
        raise ValueError('Instruction comparison exceeds size limit')
    return {'schema_version': 'skill-bundled-diff/v1', 'skill_id': identity,
            'version': version, 'card': _public_card(meta, root),
            'bundled_version': _digest(_json(_hashes(files)).encode()),
            'instructions_differ': before != after, 'unified_diff': delta,
            'bundled_files': sorted(files), 'review_required': True,
            'scope': 'instruction file only; remaining bundled files are listed for Draft review'}


def prepare_bundled_update(root: Path, request: dict) -> dict:
    """Explicitly capture a bundled version as a Draft; never overwrite reviewed Wiki."""
    from .mail_setup import asset_root
    root = _root(root)
    inspected = bundled_diff(root, request.get('id'), request.get('version'))
    if request.get('expected_bundled_version') != inspected['bundled_version']:
        raise ValueError('Bundled Skill changed; compare it again before preparing a Draft')
    meta, _ = _version_snapshot(root, inspected['skill_id'], inspected['version'])
    if _root() != root:
        raise ValueError('Explicit root does not match the import process')
    imported = import_skill(_inside(asset_root(), 'skills/' + inspected['skill_id']),
                            kind=meta.get('type', 'strategy'), category=meta.get('skill_category', 'general'),
                            skill_id=inspected['skill_id'], expected_version=inspected['bundled_version'])
    entry = imported['entry']
    return {**imported, 'path': Path(entry['file_path']).relative_to(root).as_posix(),
            'review_required': not bool(entry.get('human_reviewed_at')), 'old_wiki_changed': False}


def import_skill(source: Path, *, kind: str = "strategy", category: str = "general", skill_id: str | None = None, expected_version: str | None = None, lineage: dict | None = None, require_new_id: bool = False) -> dict:
    root = _root()
    if kind not in TYPE_DIRS:
        raise ValueError("Skill type must be strategy, anti-pattern or concept")
    category = validate_category(category)
    source = source.expanduser().absolute()
    if source.is_file():
        if source.name != "SKILL.md":
            raise ValueError("Choose SKILL.md or its containing directory")
        source = source.parent
    files, skipped = _scan(source, ignore=True)
    _portable_names(files)
    if "SKILL.md" not in files:
        raise ValueError("Skill source must contain SKILL.md")
    text = files["SKILL.md"].decode("utf-8-sig")
    frontmatter = {}
    body = text
    if text.startswith("---\n") or text.startswith("---\r\n"):
        parts = text.split("---", 2)
        if len(parts) < 3:
            raise ValueError("Invalid SKILL.md frontmatter")
        frontmatter = yaml.safe_load(parts[1]) or {}
        if not isinstance(frontmatter, dict):
            raise ValueError("Skill frontmatter must be a mapping")
        body = parts[2].strip()
    identity = _identifier(skill_id or str(frontmatter.get("name") or source.name))
    description = str(frontmatter.get("description") or "").strip()
    if not body.strip():
        raise ValueError("SKILL.md has no instructions")
    hashes = _hashes(files)
    version = _digest(_json(hashes).encode())
    if lineage is not None:
        validate_skill_lineage(lineage, skill_id=identity, skill_version=version)
    if expected_version is not None and version != expected_version:
        raise ValueError('Bundled Skill changed; compare it again before preparing a Draft')
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        known = entries()
        if require_new_id and any(entry.get("skill_id") == identity for entry in known):
            raise ValueError("Skill ID already exists; choose a new personal variant ID")
        if lineage is not None and len(lineage['parents']) == 2:
            validate_skill_merge_parents(root, lineage)
        duplicates = []
        for entry in known:
            if (entry.get("skill_id"), entry.get("skill_version"), entry.get("type"), entry.get("skill_category")) == (identity, version, kind, category):
                validate_skill_metadata(entry)
                if entry.get("skill_lineage") != lineage:
                    raise ValueError("An identical Skill identity/version has different lineage")
                duplicates.append(entry)
        if duplicates:
            return {"duplicate": True, "entry": summary(duplicates[0]), "skipped": skipped}
        location = f"raw/{datetime.now(UTC):%Y/%m/%d}/skills/{identity}-{version[:16]}"
        capture = _inside(root, location)
        manifest = {"schema_version": "oks-skill-package/v1", "skill_id": identity, "version": version,
                    "files": hashes, "instruction_card_format": "exact/v1"}
        if lineage is not None:
            manifest["lineage"] = lineage
        manifest_data = _json(manifest).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
        package_data = buffer.getvalue()
        package_path, manifest_path = capture / "package.zip", capture / "package-manifest.json"
        if manifest_path.exists():
            existing_bytes = manifest_path.read_bytes()
            existing_manifest = json.loads(existing_bytes)
            legacy_manifest = {key: value for key, value in manifest.items() if key != 'instruction_card_format'}
            if existing_manifest == legacy_manifest:
                # Another classification of the same legacy package must not
                # rewrite that package's immutable manifest during an upgrade.
                manifest, manifest_data = existing_manifest, existing_bytes
        for path, data in ((package_path, package_data), (manifest_path, manifest_data)):
            if path.exists() and path.read_bytes() != data:
                raise ValueError("An existing immutable Skill snapshot differs from this source")
            if not path.exists():
                store._atomic_write(path, data)
        evidence = capture / "evidence"
        if not evidence.exists():
            from knowledge_studio.ingest_prepare import prepare_ingest
            from knowledge_studio.raw_commit import raw_commit
            captured_source = capture / "source/SKILL.md"
            store._atomic_write(captured_source, files["SKILL.md"])
            prep = prepare_ingest(str(captured_source), kb_root=root)
            raw_commit(Path(prep["manifest_dir"]), output=evidence)
        meta = {
            "title": f"Skill: {identity}", "draft_type": kind, "draft_area": "skills",
            "status": "draft", "source_type": "skill-import", "artifact_kind": "skill",
            "skill_id": identity, "skill_version": version, "skill_category": category,
            "skill_description": description, "abstract": description[:400],
            "skill_package": package_path.relative_to(root).as_posix(), "skill_package_sha256": _digest(package_data),
            "skill_manifest": manifest_path.relative_to(root).as_posix(), "skill_manifest_sha256": _digest(manifest_data),
            "skill_dependencies": frontmatter.get("requires") or frontmatter.get("dependencies") or [],
            "raw_bundle": evidence.relative_to(root).as_posix(), "source_pages": [location],
            "source_note": f"Original Skill package {identity} at SHA256 {version}; review its instructions and assets before promotion.",
            "drafted_at": datetime.now(UTC).isoformat(), "tags": ["skill", identity, category],
        }
        if 'instruction_card_format' in manifest:
            meta['skill_instruction_format'] = manifest['instruction_card_format']
        if lineage is not None:
            meta["skill_lineage"] = lineage
        previous = [e for e in known if e.get("skill_id") == identity and e.get("type") == kind
                    and e.get("skill_category") == category and e.get("status") == "active" and e.get("human_reviewed_at")]
        if previous:
            meta.update(relates_to=max(previous, key=lambda e: str(e["human_reviewed_at"]))["slug"], relationship="supersedes")
        candidate_body = f"# {identity}\n\n{description}\n\nClassification: `{kind}` / `{category}`\n\n## Skill instructions\n\n{body}\n\n## Asset provenance\n\nPackage: `{meta['skill_package']}`\n\nVersion: `{version}`\n"
        slug = f"skill-{identity}-{version[:12]}-{kind}-{_digest(category.encode())[:6]}"
        path = _inside(root, f"drafts/{slug}.md")
        store._atomic_write(path, "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + candidate_body)
        return {"duplicate": False, "entry": summary(store.parse_wiki_file(path)), "skipped": skipped, "next_step": f"oks drafts get {slug}; then, after human review: oks drafts promote {slug}"}


def search(query: str, *, limit: int = 5, kind: str | None = None, category: str | None = None, agreement: dict | None = None, task_scope: str | None = None, debug_record: bool = False) -> list[dict]:
    from knowledge_studio.retrieval_debug import agreement_context, record
    task = agreement_context(_root(), agreement, task_scope)
    diagnostics = {"task": task}
    from knowledge_studio.recall import _recall_knowledge_via_backend, _resolve_goal_context
    pages = [p for p in entries(include_drafts=False) if p.get("status") == "active" and p.get("human_reviewed_at") and not p.get("archived")]
    if category:
        category = validate_category(category)
        pages = [p for p in pages if p.get("skill_category") == category or str(p.get("skill_category", "")).startswith(category + "/")]
    # Route by declared capability before incidental mentions in instructions.
    # This vocabulary translates task terms, never selects a hard-coded Skill ID.
    routed_query = query.lower()
    translations = {
        "知识提取": "ingestion extraction", "知识摄入": "ingestion extraction",
        "知识查询": "recall retrieval", "知识检索": "recall retrieval",
        "协作": "collaboration coordination", "通信": "mail", "通讯": "mail",
        "邮件": "mail", "文档": "document documents", "提取": "extraction",
    }
    for term, translated in translations.items():
        routed_query = routed_query.replace(term, translated)
    options = dict(topic_id=None, limit=limit, scope="skills",
                   goal_context=_resolve_goal_context("none", goal_boost=False),
                   explain=True, type_filter=kind, search_backend="fts5",
                   strategy="capability", category=category, diagnostics=diagnostics)
    search_query = f"{query} {routed_query}" if routed_query != query.lower() else query
    hits = _recall_knowledge_via_backend(query=search_query, **options)
    if not hits and routed_query == query.lower():
        options["strategy"] = "capability_body"
        hits = _recall_knowledge_via_backend(query=query, **options)
        diagnostics["capability_fallback"] = "instructions_no_metadata_match"
    by_slug = {p["slug"]: p for p in pages}
    for hit in hits:
        hit.update({key: by_slug[hit["slug"]].get(key, "") for key in ("skill_id", "skill_version", "skill_category")})
        hit["load_command"] = f"oks skills load {hit['skill_id']} --version {hit['skill_version']}"
        hit["body_preview"] = str(by_slug[hit["slug"]].get("skill_description") or hit["body_preview"])
    if debug_record:
        identifier = record(_root(), query, diagnostics, hits)
        for hit in hits:
            hit['debug_record_id'] = identifier
            hit['load_command'] += ' --retrieval-id ' + identifier
    return hits


def _selected(identity: str, version: str | None = None) -> dict:
    identity = _identifier(identity)
    all_reviewed = [p for p in entries(include_drafts=False) if p.get("skill_id") == identity and p.get("human_reviewed_at") and not p.get("archived") and p.get("status") not in {"draft", "dropped", "rejected"}]
    candidates = [p for p in all_reviewed if p.get("status") == "active"]
    if version:
        if not re.fullmatch(r"[0-9a-f]{12,64}", version):
            raise ValueError("Use at least 12 hexadecimal version characters")
        candidates = [p for p in all_reviewed if str(p.get("skill_version", "")).startswith(version)]
        if len({p["skill_version"] for p in candidates}) > 1:
            raise ValueError("Ambiguous Skill version prefix")
    if not candidates:
        raise ValueError("No active human-reviewed Wiki entry for this Skill/version; review its draft first")
    return max(candidates, key=lambda p: str(p["human_reviewed_at"]))


def _receipts(root: Path) -> tuple[Path, dict]:
    path = _inside(root, ".oks/skill-loads.json")
    return path, json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _host_path(root: Path, host: str, identity: str) -> Path:
    if host not in HOSTS:
        raise ValueError("Choose a supported project-local host")
    return _inside(root, f"{HOSTS[host]}/skills/{_identifier(identity)}")


def load(identity: str, *, version: str | None = None, host: str | None = None) -> dict:
    root = _root()
    selected = _selected(identity, version)
    files = _unpack(selected)
    validate_skill_instruction_body(selected, selected.get('body'), root=root, files=files)
    payload = {"entry": summary(selected), "instructions": files["SKILL.md"].decode("utf-8-sig"), "files": sorted(files), "executed": False}
    if host is None:
        cache = _inside(root, f".oks/skill-cache/{identity}/{selected['skill_version']}")
        with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
            if cache.exists():
                current, _ = _scan(cache)
                if _hashes(current) != _hashes(files):
                    raise ValueError("Skill cache was modified; preserve those edits before reloading")
            else:
                for name, data in files.items():
                    store._atomic_write(_inside(cache, name), data)
        return {**payload, "assets_root": str(cache)}
    destination = _host_path(root, host, identity)
    key = f"{host}/{identity}"
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        receipt_path, receipts = _receipts(root)
        if destination.exists():
            prior = receipts.get(key)
            current, _ = _scan(destination)
            if prior and prior.get("version") == selected["skill_version"] and _hashes(current) == _hashes(files):
                return {**payload, "host_path": str(destination), "assets_root": str(destination), "already_loaded": True, "host_reload_required": True}
            raise ValueError("Host Skill already exists; preserve it or unload its unchanged managed copy first")
        stage = _inside(root, f".oks/skill-staging/{uuid.uuid4().hex}")
        for name, data in files.items():
            store._atomic_write(_inside(stage, name), data)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.rename(stage, destination)
        receipts[key] = {"version": selected["skill_version"], "files": _hashes(files), "loaded_at": datetime.now(UTC).isoformat()}
        store._atomic_write(receipt_path, _json(receipts))
    return {**payload, "host_path": str(destination), "assets_root": str(destination), "already_loaded": False, "host_reload_required": True}


def unload(identity: str, *, host: str) -> dict:
    root = _root()
    destination = _host_path(root, host, identity)
    key = f"{host}/{identity}"
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        receipt_path, receipts = _receipts(root)
        prior = receipts.get(key)
        if not prior:
            raise ValueError("Skill is not an owned managed load; refusing removal")
        if destination.exists():
            files, _ = _scan(destination)
            if _hashes(files) != prior.get("files"):
                raise ValueError("Loaded Skill was modified; preserve those edits before unloading")
            expected_dirs = {str(PurePosixPath(name).parent) for name in files}
            expected_dirs.update(str(p) for name in files for p in PurePosixPath(name).parents)
            actual_dirs = {d.relative_to(destination).as_posix() for d in destination.rglob("*") if d.is_dir()}
            if not actual_dirs.issubset(expected_dirs):
                raise ValueError("Loaded Skill contains added directories; refusing removal")
            for name in files:
                _inside(destination, name).unlink()
            for directory in sorted((d for d in destination.rglob("*") if d.is_dir()), key=lambda p: len(p.parts), reverse=True):
                directory.rmdir()
            destination.rmdir()
        receipts.pop(key)
        store._atomic_write(receipt_path, _json(receipts))
    return {"skill_id": identity, "host": host, "unloaded": True, "host_reload_required": True}


def install_router(asset_root: Path, *, host: str = "agents", compact: bool = False) -> dict:
    root = _root()
    destination = _host_path(root, host, "oks")
    router_files, _ = _scan(asset_root / "skills/oks")
    preserved, backed_up = [], []
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        if destination.exists():
            current, _ = _scan(destination)
            if _hashes(current) != _hashes(router_files):
                raise ValueError("Existing OKS router differs; preserve it before installation")
        else:
            for name, data in router_files.items():
                store._atomic_write(_inside(destination, name), data)
        if compact:
            _, receipts = _receipts(root)
            backup = _inside(root, f".oks/skill-backups/{host}/{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}")
            moves = []
            for source in sorted((asset_root / "skills").iterdir()):
                if not source.is_dir() or source.name == "oks":
                    continue
                try:
                    target = _host_path(root, host, source.name)
                except ValueError:
                    preserved.append(source.name)
                    continue
                if not target.exists():
                    continue
                expected, _ = _scan(source, ignore=True)
                try:
                    actual, _ = _scan(target)
                except ValueError:
                    preserved.append(source.name)
                    continue
                expected_dirs = {str(p) for name in expected for p in PurePosixPath(name).parents}
                actual_dirs = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_dir()}
                if f"{host}/{source.name}" in receipts or _hashes(actual) != _hashes(expected):
                    preserved.append(source.name)
                    continue
                if not actual_dirs.issubset(expected_dirs):
                    preserved.append(source.name)
                    continue
                moves.append((source.name, target, _hashes(actual)))
            if moves:
                # Persist the recovery plan before moving any directory.
                store._atomic_write(backup / "restore.json", _json({"host": host,
                    "skills": {name: hashes for name, _, hashes in moves}}))
                for name, target, _ in moves:
                    os.rename(target, _inside(backup, name))
                    backed_up.append(name)
    return {"router_path": str(destination), "backed_up": backed_up, "preserved": preserved,
            "backup_path": str(backup) if compact and backed_up else None, "host_reload_required": True}


def restore_router_backup(path: Path) -> dict:
    root = _root()
    path = path.absolute()
    if not path.is_relative_to(root / ".oks/skill-backups"):
        raise ValueError("Choose a router backup inside this knowledge instance")
    backup = _inside(root, path.relative_to(root).as_posix())
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        receipt = json.loads(_inside(backup, "restore.json").read_text(encoding="utf-8"))
        host = receipt["host"]
        moves = []
        for name, hashes in receipt["skills"].items():
            source, destination = _inside(backup, _identifier(name)), _host_path(root, host, name)
            if not source.exists():
                continue  # Already restored, or a pre-recorded move never completed.
            current, _ = _scan(source)
            if _hashes(current) != hashes or destination.exists():
                raise ValueError("Backup changed or host Skill exists; preserve it before restoring")
            moves.append((source, destination))
        for source, destination in moves:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source, destination)
    return {"restored": [p.name for _, p in moves], "host": host, "host_reload_required": True}
