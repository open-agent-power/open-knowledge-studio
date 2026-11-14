"""Contract tests for the knowledge map projection.

Two invariants matter more than the shape of the output:

* every relation edge states where it came from, and
* Concept / Strategy / Anti-Strategy never become the Wiki's taxonomy.
"""
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from knowledge_studio import mail_knowledge, store


@pytest.fixture
def kb(tmp_path):
    root = tmp_path / "kb"
    (root / "wiki").mkdir(parents=True)
    (root / "drafts").mkdir()
    return root


def write(root: Path, relative: str, frontmatter: str, body: str = "正文"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    store._atomic_write(path, f"---\n{frontmatter}---\n\n{body}\n")
    return path


def point(projection, path):
    for domain in projection["domains"]:
        for cluster in domain["clusters"]:
            for item in cluster["points"]:
                if item["path"] == path:
                    return item
    raise AssertionError(f"{path} not in projection")


def raw_bundle(root, name, text="Source excerpt", status="complete"):
    base = f"raw/2026/11/08/{name}"
    write(root, base + "/raw.md", "capture_id: same-session\n", "# Capture wrapper")
    (root / base / "content.md").write_text(text, encoding="utf-8")
    (root / base / "source").mkdir()
    (root / base / "source/excerpt.txt").write_text(text, encoding="utf-8")
    (root / base / "bundle.json").write_text(json.dumps({
        "bundle_id": name, "capture_id": "same-session", "processing_status": status,
        "files": {"content": "content.md"}, "sources": [{"path": "source/excerpt.txt"}],
    }), encoding="utf-8")
    return base


def test_raw_bundles_are_single_distinct_sources_with_lazy_bodies(kb):
    a = raw_bundle(kb, "a", "Original excerpt A", "partial")
    b = raw_bundle(kb, "b", "Original excerpt B", "failed")
    before = {p: p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    data = mail_knowledge.knowledge_map(kb)
    assert {p["id"] for p in data["materials"]} == {a + "/raw.md", b + "/raw.md"}
    assert data["counts"]["source_materials"] == 2
    assert data["counts"]["candidates"] == 0
    for p in data["materials"]:
        assert p["body"] == "" and p["body_path"].endswith("/content.md")
        assert p["review"]["state"] == "not_applicable"
        assert p["title"].startswith("Original excerpt")
    assert {p["processing_status"] for p in data["materials"]} == {"partial", "failed"}
    assert {p: p.read_bytes() for p in kb.rglob("*") if p.is_file()} == before


def test_source_edges_resolve_only_recorded_paths_and_bundle_aliases(kb):
    a = raw_bundle(kb, "a")
    raw_bundle(kb, "unreferenced")
    write(kb, "drafts/idea.md", f'sources: ["{a}/source/excerpt.txt", "{a}/content.md", "raw/missing.md"]\n',
          f'[Source](../{a}/content.md)')
    data = mail_knowledge.knowledge_map(kb)
    edge, = data["material_edges"]
    assert (edge["a"], edge["b"]) == ("drafts/idea.md", a + "/raw.md")
    assert "frontmatter sources" in edge["sources"][0]
    link, = data["internal_links"]
    assert link["b"] == a + "/raw.md"
    limited = mail_knowledge.knowledge_map(kb, limit=1)
    assert limited["scope"]["truncated"]
    assert limited["material_edges"] == limited["internal_links"] == []


@pytest.mark.parametrize('current_draft', ['changed', 'deleted'])
@pytest.mark.parametrize('bom', [False, True])
def test_wiki_sources_follow_the_exact_reviewed_draft(kb, monkeypatch, current_draft, bom):
    monkeypatch.setenv('OKS_ROOT', str(kb))
    original = raw_bundle(kb, 'original')
    later = raw_bundle(kb, 'later')
    draft_path = write(kb, 'drafts/from-raw.md',
                       f'title: Retained source\ndraft_type: strategy\ndraft_area: computing\nsources: [{original}/source/excerpt.txt]\n')
    if bom:
        draft_path.write_bytes(b'\xef\xbb\xbf' + draft_path.read_bytes())
    digest = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    wiki_slug = store.promote_draft('from-raw', expected_sha256=digest)
    wiki_path = next(path for path in (kb / 'wiki').rglob('*.md') if path.stem == wiki_slug)
    relative = wiki_path.relative_to(kb).as_posix()
    if current_draft == 'changed':
        write(kb, 'drafts/from-raw.md', f'title: Later version\nsources: [{later}/source/excerpt.txt]\n')
    else:
        draft_path.unlink()
    before = {path: path.read_bytes() for path in kb.rglob('*') if path.is_file()}

    data = mail_knowledge.knowledge_map(kb)
    edges = [edge for edge in data['material_edges'] if edge['a'] == relative]
    assert len(edges) == 1
    assert edges[0]['b'] == original + '/raw.md'
    assert any('drafts/from-raw.md' in source and digest in source for source in edges[0]['sources'])
    assert {path: path.read_bytes() for path in kb.rglob('*') if path.is_file()} == before


def test_wiki_does_not_inherit_sources_from_a_mismatched_review_snapshot(kb, monkeypatch):
    monkeypatch.setenv('OKS_ROOT', str(kb))
    base = raw_bundle(kb, 'original')
    path = write(kb, 'drafts/from-raw.md',
                 f'title: Retained source\ndraft_type: strategy\ndraft_area: computing\nsources: [{base}/source/excerpt.txt]\n')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store.promote_draft('from-raw', expected_sha256=digest)
    path.unlink()
    retained = kb / '.oks/reviewed-drafts' / (digest + '.md')
    retained.write_bytes(retained.read_bytes() + b'\nChanged after review\n')
    assert mail_knowledge.knowledge_map(kb)['material_edges'] == []


@pytest.mark.parametrize('reference', ['sources', 'raw_link', 'wiki_link'])
def test_isolated_point_count_uses_visible_sources_and_document_links(kb, reference):
    base = raw_bundle(kb, 'original')
    metadata, body = 'title: Origin\narea: computing\n', 'Origin body'
    if reference == 'sources':
        metadata += f'sources: [{base}/source/excerpt.txt]\n'
    elif reference == 'raw_link':
        body = f'[Source](../{base}/content.md)'
    else:
        body = '[Related](b.md)'
        write(kb, 'wiki/b.md', 'title: Related\narea: computing\n')
    write(kb, 'wiki/a.md', metadata, body)

    projection = mail_knowledge.knowledge_map(kb)
    assert projection['counts']['points_without_relations'] == 0
    assert projection['counts']['edges'] == projection['counts']['relations'] == 0
    assert mail_knowledge.knowledge_map(kb, limit=1)['counts']['points_without_relations'] == 1


def test_source_title_skips_metadata_and_transport_markers(kb):
    raw_bundle(kb, "a", "---\ntitle: transport\n---\n\n# 实际资料标题\n正文")
    raw_bundle(kb, "b", "<send_user_message_question_reply>\n\n可读的原始内容\n</send_user_message_question_reply>")
    titles = {p["title"] for p in mail_knowledge.knowledge_map(kb)["materials"]}
    assert titles == {"实际资料标题", "可读的原始内容"}


def test_raw_without_valid_bundle_is_readable_and_bad_content_path_is_not_followed(kb):
    write(kb, "raw/note.md", "title: Standalone\nprocessing_status: partial\n")
    a = raw_bundle(kb, "a")
    manifest = kb / a / "bundle.json"
    manifest.write_text(json.dumps({"files": {"content": "../../../../../../outside.md"}}), encoding="utf-8")
    data = mail_knowledge.knowledge_map(kb)
    raw = {p["id"]: p for p in data["materials"]}
    assert raw["raw/note.md"]["processing_status"] == "partial"
    assert raw[a + "/raw.md"]["body_path"] == a + "/raw.md"
    assert not data["material_edges"]
    manifest.write_text("{broken", encoding="utf-8")
    data = mail_knowledge.knowledge_map(kb)
    assert data["warnings"]
    assert any(p["path"] == "raw/note.md" for p in data["materials"])


def test_three_levels_come_from_area_and_tags(kb):
    write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, view-layer"\nstatus: active\n')
    write(kb, "wiki/b.md", 'title: "B"\narea: engineering\ntags: "engineering, mail-protocol"\nstatus: active\n')
    write(kb, "wiki/c.md", 'title: "C"\narea: knowledge\ntags: "knowledge, recall"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    domains = {domain["key"]: {cluster["key"] for cluster in domain["clusters"]} for domain in projection["domains"]}

    assert domains == {"engineering": {"view-layer", "mail-protocol"}, "knowledge": {"recall"}}
    assert projection["counts"]["points"] == 3
    assert projection["counts"]["clusters"] == 3


def test_promoted_origins_are_bounded_unique_missing_drafts(kb):
    front = ('title: Promoted\narea: computing\nstatus: active\n'
             'human_reviewed_at: 2026-10-22T00:00:00Z\n'
             'source_candidates: [drafts/old.md, drafts/../outside.md, drafts/current.md]\n')
    write(kb, "wiki/promoted.md", front)
    write(kb, "drafts/current.md", "title: Current\nstatus: pending\n")
    before = {p: p.read_bytes() for p in kb.rglob("*.md")}
    data = mail_knowledge.knowledge_map(kb)
    assert point(data, "wiki/promoted.md")["source_candidates"] == ["drafts/old.md"]
    assert point(data, "drafts/current.md")["source_candidates"] == []
    write(kb, "wiki/duplicate.md", front)
    data = mail_knowledge.knowledge_map(kb)
    assert point(data, "wiki/promoted.md")["source_candidates"] == []
    assert point(data, "wiki/duplicate.md")["source_candidates"] == []
    assert all(p.read_bytes() == payload for p, payload in before.items())


@pytest.mark.parametrize("extra", ["", "human_reviewed_at: 2026-10-22T00:00:00Z\nstatus: provisional\n"])
def test_unreviewed_or_inactive_page_has_no_historical_alias(kb, extra):
    write(kb, "wiki/a.md", "title: A\narea: computing\nsource_candidates: [drafts/old.md]\n" + extra)
    assert point(mail_knowledge.knowledge_map(kb), "wiki/a.md")["source_candidates"] == []


def test_domain_tag_does_not_create_a_hairball(kb):
    for index in range(6):
        write(kb, f"wiki/e{index}.md", f'title: "E{index}"\narea: engineering\ntags: "engineering"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["counts"]["relations"] == 0
    assert {cluster["key"] for domain in projection["domains"] for cluster in domain["clusters"]} == {"本域通用"}


def test_declared_relations_are_sourced_and_resolved(kb):
    write(kb, "wiki/target.md", 'title: "目标知识"\narea: knowledge\ntags: "knowledge, recall"\nstatus: active\n')
    write(
        kb,
        "wiki/source.md",
        'title: "来源知识"\narea: knowledge\ntags: "knowledge, skill-governance"\nstatus: active\n'
        "relations:\n  - type: depends_on\n    target: 目标知识\n",
    )

    item = point(mail_knowledge.knowledge_map(kb), "wiki/source.md")
    edge = item["relations"][0]
    assert edge["type"] == "depends_on"
    assert edge["type_label"] == "依赖 / 前置"
    assert edge["source"] == "frontmatter relations"
    assert edge["resolved"] is True
    assert edge["target_id"] == "wiki/target.md"
    assert edge["target_title"] == "目标知识"


@pytest.mark.parametrize('kind,label', [('enriches', '补充'), ('confirms', '确认'),
                                       ('challenges', '质疑'), ('supersedes', '更新 / 替代')])
def test_evolution_relationships_reach_graph_with_direction_and_provenance(kb, kind, label):
    write(kb, 'wiki/old.md', 'title: Old\narea: computing\n')
    write(kb, 'wiki/new.md', f'title: New\narea: computing\nhuman_reviewed_at: 2026-10-22\n'
          f'relates_to: old\nrelationship: {kind}\n')
    before = {p: p.read_bytes() for p in kb.rglob('*.md')}
    data = mail_knowledge.knowledge_map(kb)
    edge, = data['explicit_edges']
    assert edge['type'] == kind and edge['type_label'] == label
    assert {edge['a'], edge['b']} == {'wiki/new.md', 'wiki/old.md'}
    claim, = edge['claims']
    assert (claim['from'], claim['to']) == ('wiki/new.md', 'wiki/old.md')
    assert claim['source'] == 'frontmatter relates_to + relationship'
    assert all(p.read_bytes() == body for p, body in before.items())


def test_matching_relation_forms_keep_both_sources_on_one_edge(kb):
    write(kb, 'wiki/old.md', 'title: Old\narea: computing\n')
    write(kb, 'wiki/new.md', 'title: New\narea: computing\nrelates_to: old\nrelationship: enriches\n'
          'relations:\n  - type: enriches\n    target: wiki/old.md\n    note: Extra context\n')
    edge, = mail_knowledge.knowledge_map(kb)['explicit_edges']
    assert {claim['source'] for claim in edge['claims']} == {
        'frontmatter relations', 'frontmatter relates_to + relationship'}
    assert any(claim['note'] == 'Extra context' for claim in edge['claims'])


@pytest.mark.parametrize('target,reason', [('same', 'ambiguous'), ('Same title', 'ambiguous'),
                                         ('wiki/missing/same.md', 'missing'), ('absent', 'missing')])
def test_relation_targets_do_not_guess_between_names_or_missing_paths(kb, target, reason):
    write(kb, 'wiki/one/same.md', 'title: Same title\narea: computing\n')
    write(kb, 'wiki/two/same.md', 'title: Same title\narea: computing\n')
    write(kb, 'wiki/source.md', f'title: Source\narea: computing\nrelates_to: {target}\nrelationship: enriches\n')
    data = mail_knowledge.knowledge_map(kb)
    relation, = point(data, 'wiki/source.md')['relations']
    assert relation['resolved'] is False and relation['resolution'] == reason
    assert data['explicit_edges'] == []
    write(kb, 'wiki/source.md', 'title: Source\narea: computing\nrelates_to: wiki/two/same.md\nrelationship: enriches\n')
    edge, = mail_knowledge.knowledge_map(kb)['explicit_edges']
    assert edge['claims'][0]['to'] == 'wiki/two/same.md'


def test_relation_name_conflict_between_title_and_slug_is_ambiguous(kb):
    write(kb, 'wiki/a.md', 'title: b\narea: computing\n')
    write(kb, 'wiki/b.md', 'title: B page\narea: computing\n')
    write(kb, 'wiki/source.md', 'title: Source\narea: computing\nrelations: "supports: b"\n')
    data = mail_knowledge.knowledge_map(kb)
    assert data['explicit_edges'] == []
    assert point(data, 'wiki/source.md')['relations'][0]['resolution'] == 'ambiguous'


def test_unknown_relation_type_and_dangling_target_are_flagged_not_remapped(kb):
    write(
        kb,
        "wiki/source.md",
        'title: "来源知识"\narea: knowledge\ntags: "knowledge, recall"\nstatus: active\n'
        "relations:\n  - type: inspired_by\n    target: 库外的东西\n",
    )

    edge = point(mail_knowledge.knowledge_map(kb), "wiki/source.md")["relations"][0]
    assert edge["type"] == "unknown"
    assert edge["type_label"] == "未识别关系"
    assert edge["raw_type"] == "inspired_by"
    assert edge["resolved"] is False
    assert edge["target_title"] == "库外的东西"
    assert edge["target_kind"] == "unresolved"


def test_shared_cluster_tag_becomes_a_sourced_relation(kb):
    write(kb, "wiki/x.md", 'title: "X"\narea: engineering\ntags: "engineering, ui, extra"\nstatus: active\n')
    write(kb, "wiki/y.md", 'title: "Y"\narea: knowledge\ntags: "knowledge, recall, extra"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    edge = point(projection, "wiki/x.md")["relations"][0]
    assert edge["type"] == "related"
    assert edge["source"] == "shared tag: extra"
    assert edge["target_id"] == "wiki/y.md"
    assert projection["explicit_edges"] == []
    assert projection["internal_links"] == []
    assert len(projection["shared_tag_edges"]) == 1
    assert "extra" in projection["shared_tag_edges"][0]["sources"][0]


def test_limited_projection_keeps_off_page_name_ambiguity(kb):
    write(kb, "wiki/00-source.md", 'title: Source\nrelations: "supports: Same title"\n')
    write(kb, "wiki/01-one.md", 'title: Same title\n')
    write(kb, "wiki/02-two.md", 'title: Same title\n')

    data = mail_knowledge.knowledge_map(kb, limit=2)

    relation, = point(data, "wiki/00-source.md")["relations"]
    assert relation["resolution"] == "ambiguous"
    assert data["explicit_edges"] == []
    assert data["scope"]["points_total"] == 3
    assert data["scope"]["points_returned"] == 2


def test_limited_projection_keeps_drawer_and_visible_edges_after_its_cap(kb):
    write(kb, "wiki/a-source.md", 'title: Source\ntags: [cluster, outside, inside]\n')
    write(kb, "wiki/b-visible.md", 'title: Visible\ntags: [other, inside]\n')
    for index in range(20):
        write(kb, f"wiki/z{index:02}.md", f'title: Outside {index}\ntags: [other, outside]\n')
    full = mail_knowledge.knowledge_map(kb)
    limited = mail_knowledge.knowledge_map(kb, limit=2)

    source = point(limited, "wiki/a-source.md")
    assert source["relations"] == point(full, "wiki/a-source.md")["relations"]
    assert len(source["relations"]) == 12
    assert source["relations_truncated"] is True
    assert all(relation["target_id"].startswith("wiki/z") for relation in source["relations"])
    edge, = limited["shared_tag_edges"]
    assert (edge["a"], edge["b"]) == ("wiki/a-source.md", "wiki/b-visible.md")
    assert edge["declared_by"] == ["wiki/a-source.md", "wiki/b-visible.md"]


def test_shared_edges_are_not_limited_to_drawer_entries(kb):
    for index in range(16):
        write(kb, f"wiki/{index:02}.md", f'title: Entry {index}\ntags: [cluster, shared]\n')

    data = mail_knowledge.knowledge_map(kb)

    assert len(data["shared_tag_edges"]) == 16 * 15 // 2
    assert len(point(data, "wiki/00.md")["relations"]) == 12
    assert point(data, "wiki/00.md")["relations_truncated"] is True


def test_limited_projection_bounds_shared_relation_materialization(kb, monkeypatch):
    class CountedLabels(dict):
        shared_lookups = 0

        def __getitem__(self, key):
            if key == "related":
                self.shared_lookups += 1
            return super().__getitem__(key)

    labels = CountedLabels(mail_knowledge.RELATION_TYPES)
    monkeypatch.setattr(mail_knowledge, "RELATION_TYPES", labels)
    for index in range(30):
        write(kb, f"wiki/{index:02}.md", f'title: Entry {index}\ntags: [cluster, shared]\n')

    data = mail_knowledge.knowledge_map(kb, limit=1)

    assert labels.shared_lookups == 13
    assert data["edges"] == []
    assert point(data, "wiki/00.md")["relations_truncated"] is True


def test_governance_types_stay_attributes_not_taxonomy(kb):
    write(kb, "wiki/s.md", 'title: "S"\ntype: strategy\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')
    write(kb, "wiki/c.md", 'title: "C"\ntype: concept\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')
    write(kb, "wiki/a.md", 'title: "A"\ntype: anti-pattern\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    # Grouping still follows the domain; the three governance types never appear
    # as domains or clusters.
    assert [domain["key"] for domain in projection["domains"]] == ["engineering"]
    # 显示名与机器键分离：area 仍是机器键，label 供界面显示。
    assert [domain["label"] for domain in projection["domains"]] == ["研发工程"]
    all_clusters = {cluster["key"] for domain in projection["domains"] for cluster in domain["clusters"]}
    assert all_clusters == {"ui"}
    assert {item["label"] for item in projection["governance"]["types"]} == {"概念", "策略", "反策略"}
    assert all(item["count"] == 0 for item in projection["governance"]["types"])
    assert all(not point(projection, path)["is_skill"] for path in ("wiki/s.md", "wiki/c.md", "wiki/a.md"))


def test_skill_boundary_is_policy_and_records_what_phase_one_does_not_do(kb):
    write(kb, "wiki/s.md", 'title: "S"\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')

    boundary = mail_knowledge.knowledge_map(kb)["governance"]["skill_boundary"]
    assert boundary["kind"] == "policy"
    assert boundary["stage"] == "phase-1"
    assert any("不自动安装" in item for item in boundary["not_done"])
    assert any("wiki_refs" in item for item in boundary["allowed"])


def test_candidates_use_draft_keys_and_are_labelled(kb):
    write(kb, "drafts/c.md", 'title: "候选知识"\ndraft_type: strategy\ndraft_area: ai\nstatus: draft\n')

    item = point(mail_knowledge.knowledge_map(kb), "drafts/c.md")
    assert item["kind"] == "candidate"
    assert item["kind_label"] == "Candidate 候选"
    assert item["area"] == "ai"
    assert item["governance"]["type"] == "strategy"
    assert item["status_label"] == "草稿待审"
    assert item["skill"]["state"] == "none"
    assert item["is_skill"] is False
    assert item["wiki_refs"] == ["drafts/c.md"]
    assert item["review"]["state"] == "pending"


@pytest.mark.parametrize("value", [None, "", "not-a-date", True, 1])
@pytest.mark.parametrize("status", ["active", "provisional"])
def test_review_summary_requires_a_valid_explicit_review_time(value, status):
    summary = mail_knowledge.review_summary({"status": status, "human_reviewed_at": value}, "wiki")
    assert summary == {
        "state": "unknown", "label": "审核记录未知", "reviewed": False,
        "human_reviewed_at": None, "kind_label": "Wiki · 审核记录未知",
    }


@pytest.mark.parametrize("value", [
    "2026-10-14T08:00:00+08:00", date(2026, 10, 14),
    datetime(2026, 10, 14, tzinfo=timezone.utc),
])
def test_review_summary_accepts_standard_review_timestamp_values(value):
    summary = mail_knowledge.review_summary({"human_reviewed_at": value}, "wiki")
    assert summary["reviewed"] is True
    assert summary["state"] == "reviewed"
    assert summary["kind_label"] == "已审核 Wiki"
    assert summary["human_reviewed_at"] == "2026-10-14T00:00:00+00:00"


def test_candidate_review_summary_remains_pending_even_with_review_field():
    summary = mail_knowledge.review_summary({"human_reviewed_at": "2026-10-14"}, "candidate")
    assert summary["state"] == "pending"
    assert summary["label"] == "待审核"
    assert summary["reviewed"] is False
    assert summary["human_reviewed_at"] is None


def test_review_counts_distinguish_wiki_location_from_review_evidence(kb):
    write(kb, "wiki/reviewed.md", 'title: "审核过"\nstatus: active\nhuman_reviewed_at: 2026-10-14\n')
    write(kb, "wiki/legacy.md", 'title: "旧记录"\nstatus: active\n')
    write(kb, "wiki/provisional.md", 'title: "待确认"\nstatus: provisional\n')
    write(kb, "wiki/invalid.md", 'title: "无效时间"\nstatus: active\nhuman_reviewed_at: invalid\n')
    write(kb, "drafts/candidate.md", 'title: "候选"\nstatus: draft\nhuman_reviewed_at: 2026-10-14\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["counts"]["wiki_count"] == 4
    assert projection["counts"]["reviewed"] == 1
    assert projection["counts"]["review_unknown"] == 3
    assert projection["counts"]["candidates"] == 1
    assert point(projection, "wiki/reviewed.md")["kind_label"] == "已审核 Wiki"
    assert point(projection, "wiki/legacy.md")["kind"] == "wiki"
    assert point(projection, "wiki/legacy.md")["kind_label"] == "Wiki · 审核记录未知"
    assert point(projection, "wiki/legacy.md")["status_label"] == "当前条目"


def test_archived_and_dropped_entries_are_reported_as_hidden(kb):
    write(kb, "wiki/live.md", 'title: "在库"\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')
    write(kb, "wiki/gone.md", 'title: "已归档"\narea: engineering\ntags: "engineering, ui"\nstatus: archived\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["counts"]["points"] == 1
    assert projection["scope"]["hidden"] == 1


def test_projection_declares_where_each_level_comes_from(kb):
    write(kb, "wiki/live.md", 'title: "在库"\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["scope"]["level_sources"] == [
        "条目自己声明的所属领域",
        "条目自己声明的关系，或与另一条知识共享的标签",
        "一份 Wiki 或候选条目；审核记录单独展示",
    ]
    # 口径可以改写，但「图是只读的、来源可追溯」这两条不能丢。
    why = projection["scope"]["why"]
    assert "不新增任何知识" in why and "不写入任何东西" in why and "来源" in why
    item = point(projection, "wiki/live.md")
    assert item["cluster_source"]


def test_scope_copy_leaks_no_protocol_words(kb):
    """普通读者看到的说明里不能出现内部字段名 —— 这是 R6 的硬要求。"""
    write(kb, "wiki/live.md", 'title: "在库"\narea: collaboration\ntags: "collaboration, checkpoint, ui"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    scope = projection["scope"]
    visible = f"{scope['note']} {scope['why']} " + " ".join(scope["level_sources"])
    governance = " ".join(
        [projection["governance"]["note"]]
        + list(projection["governance"]["skill_boundary"]["allowed"])
        + list(projection["governance"]["skill_boundary"]["not_done"])
    )
    for word in ("frontmatter", "area", "tags[0]", "collaboration", "enabled"):
        assert word not in visible, word
        assert word not in governance, word


def test_every_time_source_key_has_a_human_label():
    """时间来源要显示人话；新增时间字段却忘了起名字，这里会先拦住。"""
    missing = [
        key for key in (*mail_knowledge.TIME_KEYS, "file_mtime")
        if key not in mail_knowledge.TIME_SOURCE_LABELS
    ]
    assert missing == [], f"这些时间字段还没有人话名字：{missing}"
    # 表里没有的 key 也不许把原始字段名漏出去。
    assert mail_knowledge.time_source_label("some_new_field") == "记录时间"
    assert mail_knowledge.time_source_label("updated_at") == "条目里记录的更新时间"


# ── 治理位：库能力保留，面板没有任何调用方 ──────────────────────────────
#
# 这些测试守的是数据安全，不是功能花样：
# 写进去的必须只有一个布尔字段，其他字节与正文必须原样保留，
# 越界路径和没有 frontmatter 的文件必须被拒绝，而不是被「顺手修好」。
# 注意：面板的写路径已于 2026-09-22 移除，这里是**库能力**的契约测试；
# 将来若重新暴露，必须走 CLI / Agent，而不是无鉴权的 HTTP 路由。

def test_toggle_writes_only_the_governance_bit_and_keeps_a_backup(kb):
    path = write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, ui"\nstatus: active\n', "正文第一行\n正文第二行\n")
    before = path.read_bytes()

    result = mail_knowledge.set_enabled(kb, "wiki/a.md", False)

    after = path.read_text(encoding="utf-8")
    assert result["enabled"] is False
    assert result["previous_enabled"] is True
    assert result["changed"] is True
    assert "enabled: false" in after
    assert "正文第一行" in after and "正文第二行" in after
    assert 'title: "A"' in after and "status: active" in after
    backup = kb / result["backup"]
    assert backup.is_file()
    assert backup.read_bytes() == before


def test_toggle_is_reversible_byte_for_byte(kb):
    path = write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, ui"\nstatus: active\n', "正文\n")
    original = path.read_text(encoding="utf-8")

    mail_knowledge.set_enabled(kb, "wiki/a.md", False)
    assert "enabled: false" in path.read_text(encoding="utf-8")
    mail_knowledge.set_enabled(kb, "wiki/a.md", True)
    restored = path.read_text(encoding="utf-8")

    assert "enabled: true" in restored
    # 去掉新增的那一行之后，其余内容必须与原始文件逐字相同
    strip = lambda text: [line for line in text.splitlines() if not line.strip().startswith("enabled:")]
    assert strip(restored) == strip(original)


def test_toggle_replaces_an_existing_enabled_line_instead_of_appending(kb):
    path = write(kb, "wiki/a.md", 'title: "A"\nenabled: false\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')

    mail_knowledge.set_enabled(kb, "wiki/a.md", True)

    text = path.read_text(encoding="utf-8")
    assert text.count("enabled:") == 1
    assert "enabled: true" in text


def test_toggle_refuses_paths_outside_wiki_and_drafts(kb):
    outside = write(kb, "raw/secret.md", 'title: "raw"\narea: engineering\n')
    with pytest.raises(FileNotFoundError):
        mail_knowledge.set_enabled(kb, "raw/secret.md", False)
    assert "enabled" not in outside.read_text(encoding="utf-8")

    # 穿越到其他目录的真实文件：resolve 之后不在 wiki/ drafts/ 之内，必须拒绝
    with pytest.raises(FileNotFoundError):
        mail_knowledge.set_enabled(kb, "wiki/../raw/secret.md", False)
    assert "enabled" not in outside.read_text(encoding="utf-8")

    # 绝对路径直接拒绝
    with pytest.raises(ValueError):
        mail_knowledge.set_enabled(kb, str(outside), False)

    with pytest.raises(FileNotFoundError):
        mail_knowledge.set_enabled(kb, "wiki/missing.md", False)


def test_toggle_refuses_frontmatter_less_file_instead_of_inventing_one(kb):
    path = kb / "wiki" / "plain.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("没有 frontmatter 的正文\n", encoding="utf-8")

    with pytest.raises(ValueError):
        mail_knowledge.set_enabled(kb, "wiki/plain.md", False)
    assert path.read_text(encoding="utf-8") == "没有 frontmatter 的正文\n"


def test_projection_reports_pluggable_state_without_a_write_path(kb):
    write(kb, "wiki/on.md", 'title: "开"\nartifact_kind: skill\ntype: strategy\narea: engineering\ntags: "engineering, ui"\nstatus: active\n')
    write(kb, "wiki/off.md", 'title: "关"\nartifact_kind: skill\ntype: concept\narea: engineering\ntags: "engineering, ui"\nstatus: active\nenabled: false\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["counts"]["enabled"] == 1
    assert projection["counts"]["disabled"] == 1
    state = projection["governance"]["enabled_state"]
    assert state["field"] == "enabled"
    assert state["counts"] == {"enabled": 1, "disabled": 1}
    # 只读边界：payload 不许再宣告任何写端点或写保证 —— 面板已经不提供写路径，
    # 留一个 endpoint 在这里等于让页面替一个不存在的接口许愿。
    governance = projection["governance"]
    assert "toggle" not in governance
    assert "/api/" not in json.dumps(governance, ensure_ascii=False)
    assert [m["path"] for m in projection["governance"]["pluggable"]] == ["wiki/off.md", "wiki/on.md"]
    assert [m["enabled"] for m in projection["governance"]["pluggable"]] == [False, True]

    mail_knowledge.set_enabled(kb, "wiki/on.md", False)
    after = mail_knowledge.knowledge_map(kb)
    assert after["counts"]["enabled"] == 0
    assert after["counts"]["disabled"] == 2


# ── 主视图的关系网（2026-09-22）────────────────────────────────────────
#
# 图例列的是**关系类型**，而主视图原来画的是**目录从属**，两者对不上。
# 图例计数还有个更硬的问题：它按逐条清单累加，同一条无向关系被两端各算一次 ——
# 真实库上 14 条可画的关系被报成了 29 条。所以边表与图例现在同源。

def test_one_relation_between_two_entries_is_drawn_once(kb):
    """同一条无向关系被两端各声明一次，主视图只该画一条、图例只该算一次。"""
    write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, ui"\nstatus: active\nrelations: "supports: wiki/b.md"\n')
    write(kb, "wiki/b.md", 'title: "B"\narea: engineering\ntags: "engineering, ui"\nstatus: active\nrelations: "supports: wiki/a.md"\n')

    projection = mail_knowledge.knowledge_map(kb)
    supports = [edge for edge in projection["edges"] if edge["type"] == "supports"]
    assert len(supports) == 1
    # 合并不能丢归属：两端的声明都记在这一条边上。
    assert sorted(supports[0]["declared_by"]) == ["wiki/a.md", "wiki/b.md"]
    # 端点排序固定，两个方向不可能各画一条。
    assert supports[0]["a"] <= supports[0]["b"]

    assert projection["counts"]["edges"] == len(projection["edges"])
    # 图例合计 == 画得出来的边数。这条断言就是防「图例比图多报一倍」回归。
    assert sum(item["count"] for item in projection["relation_legend"]) == len(projection["edges"])
    assert projection["counts"]["edges_cross_domain"] == 0


def test_edges_only_include_entries_that_are_in_the_graph(kb):
    """指向未收录条目的关系画不出来，就不该出现在边表与图例里。"""
    write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, ui"\nstatus: active\nrelations: "depends_on: 还没建的条目"\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["edges"] == []
    assert sum(item["count"] for item in projection["relation_legend"]) == 0
    # 但逐条清单里不能丢：下钻时要能标出「这条指向的条目尚未收录」。
    assert point(projection, "wiki/a.md")["relations"][0]["resolved"] is False
    assert projection["counts"]["points_without_relations"] == 1


def test_two_different_relations_between_the_same_pair_are_both_kept(kb):
    """同一对节点上的两个不同说法都要留 —— 那是两条关系，不是重复。"""
    write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, release, ui"\nstatus: active\nrelations: "contrast: wiki/b.md"\n')
    write(kb, "wiki/b.md", 'title: "B"\narea: engineering\ntags: "engineering, ui, release"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert sorted(edge["type"] for edge in projection["edges"]) == ["contrast", "related"]
    # 两条边落在同一对节点上；前端要按序号把曲线错开，否则只看得见一条。
    assert len({(edge["a"], edge["b"]) for edge in projection["edges"]}) == 1


def test_cross_domain_edges_are_counted_from_the_drawable_table(kb):
    write(kb, "wiki/a.md", 'title: "A"\narea: engineering\ntags: "engineering, ui"\nstatus: active\nrelations: "applies_to: wiki/b.md"\n')
    write(kb, "wiki/b.md", 'title: "B"\narea: knowledge\ntags: "knowledge, recall"\nstatus: active\n')

    projection = mail_knowledge.knowledge_map(kb)
    assert projection["counts"]["edges"] == 1
    assert projection["counts"]["edges_cross_domain"] == 1
    assert projection["counts"]["points_without_relations"] == 0
