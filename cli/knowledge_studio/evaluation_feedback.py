"""Observed retrieval/use → explicit review → version-pinned evaluation data.

No feedback is unknown. Use receipts are signals, not human Gold labels.
"""

from __future__ import annotations
from datetime import datetime, UTC
from pathlib import Path
import hashlib
import json
from uuid import uuid4
import yaml
from . import store, tasks, workspace, studio_evaluation as ev


def preferences(root):
    target = tasks._inside(root, "settings/evaluation.yaml")
    data = (
        yaml.safe_load(target.read_text(encoding="utf-8")) if target.is_file() else {}
    )
    if not isinstance(data or {}, dict):
        raise ValueError("Evaluation settings must be a mapping")
    return {
        "capture_enabled": (data or {}).get("capture_enabled") is True,
        "retain_query": (data or {}).get("retain_query") is True,
    }


def configure(root, payload):
    values = payload.get("values")
    if (
        not isinstance(values, dict)
        or set(values) - {"capture_enabled", "retain_query"}
        or any(type(v) is not bool for v in values.values())
    ):
        raise ValueError("Choose boolean capture settings")
    target = tasks._inside(root, "settings/evaluation.yaml")
    with store._file_lock(tasks._inside(root, ".oks/locks/evaluation-settings.lock")):
        data = (
            yaml.safe_load(target.read_text(encoding="utf-8"))
            if target.is_file()
            else {}
        )
        if not isinstance(data or {}, dict):
            raise ValueError("Evaluation settings must be a mapping")
        store._atomic_write(
            target, yaml.safe_dump({**(data or {}), **values}, sort_keys=False)
        )
    return preferences(root)


def capture(root, query, hits, diagnostics=None):
    config = preferences(root)
    if not config["capture_enabled"]:
        return None
    identifier = (diagnostics or {}).get("call_trace", {}).get("id") or uuid4().hex
    item = {
        "id": identifier,
        "kind": "retrieval",
        "at": datetime.now(UTC).isoformat(),
        "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
        "query": query if config["retain_query"] else None,
        "hits": [
            {
                k: h[k]
                for k in (
                    "slug",
                    "title",
                    "source_path",
                    "source_sha256",
                    "relevance",
                    "backend",
                )
                if k in h
            }
            for h in hits[:100]
        ],
        "diagnostics": diagnostics or {},
        "adoption": "unknown",
        "source": "interactive-recall",
    }
    ev.write(root, "observations/" + identifier + ".json", item)
    return identifier


def record_use(root, slug, observation=None):
    # An unbound use remains unbound; never guess the latest query.
    item = {
        "id": uuid4().hex,
        "kind": "explicit_use",
        "at": datetime.now(UTC).isoformat(),
        "slug": slug,
        "observation_id": observation,
        "adoption": "reported_used",
        "asset": {k: v for k, v in _asset(root, slug).items() if k != "text"},
    }
    ev.write(root, "use-events/" + item["id"] + ".json", item)


def _jsonl(root):
    target = tasks._inside(root, "records/inject.jsonl")
    if not target.is_file():
        return []
    with target.open("rb") as stream:
        stream.seek(0, 2)
        offset = max(0, stream.tell() - 2 * 1024 * 1024)
        stream.seek(offset)
        data = stream.read()
    if offset:
        data = data.split(b"\n", 1)[-1]
    result = []
    for raw in data.splitlines()[-200:]:
        try:
            item = json.loads(raw)
            if not isinstance(item, dict):
                continue
            identity = {
                k: item.get(k)
                for k in ("session_id", "turn", "prompt_hash", "injected_at", "slugs")
            }
            identifier = (
                "inject-"
                + hashlib.sha256(
                    json.dumps(identity, sort_keys=True).encode()
                ).hexdigest()[:24]
            )
            result.append(
                {
                    "id": identifier,
                    "kind": "injection",
                    "at": item.get("injected_at"),
                    "query": None,
                    "query_sha256": item.get("prompt_hash"),
                    "hits": [
                        {"slug": slug}
                        for slug in item.get("slugs", [])
                        if isinstance(slug, str)
                    ],
                    "adoption": (
                        "reported_use_unattributed" if item.get("used") else "unknown"
                    ),
                    "reported_used_slugs": item.get("used_slugs", []),
                    "source": "records/inject.jsonl",
                }
            )
        except (ValueError, TypeError):
            continue
    return result


