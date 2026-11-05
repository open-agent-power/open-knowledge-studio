"""Regression tests for the persistent FTS5 backend."""

import pytest


@pytest.fixture
def backend(tmp_path):
    from knowledge_studio.search.fts5 import FTS5Backend

    instance = FTS5Backend(root=str(tmp_path))
    if not instance._use_fts5:
        instance.close()
        pytest.skip("SQLite has no FTS5 support")
    yield instance
    instance.close()


def _page(slug, **metadata):
    return {
        "slug": slug, "title": "Quasar ledger", "body": "quasar ledger policy",
        "area": "computing", "type": "concept", **metadata,
    }


def test_fts5_filters_state_before_limit_and_preserves_bm25(backend):
    pages = [
        _page("dropped", status="dropped"),
        _page("superseded", status="superseded"),
        _page("archived", status="active", archived=True),
        _page("active", status="active"),
        _page("provisional", status="provisional"),
        _page("stale", status="stale"),
        _page("legacy"),
        _page("mixed-case-dropped", status=" DROPPED "),
        _page("string-false-archive", status="active", archived="false"),
    ]
    backend.index(pages)
    unfiltered = dict(backend._conn.execute(
        "SELECT slug, -bm25(wiki_fts, 0, 0, 5, 1, 3, 0.5) "
        "FROM wiki_fts WHERE wiki_fts MATCH 'quasar'"
    ))
    hits = backend.search("quasar", limit=5)
    assert {h.slug for h in hits} == {"active", "provisional", "stale", "legacy", "string-false-archive"}
    assert all(h.score == pytest.approx(unfiltered[h.slug]) for h in hits)


def test_fts5_rank_mapping_keeps_custom_bm25_weights(tmp_path):
    from knowledge_studio.search.fts5 import FTS5Backend

    backend = FTS5Backend(root=str(tmp_path), weights={"title": 2.5, "body": 4.0})
    if not backend._use_fts5:
        backend.close()
        pytest.skip("SQLite has no FTS5 support")
    try:
        backend.index([
            _page("title-match", title="Quasar", body="unrelated"),
            _page("body-match", title="Unrelated", body="quasar ledger policy"),
        ])
        expected = backend._conn.execute(
            "SELECT slug, -bm25(wiki_fts, 0, 0, 2.5, 4.0, 3, 0.5) "
            "FROM wiki_fts WHERE wiki_fts MATCH 'quasar' ORDER BY 2 DESC"
        ).fetchall()
        hits = backend.search("quasar", limit=2)
        assert [h.slug for h in hits] == [row[0] for row in expected]
        assert [h.score for h in hits] == pytest.approx([row[1] for row in expected])
    finally:
        backend.close()


def test_fts5_distinct_page_limit_and_filters_do_not_lose_tail_candidates(backend):
    backend.index([
        _page("many-nodes", body="\n".join(
            f"## Quasar {i}\nquasar quasar quasar" for i in range(150)
        )),
        _page("tail", title="Tail policy", body="quasar", area="science", type="strategy"),
    ])
    assert {h.slug for h in backend.search("quasar", limit=2)} == {"many-nodes", "tail"}
    assert [h.slug for h in backend.search("quasar", limit=1, scope=" SCIENCE ")] == ["tail"]
    assert [h.slug for h in backend.search("quasar", limit=1, type_filter=" Strategy ")] == ["tail"]


def test_fts5_metadata_only_update_does_not_rewrite_text_index(backend):
    page = _page("changing", status="active")
    backend.index([page])
    before = backend._conn.execute("SELECT rowid, * FROM wiki_fts").fetchall()
    statements = []
    backend._conn.set_trace_callback(statements.append)
    backend.index([{**page, "status": "dropped", "area": "science", "type": "strategy"}])
    assert backend.search("quasar") == []
    assert not any(sql.startswith(("DELETE FROM wiki_fts", "INSERT INTO wiki_fts")) for sql in statements)
    assert backend._conn.execute("SELECT rowid, * FROM wiki_fts").fetchall() == before
    backend.index([{**page, "status": "provisional", "area": "science", "type": "strategy"}])
    assert [h.slug for h in backend.search("quasar", scope="science", type_filter="strategy")] == ["changing"]


