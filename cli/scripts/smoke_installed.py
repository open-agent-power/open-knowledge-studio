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
