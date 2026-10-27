"""v2 fixture contracts and post-retrieval audits; never filter engine output."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

DATASET_V2 = "recall-case/v2"
RUN_V2 = "recall-eval-run/v2"
AUDIT_MODE = "wiki-label-audit/v1"
RANKING_METRICS = {"recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5"}
AUDIT_METRICS = {"scope_leakage", "future_leakage", "version_leakage", "abstention_correct"}
COHORT_COUNTS = {"answerable_count", "unanswerable_count"}


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evaluation times require a timezone")
    return parsed


def validate_v2(data: dict[str, Any]) -> None:
    source = Path(__file__).resolve().parents[2] / "assets"
    base = source if source.is_dir() else Path(__file__).resolve().parent / "_assets"
    schema = json.loads((base / "_meta/recall-case-v2.schema.json").read_text(encoding="utf-8"))
    try:
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)
    except ValidationError as exc:
        raise ValueError(f"Invalid v2 dataset at {list(exc.absolute_path)}: {exc.message}") from exc

    assets = data["assets"]
    identities = [(a["asset_id"], a["version"]) for a in assets.values()]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate asset/version identity")
    for asset in assets.values():
        _instant(asset["available_at"])
    seen, groups = set(), {}
    for case in data["cases"]:
        if case["case_id"] in seen:
            raise ValueError(f"Duplicate case_id: {case['case_id']}")
        seen.add(case["case_id"])
        as_of = _instant(case["as_of"])
        relevant, forbidden = set(case["relevant"]), set(case.get("forbidden", []))
        if relevant & forbidden or (relevant | forbidden) - assets.keys():
            raise ValueError("Gold slugs must exist in assets and cannot be both relevant and forbidden")
        expected = case["expected_versions"]
        if any((identity, version) not in identities for identity, version in expected.items()):
            raise ValueError("Expected asset version does not exist in catalog")
        for slug in relevant:
            asset = assets[slug]
            if asset["user_scope"] not in ("shared", case["user_scope"]) or _instant(asset["available_at"]) > as_of:
                raise ValueError("Relevant gold crosses user scope or as_of boundary")
            if expected.get(asset["asset_id"]) != asset["version"]:
                raise ValueError("Relevant gold must pin its expected asset version")
        # Include both query lineage and referenced gold/negative source groups.
        keys = {("source", case["source_group"])} | {
            ("source", assets[slug]["source_group"]) for slug in relevant | forbidden
        } | {
            ("asset", assets[slug]["asset_id"]) for slug in relevant | forbidden
        }
        if case["user_scope"] != "shared":
            keys.add(("user", case["user_scope"]))
        for key in keys:
            if key in groups and groups[key] != case["split"]:
                raise ValueError(f"Cross-split leakage for {key}")
            groups[key] = case["split"]


def audit_hits(slugs: list[str], case: dict, assets: dict) -> dict[str, float | None]:
    unknown = set(slugs) - assets.keys()
    if unknown:
        raise ValueError(f"Unlabelled retrieved assets: {', '.join(sorted(unknown))}")
    hits = [assets[slug] for slug in slugs]
    expected = case["expected_versions"]
    return {
        "scope_leakage": float(any(a["user_scope"] not in ("shared", case["user_scope"]) for a in hits)),
        "future_leakage": float(any(_instant(a["available_at"]) > _instant(case["as_of"]) for a in hits)),
        "version_leakage": float(any(a["asset_id"] in expected and a["version"] != expected[a["asset_id"]] for a in hits)),
        "abstention_correct": float(not slugs) if case["answerability"] == "unanswerable" else None,
    }
