"""Offline Wiki recall evaluation, label audits and controlled run comparison."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from knowledge_studio.recall import load_recall_params, recall_knowledge
from knowledge_studio.store import _atomic_write, repo_root
from knowledge_studio.evaluation_dataset import (
    AUDIT_METRICS, AUDIT_MODE, COHORT_COUNTS, DATASET_V2, RANKING_METRICS,
    RUN_V2, audit_hits, validate_v2,
)

DATASET_SCHEMA = "recall-case/v1"
RUN_SCHEMA = "recall-eval-run/v1"
COMPARISON_SCHEMA = "recall-eval-comparison/v1"
CONTEXT_SCHEMA = "recall-eval-context/v1"
EXPERIMENT_VARIABLES = {"code": "code_sha256", "backend": "backend"}
QUALITY_METRICS = {"recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5", "no_result", "stale_leakage"}
RUN_METRICS = QUALITY_METRICS | {"latency_p50_ms", "latency_p95_ms", "case_count"}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _kb_snapshot(root: Path) -> str:
    """Hash persistent memory state to prove evaluation is read-only."""
    digest = hashlib.sha256()
    for bucket in ("wiki", "drafts", "raw", "profiles"):
        base = root / bucket
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _kb_commit(root: Path) -> str | None:
    """Commit of the knowledge-base instance, not of the CLI code."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _files_snapshot(root: Path, pattern: str) -> str:
    files = [(p.relative_to(root).as_posix(), _sha256(p))
             for p in sorted(root.rglob(pattern), key=lambda p: p.relative_to(root).as_posix()) if p.is_file()]
    return hashlib.sha256(json.dumps(files, ensure_ascii=False).encode("utf-8")).hexdigest()


def _comparison_context(root: Path, backend: str | None) -> dict[str, str]:
    params = dict(load_recall_params(root=root))
    selected = backend or params.pop("search_backend", "native")
    params.pop("search_backend", None)
    return {
        "schema_version": CONTEXT_SCHEMA,
        "settings_sha256": _files_snapshot(root / "settings", "*"),
        "parameters_sha256": hashlib.sha256(
            json.dumps(params, sort_keys=True, allow_nan=False).encode("utf-8")
        ).hexdigest(),
        # Content identity works for installed wheels and dirty source trees too.
        "code_sha256": _files_snapshot(Path(__file__).resolve().parent, "*.py"),
        "backend": "native" if selected == "legacy" else selected,
    }


def _code_version() -> str | None:
    try:
        return version("open-knowledge-studio")
    except PackageNotFoundError:
        return None


def load_dataset(path: str | Path) -> dict[str, Any]:
    dataset_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Evaluation dataset must be a YAML object")
    required = {"schema_version", "dataset_id", "version", "cases"}
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"Dataset missing required fields: {', '.join(missing)}")
    if data["schema_version"] == DATASET_V2:
        validate_v2(data)
        return data
    if data["schema_version"] != DATASET_SCHEMA:
        raise ValueError(f"Unsupported dataset schema: {data['schema_version']}")
    if not isinstance(data["cases"], list) or not data["cases"]:
        raise ValueError("Dataset cases must be a non-empty list")

    seen: set[str] = set()
    for index, case in enumerate(data["cases"], start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Case {index} must be an object")
        for field in ("case_id", "query", "relevant"):
            if not case.get(field):
                raise ValueError(f"Case {index} missing required field: {field}")
        if case["case_id"] in seen:
            raise ValueError(f"Duplicate case_id: {case['case_id']}")
        seen.add(case["case_id"])
        if not isinstance(case["relevant"], list) or not case["relevant"]:
            raise ValueError(f"Case {case['case_id']} relevant must be non-empty")
        if not isinstance(case.get("forbidden", []), list):
            raise ValueError(f"Case {case['case_id']} forbidden must be a list")
    return data


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _case_metrics(slugs: list[str], relevant: set[str], forbidden: set[str]) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {}
    for k in (1, 3, 5):
        metrics[f"recall_at_{k}"] = len(set(slugs[:k]) & relevant) / len(relevant) if relevant else None
    first = next((i for i, slug in enumerate(slugs, start=1) if slug in relevant), None)
    metrics["mrr"] = (1.0 / first if first else 0.0) if relevant else None
    seen, dcg = set(), 0.0
    for i, slug in enumerate(slugs[:5], start=1):
        if slug in relevant and slug not in seen:
            dcg += 1.0 / math.log2(i + 1)
        seen.add(slug)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(5, len(relevant)) + 1))
    metrics["ndcg_at_5"] = dcg / ideal if ideal else None
    metrics["no_result"] = float(not slugs)
    metrics["stale_leakage"] = float(bool(set(slugs[:5]) & forbidden))
    return metrics


