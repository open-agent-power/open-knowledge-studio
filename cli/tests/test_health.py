"""Tests for the health check module."""
import yaml
import pytest

from knowledge_studio.store import _atomic_write


@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    wiki = tmp_path / "wiki" / "computing" / "concepts"
    wiki.mkdir(parents=True)
    return tmp_path


def _write_page(path, meta_dict, body="Content"):
    fm = yaml.dump(meta_dict, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _atomic_write(path, f"---\n{fm}---\n\n{body}")


def test_health_check_valid_page(kb_root):
    from knowledge_studio.health import run_health_check
    wiki = kb_root / "wiki" / "computing" / "concepts"
    _write_page(wiki / "valid.md", {
        "title": "Valid Page", "type": "concept", "area": "computing",
        "status": "active", "tags": "testing",
    })
    result = run_health_check()
    assert result["summary"]["total_wiki_pages"] == 1
    assert result["summary"]["errors"] == 0


def test_health_check_missing_frontmatter(kb_root):
    from knowledge_studio.health import run_health_check
    wiki = kb_root / "wiki" / "computing" / "concepts"
    (wiki / "no-fm.md").write_text("No frontmatter here.", encoding="utf-8")
    result = run_health_check()
    assert any("missing frontmatter" in w for w in result["warnings"])


def test_health_check_missing_fields(kb_root):
    from knowledge_studio.health import run_health_check
    wiki = kb_root / "wiki" / "computing" / "concepts"
    _write_page(wiki / "incomplete.md", {"title": "Incomplete"})
    result = run_health_check()
    assert any("missing 'type'" in w for w in result["warnings"])


def test_health_check_orphan_page(kb_root):
    from knowledge_studio.health import run_health_check
    wiki = kb_root / "wiki" / "computing" / "concepts"
    _write_page(wiki / "orphan.md", {
        "title": "Orphan", "type": "concept", "area": "computing", "status": "active",
    })
    result = run_health_check()
    assert result["summary"]["orphan"] >= 1


def test_health_check_coverage(kb_root):
    from knowledge_studio.health import run_health_check
    wiki = kb_root / "wiki" / "computing" / "concepts"
    _write_page(wiki / "good.md", {
        "title": "Good", "type": "concept", "area": "computing",
        "status": "active", "tags": "test",
    })
    _write_page(wiki / "dropped.md", {
        "title": "Dropped", "type": "concept", "area": "computing",
        "status": "dropped", "tags": "test",
    })
    result = run_health_check()
    assert result["summary"]["total_wiki_pages"] == 2
    assert result["summary"]["dropped"] == 1
    assert result["summary"]["coverage_pct"] == 50.0