def test_fts5_node_v2_metadata_migration_preserves_text_rows(tmp_path):
    from knowledge_studio.search.fts5 import FTS5Backend

    original = FTS5Backend(root=str(tmp_path))
    if not original._use_fts5:
        original.close()
        pytest.skip("SQLite has no FTS5 support")
    page = _page("legacy", status="dropped")
    original.index([page])
    before = original._conn.execute("SELECT rowid, * FROM wiki_fts").fetchall()
    original._conn.executescript(
        "CREATE TABLE old_pages AS SELECT slug, content_hash, abstract FROM pages;"
        "DROP TABLE pages; ALTER TABLE old_pages RENAME TO pages;"
        "UPDATE meta SET value='node-v2' WHERE key='schema_version';"
    )
    original.close()
    upgraded = FTS5Backend(root=str(tmp_path))
    try:
        upgraded.index([page])
        assert upgraded.search("quasar") == []
        assert upgraded._conn.execute("SELECT rowid, * FROM wiki_fts").fetchall() == before
    finally:
        upgraded.close()


def test_fts5_full_wiki_refresh_removes_deleted_pages(tmp_path, monkeypatch):
    from knowledge_studio.search.fts5 import FTS5Backend

    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    page = wiki / "deleted.md"
    page.write_text("---\ntitle: Quasar ledger\n---\nquasar policy", encoding="utf-8")
    instance = FTS5Backend(root=str(tmp_path))
    try:
        assert instance.search("quasar")
        page.unlink()
        assert instance.search("quasar") == []
        assert instance._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 0
        assert instance._conn.execute("SELECT COUNT(*) FROM wiki_fts").fetchone()[0] == 0
    finally:
        instance.close()


def test_fts5_concurrent_old_index_upgrade(tmp_path):
    import sqlite3
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from knowledge_studio.search.fts5 import FTS5Backend

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
            "INSERT INTO meta VALUES ('schema_version', 'node-v2');"
            "CREATE TABLE pages (slug TEXT PRIMARY KEY, content_hash TEXT, abstract TEXT);"
            "INSERT INTO pages VALUES ('legacy', 'unchanged', 'Retained abstract');"
        )
    finally:
        conn.close()
    barrier = Barrier(8)

    def open_index(_):
        barrier.wait(timeout=10)
        backend = FTS5Backend(root=str(tmp_path), db_path=str(path))
        try:
            return backend._conn.execute(
                "SELECT slug, content_hash, abstract, status, archived FROM pages"
            ).fetchall()
        finally:
            backend.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(open_index, range(8)))
    assert results == [[("legacy", "unchanged", "Retained abstract", "active", 0)]] * 8


def test_fts5_lazy_state_refresh_reads_its_root_and_preserves_text(tmp_path, monkeypatch):
    from knowledge_studio.search.fts5 import FTS5Backend

    monkeypatch.setenv("OKS_ROOT", str(tmp_path / "other-kb"))
    wiki = tmp_path / "kb" / "wiki"
    wiki.mkdir(parents=True)
    path = wiki / "changing.md"
    backend = FTS5Backend(root=str(wiki.parent))
    before = None
    try:
        for status, archived, allowed in [
            ("active", False, True), ("dropped", False, False),
            ("provisional", False, True), ("provisional", True, False),
            ("provisional", False, True),
        ]:
            path.write_text(
                f"---\ntitle: Quasar\nstatus: {status}\narchived: {str(archived).lower()}\n---\nquasar policy",
                encoding="utf-8",
            )
            assert bool(backend.search("quasar")) is allowed
            rows = backend._conn.execute("SELECT rowid, * FROM wiki_fts").fetchall()
            if before is not None:
                assert rows == before
            before = rows
        path.unlink()
        wiki.rmdir()
        assert backend.search("quasar") == []
    finally:
        backend.close()


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


def test_fts5_reopens_current_index_without_reparsing_wiki(tmp_path, monkeypatch):
    from knowledge_studio import store
    from knowledge_studio.search.fts5 import FTS5Backend

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "policy.md"
    path.write_text("---\ntitle: Quasar\n---\nquasar policy", encoding="utf-8")
    original = FTS5Backend(root=str(tmp_path))
    try:
        expected = original.search("quasar")
        assert expected
    finally:
        original.close()

    parsed = []
    parse = store.parse_wiki_file

    def track_parse(path, **kwargs):
        parsed.append(path)
        return parse(path, **kwargs)

    monkeypatch.setattr(store, "parse_wiki_file", track_parse)
    reopened = FTS5Backend(root=str(tmp_path))
    try:
        assert reopened.search("quasar") == expected
        assert parsed == []
    finally:
        reopened.close()

    path.write_text("---\ntitle: Pulsar\n---\npulsar revised policy", encoding="utf-8")
    changed = FTS5Backend(root=str(tmp_path))
    try:
        assert changed.search("quasar") == []
        assert [hit.slug for hit in changed.search("pulsar")] == ["policy"]
        assert parsed == [path]
    finally:
        changed.close()


