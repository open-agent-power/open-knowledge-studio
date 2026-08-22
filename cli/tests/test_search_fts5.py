"""Regression tests for the persistent FTS5 backend."""


def test_fts5_creates_missing_state_directory_before_connecting(tmp_path):
    from knowledge_studio.search.fts5 import FTS5Backend

    db_path = tmp_path / ".oks" / "fts5.db"
    assert not db_path.parent.exists()

    backend = FTS5Backend(root=str(tmp_path))
    try:
        backend.index([{
            "slug": "git-branching",
            "title": "Git Branching",
            "body": "Git branches keep work isolated.",
            "tags": "git",
        }])
        hits = backend.search("git", limit=5)
    finally:
        backend._conn.close()

    assert db_path.is_file()
    assert any(hit.slug == "git-branching" for hit in hits)