def observations(root):
    from .retrieval_debug import read_records
    from .vfs_observation import history

    result = {}
    for target in sorted(ev.path(root, "observations").glob("*.json")):
        item = ev.read(root, "observations/" + target.name)
        result[item["id"]] = item
    for item in read_records(root)["records"]:
        result.setdefault(
            item["id"],
            {
                **item,
                "query": None,
                "kind": "retrieval",
                "adoption": "unknown",
                "source": ".oks/retrieval-debug.json",
            },
        )
    for item in _jsonl(root):
        result.setdefault(item["id"], item)
    for item in history(root, "recall")["records"]:
        result.setdefault(
            item["id"],
            {
                **item,
                "query": None,
                "kind": "retrieval",
                "adoption": "unknown",
                "source": "records/observability/recall.json",
            },
        )
    for item in _use_events(root):
        if not item.get("observation_id"):
            identifier = "use-" + item["id"]
            result[identifier] = {
                "id": identifier,
                "kind": "explicit_use",
                "at": item["at"],
                "query": None,
                "query_sha256": None,
                "hits": [item.get("asset", {"slug": item["slug"]})],
                "adoption": "reported_used",
                "source": "explicit-use-unbound",
            }
    return result


def _use_events(root):
    return [
        ev.read(root, "use-events/" + p.name)
        for p in ev.path(root, "use-events").glob("*.json")
    ]


def candidate(root, identifier, *, observed=None, receipts=None):
    ev.identifier(identifier)
    item = (observed if observed is not None else observations(root)).get(identifier)
    if item is None:
        raise ValueError("Observation is missing or expired")
    target = ev.path(root, "feedback/" + identifier + ".json")
    review = (
        ev.read(root, "feedback/" + identifier + ".json") if target.is_file() else None
    )
    signals = []
    for value in (receipts if receipts is not None else _use_events(root)):
        if value.get("observation_id") == identifier:
            signals.append(value)
    return {
        **item,
        "review": review,
        "review_sha256": (
            hashlib.sha256(target.read_bytes()).hexdigest() if review else None
        ),
        "signals": signals,
    }


def candidates(root):
    items = []
    observed = observations(root)
    receipts = _use_events(root)
    for identifier in observed:
        item = candidate(root, identifier, observed=observed, receipts=receipts)
        review = item["review"]
        item["status"] = "reviewed" if review else "pending"
        item["query"] = review["query"] if review else item.get("query")
        items.append(item)
    return {
        "preferences": preferences(root),
        "items": sorted(items, key=lambda v: str(v.get("at") or ""), reverse=True),
        "note": "Use is a signal; only confirmed feedback enters datasets. Missing feedback is unknown.",
    }


def _asset(root, slug):
    if not isinstance(slug, str) or not slug or "/" in slug or "\\" in slug:
        raise ValueError("Choose a Wiki slug")
    matches = [p for p in (root / "wiki").rglob("*.md") if p.stem == slug]
    if len(matches) != 1:
        raise ValueError("Wiki slug is missing or ambiguous: " + slug)
    relative = matches[0].relative_to(root).as_posix()
    item = workspace._text_file(root, relative, {".md"})
    return {
        "slug": slug,
        "source_path": relative,
        "source_sha256": item["sha256"],
        "text": item["text"],
    }