@pytest.mark.parametrize("invalidator", ["schema", "engine", "pages", "wiki_fts", "skill_fts"])
def test_fts5_reopens_invalidated_index_from_source(tmp_path, monkeypatch, invalidator):
    from knowledge_studio import store
    from knowledge_studio.search.fts5 import FTS5Backend

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "policy.md"
    path.write_text("---\ntitle: Quasar\n---\nquasar policy", encoding="utf-8")
    original = FTS5Backend(root=str(tmp_path))
    if not original._use_fts5:
        original.close()
        pytest.skip("SQLite has no FTS5 support")
    try:
        assert original.search("quasar")
        if invalidator == "schema":
            original._conn.execute("UPDATE meta SET value='node-v3' WHERE key='schema_version'")
        elif invalidator == "engine":
            original._conn.execute("UPDATE meta SET value='like' WHERE key='index_engine'")
        else:
            original._conn.execute(f"DROP TABLE {invalidator}")
        original._conn.commit()
    finally:
        original.close()

    parsed = []
    parse = store.parse_wiki_file

    def track_parse(path, **kwargs):
        parsed.append(path)
        return parse(path, **kwargs)

    monkeypatch.setattr(store, "parse_wiki_file", track_parse)
    reopened = FTS5Backend(root=str(tmp_path))
    try:
        assert [hit.slug for hit in reopened.search("quasar")] == ["policy"]
        assert reopened.search("quasar")
        assert parsed == [path]
    finally:
        reopened.close()


@pytest.mark.parametrize("remove_source", [False, True])
def test_fts5_explicit_override_is_local_to_its_instance(tmp_path, remove_source):
    from knowledge_studio.search.fts5 import FTS5Backend

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "policy.md"
    path.write_text("---\ntitle: Quasar\n---\nquasar policy", encoding="utf-8")
    original = FTS5Backend(root=str(tmp_path))
    try:
        assert original.search("quasar")
        original.index([_page("policy", title="Pulsar", body="pulsar policy")])
        assert original.search("quasar") == []
        assert [hit.slug for hit in original.search("pulsar")] == ["policy"]
    finally:
        original.close()

    if remove_source:
        path.unlink()
        wiki.rmdir()
    reopened = FTS5Backend(root=str(tmp_path))
    try:
        assert reopened.search("pulsar") == []
        assert [hit.slug for hit in reopened.search("quasar")] == ([] if remove_source else ["policy"])
    finally:
        reopened.close()


@pytest.mark.parametrize("reopen", [False, True])
def test_fts5_retries_incomplete_source_reads(tmp_path, monkeypatch, reopen):
    from knowledge_studio import store
    from knowledge_studio.search.fts5 import FTS5Backend

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    path = wiki / "policy.md"
    path.write_text("---\ntitle: Quasar\n---\nquasar policy", encoding="utf-8")
    read = type(path).read_text
    unavailable = True

    def read_text(file, *args, **kwargs):
        if file == path and unavailable:
            raise PermissionError("temporarily unreadable")
        return read(file, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", read_text)
    assert store.parse_wiki_file(path) is None
    with pytest.raises(PermissionError):
        store.parse_wiki_file(path, strict=True)
    instance = FTS5Backend(root=str(tmp_path))
    try:
        assert instance.search("quasar") == []
        unavailable = False
        if reopen:
            instance.close()
            instance = FTS5Backend(root=str(tmp_path))
        assert [hit.slug for hit in instance.search("quasar")] == ["policy"]
    finally:
        instance.close()


def test_fts5_readable_invalid_markdown_does_not_prevent_reuse(tmp_path, monkeypatch):
    from knowledge_studio import store
    from knowledge_studio.search.fts5 import FTS5Backend

    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "policy.md").write_text("---\ntitle: Quasar\n---\nquasar policy", encoding="utf-8")
    (wiki / "no-frontmatter.md").write_text("# Unstructured", encoding="utf-8")
    (wiki / "bad-yaml.md").write_text("---\ntitle: [\n---\n# Invalid", encoding="utf-8")
    original = FTS5Backend(root=str(tmp_path))
    try:
        assert original.search("quasar")
    finally:
        original.close()

    def unexpected_parse(*args, **kwargs):
        pytest.fail("Unchanged readable files should reuse the persisted index")

    monkeypatch.setattr(store, "parse_wiki_file", unexpected_parse)
    reopened = FTS5Backend(root=str(tmp_path))
    try:
        assert [hit.slug for hit in reopened.search("quasar")] == ["policy"]
    finally:
        reopened.close()
