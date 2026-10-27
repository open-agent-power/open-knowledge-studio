"""Tests for deterministic, read-only recall evaluation."""
import json
from copy import deepcopy

import pytest
import yaml

from knowledge_studio.evaluation import compare_runs, load_dataset, run_evaluation
from knowledge_studio.store import _atomic_write


def _comparison_pair(tmp_path):
    run = {
        "schema_version": "recall-eval-run/v1",
        "manifest": {
            "dataset_sha256": "a" * 64, "limit": 5,
            "kb_snapshot_before": "b" * 64, "kb_snapshot_after": "b" * 64,
            "comparison_context": {
                "schema_version": "recall-eval-context/v1",
                "settings_sha256": "c" * 64, "parameters_sha256": "d" * 64,
                "code_sha256": "e" * 64, "backend": "native",
            },
        },
        "metrics": {
            "case_count": 1, "mrr": 0.5, "recall_at_1": 0.0,
            "recall_at_3": 1.0, "recall_at_5": 1.0, "ndcg_at_5": 0.63,
            "no_result": 0.0, "stale_leakage": 0.0,
            "latency_p50_ms": 2.0, "latency_p95_ms": 2.0,
        },
        "cases": [{"case_id": "c1"}],
    }
    return run, deepcopy(run)


def _compare_pair(tmp_path, left, right, **kwargs):
    first, second = tmp_path / "left.json", tmp_path / "right.json"
    first.write_text(json.dumps(left), encoding="utf-8")
    second.write_text(json.dumps(right), encoding="utf-8")
    return compare_runs(first, second, **kwargs)


def test_compare_rejects_changed_or_mutated_kb(tmp_path):
    left, right = _comparison_pair(tmp_path)
    right["manifest"]["kb_snapshot_before"] = "f" * 64
    right["manifest"]["kb_snapshot_after"] = "f" * 64
    with pytest.raises(ValueError, match="knowledge-base snapshots"):
        _compare_pair(tmp_path, left, right)
    right["manifest"]["kb_snapshot_after"] = "b" * 64
    with pytest.raises(ValueError, match="mutated"):
        _compare_pair(tmp_path, left, right)


@pytest.mark.parametrize("variable,field,value", [
    ("backend", "backend", "fts5"), ("code", "code_sha256", "f" * 64),
])
def test_comparison_requires_declared_experiment_variable(tmp_path, variable, field, value):
    left, right = _comparison_pair(tmp_path)
    right["manifest"]["comparison_context"][field] = value
    right["metrics"]["mrr"] = 0.75
    with pytest.raises(ValueError, match="--vary"):
        _compare_pair(tmp_path, left, right)
    result = _compare_pair(tmp_path, left, right, vary=[variable])
    assert result["deltas"]["mrr"] == 0.25
    assert result["comparability"]["status"] == "matched"
    assert result["comparability"]["variables"][variable] == {
        "baseline": left["manifest"]["comparison_context"][field], "candidate": value,
    }


@pytest.mark.parametrize("field", ["settings_sha256", "parameters_sha256"])
def test_config_changes_cannot_be_declared_as_code_changes(tmp_path, field):
    left, right = _comparison_pair(tmp_path)
    right["manifest"]["comparison_context"][field] = "f" * 64
    with pytest.raises(ValueError, match=field):
        _compare_pair(tmp_path, left, right, vary=["code"])


@pytest.mark.parametrize("both_legacy", [True, False])
def test_legacy_runs_report_missing_comparison_evidence(tmp_path, both_legacy):
    left, right = _comparison_pair(tmp_path)
    del left["manifest"]["comparison_context"]
    if both_legacy:
        del right["manifest"]["comparison_context"]
    result = _compare_pair(tmp_path, left, right)
    assert result["comparability"]["status"] == "limited"
    assert result["comparability"]["warnings"]
    assert result["deltas"]["mrr"] == 0


@pytest.mark.parametrize("defect", ["missing_kb", "case_id", "duplicate_case", "count", "metric_keys", "nan", "bool", "context"])
def test_invalid_evidence_never_overwrites_comparison(tmp_path, defect):
    left, right = _comparison_pair(tmp_path)
    if defect == "missing_kb":
        del right["manifest"]["kb_snapshot_before"]
    elif defect == "case_id":
        right["cases"][0]["case_id"] = "other"
    elif defect == "duplicate_case":
        right["cases"] *= 2
        right["metrics"]["case_count"] = 2
    elif defect == "count":
        right["metrics"]["case_count"] = 2
    elif defect == "metric_keys":
        right["metrics"]["extra"] = 1
    elif defect == "context":
        del right["manifest"]["comparison_context"]["code_sha256"]
    else:
        right["metrics"]["mrr"] = float("nan") if defect == "nan" else True
    output = tmp_path / "comparison.json"
    output.write_text("keep existing evidence", encoding="utf-8")
    with pytest.raises(ValueError):
        _compare_pair(tmp_path, left, right, output_path=output)
    assert output.read_text() == "keep existing evidence"


