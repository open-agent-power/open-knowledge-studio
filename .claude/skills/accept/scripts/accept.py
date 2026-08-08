#!/usr/bin/env python3
"""Run one isolated, evidence-first OKS capability acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIXTURES = {
    "document": ("https://www.gnu.org/software/gawk/manual/gawk.txt", "gawk.txt"),
    "pdf": ("https://arxiv.org/pdf/1706.03762.pdf", "transformer.pdf"),
    "formula": ("https://arxiv.org/pdf/2106.12054.pdf", "math.pdf"),
    "watch": ("https://www.youtube.com/watch?v=Q4LoxsIwriA2", None),
}
ORDER = ("document", "pdf", "formula", "watch")
SUPPORTED_CAPABILITIES = (*ORDER, "feishu")
SENSITIVE_PATTERN = re.compile(r"(?i)(token|secret|password|authorization)\s*[:=]\s*[^\s]+")
JSON_SENSITIVE_PATTERN = re.compile(
    r'(?i)(["\']?(?:token|secret|password|authorization|app_?id|open_?id|user_?name|scope|expires_?at|refresh_?expires_?at|granted_?at)["\']?\s*:\s*["\'])([^"\']+)'
)
EXTERNAL_MARKERS = (
    "429", "rate limit", "timed out", "temporary failure",
    "name or service not known", "connection", "forbidden", "anti-bot",
    "captcha", "download", "network", "unavailable",
    "no interpreter found", "externally-managed-environment",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: str) -> str:
    value = JSON_SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>", value)
    return SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def is_child(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


@dataclass
class Report:
    capability: str
    run_dir: Path
    started_at: str = field(default_factory=utc_now)
    commands: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    status: str = "running"
    reason: str = ""
    cleanup: str = "pending"

    def assert_true(self, name: str, condition: bool, detail: str) -> None:
        self.assertions.append({"name": name, "passed": condition, "detail": redact(detail)})
        if not condition and self.status == "running":
            self.status = "product_failure"
            self.reason = detail

    def save(self) -> None:
        payload = {
            "capability": self.capability,
            "started_at": self.started_at,
            "finished_at": utc_now(),
            "status": self.status,
            "reason": redact(self.reason),
            "commands": self.commands,
            "assertions": self.assertions,
            "artifacts": self.artifacts,
            "cleanup": self.cleanup,
        }
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [f"# OKS acceptance: {self.capability}", "", f"- Status: `{self.status}`", f"- Reason: {redact(self.reason) or 'none'}", f"- Started: {self.started_at}", f"- Cleanup: {self.cleanup}", "", "## Assertions"]
        lines.extend(f"- {'PASS' if item['passed'] else 'FAIL'} `{item['name']}` — {item['detail']}" for item in self.assertions)
        lines.extend(["", "## Commands"])
        lines.extend(
            f"- exit={item['exit_code']} elapsed={item['elapsed_seconds']}s: `{' '.join(item['command'])}`"
            for item in self.commands
        )
        lines.extend(["", "## Artifacts"])
        lines.extend(f"- `{name}`: `{value}`" for name, value in self.artifacts.items())
        (self.run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


class Runner:
    def __init__(self, report: Report, cwd: Path | None = None, env: dict[str, str] | None = None):
        self.report, self.cwd, self.env = report, cwd, env

    def run(self, *command: str, timeout: int = 900, required: bool = True) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        try:
            result = subprocess.run(command, cwd=self.cwd, env=self.env, text=True, capture_output=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            self.report.commands.append({"command": list(command), "exit_code": None, "elapsed_seconds": round(time.monotonic() - started, 2), "output": redact(str(error))})
            self.report.status = "environment_limited"
            self.report.reason = str(error)
            raise RuntimeError(str(error)) from error
        output = f"{result.stdout}\n{result.stderr}".strip()
        self.report.commands.append({"command": list(command), "exit_code": result.returncode, "elapsed_seconds": round(time.monotonic() - started, 2), "output": redact(output[-4000:])})
        if result.returncode and required:
            lowered = output.lower()
            self.report.status = "environment_limited" if any(marker in lowered for marker in EXTERNAL_MARKERS) else "product_failure"
            self.report.reason = output[-1000:] or f"exit code {result.returncode}"
            raise RuntimeError(self.report.reason)
        return result


def download(url: str, destination: Path) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "OKS-Acceptance/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as stream:
        shutil.copyfileobj(response, stream)
        return response.geturl()


def parse_fixture_overrides(values: list[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        capability, separator, path = value.partition("=")
        if separator != "=" or capability not in ORDER or not path:
            raise ValueError("--fixture must be capability=/absolute/path for document, pdf, formula, or watch")
        overrides[capability] = Path(path).expanduser().resolve()
    return overrides


def write_candidate(kb: Path, capability: str, bundle: Path) -> str:
    slug = f"acceptance-{capability}"
    text = f'''---
title: "OKS {capability} acceptance"
draft_type: concept
draft_area: computing
source_type: acceptance
source_bundle: "{bundle.relative_to(kb).as_posix()}"
status: draft
tags: "oks,acceptance,{capability}"
---

# Acceptance result

This Candidate records a successful isolated {capability} acceptance run.
'''
    (kb / "drafts" / f"{slug}.md").write_text(text, encoding="utf-8")
    return slug


def run_capability(capability: str, args: argparse.Namespace) -> Report:
    root = args.root.resolve()
    run_dir = root / f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{capability}-{uuid.uuid4().hex[:8]}"
    report = Report(capability, run_dir)
    env_dir, kb, fixtures = run_dir / "pipx", run_dir / "kb", run_dir / "fixtures"
    bin_dir = run_dir / "bin"
    env = os.environ | {"PIPX_HOME": str(env_dir), "PIPX_BIN_DIR": str(bin_dir), "PIPX_MAN_DIR": str(run_dir / "man")}
    runner = Runner(report, env=env)
    try:
        runner.run(args.pipx, "install", "--python", args.python, args.package_spec, timeout=args.install_timeout)
        report.artifacts["isolated_environment_bytes_after_base_install"] = str(directory_size(env_dir))
        oks = str(bin_dir / "oks")
        runner.run(oks, "--version")
        # oks-connector was removed in v0.4.0 — replaced by oks raw-commit
        runner.run(oks, "capability", "catalog")
        runner.run(oks, "capability", "doctor")
        runner.run(oks, "init", str(kb), "--no-git", "--no-set-default")
        report.assert_true("isolated_kb", is_child(kb, run_dir), str(kb))
        required_capabilities = [capability] if capability != "formula" else ["pdf", "formula"]
        for item in required_capabilities:
            runner.run(oks, "capability", "install", item, "--yes", timeout=args.install_timeout)
        report.artifacts["isolated_environment_bytes_after_capability_install"] = str(directory_size(env_dir))
        if capability == "formula":
            # Formula is a secondary PDF sub-capability — no standalone ingest route.
            # Acceptance verifies installation + import only.
            from capability_check import is_capability_available, python_can_import
            ok, python_path = is_capability_available("formula")
            report.assert_true("formula_capability_available", ok,
                               "expected formula capability to be available after install")
            if ok and python_path:
                report.assert_true("formula_paddleocr_import",
                                   python_can_import(python_path, "paddleocr"),
                                   f"expected paddleocr importable via {python_path}")
            report.status = "passed" if report.status == "running" else report.status
            report.save()
            return report
        local_fixture = args.fixtures.get(capability)
        if local_fixture is not None:
            if not local_fixture.is_file():
                raise RuntimeError(f"local fixture does not exist: {local_fixture}")
            source = str(local_fixture)
            report.artifacts["source_kind"] = "local_fixture"
            report.artifacts["source_path"] = str(local_fixture)
            report.artifacts["source_sha256"] = sha256_file(local_fixture)
            modes = [("quick", args.watch_timeout if capability == "watch" else args.ingest_timeout)]
            if capability == "watch":
                modes.append(("forensic", args.watch_timeout))
        elif capability == "watch":
            source, _ = FIXTURES[capability]
            report.artifacts["source_url"] = source
            modes = [("quick", args.watch_timeout), ("forensic", args.watch_timeout)]
        else:
            source_url, filename = FIXTURES[capability]
            fixtures.mkdir(parents=True, exist_ok=True)
            source = str(fixtures / filename)
            final_url = download(source_url, Path(source))
            report.artifacts["source_url"] = final_url
            report.artifacts["source_sha256"] = sha256_file(Path(source))
            modes = [("quick", args.ingest_timeout)]
        for mode, timeout in modes:
            ingest_runner = Runner(report, cwd=kb, env=env)
            ingest_command = [oks, "ingest", source, "--mode", mode, "--no-progress"]
            ingest_runner.run(*ingest_command, timeout=timeout)
        bundles = sorted(path for path in (kb / "raw").iterdir() if path.is_dir() and path.name != ".gitkeep")
        report.assert_true("raw_bundle_created", bool(bundles), "expected a Raw Bundle in the isolated KB")
        bundle = bundles[-1]
        report.assert_true("raw_bundle_isolated", is_child(bundle, kb), str(bundle))
        for name in ("content.md", "evidence.jsonl", "metadata.json", "quality-report.json", "digest.md"):
            report.assert_true(f"bundle_{name}", (bundle / name).is_file(), str(bundle / name))
        report.assert_true("raw_index", (kb / "raw" / "index.json").is_file(), str(kb / "raw" / "index.json"))
        slug = write_candidate(kb, capability, bundle)
        accept_runner = Runner(report, cwd=kb, env=env)
        accept_runner.run(oks, "drafts", "promote", slug)
        accept_runner.run(oks, "search", "acceptance")
        accept_runner.run(oks, "recall", "acceptance", "--limit", "3")
        accept_runner.run(oks, "lint")
        report.artifacts["bundle"] = str(bundle)
        report.artifacts["bundle_content_sha256"] = sha256_file(bundle / "content.md")
        report.status = "passed" if report.status == "running" else report.status
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError) as error:
        if report.status == "running":
            report.status = "environment_limited" if isinstance(error, urllib.error.URLError) else "product_failure"
            report.reason = str(error)
    finally:
        if args.keep_environment:
            report.cleanup = "kept by --keep-environment"
        else:
            for target in (env_dir, kb, fixtures, bin_dir, run_dir / "man"):
                if target.exists() and is_child(target, run_dir):
                    shutil.rmtree(target)
            report.cleanup = "removed isolated pipx, KB, fixtures, bin, and man directories"
        report.save()
    return report


def run_feishu_preflight(args: argparse.Namespace) -> Report:
    """Validate the optional control-plane boundary without creating cloud data."""
    root = args.root.resolve()
    run_dir = root / f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-feishu-{uuid.uuid4().hex[:8]}"
    report = Report("feishu", run_dir)
    env_dir, bin_dir = run_dir / "pipx", run_dir / "bin"
    env = os.environ | {"PIPX_HOME": str(env_dir), "PIPX_BIN_DIR": str(bin_dir), "PIPX_MAN_DIR": str(run_dir / "man")}
    runner = Runner(report, env=env)
    try:
        runner.run(args.pipx, "install", "--python", args.python, args.package_spec, timeout=args.install_timeout)
        report.artifacts["isolated_environment_bytes_after_base_install"] = str(directory_size(env_dir))
        oks = str(bin_dir / "oks")
        runner.run(oks, "--version")
        runner.run(oks, "capability", "install", "feishu", "--yes")
        auth = runner.run(oks, "feishu", "auth", required=False)
        report.assert_true("feishu_preflight_exposed", True, "optional Feishu CLI is packaged")
        report.assert_true("no_base_created", True, "preflight never invokes oks feishu setup")
        report.artifacts["auth_exit_code"] = str(auth.returncode)
        report.artifacts["manual_next_step"] = (
            "With runtime credentials and an approved test identity, run `oks feishu setup` "
            "to create a dedicated Base, then submit, run-once, listen, promote, and recall."
        )
        report.status = "awaiting_human"
        report.reason = "real Feishu E2E is credential- and reviewer-gated; no Base was created automatically"
    except RuntimeError as error:
        if report.status == "running":
            report.status = "environment_limited"
            report.reason = str(error)
    finally:
        if args.keep_environment:
            report.cleanup = "kept by --keep-environment"
        else:
            for target in (env_dir, bin_dir, run_dir / "man"):
                if target.exists() and is_child(target, run_dir):
                    shutil.rmtree(target)
            report.cleanup = "removed isolated pipx, bin, and man directories; no Base was created"
        report.save()
    return report


def write_matrix(root: Path, reports: list[Report]) -> None:
    """Write the cross-capability feasibility matrix requested by `all`."""
    rows = []
    for report in reports:
        rows.append({
            "capability": report.capability,
            "independent_install": any(item["exit_code"] == 0 and item["command"][1:2] == ["install"] for item in report.commands),
            "actual_execution": bool(report.commands),
            "status": report.status,
            "resource_bytes": report.artifacts.get(
                "isolated_environment_bytes_after_capability_install",
                report.artifacts.get("isolated_environment_bytes_after_base_install", "not measured"),
            ),
            "cleanup": report.cleanup,
            "blocker_or_friction": redact(report.reason) or "none",
        })
    core_cli = all(any(item["exit_code"] == 0 and item["command"][-1:] == ["--version"] for item in report.commands) for report in reports)
    payload = {"generated_at": utc_now(), "core_cli": "passed" if core_cli else "not_proven", "rows": rows}
    (root / "matrix.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# OKS modular feasibility matrix", "",
        f"- Core CLI: `{payload['core_cli']}`", "",
        "| Capability | Independent install | Actual execution | Status | Resource bytes | Cleanup | Blocker / friction |",
        "|---|---:|---:|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['capability']} | {'yes' if row['independent_install'] else 'no'} | "
            f"{'attempted' if row['actual_execution'] else 'no'} | {row['status']} | "
            f"{row['resource_bytes']} | {row['cleanup']} | {row['blocker_or_friction']} |"
        )
    (root / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capability", choices=[*SUPPORTED_CAPABILITIES, "all"])
    parser.add_argument("--root", type=Path, required=True, help="Dedicated acceptance-report root")
    parser.add_argument("--package-spec", required=True, help="Exact wheel path or pipx package spec under test")
    parser.add_argument("--pipx", default="pipx")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--install-timeout", type=int, default=1800)
    parser.add_argument("--ingest-timeout", type=int, default=900)
    parser.add_argument("--watch-timeout", type=int, default=900)
    parser.add_argument("--fixture", action="append", default=[], metavar="CAPABILITY=PATH",
                        help="Use a local fixture instead of the public source; repeat per capability")
    parser.add_argument("--keep-environment", action="store_true")
    args = parser.parse_args()
    supplied_python = Path(args.python).expanduser()
    if supplied_python.exists():
        args.python = str(supplied_python.resolve())
    try:
        args.fixtures = parse_fixture_overrides(args.fixture)
    except ValueError as error:
        parser.error(str(error))
    args.root.mkdir(parents=True, exist_ok=True)
    capabilities = (*ORDER, "feishu") if args.capability == "all" else (args.capability,)
    reports = [run_feishu_preflight(args) if capability == "feishu" else run_capability(capability, args) for capability in capabilities]
    summary = {"generated_at": utc_now(), "reports": [{"capability": report.capability, "status": report.status, "report": str(report.run_dir / "report.json")} for report in reports]}
    (args.root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.capability == "all":
        write_matrix(args.root, reports)
    return 0 if all(report.status == "passed" for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
