#!/usr/bin/env python3
"""Run an explicitly selected extractor and emit an OKS Raw bundle.

The Agent remains the orchestrator: it selects a subcommand before invoking
this Level-1 capability.  The adapter may call mature external extractors, but
it never summarizes, corrects, grades, or promotes source content to Draft or
Wiki.  Its contract is faithful extraction plus provenance and evidence.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import socket
import ssl
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


from constants import SCHEMA_VERSION, FETCH_RECEIPT_VERSION, PLUGIN_VERSION, RAW_V2_VERSION, _WATCH_OVERRIDE_LOCK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oks-connector", description=__doc__)
    parser.add_argument(
        "--version",
        action="version",
        version=f"oks-connector {PLUGIN_VERSION}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    mineru = subparsers.add_parser(
        "mineru", help="Package an existing MinerU result directory."
    )
    mineru.add_argument("result_dir", type=Path)
    mineru.add_argument("--source", type=Path, required=True)
    mineru.add_argument("--output", type=Path, required=True)
    mineru.add_argument("--title")
    mineru.add_argument("--extractor-version", default="unknown")
    mineru.add_argument("--formula-candidates", type=Path)
    mineru.add_argument("--warning", action="append", default=[])
    mineru.add_argument("--benchmark", action="store_true")
    mineru.add_argument("--overwrite", action="store_true")

    markitdown = subparsers.add_parser(
        "markitdown",
        help="Run MarkItDown or package an existing MarkItDown Markdown result.",
    )
    markitdown.add_argument("source", type=Path)
    markitdown.add_argument("--markdown", type=Path)
    markitdown.add_argument("--output", type=Path, required=True)
    markitdown.add_argument("--title")
    markitdown.add_argument("--extractor-version", default="unknown")
    markitdown.add_argument("--warning", action="append", default=[])
    markitdown.add_argument("--benchmark", action="store_true")
    markitdown.add_argument("--overwrite", action="store_true")

    watch = subparsers.add_parser(
        "watch", help="Run Watch Skill and package its evidence as Raw."
    )
    watch.add_argument("source")
    watch.add_argument("--source-file", type=Path)
    watch.add_argument("--output", type=Path, required=True)
    watch.add_argument("--title")
    watch.add_argument("--extractor-version", default="unknown")
    watch.add_argument("--max-frames", type=int, default=12)
    watch.add_argument("--hotwords")
    watch.add_argument("--initial-prompt")
    watch.add_argument("--asr-model", default="auto")
    watch.add_argument("--asr-language")
    watch.add_argument(
        "--video-profile", choices=("auto", "speech", "shots", "screen"), default="auto"
    )
    watch.add_argument("--ocr-roi")
    watch.add_argument("--screen-change-threshold", type=float, default=6.0)
    watch.add_argument("--screen-sample-seconds", type=float, default=1.0)
    watch.add_argument(
        "--evidence-tier", choices=("quick", "forensic"), default="forensic",
        help="quick keeps transcript-only extraction; forensic uses subtitle topic anchors before visual evidence.",
    )
    watch.add_argument("--progress", action="store_true", help="Write JSONL progress events to stderr.")
    watch.add_argument("--timeout-seconds", type=float, help="Deadline supplied by ingest for progress ETA reporting.")
    watch.add_argument("--transcript-only", action="store_true")
    watch.add_argument("--no-local-whisper", action="store_true")
    watch.add_argument(
        "--subtitle-langs",
        default="zh.*,ai-zh,en.*",
        help="Caption language patterns passed to Watch/yt-dlp.",
    )
    watch.add_argument("--warning", action="append", default=[])
    watch.add_argument("--benchmark", action="store_true")
    watch.add_argument("--overwrite", action="store_true")

    watch_result = subparsers.add_parser(
        "watch-result", help="Package an exported Watch Skill JSON result."
    )
    watch_result.add_argument("result", type=Path)
    watch_result.add_argument("--source", required=True)
    watch_result.add_argument("--source-file", type=Path)
    watch_result.add_argument("--output", type=Path, required=True)
    watch_result.add_argument("--title")
    watch_result.add_argument("--extractor-version", default="unknown")
    watch_result.add_argument("--warning", action="append", default=[])
    watch_result.add_argument("--benchmark", action="store_true")
    watch_result.add_argument("--overwrite", action="store_true")

    image = subparsers.add_parser(
        "image", help="Run RapidOCR and package one image as Raw."
    )
    image.add_argument("source", type=Path)
    image.add_argument("--output", type=Path, required=True)
    image.add_argument("--title")
    image.add_argument("--extractor-version", default="unknown")
    image.add_argument("--min-confidence", type=float, default=0.5)
    image.add_argument("--ocr-roi", help="OCR region x1,y1,x2,y2 in source pixels.")
    image.add_argument("--warning", action="append", default=[])
    image.add_argument("--benchmark", action="store_true")
    image.add_argument("--overwrite", action="store_true")

    ingest = subparsers.add_parser(
        "ingest",
        help="Route one supported source to its installed extractor and emit a Raw bundle.",
    )
    ingest.add_argument("source")
    ingest.add_argument("--output", type=Path)
    ingest.add_argument("--title")
    ingest.add_argument(
        "--mode",
        choices=("quick", "forensic", "fast", "full"),
        default="quick",
        help="quick (legacy: fast) uses captions only; forensic (legacy: full) adds subtitle-anchored visual evidence.",
    )
    ingest.add_argument(
        "--subtitle-langs",
        default="zh.*,ai-zh,en.*",
        help="Caption language patterns passed to Watch/yt-dlp.",
    )
    ingest.add_argument("--mineru-backend", default="pipeline")
    ingest.add_argument("--mineru-method", default="auto")
    ingest.add_argument("--formula-secondary", action="store_true", help="Run PaddleOCR PP-FormulaNet on MinerU equation crops and embed second candidates.")
    ingest.add_argument("--formula-max-regions", type=int, default=20, help="Cap equation blocks for formula secondary extraction.")
    ingest.add_argument("--overwrite", action="store_true")
    ingest.add_argument(
        "--timeout-seconds", type=float,
        help="Whole extractor deadline. Defaults to 120 seconds for quick and 900 seconds for forensic.",
    )
    ingest.add_argument("--progress", action="store_true", help="Write JSONL progress events to stderr.")

    route = subparsers.add_parser(
        "route", help="Inspect a local source or URL and print the Raw route plan."
    )
    route.add_argument("source")

    probe = subparsers.add_parser(
        "probe",
        help="Safely inspect one public HTTP(S) URL and emit a Fetch Receipt.",
    )
    probe.add_argument("source")
    probe.add_argument("--timeout", type=float, default=15.0)
    probe.add_argument("--max-bytes", type=int, default=64 * 1024)
    probe.add_argument("--max-redirects", type=int, default=5)

    fetch = subparsers.add_parser(
        "fetch",
        help="Safely download one public HTTP(S) source snapshot and emit a Fetch Receipt.",
    )
    fetch.add_argument("source")
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--timeout", type=float, default=30.0)
    fetch.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    fetch.add_argument("--max-redirects", type=int, default=5)
    fetch.add_argument("--overwrite", action="store_true")

    validate = subparsers.add_parser(
        "validate", help="Validate an existing Raw bundle without modifying it."
    )
    validate.add_argument("bundle", type=Path)

    finalize_v2 = subparsers.add_parser(
        "finalize-v2",
        help="Add the Raw Bundle v0.2 manifest, source snapshot, provenance, and run journal to a validated v0.1 bundle.",
    )
    finalize_v2.add_argument("bundle", type=Path)
    finalize_v2.add_argument("--capture-envelope", type=Path, required=True)
    finalize_v2.add_argument("--processing-run", type=Path, required=True)
    finalize_v2.add_argument("--source", type=Path)

    validate_v2 = subparsers.add_parser(
        "validate-v2", help="Validate Raw Bundle v0.2 structure and provenance invariants."
    )
    validate_v2.add_argument("bundle", type=Path)

    check = subparsers.add_parser(
        "check",
        help="验证提取器环境是否可用（Python 版本 + 模块导入）。",
    )
    check.add_argument(
        "extractor",
        nargs="?",
        choices=["watch", "rapidocr", "markitdown", "mineru", "formula", "all"],
        default="all",
    )
    check.add_argument("--minimal", action="store_true", help="仅输出版本兼容性检查，不逐个验证提取器。")
    return parser




from route import is_url, platform_for, route_plan
from digest import write_digest, update_raw_index
from i18n import t
from _shared import (
    emit_json, emit_progress, sha256_file, write_json, write_jsonl,
    exactly_one, prepare_output, normalize_ocr_text, order_ocr_blocks,
    parse_ocr_roi, format_media_time, common_metadata, coverage_report,
    source_identity,
)

def default_ingest_output(source: str) -> Path:
    """Return a unique, human-readable bundle path for one immutable run."""
    if is_url(source):
        parsed = urlparse(source)
        label = f"{parsed.hostname or 'url'}-{Path(parsed.path).stem or 'source'}"
        identity = source
    else:
        local = Path(source).expanduser().resolve()
        label = local.stem or "source"
        identity = str(local)
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", label).strip("-._").lower() or "source"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    timestamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}-{uuid.uuid4().hex[:8]}"
    return (default_raw_root() / f"{timestamp}-{slug[:64]}-{digest}").resolve()


def default_raw_root() -> Path:
    """Resolve the active KB raw/ directory for connector-managed ingest.

    Keep this local instead of importing knowledge_studio.config: the connector
    is also exposed as a standalone console script and should not gain review or
    Wiki behavior. It only needs the same root resolution contract.
    """
    env_root = os.environ.get("OKS_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve() / "raw"

    cwd = Path.cwd()
    if (cwd / "wiki").is_dir():
        return cwd.resolve() / "raw"

    config_path = Path.home() / ".oks" / "config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
        kb_path = config.get("knowledge_base_path")
        if kb_path:
            return Path(kb_path).expanduser().resolve() / "raw"

    return (cwd / "raw").resolve()


def _extractor_python(extractor: str) -> Path:
    environment = {
        "watch": "OKS_WATCH_PYTHON",
        "rapidocr": "OKS_WATCH_PYTHON",
        "markitdown": "OKS_DOCUMENT_PYTHON",
        "mineru": "OKS_MINERU_PYTHON",
        "formula": "OKS_FORMULA_PYTHON",
    }[extractor]
    extra = {
        "watch": "watch",
        "rapidocr": "watch",
        "markitdown": "document",
        "mineru": "pdf",
        "formula": "formula",
    }[extractor]
    module = {
        "watch": "watch_skill",
        "rapidocr": "rapidocr",
        "markitdown": "markitdown",
        "mineru": "mineru",
        "formula": "paddleocr",
    }[extractor]

    # 1. Already installed (via oks capability install) — shared check
    # Map extractor names to capability names for the shared check
    _extractor_to_capability = {"watch": "watch", "rapidocr": "watch",
                                "markitdown": "document", "mineru": "pdf",
                                "formula": "formula"}
    capability = _extractor_to_capability.get(extractor, extractor)
    from capability_check import is_capability_available as _cap_ok
    cap_ok, cap_python = _cap_ok(capability)
    if cap_ok and cap_python is not None:
        return cap_python

    # 2. Explicit env var override
    configured = os.environ.get(environment)
    if configured:
        candidate = Path(configured).expanduser().absolute()
        if not candidate.is_file():
            raise FileNotFoundError(f"{environment} does not point to a Python executable: {candidate}")
        return _validate_extractor_python(candidate, extractor, environment=environment)

    # 3. Repo layout (.venv-watch etc.)
    root = Path(__file__).resolve().parent.parent
    environment_dir = {
        "watch": ".venv-watch",
        "rapidocr": ".venv-watch",
        "markitdown": ".venv-document",
        "mineru": ".venv-pdf",
        "formula": ".venv-formula",
    }[extractor]
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidate = root / environment_dir / relative
    if candidate.is_file():
        return _validate_extractor_python(candidate.absolute(), extractor, environment=environment)

    raise RuntimeError(
        f"{t('capability_missing', name=extractor)}\n"
        f"{t('capability_missing_hint', name=extra, env=environment)}"
    )


def _validate_extractor_python(
    candidate: Path,
    extractor: str,
    *,
    environment: str | None = None,
) -> Path:
    """验证发现到的 Python 解释器版本和模块导入能力。"""
    # Preserve a virtualenv executable symlink. Resolving it would turn a pipx
    # interpreter into the host Python and hide optional packages.
    candidate = candidate.absolute()

    # 1. 验证解释器能否启动
    try:
        version_result = subprocess.run(
            [str(candidate), "-c",
             "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        context = f"（通过 {environment} 或项目布局解析到此路径）" if environment else ""
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 无法启动: {exc}\n{context}"
        )
    if version_result.returncode != 0:
        context = f"（通过 {environment} 或项目布局解析到此路径）" if environment else ""
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 不是有效的 Python 解释器。\n"
            f"stderr: {version_result.stderr.strip()[-500:]}\n{context}"
        )

    # 2. 验证 Python 版本 >= 3.12
    try:
        major, minor = map(int, version_result.stdout.strip().split("."))
    except ValueError:
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 返回了无法解析的版本号: "
            f"{version_result.stdout.strip()}"
        )
    if (major, minor) < (3, 12):
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 是 {major}.{minor}，"
            f"但此模块要求 Python >= 3.12。\n"
            f"请使用 Python 3.12+ 创建虚拟环境，并设置 {environment} 环境变量指向其解释器路径。"
        )

    # 3. 验证所需模块能否导入
    module_query = {
        "watch": "watch_skill",
        "rapidocr": "rapidocr",
        "markitdown": "markitdown",
        "mineru": "mineru",
        "formula": "paddleocr",
    }[extractor]
    try:
        import_result = subprocess.run(
            [str(candidate), "-c", f"import {module_query}"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        extra_name = {
            "watch": "watch", "rapidocr": "watch",
            "markitdown": "document", "mineru": "pdf",
            "formula": "formula",
        }[extractor]
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 导入 {module_query} 时超时。\n"
            f"可选依赖可能已损坏或未安装。\n"
            f"重新安装: oks capability install {extra_name} --yes"
        )
    if import_result.returncode != 0:
        extra_name = {
            "watch": "watch", "rapidocr": "watch",
            "markitdown": "document", "mineru": "pdf",
            "formula": "formula",
        }[extractor]
        raise RuntimeError(
            f"{extractor} Python 在 {candidate} 无法导入 {module_query}:\n"
            f"{import_result.stderr.strip()[-800:]}\n"
            f"安装: oks capability install {extra_name} --yes\n"
            f"或设置 {environment} 指向已安装完整 {extractor} 依赖的 Python 解释器。"
        )

    return candidate


def ingest_child_argv(
    args: argparse.Namespace,
    plan: dict[str, Any],
    output: Path,
    extractor_python: Path,
    *,
    mineru_result: Path | None = None,
) -> list[str]:
    """Build the explicit extractor command selected by the deterministic route."""
    adapter = Path(__file__).resolve()
    base = [str(extractor_python), str(adapter)]
    extractor = plan["extractor"]
    tier = canonical_evidence_tier(args.mode)
    if extractor == "watch":
        command = [*base, "watch", args.source, "--output", str(output)]
        if plan["source_type"] == "audio" or tier == "quick":
            command.append("--transcript-only")
        if plan["source_type"] == "video" and tier == "quick":
            command.append("--no-local-whisper")
        command.extend(["--subtitle-langs", args.subtitle_langs, "--evidence-tier", tier])
        timeout = getattr(args, "timeout_seconds", None)
        if timeout is not None:
            command.extend(["--timeout-seconds", str(timeout)])
        if getattr(args, "progress", False):
            command.append("--progress")
    elif extractor == "rapidocr":
        command = [*base, "image", args.source, "--output", str(output)]
    elif extractor == "markitdown":
        command = [*base, "markitdown", args.source, "--output", str(output)]
    elif extractor == "mineru":
        if mineru_result is None:
            raise ValueError("mineru_result is required for the PDF packaging stage")
        command = [
            *base,
            "mineru",
            str(mineru_result),
            "--source",
            args.source,
            "--output",
            str(output),
        ]
    else:
        raise ValueError(f"unsupported extractor: {extractor}")
    if args.title:
        command.extend(["--title", args.title])
    if args.overwrite:
        command.append("--overwrite")
    return command


def canonical_evidence_tier(mode: str) -> str:
    """Keep the earlier fast/full spelling working while exposing stable tier names."""
    return {"fast": "quick", "full": "forensic"}.get(mode, mode)


def ingest_timeout_seconds(args: argparse.Namespace, extractor: str | None = None) -> float:
    timeout = getattr(args, "timeout_seconds", None)
    if timeout is not None:
        if timeout <= 0:
            raise ValueError("timeout-seconds must be positive")
        return timeout
    if extractor == "mineru":
        # MinerU cold-starts a local service and models; its quick path is not
        # comparable to caption-only video or document extraction.
        return 900.0
    return 120.0 if canonical_evidence_tier(args.mode) == "quick" else 900.0


def _ffprobe_preflight(source: str, plan: dict[str, Any]) -> None:
    """验证本地视频/音频文件需要 ffprobe 时的系统依赖。

    不自动安装系统包；仅对本地视频/音频文件在需要本地处理时进行检查。
    URL 源和纯字幕快速模式不需要 ffprobe。
    """
    if is_url(source):
        return  # yt-dlp handles remote acquisition; ffprobe not needed at this layer
    source_type = plan.get("source_type", "")
    if source_type not in ("video", "audio"):
        return

    ffprobe_cmd = os.environ.get("OKS_FFPROBE")
    if ffprobe_cmd:
        candidate = shutil.which(ffprobe_cmd) or (ffprobe_cmd if Path(ffprobe_cmd).is_file() else None)
    else:
        candidate = shutil.which("ffprobe")
    if candidate is None:
        env_hint = " 设置 OKS_FFPROBE 环境变量指向 ffprobe 可执行文件路径；或" if not ffprobe_cmd else ""
        raise RuntimeError(
            f"本地{source_type}文件需要 ffprobe（由 ffmpeg 提供），但系统上找不到 ffprobe。\n"
            f"{env_hint}"
            f" 安装 ffmpeg: https://ffmpeg.org/download.html\n"
            f" 完整安装说明: oks capability install watch"
        )


def run_ingest(args: argparse.Namespace) -> int:
    """Route and execute one source without adding Studio review or Wiki behavior."""
    plan = route_plan(args.source)
    extractor = plan.get("extractor")
    if extractor is None:
        diag = plan.get("diagnostics", {})
        ext = diag.get("detected_extension", "")
        ext_info = f" (扩展名: {ext})" if ext else ""
        suggestion = diag.get("suggestion", "")
        raise RuntimeError(
            f"没有匹配的 Raw 提取路由{ext_info}\n"
            f"来源类型: {plan.get('source_type', 'unknown')} | "
            f"平台: {plan.get('platform', 'unknown')}\n"
            f"\n{suggestion}\n"
            f"\n运行 `oks-connector route \"{args.source}\"` 查看路由决策详情。"
        )
    if is_url(args.source) and plan["platform"] not in {"bilibili", "douyin", "youtube"}:
        raise RuntimeError(
            "direct non-platform URL acquisition is not yet provenance-safe in ingest; "
            "use fetch followed by ingest on the local snapshot"
        )
    if not is_url(args.source) and not Path(args.source).expanduser().is_file():
        raise FileNotFoundError(Path(args.source).expanduser().resolve())

    output = (args.output or default_ingest_output(args.source)).expanduser().resolve()
    extractor_python = _extractor_python(extractor)
    timeout = ingest_timeout_seconds(args, extractor)
    tier = canonical_evidence_tier(args.mode)
    started = time.monotonic()
    emit_progress(getattr(args, "progress", False), "routing", 0.02, int(timeout))

    # ── preflight: verify system dependencies before costly extraction ──
    if extractor == "watch":
        _ffprobe_preflight(args.source, plan)

    if extractor != "mineru":
        command = ingest_child_argv(args, plan, output, extractor_python)
        try:
            completed = subprocess.run(
                command,
                stdout=None,  # pass through to terminal for real-time progress
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            emit_json({
                "status": "partial",
                "contract": SCHEMA_VERSION,
                "source": args.source,
                "evidence_tier": tier,
                "error": {"code": "EXTRACTION_TIMEOUT", "retryable": True,
                          "message": f"{tier} extraction exceeded {int(timeout)} seconds"},
                "next_action": "retry_with_larger_timeout_or_quick_tier",
            })
            return 2
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip()
            raise RuntimeError(
                f"{extractor} 提取失败 (exit code {completed.returncode})"
                f"\n--- stderr (最后 3000 字符) ---\n{detail[-3000:] or '(无)'}"
                f"\n--- 命令 ---\n{' '.join(command)}"
            )
        return 0

    with tempfile.TemporaryDirectory(prefix="oks-mineru-") as temporary:
        result_dir = Path(temporary)
        # MinerU 3.4+ uses a standalone CLI entry point, not `python -m mineru`.
        # Discover binary from the selected Python environment only; never silently
        # use an unrelated global binary or bare name that would fail at subprocess.run.
        scripts_dir = Path(extractor_python).parent
        mineru_binary_name = "mineru.exe" if os.name == "nt" else "mineru"
        candidate = scripts_dir / mineru_binary_name
        if not candidate.is_file():
            raise RuntimeError(
                f"在选定的 PDF 提取器环境中找不到 mineru 可执行文件。\n"
                f"  解释器: {extractor_python}\n"
                f"  预期位置: {scripts_dir / mineru_binary_name}\n"
                f"  安装: oks capability install pdf --yes\n"
                f"  或设置 OKS_MINERU_PYTHON 指向已安装 mineru[pipeline] 的 Python 环境。"
            )
        mineru_cli = str(candidate)
        mineru = subprocess.run(
            [
                mineru_cli,
                "-p",
                str(Path(args.source).expanduser().resolve()),
                "-o",
                str(result_dir),
                "-b",
                args.mineru_backend,
                "-m",
                args.mineru_method,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if mineru.returncode != 0:
            detail = (mineru.stderr or mineru.stdout).strip()
            raise RuntimeError(f"MinerU extraction failed: {detail[-2000:]}")
        # ── optional formula secondary extraction ──
        formula_candidates = None
        if getattr(args, "formula_secondary", False):
            formula_candidates = Path(temporary) / "formula-candidates.json"
            formula_python = _extractor_python("formula")
            formula_script = Path(__file__).resolve().parent / "formula_candidates.py"
            formula_result = subprocess.run(
                [
                    str(formula_python), str(formula_script),
                    str(result_dir),
                    "--output", str(formula_candidates),
                    "--max-regions", str(getattr(args, "formula_max_regions", 20)),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if formula_result.returncode != 0:
                detail = (formula_result.stderr or formula_result.stdout).strip()
                raise RuntimeError(f"Formula secondary extraction failed: {detail[-2000:]}")
        command = ingest_child_argv(
            args,
            plan,
            output,
            Path(sys.executable).absolute(),
            mineru_result=result_dir,
        )
        if formula_candidates is not None:
            command.extend(["--formula-candidates", str(formula_candidates)])
        remaining = max(0.1, timeout - (time.monotonic() - started))
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=remaining,
            )
        except subprocess.TimeoutExpired:
            emit_json({
                "status": "partial",
                "contract": SCHEMA_VERSION,
                "source": args.source,
                "evidence_tier": tier,
                "error": {"code": "EXTRACTION_TIMEOUT", "retryable": True,
                          "message": f"{tier} extraction exceeded {int(timeout)} seconds"},
                "next_action": "retry_with_larger_timeout_or_quick_tier",
            })
            return 2
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(
                f"MinerU 打包失败 (exit code {completed.returncode})"
                f"\n--- stderr (最后 3000 字符) ---\n{detail[-3000:]}"
                f"\n--- 命令 ---\n{' '.join(command)}"
            )
        return 0


def run_check(args: argparse.Namespace) -> int:
    """验证提取器环境（Python 版本 + 模块导入）。"""
    if getattr(args, "minimal", False):
        emit_json({
            "connector_version": PLUGIN_VERSION,
            "schema_versions": [SCHEMA_VERSION],
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "compatibility": "compatible",
        }, indent=2)
        return 0

    extractors = (
        ["watch", "rapidocr", "markitdown", "mineru", "formula"]
        if args.extractor == "all"
        else [args.extractor]
    )
    results: dict[str, dict[str, Any]] = {}
    all_ok = True
    for ext in extractors:
        try:
            python_path = _extractor_python(ext)
            results[ext] = {
                "status": "available",
                "python": str(python_path),
                "environment_variable": {
                    "watch": "OKS_WATCH_PYTHON",
                    "rapidocr": "OKS_WATCH_PYTHON",
                    "markitdown": "OKS_DOCUMENT_PYTHON",
                    "mineru": "OKS_MINERU_PYTHON",
                    "formula": "OKS_FORMULA_PYTHON",
                }[ext],
            }
        except (RuntimeError, FileNotFoundError) as exc:
            results[ext] = {"status": "unavailable", "error": str(exc)}
            all_ok = False
    emit_json({
        "connector_version": PLUGIN_VERSION,
        "schema_versions": [SCHEMA_VERSION],
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "extractors": results,
        "all_available": all_ok,
    }, indent=2)
    return 0 if all_ok else 2



def bundle_protocol_result(bundle: Path) -> dict[str, Any]:
    """Return the Level-1 JSON envelope for one generated Raw bundle."""
    from validator import validate_bundle
    bundle = bundle.expanduser().resolve()
    validation = validate_bundle(bundle)
    metadata_path = bundle / "metadata.json"
    content_path = bundle / "content.md"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = metadata.get("source", {})
    if not isinstance(source, dict):
        source = {"value": source}
    return {
        "status": "ok" if validation["valid"] else "invalid",
        "contract": SCHEMA_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "bundle": str(bundle),
        "markdown": content_path.read_text(encoding="utf-8"),
        "markdown_path": str(content_path),
        "title": source.get("title"),
        "source": source.get("url") or source.get("path") or source.get("value"),
        "modality": metadata.get("source_type"),
        "metadata": metadata,
        "validation": validation,
    }


def emit_bundle(bundle: Path) -> int:
    result = bundle_protocol_result(bundle)
    emit_json(result)
    try:
        write_digest(bundle)
        update_raw_index(bundle)
    except Exception:
        pass  # digest/index are best-effort, never fail the ingest
    return 0 if result["status"] == "ok" else 2


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "mineru":
            from extractors.mineru import package_mineru
            return emit_bundle(package_mineru(args))
        if args.command == "markitdown":
            from extractors.markitdown import package_markitdown
            return emit_bundle(package_markitdown(args))
        if args.command == "watch":
            from extractors.watch import run_watch
            return emit_bundle(run_watch(args))
        if args.command == "watch-result":
            from extractors.watch import package_watch_payload
            payload = json.loads(args.result.expanduser().resolve().read_text(encoding="utf-8"))
            return emit_bundle(
                package_watch_payload(
                    payload,
                    source=args.source,
                    source_file=args.source_file,
                    output_path=args.output,
                    title=args.title,
                    extractor_version=args.extractor_version,
                    warnings=args.warning,
                    benchmark=args.benchmark,
                    overwrite=args.overwrite,
                    frame_fallback_dir=args.result.expanduser().resolve().parent
                    / "assets"
                    / "frames",
                )
            )
        if args.command == "image":
            from extractors.image import run_image
            return emit_bundle(run_image(args))
        if args.command == "ingest":
            return run_ingest(args)
        if args.command == "route":
            emit_json(route_plan(args.source), indent=2)
            return 0
        if args.command == "probe":
            from network import probe_url
            receipt = probe_url(
                args.source,
                timeout=args.timeout,
                max_bytes=args.max_bytes,
                max_redirects=args.max_redirects,
            )
            emit_json(receipt, indent=2)
            return 0 if receipt["status"] in {"ok", "needs_user_action"} else 2
        if args.command == "fetch":
            from network import fetch_url
            receipt = fetch_url(
                args.source,
                args.output,
                timeout=args.timeout,
                max_bytes=args.max_bytes,
                max_redirects=args.max_redirects,
                overwrite=args.overwrite,
            )
            emit_json(receipt, indent=2)
            return 0 if receipt["status"] in {"ok", "needs_user_action"} else 2
        if args.command == "validate":
            from validator import validate_bundle
            report = validate_bundle(args.bundle)
            emit_json(report, indent=2)
            return 0 if report["valid"] else 2
        if args.command == "finalize-v2":
            from validator import finalize_bundle_v2
            report = finalize_bundle_v2(
                args.bundle,
                args.capture_envelope,
                args.processing_run,
                args.source,
            )
            emit_json(report, indent=2)
            return 0
        if args.command == "validate-v2":
            from validator import validate_bundle_v2
            report = validate_bundle_v2(args.bundle)
            emit_json(report, indent=2)
            return 0 if report["valid"] else 2
        if args.command == "check":
            return run_check(args)
        raise AssertionError(args.command)
    except subprocess.TimeoutExpired as exc:
        emit_json(
            {
                "status": "partial",
                "contract": SCHEMA_VERSION,
                "error": {"code": "EXTRACTION_TIMEOUT", "retryable": True,
                          "message": f"extractor exceeded its deadline: {exc.cmd}"},
                "next_action": "retry_with_larger_timeout_or_quick_tier",
            }
        )
        return 2
    except Exception as exc:  # CLI boundary: failures must remain machine-readable.
        emit_json(
            {
                "status": "error",
                "contract": SCHEMA_VERSION,
                "plugin_version": PLUGIN_VERSION,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