def run_evaluation(dataset_path: str | Path, output_path: str | Path, *, limit: int = 5,
                   search_backend: str | None = None, split: str | None = None) -> dict[str, Any]:
    if limit < 5:
        raise ValueError("limit must be >= 5 so recall_at_5 and ndcg_at_5 stay meaningful")
    dataset_path = Path(dataset_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    dataset = load_dataset(dataset_path)
    is_v2 = dataset["schema_version"] == DATASET_V2
    evaluation_cases = dataset["cases"]
    if is_v2:
        splits = {case["split"] for case in evaluation_cases}
        if split is None and len(splits) != 1:
            raise ValueError("Mixed-split v2 datasets require explicit --split train|validation|test")
        split = split or next(iter(splits))
        if split not in splits:
            raise ValueError("Requested split has no cases in this dataset")
        evaluation_cases = [case for case in evaluation_cases if case["split"] == split]
    elif split is not None:
        raise ValueError("--split requires a v2 dataset")
    root = repo_root()
    if output_path == dataset_path or any(
        output_path.is_relative_to((root / bucket).resolve())
        for bucket in ("wiki", "drafts", "raw", "profiles", "settings")
    ):
        raise ValueError("Evaluation output must not overwrite the dataset or persistent KB inputs")
    dataset_sha = _sha256(dataset_path)
    context = _comparison_context(root, search_backend)
    before = _kb_snapshot(root)
    cases: list[dict[str, Any]] = []
    latencies: list[float] = []

    for case in evaluation_cases:
        started = time.perf_counter()
        hits = recall_knowledge(
            query=str(case["query"]), limit=limit,
            scope=case.get("scope"), goal=str(case.get("goal", "none")),
            explain=True, type_filter=case.get("type_filter"),
            search_backend=context["backend"],
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        slugs = [str(hit["slug"]) for hit in hits]
        metrics = _case_metrics(slugs, set(case["relevant"]), set(case.get("forbidden", [])))
        if is_v2:
            metrics.update(audit_hits(slugs, case, dataset["assets"]))
            # All returned hits are audited, including hits beyond rank five.
            metrics["stale_leakage"] = float(bool(set(slugs) & set(case.get("forbidden", []))))
        cases.append({
            "case_id": case["case_id"], "query": case["query"],
            "goal": case.get("goal", "none"), "retrieved": slugs,
            "relevant": case["relevant"], "forbidden": case.get("forbidden", []),
            "latency_ms": round(latency_ms, 3), "metrics": metrics,
        })
        if is_v2:
            cases[-1].update({key: case[key] for key in (
                "answerability", "user_scope", "as_of", "split", "source_group", "expected_versions",
            )})

    after = _kb_snapshot(root)
    if before != after:
        raise RuntimeError("Recall evaluation mutated persistent knowledge-base state")
    if dataset_sha != _sha256(dataset_path) or context != _comparison_context(root, search_backend):
        raise RuntimeError("Evaluation dataset, configuration or code changed during the run")
    aggregate = {}
    for name in sorted(QUALITY_METRICS | (AUDIT_METRICS if is_v2 else set())):
        values = [case["metrics"][name] for case in cases if case["metrics"][name] is not None]
        aggregate[name] = round(sum(values) / len(values), 6) if values else None
    if is_v2:
        aggregate.update({
            "answerable_count": sum(case["answerability"] == "answerable" for case in cases),
            "unanswerable_count": sum(case["answerability"] == "unanswerable" for case in cases),
        })
    aggregate.update({
        "latency_p50_ms": round(_percentile(latencies, 0.50), 3),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 3),
        "case_count": len(cases),
    })
    result = {
        "schema_version": RUN_V2 if is_v2 else RUN_SCHEMA,
        "generated_at": _utc_now(),
        "manifest": {
            "code_version": _code_version(),
            "kb_commit": _kb_commit(root),
            "dataset_path": str(dataset_path),
            "dataset_sha256": dataset_sha,
            "dataset_id": dataset["dataset_id"],
            "dataset_version": str(dataset["version"]),
            "limit": limit,
            "goal_modes": sorted({str(case.get("goal", "none")) for case in evaluation_cases}),
            "kb_snapshot_before": before,
            "kb_snapshot_after": after,
            "comparison_context": context,
        },
        "metrics": aggregate,
        "cases": cases,
    }
    if is_v2:
        result["manifest"].update(dataset_schema=DATASET_V2, evaluation_mode=AUDIT_MODE, split=split)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(output_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def _validate_run(run: dict[str, Any]) -> list[str]:
    is_v2 = run.get("schema_version") == RUN_V2
    manifest, metrics, cases = run.get("manifest"), run.get("metrics"), run.get("cases")
    if not isinstance(manifest, dict) or not isinstance(metrics, dict) or not isinstance(cases, list) or not cases:
        raise ValueError("Run requires a manifest, metrics and non-empty cases")
    for key in ("dataset_sha256", "kb_snapshot_before", "kb_snapshot_after"):
        if not isinstance(manifest.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", manifest[key]):
            raise ValueError(f"Run missing or invalid {key}")
    if manifest["kb_snapshot_before"] != manifest["kb_snapshot_after"]:
        raise ValueError("Cannot compare a run that mutated its knowledge base")
    if type(manifest.get("limit")) is not int or manifest["limit"] < 5:
        raise ValueError("Run limit must be an integer >= 5")
    ids = [case.get("case_id") if isinstance(case, dict) else None for case in cases]
    if any(not isinstance(cid, str) or not cid.strip() for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Run has missing or duplicate case IDs")
    if type(metrics.get("case_count")) is not int or metrics["case_count"] != len(ids):
        raise ValueError("Run case_count does not match its cases")
    expected_metrics = RUN_METRICS | (AUDIT_METRICS | COHORT_COUNTS if is_v2 else set())
    if metrics.keys() != expected_metrics:
        raise ValueError(f"Run must contain the complete {run['schema_version']} metric set")
    nullable = set()
    if is_v2:
        if manifest.get("dataset_schema") != DATASET_V2 or manifest.get("evaluation_mode") != AUDIT_MODE:
            raise ValueError("v2 run requires dataset schema and label-audit mode")
        if manifest.get("split") not in ("train", "validation", "test") or any(
            c.get("split") != manifest["split"] for c in cases
        ):
            raise ValueError("v2 run must record one matching split for all cases")
        for answerability in ("answerable", "unanswerable"):
            count = metrics[answerability + "_count"]
            if type(count) is not int or count != sum(c.get("answerability") == answerability for c in cases):
                raise ValueError("Invalid v2 cohort count")
        if metrics["answerable_count"] + metrics["unanswerable_count"] != len(cases):
            raise ValueError("Invalid case answerability")
        if not metrics["answerable_count"]:
            nullable |= RANKING_METRICS
        if not metrics["unanswerable_count"]:
            nullable.add("abstention_correct")
        if any(metrics[key] is not None for key in nullable):
            raise ValueError("Metrics for absent cohorts must be null")
    measured = {key: value for key, value in metrics.items() if key not in nullable}
    try:
        valid_numbers = all(type(v) in (int, float) and math.isfinite(v) for v in measured.values())
    except OverflowError:
        valid_numbers = False
    if not valid_numbers:
        raise ValueError("Run metrics must contain finite numeric measurements")
    if any(not 0 <= metrics[key] <= 1 for key in (QUALITY_METRICS | AUDIT_METRICS) & measured.keys()) or any(
        metrics[key] < 0 for key in ("latency_p50_ms", "latency_p95_ms")
    ):
        raise ValueError("Run metric values are outside their valid ranges")
    context = manifest.get("comparison_context")
    if is_v2 and context is None:
        raise ValueError("v2 run requires comparison context")
    if "comparison_context" in manifest:
        if not isinstance(context, dict) or context.get("schema_version") != CONTEXT_SCHEMA:
            raise ValueError("Invalid comparison context schema")
        for key in ("settings_sha256", "parameters_sha256", "code_sha256"):
            if not isinstance(context.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", context[key]):
                raise ValueError(f"Invalid comparison context {key}")
        if not isinstance(context.get("backend"), str) or not context["backend"].strip():
            raise ValueError("Invalid comparison context backend")
    return ids


def compare_runs(baseline_path: str | Path, candidate_path: str | Path, output_path: str | Path | None = None,
                 *, vary: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """Compare recorded controls, requiring explicit code/backend experiments.

    Legacy v1 runs lack configuration/code context: their deltas are retained,
    but flagged limited. Matching records does not establish causal improvement
    or control clocks, filesystem timestamps, dependencies or external backends.
    """
    unknown = set(vary) - EXPERIMENT_VARIABLES.keys()
    if unknown:
        raise ValueError(f"Unknown experiment variable: {', '.join(sorted(unknown))}")
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    if any(not isinstance(run, dict) or run.get("schema_version") not in (RUN_SCHEMA, RUN_V2) for run in (baseline, candidate)):
        raise ValueError("Both inputs must use recall-eval-run/v1 or v2")
    if baseline["schema_version"] != candidate["schema_version"]:
        raise ValueError("Cannot compare different run schema versions")
    is_v2 = baseline["schema_version"] == RUN_V2
    left, right = baseline.get("manifest"), candidate.get("manifest")
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("Both runs require a manifest")
    if left.get("dataset_sha256") != right.get("dataset_sha256"):
        raise ValueError("Cannot compare runs from different dataset snapshots")
    if left.get("limit") != right.get("limit"):
        raise ValueError("Cannot compare runs evaluated with different limits")
    left_ids, right_ids = _validate_run(baseline), _validate_run(candidate)
    if left["kb_snapshot_before"] != right["kb_snapshot_before"]:
        raise ValueError("Cannot compare runs from different knowledge-base snapshots")
    if left_ids != right_ids:
        raise ValueError("Cannot compare runs with different cases or case ordering")
    if is_v2:
        for a_case, b_case in zip(baseline["cases"], candidate["cases"]):
            for key in ("answerability", "user_scope", "as_of", "split", "source_group", "expected_versions"):
                if key not in a_case or key not in b_case or a_case[key] != b_case[key]:
                    raise ValueError(f"Cannot compare runs with different or missing case {key}")
    if baseline["metrics"].keys() != candidate["metrics"].keys():
        raise ValueError("Cannot compare runs with different metric coverage")
    a, b = left.get("comparison_context"), right.get("comparison_context")
    warnings, variables = [], {}
    if a is None or b is None:
        warnings.append("Legacy run lacks comparison context; settings, parameters, code and backend equality are unverified")
    else:
        for key in ("settings_sha256", "parameters_sha256"):
            if a[key] != b[key]:
                raise ValueError(f"Cannot compare runs with different {key}")
        for variable, field in EXPERIMENT_VARIABLES.items():
            if a[field] != b[field] and variable not in vary:
                raise ValueError(f"Changed {variable}; declare --vary {variable} for an intentional experiment")
    for variable in sorted(set(vary)):
        field = EXPERIMENT_VARIABLES[variable]
        variables[variable] = {"baseline": a[field] if a else None, "candidate": b[field] if b else None}
    keys = sorted(set(baseline["metrics"]) - {"case_count"} - COHORT_COUNTS)
    result = {
        "schema_version": "recall-eval-comparison/v2" if is_v2 else COMPARISON_SCHEMA,
        "generated_at": _utc_now(),
        "baseline": str(Path(baseline_path).resolve()),
        "candidate": str(Path(candidate_path).resolve()),
        "comparability": {
            "status": "limited" if warnings else "matched",
            "warnings": warnings, "variables": variables,
            "not_controlled": ["clock", "filesystem_timestamps", "runtime_dependencies", "external_backend_state"],
        },
        "deltas": {key: round(candidate["metrics"][key] - baseline["metrics"][key], 6)
                   if baseline["metrics"][key] is not None and candidate["metrics"][key] is not None else None
                   for key in keys},
    }
    if is_v2:
        result["comparability"]["evaluation_mode"] = AUDIT_MODE
        result["comparability"]["unmeasured_metrics"] = [key for key in keys if result["deltas"][key] is None]
    result["goal_lift"] = {
        key: result["deltas"][key]
        for key in ("recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5")
        if key in result["deltas"]
    }
    if output_path:
        path = Path(output_path).expanduser().resolve()
        if path in (Path(baseline_path).resolve(), Path(candidate_path).resolve()):
            raise ValueError("Comparison output must not overwrite its input runs")
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result
