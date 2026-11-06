#!/usr/bin/env python3
"""One-command dispatcher for the existing multimodal Raw adapters.

This script selects and invokes mature extractors.  It does not summarize,
correct, score, or promote extracted content.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

# Isolated extraction interpreters need access to this bundled package.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oks_connector.route import route_plan
from oks_connector.validator import validate_bundle


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = Path(__file__).resolve().with_name("raw_bundle_adapter.py")
FORMULA_CANDIDATES = Path(__file__).resolve().with_name("formula_candidates.py")
DEFAULT_CONFIG = ROOT / ".oks" / "raw-tools.json"
ENV_OVERRIDES = {
    "watch_python": "OKS_WATCH_PYTHON",
    "document_python": "OKS_DOCUMENT_PYTHON",
    "mineru_python": "OKS_MINERU_PYTHON",
    "formula_python": "OKS_FORMULA_PYTHON",
    "ffmpeg": "OKS_FFMPEG",
    "ffprobe": "OKS_FFPROBE",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Report extractor availability.")
    doctor.add_argument("--json", action="store_true")

    route = commands.add_parser("route", help="Print the selected extraction route.")
    route.add_argument("source")

    ingest = commands.add_parser("ingest", help="Extract one source into a Raw bundle.")
    ingest.add_argument("source")
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--title")
    ingest.add_argument("--overwrite", action="store_true")
    ingest.add_argument("--benchmark", action="store_true")
    ingest.add_argument("--transcript-only", action="store_true")
    ingest.add_argument("--max-frames", type=int, default=12)
    ingest.add_argument(
        "--hotwords",
        help="Comma-separated domain terms passed to local faster-whisper.",
    )
    ingest.add_argument("--initial-prompt", help="Context prompt passed to local faster-whisper.")
    ingest.add_argument("--asr-model", default="auto", help="Local faster-whisper model name.")
    ingest.add_argument("--asr-language", help="Optional ASR language code; default is auto-detect.")
    ingest.add_argument(
        "--video-profile",
        choices=("auto", "speech", "shots", "screen"),
        default="auto",
        help="Transparent frame-selection route for local video.",
    )
    ingest.add_argument(
        "--ocr-roi",
        help="OCR region x1,y1,x2,y2 in source/frame pixels.",
    )
    ingest.add_argument(
        "--screen-change-threshold",
        type=float,
        default=6.0,
        help="Mean pixel-difference threshold for screen recordings.",
    )
    ingest.add_argument("--screen-sample-seconds", type=float, default=1.0)
    ingest.add_argument("--mineru-method", choices=("auto", "txt", "ocr"), default="auto")
    ingest.add_argument("--mineru-backend", default="pipeline")
    ingest.add_argument("--formula-secondary", action="store_true")
    ingest.add_argument("--formula-max-regions", type=int, default=20)
    return parser


def _resolve_path(value: str, base: Path) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return str(candidate)
    if any(separator in expanded for separator in ("/", "\\")):
        return str((base / candidate).resolve())
    return expanded


def load_config(path: Path) -> dict[str, str]:
    path = path.expanduser()
    values: dict[str, Any] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"tool config must be a JSON object: {path}")
        values.update(loaded)
    # Committed examples and local .oks configs both interpret relative paths
    # from the repository root, so moving/copying the config does not change it.
    base = ROOT
    defaults = {
        "watch_python": sys.executable,
        "document_python": sys.executable,
        "mineru_python": sys.executable,
        "formula_python": sys.executable,
        "ffmpeg": "ffmpeg",
        "ffprobe": "ffprobe",
    }
    result: dict[str, str] = {}
    for key, default in defaults.items():
        raw = os.environ.get(ENV_OVERRIDES[key], values.get(key, default))
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"invalid tool config value: {key}")
        result[key] = _resolve_path(raw.strip(), base)
    return result


def run(
    command: Sequence[str],
    *,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        env=env,
    )


PROBE_CODE = r"""
import importlib.metadata as m, importlib.util as u, json, sys
mods = sys.argv[1:]
out = {}
for name in mods:
    found = u.find_spec(name) is not None
    version = None
    if found:
        for dist in (name, name.replace('_', '-')):
            try:
                version = m.version(dist)
                break
            except m.PackageNotFoundError:
                pass
    out[name] = {"available": found, "version": version}
