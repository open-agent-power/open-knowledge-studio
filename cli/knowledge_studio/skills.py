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
    "skill_dependencies", "raw_bundle",
)
MAX_FILES = 1024
MAX_BYTES = 64 * 1024 * 1024
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


def _root() -> Path:
    root = store.repo_root().resolve()
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


def _unpack(meta: dict) -> dict[str, bytes]:
    root = _root()
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
    if manifest.get("skill_id") != meta.get("skill_id") or manifest.get("version") != meta.get("skill_version"):
        raise ValueError("Skill manifest does not match the reviewed identity/version")
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


def validate_skill_metadata(meta: dict) -> None:
    _identifier(str(meta.get("skill_id", "")))
    validate_category(str(meta.get("skill_category", "")))
    if not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("skill_version", ""))):
        raise ValueError("Skill version must be a SHA256 digest")
    _unpack(meta)


def entries(*, include_drafts: bool = True) -> list[dict]:
    root = _root()
    result = [p for p in store.list_wiki_pages() if p.get("artifact_kind") == "skill"
              and p.get("area") == "skills" and Path(p["file_path"]).is_relative_to(root / "wiki/skills")]
    if include_drafts:
        for path in sorted((root / "drafts").glob("*.md")):
            meta = store.parse_wiki_file(path)
            if meta and meta.get("artifact_kind") == "skill":
                meta["type"] = meta.get("draft_type", "strategy")
                meta["area"] = "skills"
                result.append(meta)
    return result


def summary(meta: dict) -> dict:
    result = {key: meta.get(key, "") for key in (
        "skill_id", "skill_version", "title", "type", "skill_category", "status",
        "human_reviewed_at", "slug", "file_path", "skill_description", "skill_dependencies",
    )}
    result["type"] = meta.get("type", meta.get("draft_type", ""))
    return result


def import_skill(source: Path, *, kind: str = "strategy", category: str = "general", skill_id: str | None = None) -> dict:
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
    with store._file_lock(_inside(root, ".oks/locks/skills.lock")):
        known = entries()
        for entry in known:
            if (entry.get("skill_id"), entry.get("skill_version"), entry.get("type"), entry.get("skill_category")) == (identity, version, kind, category):
                validate_skill_metadata(entry)
                return {"duplicate": True, "entry": summary(entry), "skipped": skipped}
        location = f"raw/{datetime.now(UTC):%Y/%m/%d}/skills/{identity}-{version[:16]}"
        capture = _inside(root, location)
        manifest = {"schema_version": "oks-skill-package/v1", "skill_id": identity, "version": version, "files": hashes}
        manifest_data = _json(manifest).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(files.items()):
                archive.writestr(zipfile.ZipInfo(name), data, compress_type=zipfile.ZIP_DEFLATED)
        package_data = buffer.getvalue()
        package_path, manifest_path = capture / "package.zip", capture / "package-manifest.json"
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
        record(_root(), query, diagnostics, hits)
    return hits


def _selected(identity: str, version: str | None = None) -> dict:
    identity = _identifier(identity)
    candidates = [p for p in entries(include_drafts=False) if p.get("skill_id") == identity and p.get("status") == "active" and p.get("human_reviewed_at") and not p.get("archived")]
    if version:
        if not re.fullmatch(r"[0-9a-f]{12,64}", version):
            raise ValueError("Use at least 12 hexadecimal version characters")
        candidates = [p for p in candidates if str(p.get("skill_version", "")).startswith(version)]
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
