"""Synthetic contracts: evaluator detects leaks without hiding engine failures."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from knowledge_studio.cli import app
from knowledge_studio.evaluation import compare_runs, load_dataset, run_evaluation
from knowledge_studio.evaluation_dataset import validate_v2

FIXTURE = Path(__file__).parent / "fixtures/evaluation-v2/dataset.yaml"


@pytest.fixture
def data():
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def write_dataset(tmp_path, data):
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def mock_run(tmp_path, monkeypatch, data, slugs, name="run.json"):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    monkeypatch.setattr("knowledge_studio.evaluation.recall_knowledge",
                        lambda **kwargs: [{"slug": s} for s in slugs.get(kwargs["query"], [])])
    return run_evaluation(write_dataset(tmp_path, data), tmp_path / name, search_backend="native")


@pytest.mark.parametrize("defect", [
    "empty_answer", "nonempty_no_answer", "missing_provenance", "naive_time", "bad_time",
    "unknown_slug", "overlap", "wrong_user_gold", "future_gold", "wrong_version_gold",
    "duplicate_case", "duplicate_asset", "unknown_version", "unknown_field",
    "source_split", "user_split", "negative_source_split",
])
def test_invalid_v2_gold_rejected(tmp_path, data, defect):
    case = data["cases"][0]
    if defect == "empty_answer":
        case["relevant"] = []
    elif defect == "nonempty_no_answer":
        data["cases"][1]["relevant"] = ["alpha"]
    elif defect == "missing_provenance":
        del data["provenance"]
    elif defect == "naive_time":
        case["as_of"] = "2026-06-01T00:00:00"
    elif defect == "bad_time":
        data["assets"]["alpha"]["available_at"] = "nonsense"
    elif defect == "unknown_slug":
        case["forbidden"].append("missing")
    elif defect == "overlap":
        case["forbidden"].append("alpha")
    elif defect == "wrong_user_gold":
        data["assets"]["alpha"]["user_scope"] = "bob"
    elif defect == "future_gold":
        case["as_of"] = "2020-01-01T00:00:00Z"
    elif defect == "wrong_version_gold":
        case["expected_versions"]["guide"] = "1"
    elif defect == "duplicate_case":
        data["cases"].append(deepcopy(case))
    elif defect == "duplicate_asset":
        data["assets"]["alias"] = deepcopy(data["assets"]["alpha"])
    elif defect == "unknown_version":
        case["expected_versions"]["missing"] = "1"
    elif defect == "unknown_field":
        case["user_scpoe"] = "alice"
    else:
        other = data["cases"][1]
        other["split"] = "train"
        if defect != "user_split":
            other["user_scope"] = "charlie"
        if defect != "source_split":
            other["source_group"] = "unrelated"
        if defect == "negative_source_split":
            other["forbidden"] = ["old"]
    with pytest.raises(ValueError):
        load_dataset(write_dataset(tmp_path, data))


def test_v1_still_rejects_empty_gold(tmp_path):
    data = {"schema_version": "recall-case/v1", "dataset_id": "old", "version": "1",
            "cases": [{"case_id": "empty", "query": "none", "relevant": []}]}
    with pytest.raises(ValueError, match="relevant"):
        load_dataset(write_dataset(tmp_path, data))


def test_v2_reports_all_boundary_failures_and_separates_no_answer(tmp_path, monkeypatch, data):
    result = mock_run(tmp_path, monkeypatch, data, {
        "boundarytoken": ["alpha", "old", "future", "bob"],
    })
    assert result["schema_version"] == "recall-eval-run/v2"
    assert result["metrics"]["recall_at_1"] == 1  # no-answer excluded from ranking denominator
    assert result["metrics"]["abstention_correct"] == 1
    for metric in ("scope_leakage", "future_leakage", "version_leakage", "stale_leakage"):
        assert result["metrics"][metric] == 0.5
    assert result["metrics"]["answerable_count"] == result["metrics"]["unanswerable_count"] == 1
    assert result["cases"][0]["retrieved"] == ["alpha", "old", "future", "bob"]
    assert result["cases"][1]["metrics"]["mrr"] is None
    assert result["manifest"]["evaluation_mode"] == "wiki-label-audit/v1"


def test_unanswerable_false_positive_and_rank_six_leak_are_not_hidden(tmp_path, monkeypatch, data):
    result = mock_run(tmp_path, monkeypatch, data, {
        "boundarytoken": ["alpha"] * 5 + ["bob"], "zxqnonexistenttoken": ["alpha"],
    })
    assert result["metrics"]["abstention_correct"] == 0
    assert result["cases"][0]["metrics"]["scope_leakage"] == 1
    assert result["cases"][0]["metrics"]["stale_leakage"] == 1
    assert result["cases"][0]["metrics"]["ndcg_at_5"] == 1  # duplicate hits get no extra credit


@pytest.mark.parametrize("keep,missing", [(0, "abstention_correct"), (1, "mrr")])
def test_absent_cohort_stays_null_in_run_and_comparison(tmp_path, monkeypatch, data, keep, missing):
    data["cases"] = [data["cases"][keep]]
    result = mock_run(tmp_path, monkeypatch, data, {}, "first.json")
    mock_run(tmp_path, monkeypatch, data, {}, "second.json")
    assert result["metrics"][missing] is None
    compared = compare_runs(tmp_path / "first.json", tmp_path / "second.json")
    assert compared["schema_version"] == "recall-eval-comparison/v2"
    assert compared["deltas"][missing] is None
    assert missing in compared["comparability"]["unmeasured_metrics"]


def test_unknown_hit_fails_without_overwriting_existing_evidence(tmp_path, monkeypatch, data):
    (tmp_path / "run.json").write_text("existing evidence", encoding="utf-8")
    with pytest.raises(ValueError, match="Unlabelled"):
        mock_run(tmp_path, monkeypatch, data, {"boundarytoken": ["unlabelled"]})
    assert (tmp_path / "run.json").read_text() == "existing evidence"


def test_timezone_equivalence_and_valid_separate_splits(data):
    data["cases"][0]["as_of"] = "2026-01-01T08:00:00+08:00"
    other = data["cases"][1]
    other.update(user_scope="charlie", split="train", source_group="different")
    validate_v2(data)


def test_asset_versions_cannot_evade_split_groups(data):
    other = data["cases"][1]
    other.update(user_scope="charlie", source_group="other", split="train", forbidden=["old"])
    data["cases"][0]["forbidden"] = []
    data["assets"]["old"]["source_group"] = "other"
    with pytest.raises(ValueError, match="Cross-split"):
        validate_v2(data)


def test_mixed_dataset_requires_explicit_split_and_cli_selects_only_that_split(tmp_path, monkeypatch, data):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    data["cases"][1].update(user_scope="charlie", source_group="other", split="train")
    queries = []

    def capture(**kwargs):
        queries.append(kwargs["query"])
        return []

    monkeypatch.setattr("knowledge_studio.evaluation.recall_knowledge", capture)
    dataset = write_dataset(tmp_path, data)
    with pytest.raises(ValueError, match="explicit --split"):
        run_evaluation(dataset, tmp_path / "run.json")
    assert not queries and not (tmp_path / "run.json").exists()
    result = CliRunner().invoke(app, ["eval", "recall", str(dataset), "--output", str(tmp_path / "run.json"), "--split", "train"])
    assert result.exit_code == 0, result.output
    run = json.loads((tmp_path / "run.json").read_text())
    assert queries == ["zxqnonexistenttoken"]
    assert run["manifest"]["split"] == "train" and run["metrics"]["case_count"] == 1
    with pytest.raises(ValueError, match="no cases"):
        run_evaluation(dataset, tmp_path / "missing.json", split="validation")


@pytest.mark.parametrize("defect", ["mixed_schema", "case_context", "cohort_count", "fake_zero", "missing_context"])
def test_comparison_rejects_invalid_v2_runs(tmp_path, monkeypatch, data, defect):
    data["cases"] = [data["cases"][1]]
    first = mock_run(tmp_path, monkeypatch, data, {}, "first.json")
    second = deepcopy(first)
    if defect == "mixed_schema":
        second["schema_version"] = "recall-eval-run/v1"
    elif defect == "case_context":
        second["cases"][0]["as_of"] = "2028-01-01T00:00:00Z"
    elif defect == "cohort_count":
        second["metrics"]["answerable_count"] = 1
    elif defect == "fake_zero":
        second["metrics"]["mrr"] = 0
    else:
        del second["manifest"]["comparison_context"]
    (tmp_path / "second.json").write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError):
        compare_runs(tmp_path / "first.json", tmp_path / "second.json")


def test_actual_cli_v2_retains_engine_leaks_and_does_not_modify_kb(tmp_path, monkeypatch, data):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    wiki = tmp_path / "wiki/computing/concepts"
    wiki.mkdir(parents=True)
    for slug in data["assets"]:
        (wiki / f"{slug}.md").write_text(
            "---\ntitle: Boundary\ntype: concept\narea: computing\nstatus: active\n"
            "importance: 0.8\nconfidence: 0.8\ncreated: '2026-01-01T00:00:00Z'\n"
            "pinned: true\ntags: boundarytoken\n---\nboundarytoken\n", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in wiki.iterdir()}
    dataset = write_dataset(tmp_path, data)
    result = CliRunner().invoke(app, ["eval", "recall", str(dataset), "--output", str(tmp_path / "run.json"), "--search-backend", "native"])
    assert result.exit_code == 0, result.output
    run = json.loads((tmp_path / "run.json").read_text())
    assert set(run["cases"][0]["retrieved"]) == set(data["assets"])
    assert run["metrics"]["scope_leakage"] == run["metrics"]["future_leakage"] == 0.5
    assert run["metrics"]["abstention_correct"] == 1
    assert {p.name: p.read_bytes() for p in wiki.iterdir()} == before


def test_v2_schema_packaged_asset_fallback(tmp_path, monkeypatch, data):
    import knowledge_studio.evaluation_dataset as module
    package = tmp_path / "installed/knowledge_studio"
    destination = package / "_assets/_meta"
    destination.mkdir(parents=True)
    schema = Path(module.__file__).resolve().parents[2] / "assets/_meta/recall-case-v2.schema.json"
    (destination / schema.name).write_bytes(schema.read_bytes())
    monkeypatch.setattr(module, "__file__", str(package / "evaluation_dataset.py"))
    validate_v2(data)
