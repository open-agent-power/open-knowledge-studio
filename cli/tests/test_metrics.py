"""Focused tests for metrics trust semantics (unknown != rejected)."""

import json
from datetime import UTC, datetime


def test_unknown_injection_is_not_counted_as_rejected(tmp_path, monkeypatch):
    from knowledge_studio.cli import _generate_metrics_html

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    (tmp_path / "wiki").mkdir()
    records = tmp_path / "records"
    records.mkdir()
    injects = [
        {"slugs": ["adopted-page"], "rels": [0.91], "used": True},
        {"slugs": ["unknown-page"], "rels": [0.12]},
    ]
    (records / "inject.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in injects) + "\n",
        encoding="utf-8",
    )
    (records / "trace-feedback.jsonl").write_text(
        json.dumps({"run_id": "unlinked-run", "outcome": "rejected", "comment": "bad"}) + "\n",
        encoding="utf-8",
    )

    html = _generate_metrics_html(tmp_path)

    assert "adopted <b>1</b>" in html
    assert "rejected <b>N/A</b>" in html
    assert "unknown <b>1</b>" in html
    assert "观测采纳率 <b>50%</b>" in html
    assert "<td>unknown-page</td><td>1</td><td>0</td><td>—</td><td>1</td>" in html
    assert "rejected rel 中位数</td><td>不可用</td>" in html
    assert "unknown rel 中位数</td><td>0.12</td>" in html


def test_review_coverage_uses_human_reviewed_at_not_legacy_review():
    from knowledge_studio.metrics import _compute_credibility, _compute_value

    pages = [
        {"human_reviewed_at": "2026-08-15T00:00:00+00:00"},
        {"review": {"outcome": "success", "decision_correct": True}},
    ]

    value = _compute_value(pages)
    credibility = _compute_credibility(
        pages,
        datetime(2026, 5, 17, tzinfo=UTC),
    )

    assert value["wiki_with_review"] == 1
    assert credibility["review_coverage"] == 0.5
