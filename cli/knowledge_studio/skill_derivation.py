"""Reviewed Skill snapshots -> personal Drafts and explicit three-way updates.

No Wiki, host-copy or receipt writes. Git performs text merging; all unresolved
file conflicts remain in the preview until the caller supplies a decision.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

import yaml

from . import skills, store


def _ref(meta):
    return {"id": meta["skill_id"], "version": meta["skill_version"],
            "package_sha256": meta["skill_package_sha256"],
            "manifest_sha256": meta["skill_manifest_sha256"]}


def _snapshot(root, reference):
    if not isinstance(reference, dict) or not isinstance(reference.get("id"), str):
        raise ValueError("Choose an exact Skill reference with id and version")
    identity = skills._identifier(reference["id"])
    version = reference.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9a-f]{64}", version):
        raise ValueError("Use the full 64-character Skill version")
    cards = [item for item in skills.entries(root=root, include_drafts=False)
             if item.get("skill_id") == identity and item.get("skill_version") == version
             and skills._loadable_reviewed(item)]
    if not cards:
        raise ValueError("Choose a human-reviewed Skill version; pending Drafts cannot be used")
    intact = []
    for meta in cards:
        fixed = _ref(meta)
        if any(key in reference and reference[key] != fixed[key]
               for key in ("package_sha256", "manifest_sha256")):
            continue
        files = skills._unpack(meta, root)
        skills.validate_skill_instruction_body(meta, meta.get("body", ""), root=root, files=files)
        _check_files(files)
        intact.append((meta, files, fixed))
    if not intact:
        raise ValueError("Skill reference hashes changed; inspect the exact version again")
    if len({skills._json(item[2]) for item in intact}) != 1:
        raise ValueError("Skill version has ambiguous snapshots; choose full reference hashes")
    return intact[0]


def _check_files(files):
    skills._portable_names(files)
    if len(files) > skills.MAX_FILES or sum(map(len, files.values())) > skills.MAX_BYTES:
        raise ValueError("Skill package exceeds the file or byte limit")
    if "SKILL.md" not in files:
        raise ValueError("A personal Skill must retain SKILL.md")
    if any(part in skills._IGNORED for name in files for part in Path(name).parts):
        raise ValueError("Skill contains paths excluded by the package importer")
    if _text(files["SKILL.md"]) is None:
        raise ValueError("SKILL.md must contain UTF-8 text")


def _text(data):
    if data is None or b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeError:
        return None


def _named_instructions(data, identity):
    text = data.decode("utf-8-sig")
    match = re.match(r"\A---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)", text)
    try:
        meta = (yaml.safe_load(match[1]) or {}) if match else {}
    except yaml.YAMLError as exc:
        raise ValueError("SKILL.md frontmatter is not valid YAML") from exc
    if not isinstance(meta, dict):
        raise ValueError("SKILL.md frontmatter must be a mapping")
    body = text[match.end():] if match else text
    if not body.strip():
        raise ValueError("SKILL.md has no instructions")
    meta["name"] = identity
    return ("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
            + "---\n" + body).encode("utf-8")


def detail(root, ref):
    """Read the complete instructions and fixed identity of an approved snapshot."""
    root = skills._root(root)
    meta, files, fixed = _snapshot(root, ref)
    return {"knowledge_base": str(root), "ref": fixed,
            "instructions": files["SKILL.md"].decode("utf-8-sig"),
            "lineage": meta.get("skill_lineage"), "card": skills._public_card(meta, root),
            "files": [{"path": name, "sha256": skills._digest(data), "size": len(data),
                       "binary": _text(data) is None} for name, data in sorted(files.items())]}


def _mutation_root(root):
    root = skills._root(root)
    if store.repo_root().resolve() != root:
        raise ValueError("Explicit root does not match the import process")
    return root


def _import(root, identity, files, meta, lineage, *, new_identity=False):
    _check_files(files)
    with tempfile.TemporaryDirectory(prefix="oks-skill-derive-") as folder:
        stage = Path(folder)
        for name, data in files.items():
            path = skills._inside(stage, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = skills.import_skill(stage, skill_id=identity, kind=meta.get("type", "strategy"),
            category=meta.get("skill_category", "general"), lineage=lineage, require_new_id=new_identity,
            expected_version=skills._digest(skills._json(skills._hashes(files)).encode()))
    entry = result["entry"]
    if entry.get("human_reviewed_at") or entry.get("status") != "draft":
        raise ValueError("This exact result was already reviewed; no new Draft was created")
    path = Path(entry["file_path"]).relative_to(root).as_posix()
    captured = store.parse_wiki_file(skills._inside(root, path))
    return {**result, "knowledge_base": str(root), "path": path, "draft_path": path,
            "ref": _ref(captured), "lineage": lineage, "review_state": "pending_review",
            "review_required": True, "old_wiki_changed": False, "host_changed": False}


def derive(root, request):
    """Capture an independent personal variant as a new, unapproved Draft."""
    root = _mutation_root(root)
    if not isinstance(request, dict) or not isinstance(request.get("changes"), dict):
        raise ValueError("Provide changes as relative paths mapped to UTF-8 text or null")
    with store._file_lock(skills._inside(root, ".oks/locks/skill-derivation.lock")):
        meta, files, fixed = _snapshot(root, request.get("base"))
        identity = request.get("variant_id")
        if identity is None:
            identity = fixed["id"][:38].rstrip("-") + "-personal-" + uuid.uuid4().hex[:12]
        if not isinstance(identity, str):
            raise ValueError("variant_id must be a portable Skill identifier")
        identity = skills._identifier(identity)
        if identity == fixed["id"] or any(item.get("skill_id") == identity for item in skills.entries(root=root)):
            raise ValueError("variant_id already exists; choose a new independent Skill identifier")
        files = dict(files)
        for name, value in request["changes"].items():
            name = skills._relative(name)
            if value is None:
                files.pop(name, None)
            elif isinstance(value, str):
                files[name] = value.encode("utf-8")
            else:
                raise ValueError("Skill changes must be UTF-8 text or null")
        _check_files(files)
        files["SKILL.md"] = _named_instructions(files["SKILL.md"], identity)
        lineage = {"schema_version": "skill-lineage/v1",
                   "derived_from": (meta.get("skill_lineage") or {}).get("derived_from", fixed),
                   "upstream_base": fixed, "parents": [fixed]}
        return _import(root, identity, files, meta, lineage, new_identity=True)


def _merge_text(git, base, ours, theirs):
    if max(map(len, (base, ours, theirs))) > skills.MAX_DIFF_FILE_BYTES:
        return None, "text_capacity"
    with tempfile.TemporaryDirectory(prefix="oks-skill-merge-") as folder:
        directory = Path(folder)
        for name, data in (("base", base), ("ours", ours), ("theirs", theirs)):
            (directory / name).write_bytes(data)
        try:
            result = subprocess.run([git, "merge-file", "-p", "--diff3", "-L", "ours",
                "-L", "base", "-L", "theirs", "ours", "base", "theirs"],
                cwd=directory, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Git text merge unavailable or timed out; snapshots were preserved") from exc
    if result.returncode == 0:
        return result.stdout, None
    if 1 <= result.returncode <= 127:
        return result.stdout, "text_conflict"
    raise ValueError("Git text merge failed; snapshots were preserved")


def _file_preview(data, budget):
    if data is None:
        return {"exists": False, "sha256": None, "size": 0, "text": None,
                "binary": False, "truncated": False}
    text = _text(data)
    result = {"exists": True, "sha256": skills._digest(data), "size": len(data),
              "text": None, "binary": text is None, "truncated": False}
    if text is not None:
        limit = min(skills.MAX_DIFF_FILE_BYTES, budget[0])
        preview = data[:limit].decode("utf-8", errors="ignore")
        preview = "".join(preview.splitlines(keepends=True)[:skills.MAX_DIFF_LINES])
        result.update(text=preview, truncated=len(preview.encode("utf-8")) != len(data))
        budget[0] -= len(preview.encode("utf-8"))
    return result


def _plan(root, request):
    if not isinstance(request, dict):
        raise ValueError("Provide ours and theirs exact Skill references")
    git = shutil.which("git")
    if not git:
        raise ValueError("Git is unavailable; install Git before previewing a Skill merge")
    ours_meta, ours, ours_ref = _snapshot(root, request.get("ours"))
    lineage = ours_meta.get("skill_lineage")
    if not isinstance(lineage, dict) or lineage.get("schema_version") != "skill-lineage/v1":
        raise ValueError("The personal Skill has no verified derivation lineage")
    _, base, base_ref = _snapshot(root, lineage.get("upstream_base"))
    theirs_meta, theirs, theirs_ref = _snapshot(root, request.get("theirs"))
    if ours_meta.get("status") != "active" or theirs_meta.get("status") != "active":
        raise ValueError("Personal or upstream version is no longer active; select current versions and preview again")
    if theirs_ref["id"] != base_ref["id"] or ours_ref["id"] == theirs_ref["id"]:
        raise ValueError("Choose an upstream version of this variant's recorded base Skill")
    if theirs_ref == base_ref:
        raise ValueError("The selected upstream version is already this variant's base")
    names = sorted(set(base) | set(ours) | set(theirs))
    skills._portable_names(names)
    if len(names) > skills.MAX_FILES:
        raise ValueError("Merged Skill exceeds the file limit")
    rows, conflicts, merged, decisions = [], [], {}, []
    budget = [skills.MAX_DIFF_TOTAL_BYTES]
    for name in names:
        b, o, t = base.get(name), ours.get(name), theirs.get(name)
        reason = None
        if o == t:
            value, status = o, "unchanged" if o == b else "same_change"
        elif o == b:
            value, status = t, "theirs"
        elif t == b:
            value, status = o, "ours"
        elif b is None:
            value, status, reason = None, "conflict", "add_add"
        elif o is None or t is None:
            value, status, reason = None, "conflict", "delete_modify"
        elif any(_text(data) is None for data in (b, o, t)):
            value, status, reason = None, "conflict", "binary"
        else:
            value, reason = _merge_text(git, b, o, t)
            status = "conflict" if reason else "merged"
        if reason:
            conflicts.append(name)
        elif value is not None:
            merged[name] = value
        row = {"path": name, "status": status, "reason": reason,
               "base": _file_preview(b, budget), "ours": _file_preview(o, budget),
               "theirs": _file_preview(t, budget), "merged": _file_preview(value, budget)}
        rows.append(row)
        decisions.append({"path": name, "status": status, "reason": reason,
                          **{side: row[side]["sha256"] for side in ("base", "ours", "theirs", "merged")}})
    proof = {"schema_version": "skill-merge-plan/v1", "base": base_ref,
             "ours": ours_ref, "theirs": theirs_ref, "files": decisions}
    plan = {**proof, "knowledge_base": str(root), "files": rows, "conflicts": conflicts,
            "plan_digest": skills._digest(skills._json(proof).encode()),
            "ready": not conflicts, "preview_truncated": any(row[side]["truncated"]
                for row in rows for side in ("base", "ours", "theirs", "merged")),
            "review_required": True, "state_mutated": False}
    return plan, ours_meta, ours, theirs, merged


def preview_merge(root, request):
    """Reconstruct three immutable snapshots and return a bounded, read-only plan."""
    return _plan(skills._root(root), request)[0]


def prepare_merge(root, request):
    """Recheck the preview and require an explicit resolution for every conflict."""
    root = _mutation_root(root)
    with store._file_lock(skills._inside(root, ".oks/locks/skill-derivation.lock")):
        plan, meta, ours, theirs, merged = _plan(root, request)
        if request.get("expected_plan_digest") != plan["plan_digest"]:
            raise ValueError("Merge plan changed; preview these exact versions again")
        resolutions = request.get("resolutions", {})
        if not isinstance(resolutions, dict) or set(resolutions) != set(plan["conflicts"]):
            raise ValueError("Every conflict needs one explicit resolution; no extra paths are allowed")
        for name, resolution in resolutions.items():
            if not isinstance(resolution, dict):
                raise ValueError("Each conflict resolution needs an explicit choice")
            choice = resolution.get("choice")
            if choice in ("ours", "theirs"):
                value = (ours if choice == "ours" else theirs).get(name)
            elif choice == "delete":
                value = None
            elif choice == "text" and isinstance(resolution.get("text"), str):
                value = resolution["text"].encode("utf-8")
                if re.search(rb"(?m)^(?:<{7}|\|{7}|={7}|>{7})(?: |\r?$)", value):
                    raise ValueError("Remove unresolved Git conflict markers from the resolution")
            else:
                raise ValueError("Choose ours, theirs, delete, or explicit UTF-8 text")
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        _check_files(merged)
        merged["SKILL.md"] = _named_instructions(merged["SKILL.md"], plan["ours"]["id"])
        if merged == ours:
            raise ValueError("Merge produces no new Skill bytes; current version and lineage are preserved")
        lineage = {"schema_version": "skill-lineage/v1",
                   "derived_from": meta["skill_lineage"]["derived_from"],
                   "upstream_base": plan["theirs"], "parents": [plan["ours"], plan["theirs"]]}
        return {**_import(root, plan["ours"]["id"], merged, meta, lineage),
                "plan_digest": plan["plan_digest"], "resolved_conflicts": sorted(resolutions)}