def review(root, payload):
    identifier = ev.identifier(payload.get("id"))
    if payload.get("confirm") is not True:
        raise ValueError("Explicit confirmation is required for evaluation labels")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("Provide a reviewed query")
    accepted, rejected, clear = [
        payload.get(k, []) for k in ("accept", "reject", "clear")
    ]
    if any(
        not isinstance(values, list) or any(not isinstance(v, str) for v in values)
        for values in (accepted, rejected, clear)
    ):
        raise ValueError("Accept/reject/clear must be slug lists")
    if sum(map(len, (accepted, rejected, clear))) > 100:
        raise ValueError("Review at most 100 decisions at a time")
    if set(accepted) & set(rejected) or (set(accepted) | set(rejected)) & set(clear):
        raise ValueError("Conflicting decisions")
    if rejected and not str(payload.get("reason") or "").strip():
        raise ValueError("A rejection needs a reason")
    with store._file_lock(ev.path(root, ".review-" + identifier + ".lock")):
        item = candidate(root, identifier)
        if (
            "expected_sha256" in payload
            and item["review_sha256"] != payload["expected_sha256"]
        ):
            raise ValueError("Review changed; reload first")
        digest = hashlib.sha256(query.strip().encode()).hexdigest()
        original = item.get("query_sha256")
        derived = not original or not digest.startswith(original)
        if derived and payload.get("derived_query") is not True:
            raise ValueError(
                "Query differs from observation; explicitly confirm a derived query"
            )
        old = item["review"] or {}
        decisions = dict(old.get("decisions", {}))
        if (
            old.get("query")
            and old["query"] != query.strip()
            and not set(decisions) <= set(accepted + rejected + clear)
        ):
            raise ValueError(
                "Changed query requires re-reviewing every existing decision"
            )
        observed = {h.get("slug") for h in item["hits"]}
        for decision, slugs in [("accepted", accepted), ("rejected", rejected)]:
            for slug in slugs:
                asset = _asset(root, slug)
                source = next((h for h in item["hits"] if h.get("slug") == slug), {})
                if (
                    source.get("source_sha256")
                    and source["source_sha256"] != asset["source_sha256"]
                ):
                    raise ValueError(
                        "Observed Wiki version changed; capture a fresh query"
                    )
                decisions[slug] = {k: v for k, v in asset.items() if k != "text"}
                decisions[slug].update(
                    decision=decision,
                    reason=str(payload.get("reason") or ""),
                    observed=slug in observed,
                )
        for slug in clear:
            decisions.pop(slug, None)
        value = {
            "id": identifier,
            "query": query.strip(),
            "derived_query": derived,
            "original_query_sha256": original,
            "decisions": decisions,
            "at": datetime.now(UTC).isoformat(),
            "event_id": uuid4().hex,
            "parent_sha256": item["review_sha256"],
            "confirmation_reported": True,
        }
        ev.write(root, "feedback-events/" + value["event_id"] + ".json", value)
        ev.write(root, "feedback/" + identifier + ".json", value)
    return candidate(root, identifier)


def export(root, payload):
    name = payload.get("name")
    kind = payload.get("kind", "recall")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 100
        or kind not in {"recall", "preference"}
    ):
        raise ValueError("Provide a dataset name and recall/preference kind")
    selected = payload.get("ids")
    rows = []
    skipped = []
    if selected is not None and (
        not isinstance(selected, list) or any(not isinstance(i, str) for i in selected)
    ):
        raise ValueError("Case IDs must be a list")
    for item in candidates(root)["items"]:
        if selected is not None and item["id"] not in selected:
            continue
        value = item["review"]
        if not value:
            continue
        decisions = value["decisions"]
        positive = []
        negative = []
        for slug, decision in decisions.items():
            asset = _asset(root, slug)
            if asset["source_sha256"] != decision["source_sha256"]:
                raise ValueError("Reviewed source changed; re-review " + slug)
            (positive if decision["decision"] == "accepted" else negative).append(asset)
        if not positive or (kind == "preference" and not negative):
            skipped.append(item["id"])
            continue
        provenance = {
            "observation_id": item["id"],
            "review_event": value["event_id"],
            "derived_query": value["derived_query"],
        }
        if kind == "recall":
            rows.append(
                {
                    "case_id": "review-" + item["id"],
                    "query": value["query"],
                    "relevant": [a["slug"] for a in positive],
                    "forbidden": [a["slug"] for a in negative],
                    "provenance": provenance,
                }
            )
        else:
            for chosen in positive:
                for rejected in negative:
                    rows.append(
                        {
                            "schema_version": "retrieval-preference/v1",
                            "prompt": value["query"],
                            "chosen": chosen,
                            "rejected": rejected,
                            "provenance": provenance,
                        }
                    )
    if not rows:
        raise ValueError(
            "No confirmed, version-current samples meet export requirements"
        )
    if kind == "recall":
        data = {
            "schema_version": "recall-case/v1",
            "dataset_id": name.strip(),
            "version": "1",
            "cases": rows,
        }
        result = ev.import_dataset(
            root,
            {
                "filename": "reviewed.yaml",
                "text": yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            },
        )
        result.update(case_count=len(rows), skipped=skipped)
        return result
    identifier = "preference-" + uuid4().hex[:16]
    relative = "exports/" + identifier + ".jsonl"
    store._atomic_write(
        ev.path(root, relative),
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
    )
    metadata = {
        "id": identifier,
        "title": name.strip(),
        "kind": "retrieval-preference",
        "pair_count": len(rows),
        "path": relative,
        "at": datetime.now(UTC).isoformat(),
        "skipped": skipped,
        "meaning": "Knowledge-selection preference pairs; not a claim of dialogue DPO readiness",
    }
    ev.write(root, "exports/" + identifier + ".json", metadata)
    return metadata