def test_comparison_rejects_unknown_variables(tmp_path):
    left, right = _comparison_pair(tmp_path)
    with pytest.raises(ValueError, match="Unknown experiment variable"):
        _compare_pair(tmp_path, left, right, vary=["knowledge_base"])


def test_two_incomplete_metric_sets_are_rejected(tmp_path):
    left, right = _comparison_pair(tmp_path)
    for run in (left, right):
        del run["metrics"]["recall_at_1"]
    with pytest.raises(ValueError, match="complete.*metric set"):
        _compare_pair(tmp_path, left, right)


@pytest.mark.parametrize("field,value", [
    ("mrr", 10**1000), ("mrr", -0.1), ("mrr", 1.1), ("latency_p50_ms", -1),
])
def test_invalid_metric_values_are_rejected(tmp_path, field, value):
    left, right = _comparison_pair(tmp_path)
    right["metrics"][field] = value
    with pytest.raises(ValueError, match="metric"):
        _compare_pair(tmp_path, left, right)


def test_comparison_cannot_overwrite_input_run(tmp_path):
    left, right = _comparison_pair(tmp_path)
    with pytest.raises(ValueError, match="overwrite"):
        _compare_pair(tmp_path, left, right, output_path=tmp_path / "left.json")
    assert json.loads((tmp_path / "left.json").read_text()) == left


def test_cli_comparison_requires_explicit_backend_experiment(tmp_path):
    from typer.testing import CliRunner
    from knowledge_studio.cli import app

    left, right = _comparison_pair(tmp_path)
    right["manifest"]["comparison_context"]["backend"] = "fts5"
    _compare_pair(tmp_path, left, right, vary=["backend"])
    command = ["eval", "compare", str(tmp_path / "left.json"), str(tmp_path / "right.json")]
    runner = CliRunner()
    rejected = runner.invoke(app, command)
    assert rejected.exit_code == 1
    assert "--vary backend" in rejected.output
    accepted = runner.invoke(app, command + ["--vary", "backend"])
    assert accepted.exit_code == 0, accepted.output
    result = json.loads(accepted.output)
    assert result["comparability"]["variables"]["backend"] == {"baseline": "native", "candidate": "fts5"}


@pytest.mark.parametrize("change", ["settings", "environment"])
def test_actual_runs_capture_config_changes(tmp_path, monkeypatch, change):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    monkeypatch.setattr("knowledge_studio.evaluation.recall_knowledge", lambda **kwargs: [])
    dataset = _dataset(tmp_path / "dataset.yaml")
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    run_evaluation(dataset, first, search_backend="native")
    if change == "settings":
        (tmp_path / "settings").mkdir()
        (tmp_path / "settings" / "recall.yaml").write_text("recall_floor: 0.99\n", encoding="utf-8")
    else:
        monkeypatch.setenv("OKS_RECALL_FLOOR", "0.99")
    run_evaluation(dataset, second, search_backend="native")
    with pytest.raises(ValueError, match="different .*sha256"):
        compare_runs(first, second)


def test_evaluation_detects_inputs_changing_during_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    dataset = _dataset(tmp_path / "dataset.yaml")
    output = tmp_path / "run.json"

    def change_dataset(**kwargs):
        dataset.write_text(dataset.read_text() + "\n# changed", encoding="utf-8")
        return []

    monkeypatch.setattr("knowledge_studio.evaluation.recall_knowledge", change_dataset)
    with pytest.raises(RuntimeError, match="changed during"):
        run_evaluation(dataset, output)
    assert not output.exists()


@pytest.mark.parametrize("output", ["dataset.yaml", "wiki/run.json", "settings/run.json"])
def test_evaluation_cannot_overwrite_inputs(tmp_path, monkeypatch, output):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    dataset = _dataset(tmp_path / "dataset.yaml")
    before = dataset.read_bytes()
    with pytest.raises(ValueError, match="output"):
        run_evaluation(dataset, tmp_path / output)
    assert dataset.read_bytes() == before


