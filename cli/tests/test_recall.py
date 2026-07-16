"""Tests for the 6-factor recall engine."""
import json
import yaml
from pathlib import Path

import pytest

from knowledge_studio.store import _atomic_write


@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    """Create a temporary knowledge base with wiki pages."""
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))

    wiki = tmp_path / "wiki" / "computing" / "concepts"
    wiki.mkdir(parents=True)

    pages = [
        {
            "slug": "git-branching",
            "title": "Git Branching Strategy",
            "type": "concept",
            "area": "computing",
            "status": "active",
            "importance": 0.8,
            "confidence": 0.9,
            "created": "2026-01-15T00:00:00+00:00",
            "tags": "git, version-control",
            "body": "Git branching strategy for managing feature development.",
        },
        {
            "slug": "docker-deployment",
            "title": "Docker Container Deployment",
            "type": "strategy",
            "area": "computing",
            "status": "active",
            "importance": 0.7,
            "confidence": 0.8,
            "created": "2026-02-01T00:00:00+00:00",
            "tags": "docker, deployment",
            "body": "Deploy containers using docker-compose for production.",
        },
        {
            "slug": "no-tests",
            "title": "Deploying Without Tests",
            "type": "anti-pattern",
            "area": "computing",
            "status": "active",
            "importance": 0.9,
            "confidence": 0.95,
            "created": "2026-03-01T00:00:00+00:00",
            "tags": "testing, deployment",
            "body": "Deploying to production without running tests leads to failures.",
            "review": {"decision_correct": False, "outcome": "failure"},
        },
    ]

    for page in pages:
        fm = {k: v for k, v in page.items() if k != "body" and k != "slug"}
        fm["pinned"] = False
        fm["archived"] = False
        fm["access_count"] = 0
        fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
        content = f"---\n{fm_str}---\n\n{page['body']}"
        _atomic_write(wiki / f"{page['slug']}.md", content)

    return tmp_path


def test_tokenize():
    from knowledge_studio.recall import _tokenize
    tokens = _tokenize("git branch strategy")
    assert isinstance(tokens, set)
    assert len(tokens) > 0


def test_recall_knowledge_returns_results(kb_root):
    from knowledge_studio.recall import recall_knowledge
    results = recall_knowledge("git branching", limit=5)
    assert len(results) > 0
    assert any(r["slug"] == "git-branching" for r in results)


def test_recall_knowledge_anti_pattern_boosted(kb_root):
    from knowledge_studio.recall import recall_knowledge
    results = recall_knowledge("deployment", limit=5)
    slugs = [r["slug"] for r in results]
    if "no-tests" in slugs and "docker-deployment" in slugs:
        assert slugs.index("no-tests") <= slugs.index("docker-deployment")


def test_recall_knowledge_no_results(kb_root):
    from knowledge_studio.recall import recall_knowledge
    results = recall_knowledge("nonexistent_topic_xyz123", limit=5)
    assert len(results) == 0


def test_recall_combined(kb_root):
    from knowledge_studio.recall import recall
    result = recall("git", limit=5)
    assert "episodic" in result
    assert "knowledge" in result
    assert isinstance(result["episodic"], list)
    assert isinstance(result["knowledge"], list)


def test_recall_multimodal_bundle_uses_content_not_sidecars(kb_root):
    from knowledge_studio.recall import recall_episodic

    bundle = kb_root / "raw" / "2026" / "07" / "16" / "videos" / "java-video"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(
        json.dumps({"schema_version": "raw-multimodal/v0.1", "processing_status": "partial"}),
        encoding="utf-8",
    )
    (bundle / "raw.md").write_text("索引说明 三元运算符", encoding="utf-8")
    (bundle / "content.md").write_text(
        "# Raw提取正文\n\n00:19–00:21 使用三元运算符。", encoding="utf-8"
    )
    (bundle / "transcript.md").write_text("三元运算符逐字稿", encoding="utf-8")
    (bundle / "evidence.jsonl").write_text(
        json.dumps(
            {
                "kind": "speech",
                "text": "三元运算符",
                "method": "test",
                "locator": {"start": 19.8, "end": 21.0},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = recall_episodic("三元运算符", limit=10)

    bundle_results = [item for item in results if "java-video" in item["source_path"]]
    assert len(bundle_results) == 1
    assert bundle_results[0]["source_path"].endswith("content.md")
    assert "三元运算符" in bundle_results[0]["snippet"]


def test_recall_multimodal_ocr_fallback_keeps_locator(kb_root):
    from knowledge_studio.recall import recall_episodic

    bundle = kb_root / "raw" / "2026" / "07" / "16" / "misc" / "image-only"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(
        json.dumps({"schema_version": "raw-multimodal/v0.1", "processing_status": "partial"}),
        encoding="utf-8",
    )
    (bundle / "content.md").write_text("# 图片Raw\n\nOCR正文仅保留高层索引。", encoding="utf-8")
    locator = {"asset": "assets/original/screen.png", "bbox": [1, 2, 30, 40]}
    (bundle / "evidence.jsonl").write_text(
        json.dumps(
            {
                "id": "rapidocr-text-000001",
                "kind": "ocr",
                "text": "知识复利基础设施",
                "method": "rapidocr",
                "locator": locator,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    results = recall_episodic("知识复利基础设施", limit=5)

    assert len(results) == 1
    assert results[0]["type"] == "ocr_evidence"
    assert results[0]["locator"] == locator
    assert results[0]["evidence_id"] == "rapidocr-text-000001"