print(json.dumps(out))
"""


def probe_python(name: str, interpreter: str, modules: Sequence[str]) -> dict[str, Any]:
    executable = shutil.which(interpreter) or (interpreter if Path(interpreter).is_file() else None)
    if not executable:
        return {"name": name, "status": "missing", "path": interpreter, "reason": "Python解释器不存在"}
    completed = run([executable, "-c", PROBE_CODE, *modules], capture=True)
    if completed.returncode != 0:
        return {"name": name, "status": "failed", "path": executable, "reason": completed.stderr.strip()}
    detail = json.loads(completed.stdout)
    missing = [module for module, state in detail.items() if not state["available"]]
    return {
        "name": name,
        "status": "ready" if not missing else "partial",
        "path": str(Path(executable).resolve()),
        "modules": detail,
        "reason": "" if not missing else "缺少模块: " + ", ".join(missing),
    }


def probe_command(name: str, command: str) -> dict[str, Any]:
    executable = shutil.which(command) or (command if Path(command).is_file() else None)
    if not executable:
        return {"name": name, "status": "missing", "path": command, "reason": "命令不存在"}
    completed = run([executable, "-version"], capture=True)
    first_line = (completed.stdout or completed.stderr).splitlines()
    return {
        "name": name,
        "status": "ready" if completed.returncode == 0 else "failed",
        "path": str(Path(executable).resolve()),
        "version": first_line[0] if first_line else None,
        "reason": "" if completed.returncode == 0 else (completed.stderr.strip() or "版本检查失败"),
    }


def mineru_cli_path(interpreter: str) -> Path:
    scripts_dir = Path(interpreter).expanduser().resolve().parent
    windows_cli = scripts_dir / "mineru.exe"
    return windows_cli if windows_cli.is_file() else scripts_dir / "mineru"


def probe_file(name: str, path: Path) -> dict[str, Any]:
    return {
        "name": name,
        "status": "ready" if path.is_file() else "missing",
        "path": str(path),
        "reason": "" if path.is_file() else "可执行文件不存在",
    }


def local_bypass_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("NO_PROXY", "no_proxy"):
        existing = env.get(key, "")
        values = [item.strip() for item in existing.split(",") if item.strip()]
        for host in ("127.0.0.1", "localhost"):
            if host not in values:
                values.append(host)
        env[key] = ",".join(values)
    return env


def doctor_report(config: dict[str, str]) -> dict[str, Any]:
    checks = [
        probe_python("watch", config["watch_python"], ["watch_skill", "rapidocr", "faster_whisper", "yt_dlp"]),
        probe_python("document", config["document_python"], ["markitdown"]),
        probe_python("mineru", config["mineru_python"], ["mineru"]),
        probe_python("formula", config["formula_python"], ["paddleocr", "paddle"]),
        probe_file("mineru-cli", mineru_cli_path(config["mineru_python"])),
        probe_command("ffmpeg", config["ffmpeg"]),
        probe_command("ffprobe", config["ffprobe"]),
    ]
    return {"ready": all(item["status"] == "ready" for item in checks), "checks": checks}


def common_adapter_args(args: argparse.Namespace) -> list[str]:
    values: list[str] = []
    if args.title:
        values += ["--title", args.title]
    if args.overwrite:
        values.append("--overwrite")
    if args.benchmark:
        values.append("--benchmark")
    return values


def find_mineru_result(root: Path) -> Path:
    candidates = []
    for markdown in root.rglob("*.md"):
        parent = markdown.parent
        if list(parent.glob("*_content_list.json")):
            candidates.append(parent)
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise RuntimeError(f"expected one MinerU result under {root}, found {len(unique)}")
    return unique[0]


def adapter_command(python: str, subcommand: str, source: str, output: Path, args: argparse.Namespace) -> list[str]:
    command = [python, str(ADAPTER), subcommand, source, "--output", str(output)]
    command.extend(common_adapter_args(args))
    return command


def execute_ingest(args: argparse.Namespace, config: dict[str, str]) -> Path:
    plan = route_plan(args.source)
    extractor = plan["extractor"]
    output = args.output.expanduser().resolve()
    if extractor == "watch":
        command = adapter_command(config["watch_python"], "watch", args.source, output, args)
        local_source = Path(args.source).expanduser()
        if local_source.is_file():
            command += ["--source-file", str(local_source.resolve())]
        command += ["--max-frames", str(args.max_frames)]
        command += [
            "--asr-model", getattr(args, "asr_model", "auto"),
            "--video-profile", getattr(args, "video_profile", "auto"),
        ]
        if getattr(args, "asr_language", None):
            command += ["--asr-language", args.asr_language]
        command += [
            "--screen-change-threshold",
            str(getattr(args, "screen_change_threshold", 6.0)),
        ]
        command += [
            "--screen-sample-seconds",
            str(getattr(args, "screen_sample_seconds", 1.0)),
        ]
        if getattr(args, "hotwords", None):
            command += ["--hotwords", args.hotwords]
        if getattr(args, "initial_prompt", None):
            command += ["--initial-prompt", args.initial_prompt]
        if getattr(args, "ocr_roi", None):
            command += ["--ocr-roi", args.ocr_roi]
        if args.transcript_only or plan["source_type"] == "audio":
            command.append("--transcript-only")
        completed = run(command)
    elif extractor == "rapidocr":
        command = adapter_command(config["watch_python"], "image", args.source, output, args)
        if getattr(args, "ocr_roi", None):
            command += ["--ocr-roi", args.ocr_roi]
        completed = run(command)
    elif extractor == "markitdown":
        completed = run(adapter_command(config["document_python"], "markitdown", args.source, output, args))
    elif extractor == "mineru":
        source = Path(args.source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        with tempfile.TemporaryDirectory(prefix="oks-mineru-") as temp:
            mineru_executable = mineru_cli_path(config["mineru_python"])
            mineru_command = [
                str(mineru_executable), "-p", str(source), "-o", temp,
                "-m", args.mineru_method, "-b", args.mineru_backend,
            ]
            # MinerU 3.4 starts a local API and talks to it with httpx.  On
            # Windows, httpx can inherit the system proxy even when no proxy
            # environment variable exists, so loopback must be explicit.
            extracted = run(mineru_command, env=local_bypass_env())
            if extracted.returncode != 0:
                raise RuntimeError(f"MinerU failed with exit code {extracted.returncode}")
            result_dir = find_mineru_result(Path(temp))
            formula_candidates = None
            if args.formula_secondary:
                formula_candidates = Path(temp) / "formula-candidates.json"
                candidate_command = [
                    config["formula_python"], str(FORMULA_CANDIDATES), str(result_dir),
                    "--output", str(formula_candidates),
                    "--max-regions", str(args.formula_max_regions),
                ]
                candidate_result = run(candidate_command)
                if candidate_result.returncode != 0:
                    raise RuntimeError(
                        f"formula candidate extractor failed with exit code {candidate_result.returncode}"
                    )
            command = [
                sys.executable, str(ADAPTER), "mineru", str(result_dir),
                "--source", str(source), "--output", str(output),
            ] + common_adapter_args(args)
            if formula_candidates is not None:
                command += ["--formula-candidates", str(formula_candidates)]
            completed = run(command)
    else:
        raise RuntimeError(f"unsupported extractor route: {extractor}")
    if completed.returncode != 0:
        raise RuntimeError(f"{extractor} adapter failed with exit code {completed.returncode}")
    report = validate_bundle(output)
    print(json.dumps({"route": plan, "bundle": str(output), "validation": report}, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise RuntimeError("Raw bundle validation failed")
    return output


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    if args.command == "doctor":
        report = doctor_report(config)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ready"] else 2
    if args.command == "route":
        print(json.dumps(route_plan(args.source), ensure_ascii=False, indent=2))
        return 0
    if args.command == "ingest":
        execute_ingest(args, config)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