def _page(path, title, body, *, page_type="concept", tags="recall"):
    meta = {
        "title": title, "type": page_type, "area": "computing",
        "status": "active", "importance": 0.8, "confidence": 0.8,
        "created": "2026-07-27T00:00:00Z", "pinned": False,
        "archived": False, "tags": tags,
    }
    fm = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    _atomic_write(path, f"---\n{fm}---\n\n{body}")


def _dataset(path):
    data = {
        "schema_version": "recall-case/v1", "dataset_id": "unit",
        "version": "1", "cases": [{
            "case_id": "c1", "query": "alpha recall", "goal": "none",
            "relevant": ["alpha"], "forbidden": ["stale"],
        }],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_evaluation_metrics_manifest_and_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    wiki = tmp_path / "wiki" / "computing" / "concepts"
    wiki.mkdir(parents=True)
    _page(wiki / "alpha.md", "Alpha Recall", "alpha recall is the expected page")
    _page(wiki / "stale.md", "Unrelated", "not a matching document", tags="other")
    dataset = _dataset(tmp_path / "dataset.yaml")
    before = (wiki / "alpha.md").read_bytes()

    result = run_evaluation(dataset, tmp_path / "runs" / "one.json")

    assert result["metrics"]["recall_at_1"] == 1.0
    assert result["metrics"]["mrr"] == 1.0
    assert result["metrics"]["stale_leakage"] == 0.0
    assert result["manifest"]["dataset_sha256"]
    assert result["manifest"]["kb_snapshot_before"] == result["manifest"]["kb_snapshot_after"]
    assert "code_commit" not in result["manifest"]
    assert "kb_commit" in result["manifest"] and "code_version" in result["manifest"]
    assert (wiki / "alpha.md").read_bytes() == before
    assert not (tmp_path / ".oks").exists()


def test_limit_below_five_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    dataset = _dataset(tmp_path / "dataset.yaml")
    try:
        run_evaluation(dataset, tmp_path / "runs" / "small.json", limit=3)
    except ValueError as exc:
        assert "limit must be >= 5" in str(exc)
    else:
        raise AssertionError("limit below 5 should be rejected")


def test_compare_rejects_different_limits(tmp_path):
    left = {"schema_version": "recall-eval-run/v1", "manifest": {"dataset_sha256": "a", "limit": 5}, "metrics": {}}
    right = {"schema_version": "recall-eval-run/v1", "manifest": {"dataset_sha256": "a", "limit": 10}, "metrics": {}}
    (tmp_path / "left.json").write_text(json.dumps(left), encoding="utf-8")
    (tmp_path / "right.json").write_text(json.dumps(right), encoding="utf-8")
    try:
        compare_runs(tmp_path / "left.json", tmp_path / "right.json")
    except ValueError as exc:
        assert "different limits" in str(exc)
    else:
        raise AssertionError("comparison should reject mismatched limits")


def test_dataset_validation_and_run_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    wiki = tmp_path / "wiki" / "computing" / "concepts"
    wiki.mkdir(parents=True)
    _page(wiki / "alpha.md", "Alpha Recall", "alpha recall")
    dataset = _dataset(tmp_path / "dataset.yaml")
    assert load_dataset(dataset)["dataset_id"] == "unit"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    run_evaluation(dataset, first)
    run_evaluation(dataset, second)
    comparison = compare_runs(first, second, tmp_path / "comparison.json")
    assert comparison["deltas"]["recall_at_5"] == 0.0
    assert comparison["goal_lift"]["recall_at_5"] == 0.0
    assert json.loads((tmp_path / "comparison.json").read_text())["schema_version"] == "recall-eval-comparison/v1"


def test_compare_rejects_different_dataset_snapshots(tmp_path):
    left = {"schema_version": "recall-eval-run/v1", "manifest": {"dataset_sha256": "a"}, "metrics": {}}
    right = {"schema_version": "recall-eval-run/v1", "manifest": {"dataset_sha256": "b"}, "metrics": {}}
    (tmp_path / "left.json").write_text(json.dumps(left), encoding="utf-8")
    (tmp_path / "right.json").write_text(json.dumps(right), encoding="utf-8")
    try:
        compare_runs(tmp_path / "left.json", tmp_path / "right.json")
    except ValueError as exc:
        assert "different dataset" in str(exc)
    else:
        raise AssertionError("comparison should reject different datasets")
