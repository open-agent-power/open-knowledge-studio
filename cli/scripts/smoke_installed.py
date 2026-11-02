#!/usr/bin/env python3
"""Exercise built wheel and sdist in clean environments, outside the checkout.

Usage: python cli/scripts/smoke_installed.py dist --work-dir /new/scratch/path
The scratch path must not exist. It is retained (including failure logs) for
inspection. No global installs, editable imports or default-KB changes are made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile


def save_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".smoke-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def clean_env() -> dict[str, str]:
    # Ambient recall overrides and source import paths must not affect a probe.
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("OKS_") and k.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return env


def execute(args: list[str], cwd: Path, env: dict, log: Path, timeout: int = 180) -> str:
    print(f"Running {log.name}", flush=True)
    try:
        completed = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Preserve partial evidence, without assuming that a timeout is success.
        output = (exc.stdout or b"") + (exc.stderr or b"")
        log.write_bytes(output if isinstance(output, bytes) else output.encode("utf-8"))
        raise RuntimeError(f"Timed out: {log}") from exc
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}); see {log}\n{completed.stderr[-1500:]}")
    return completed.stdout


def snapshot(root: Path) -> str:
    files = []
    for bucket in ("wiki", "drafts", "raw", "profiles", "settings"):
        for path in (root / bucket).rglob("*"):
            if path.is_file():
                files.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(sorted(files)).encode()).hexdigest()


def feedback_probe(cli: Path, work: Path, env: dict, root: Path, agreement: Path, asset: Path) -> dict:
    """Synthetic explicit review, packaged Hook consumption and revocation."""
    env = {**env, "OKS_FEEDBACK_HOME": str(work / "private-feedback")}
    scope = {"subject": "smoke-user", "project": "smoke-project", "task": "smoke:report"}
    def request(command, payload, *flags):
        path = work / f"feedback-{command}.json"
        save_json(path, {"scope": scope, **payload})
        return json.loads(execute([str(cli), "feedback", command, str(path), *flags], work, env,
                                  work / f"feedback-{command}.log"))
    request("record", {"event_id": "e1", "action": "adopted", "reason": "Synthetic explicit feedback",
                       "agreement": json.loads(agreement.read_text(encoding="utf-8")),
                       "asset_path": asset.relative_to(root).as_posix()})
    candidate = request("propose", {"candidate_id": "c1", "event_ids": ["e1"],
                                    "title": "Synthetic learning", "summary": "PRIVATE_INSTALLED_FEEDBACK"})
    candidate = request("review", {"candidate_id": "c1", "decision": "approve",
                                   "expected_revision": candidate["revision"], "comment": "Synthetic review"})
    exported = request("export", {"candidate_id": "c1", "expected_revision": candidate["revision"]}, "--confirm-share")
    def manual_query(label):
        return json.loads(execute([str(cli), "recall", "handoff policy retrieval", "--agreement", str(agreement),
                                  "--task-scope", scope["task"], "--feedback-subject", scope["subject"],
                                  "--feedback-project", scope["project"], "--debug-record", "--format", "json"],
                                 work, env, work / f"feedback-query-{label}.log"))
    queried = manual_query("approved")
    if queried["task_context"]["candidates"][0]["summary"] != "PRIVATE_INSTALLED_FEEDBACK":
        raise RuntimeError("Installed manual query lost explicit task requirements")
    hit = next(h for h in queried["knowledge"] if h.get("artifact_kind") == "skill")
    loaded = json.loads(execute([str(cli), "skills", "load", hit["skill_id"], "--version", hit["skill_version"]],
                               work, env, work / "query-skill-load.log"))
    if loaded["executed"] or not (Path(loaded["assets_root"]) / "SKILL.md").is_file():
        raise RuntimeError("Query Skill could not be read from its pinned package")
    def hook(label):
        hook_env = {**env, "OKS_HOOK_OUTPUT": "json", "OKS_TASK_AGREEMENT": str(agreement),
                    "OKS_TASK_SCOPE": scope["task"], "OKS_FEEDBACK_SUBJECT": scope["subject"],
                    "OKS_FEEDBACK_PROJECT": scope["project"]}
        result = subprocess.run([sys.executable, str(root / ".codex/hooks/user-prompt-recall.py")],
                                input=json.dumps({"prompt": "handoff policy retrieval", "cwd": str(root)}),
                                cwd=work, env=hook_env, text=True, encoding="utf-8", capture_output=True, timeout=60)
        (work / f"feedback-hook-{label}.log").write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Installed feedback Hook failed")
        return result.stdout or ""
    if "PRIVATE_INSTALLED_FEEDBACK" not in hook("approved"):
        raise RuntimeError("Installed Hook did not consume approved scoped feedback")
    request("withdraw", {"event_id": "e1"})
    if manual_query("withdrawn")["task_context"]["candidates"]:
        raise RuntimeError("Manual query returned withdrawn requirements")
    if "PRIVATE_INSTALLED_FEEDBACK" in hook("withdrawn"):
        raise RuntimeError("Installed Hook consumed withdrawn feedback")
    shared = (root / ".oks/retrieval-debug.json").read_text(encoding="utf-8")
    if "PRIVATE_INSTALLED_FEEDBACK" in shared or scope["subject"] in shared or scope["project"] in shared:
        raise RuntimeError("Private query requirements leaked into shared diagnostics")
    blocked = subprocess.run([str(cli), "drafts", "promote", Path(exported["path"]).stem],
                             cwd=work, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    (work / "feedback-promotion-blocked.log").write_text(blocked.stdout + blocked.stderr, encoding="utf-8")
    if not blocked.returncode:
        raise RuntimeError("Withdrawn feedback Draft was promoted")
    forgotten = request("forget", {}, "--confirm")
    if forgotten["status"] != "partial" or not forgotten["consumer_disabled"]:
        raise RuntimeError("Shared export deletion boundary was lost")
    return {"status": "passed", "kind": "synthetic CLI and packaged Hook; no host consumption claim"}


def handoff_probe(cli: Path, work: Path, env: dict, root: Path) -> dict:
    """Real installed CLI calls, with explicitly synthetic review material."""
    import yaml
    goals = root / "profiles/goals"
    goals.mkdir(parents=True, exist_ok=True)
    goal = goals / "handoff-report.md"
    goal.write_text("---\ntype: goal\ntitle: Synthetic report\n---\nStay offline and cite sources.\n", encoding="utf-8")
    options = [{"id": "offline", "chosen": True, "rationale": "Private input"},
               {"id": "cloud", "chosen": False, "rejected_because": "No upload"},
               {"id": "audience", "status": "unresolved"}]
    draft = root / "drafts/handoff-smoke.md"
    draft.parent.mkdir(exist_ok=True)
    draft.write_text("---\n" + yaml.safe_dump({"title": "Synthetic handoff policy", "draft_type": "strategy",
                     "draft_area": "computing", "options": options}) + "---\nHandoff synthetic policy.\n", encoding="utf-8")
    execute([str(cli), "drafts", "promote", "handoff-smoke"], work, env, work / "handoff-promote.log")
    pages = list((root / "wiki/computing/strategies").glob("*synthetic-handoff-policy*.md"))
    if len(pages) != 1:
        raise RuntimeError("Installed promotion did not create the handoff policy")
    meta = yaml.safe_load(pages[0].read_text(encoding="utf-8").split("---", 2)[1])
    if meta.get("options") != options or not meta.get("human_reviewed_at"):
        raise RuntimeError("Installed promotion lost decision or review metadata")
    agreement = work / "handoff-agreement.json"
    execute([str(cli), "handoff", "prepare", "--goal", "profiles/goals/handoff-report.md",
             "--wiki", pages[0].stem, "--scope", "smoke:report", "--output", str(agreement)],
            work, env, work / "handoff-prepare.log")
    sent = json.loads(execute([str(cli), "mail", "delegate", "--task", "Continue synthetic report",
                              "--to", "smoke-receiver", "--session-id", "smoke-first",
                              "--agreement", str(agreement), "--format", "json"],
                             work, env, work / "handoff-delegate.log"))
    receiver_env = {**env, "OKS_AGENT_ID": "smoke-receiver"}
    execute([str(cli), "trace", "start", "handoff-report", "--run-id", "handoff-installed"],
            work, receiver_env, work / "handoff-trace-start.log")
    checked = json.loads(execute([str(cli), "handoff", "check", sent["message_id"], "--scope", "smoke:report",
                                 "--run-id", "handoff-installed"], work, receiver_env, work / "handoff-check.log"))
    if checked["status"] != "current" or checked["execution_verified"] is not False:
        raise RuntimeError("Installed handoff check did not preserve the evidence boundary")
    execute([str(cli), "trace", "validate", "handoff-installed"], work, receiver_env, work / "handoff-trace-validate.log")
    retrieval = json.loads(execute([str(cli), "recall", "handoff policy", "--agreement", str(agreement),
                                    "--task-scope", "smoke:report", "--debug-record", "--format", "json"],
                                   work, env, work / "retrieval-agreement.log"))
    if retrieval["diagnostics"]["actual_backends"] != ["fts5"] or not retrieval["diagnostics"]["task"]:
        raise RuntimeError("Installed retrieval did not use FTS5 with current agreement")
    source = work / "trial-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: trial-retrieval\ndescription: Handoff policy retrieval\n---\nRead sources before answering.\n", encoding="utf-8")
    imported = json.loads(execute([str(cli), "skills", "import", str(source)], work, env, work / "retrieval-import.log"))
    execute([str(cli), "drafts", "promote", imported["entry"]["slug"]], work, env, work / "retrieval-promote.log")
    routed = json.loads(execute([str(cli), "skills", "search", "handoff policy", "--debug-record"],
                                work, env, work / "retrieval-skill-search.log"))
    if not routed["hits"] or routed["hits"][0]["backend"] != "fts5":
        raise RuntimeError("Installed Skill routing did not use shared FTS5")
    config = root / "settings/recall.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "\ndebug_record: true\n", encoding="utf-8")
    hook_env = {**env, "OKS_HOOK_OUTPUT": "json", "OKS_TASK_AGREEMENT": str(agreement), "OKS_TASK_SCOPE": "smoke:report"}
    hooked = subprocess.run([sys.executable, str(root / ".codex/hooks/user-prompt-recall.py")],
                            input=json.dumps({"prompt": "handoff policy retrieval", "session_id": "installed-debug", "cwd": str(root)}),
                            cwd=work, env=hook_env, text=True, encoding="utf-8", capture_output=True, timeout=60)
    (work / "retrieval-hook.log").write_text((hooked.stdout or "") + (hooked.stderr or ""), encoding="utf-8")
    if hooked.returncode or "oks skills load trial-retrieval --version" not in (hooked.stdout or ""):
        raise RuntimeError("Installed Hook did not emit pinned Skill catalog")
    records = json.loads((root / ".oks/retrieval-debug.json").read_text(encoding="utf-8"))
    if records[0]["stage"] != "hook_emitted" or not records[0]["diagnostics"].get("task"):
        raise RuntimeError("Installed Hook diagnostic lost task/stage evidence")
    from knowledge_studio.cli import _asset_source
    query_instructions = (_asset_source() / "skills/query/SKILL.md").read_text(encoding="utf-8")
    if "task_context.candidates" not in query_instructions or "6-factor recall engine" in query_instructions:
        raise RuntimeError("Packaged query instructions are stale")
    for name in ("debug.html", "debug.js", "debug.css"):
        if not (_asset_source() / "mail-web" / name).is_file():
            raise RuntimeError("Debug page missing from installed package")
    feedback_result = feedback_probe(cli, work, env, root, agreement, pages[0])
    goal.write_text(goal.read_text(encoding="utf-8") + "Changed human constraint.\n", encoding="utf-8")
    stale = subprocess.run([str(cli), "handoff", "check", sent["message_id"], "--scope", "smoke:report"],
                           cwd=work, env=receiver_env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    (work / "handoff-stale.log").write_text(stale.stdout + stale.stderr, encoding="utf-8")
    if stale.returncode != 1 or json.loads(stale.stdout)["status"] != "needs_review":
        raise RuntimeError("Installed handoff failed to detect a changed Goal")
    return {"status": "passed", "message_id": sent["message_id"], "check": checked,
            "stale_exit_code": stale.returncode, "kind": "synthetic installed CLI trial",
            "retrieval": "FTS5 Wiki + capability, agreement, packaged Hook catalog and debug records passed",
            "feedback": feedback_result}


def probe(work: Path) -> dict:
    # Executed with the installed interpreter under -I, never the source Python.
    import knowledge_studio
    from knowledge_studio.cli import _asset_source
    import yaml

    module = Path(knowledge_studio.__file__).resolve()
    if not module.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(f"Imported code outside the clean environment: {module}")
    packaged = module.parent / "_assets"
    if _asset_source().resolve() != packaged.resolve():
        raise RuntimeError("Schema/assets are resolving to a checkout instead of the installed package")
    for schema in ("recall-case.schema.json", "recall-case-v2.schema.json"):
        if not (packaged / "_meta" / schema).is_file():
            raise RuntimeError(f"Missing packaged schema: {schema}")
    cli = Path(sys.executable).parent / ("oks.exe" if os.name == "nt" else "oks")
    env = clean_env()
    root = work / "知识库 & smoke"
    env["OKS_ROOT"] = str(root)
    execute([str(cli), "init", str(root), "--no-set-default", "--no-git"], work, env, work / "init.log")
    execute([str(cli), "--help"], work, env, work / "help.log")
    fixture = yaml.safe_load((work / "fixture.yaml").read_text(encoding="utf-8"))
    wiki = root / "wiki/computing/concepts"
    wiki.mkdir(parents=True, exist_ok=True)
    for slug in fixture["assets"]:
        (wiki / f"{slug}.md").write_text(
            "---\ntitle: Boundary\ntype: concept\narea: computing\nstatus: active\n"
            "importance: 0.8\nconfidence: 0.8\ncreated: '2026-01-01T00:00:00Z'\n"
            "pinned: true\ntags: boundarytoken\n---\nboundarytoken\n", encoding="utf-8")
    before = snapshot(root)
    legacy = {"schema_version": "recall-case/v1", "dataset_id": "installed-legacy", "version": "1",
              "cases": [{"case_id": "legacy", "query": "boundarytoken", "relevant": ["alpha"]}]}
    (work / "legacy.yaml").write_text(yaml.safe_dump(legacy), encoding="utf-8")
    results = {}
    for version, dataset in (("v1", "legacy.yaml"), ("v2", "fixture.yaml")):
        for suffix in ("baseline", "candidate"):
            run_path = work / f"{version}-{suffix}.json"
            command = [str(cli), "eval", "recall", str(work / dataset), "--output", str(run_path), "--search-backend", "native"]
            if version == "v2":
                command.extend(["--split", "test"])
            execute(command, work, env, work / f"{version}-{suffix}.log")
        output = execute([str(cli), "eval", "compare", str(work / f"{version}-baseline.json"),
                          str(work / f"{version}-candidate.json")], work, env, work / f"{version}-compare.log")
        comparison = json.loads(output)
        if comparison["comparability"]["status"] != "matched" or comparison["deltas"]["recall_at_5"] != 0:
            raise RuntimeError(f"Installed {version} comparison did not match equivalent runs")
        run = json.loads((work / f"{version}-baseline.json").read_text(encoding="utf-8"))
        if run["schema_version"] != f"recall-eval-run/{version}":
            raise RuntimeError("Wrong installed run schema")
        if set(run["cases"][0]["retrieved"]) != set(fixture["assets"]):
            raise RuntimeError("Installed recall did not retrieve the synthetic corpus")
        if version == "v2":
            if run["metrics"]["abstention_correct"] != 1 or any(
                run["metrics"][key] != 0.5 for key in ("scope_leakage", "future_leakage", "version_leakage")
            ):
                raise RuntimeError("Installed v2 did not correctly report the deliberate label violations")
        results[version] = {"metrics": run["metrics"], "comparison_schema": comparison["schema_version"]}
    after = snapshot(root)
    if before != after:
        raise RuntimeError("Installed evaluation mutated persistent KB inputs")
    results["handoff"] = handoff_probe(cli, work, env, root)
    return {"status": "passed", "python": sys.version, "executable": sys.executable,
            "module": str(module), "packaged_assets": str(packaged),
            "kb_before": before, "kb_after": after, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path, nargs="?")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    work = args.work_dir.resolve()
    if args.probe:
        save_json(work / "probe.json", probe(work))
        return 0
    if not args.dist:
        parser.error("dist is required")
    artifacts = {}
    for kind, pattern in (("wheel", "*.whl"), ("sdist", "*.tar.gz")):
        matches = list(args.dist.resolve().glob(pattern))
        if len(matches) != 1:
            parser.error(f"Expected exactly one {kind}, found {len(matches)}")
        artifacts[kind] = matches[0]
    work.mkdir(parents=True, exist_ok=False)
    report = {"platform": platform.platform(), "python": sys.version, "status": "running", "artifacts": {}}
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/evaluation-v2/dataset.yaml"
    try:
        for kind, artifact in artifacts.items():
            target = work / kind
            target.mkdir()
            (target / "fixture.yaml").write_bytes(fixture.read_bytes())
            entry = {"artifact": artifact.name, "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "status": "running"}
            report["artifacts"][kind] = entry
            save_json(work / "report.json", report)
            env = clean_env()
            execute([sys.executable, "-I", "-m", "venv", str(target / "venv")], target, env, target / "venv.log")
            python = target / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            execute([str(python), "-I", "-m", "pip", "install", "--no-input", str(artifact)], target, env, target / "install.log", timeout=600)
            execute([str(python), "-I", str(Path(__file__).resolve()), "--probe", "--work-dir", str(target)],
                    target, env, target / "probe.log", timeout=180)
            entry.update(status="passed", probe=str(target / "probe.json"))
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        for entry in report["artifacts"].values():
            if entry["status"] == "running":
                entry["status"] = "failed"
        raise
    finally:
        save_json(work / "report.json", report)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
