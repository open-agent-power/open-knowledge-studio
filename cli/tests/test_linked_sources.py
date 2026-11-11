import hashlib
import json
import subprocess
import pytest
import yaml
from knowledge_studio import linked_sources as sources


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


def commit(repo):
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def linked(tmp_path):
    root = tmp_path / "personal"
    root.mkdir()
    repo = tmp_path / "team"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "core.autocrlf", "true")
    (repo / "catalog").mkdir()
    (repo / "knowledge").mkdir()
    (repo / "sources/reviews").mkdir(parents=True)
    body = "# Quartz cancellation\nUse explicit refunds."
    (repo / "knowledge/one.md").write_text(body)
    (repo / "sources/index.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "one",
                        "url": "https://example.org/evidence",
                        "version": "v1",
                        "sha256": "a" * 64,
                    }
                ]
            }
        )
    )
    rows = {
        "schema_version": 1,
        "repository": "org/team",
        "knowledge": [
            {
                "id": "one",
                "title": "Quartz cancellation",
                "path": "knowledge/one.md",
                "kind": "how-to",
                "topics": ["test"],
                "status": "candidate",
                "approval": None,
            }
        ],
    }
    (repo / "catalog/knowledge.yaml").write_text(yaml.safe_dump(rows))
    commit(repo)
    sources.link(root, "team", repo, "org/team")
    return root, repo, rows


def approve(repo, rows):
    rows["knowledge"][0].update(status="approved", approval="sources/reviews/one.json")
    (repo / "catalog/knowledge.yaml").write_text(yaml.safe_dump(rows))
    (repo / "sources/reviews/one.json").write_text(
        json.dumps(
            {
                "id": "one",
                "decision": "approved",
                "reviewer": "Human",
                "decided_at": "2026-11-05T00:00:00Z",
                "decision_ref": "https://example.org/decision",
                "body_sha256": hashlib.sha256(
                    subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:knowledge/one.md"])
                ).hexdigest(),
            }
        )
    )
    return commit(repo)


def test_candidates_are_visible_but_never_recalled_and_upstream_unchanged(linked):
    root, repo, rows = linked
    before = git(repo, "status", "--porcelain")
    assert sources.catalog(root)["sources"][0]["candidate_count"] == 1
    assert sources.search(root, "quartz")[0] == []
    assert git(repo, "status", "--porcelain") == before
    assert not (repo / ".oks").exists() and not (root / "wiki").exists()


def test_head_refresh_is_committed_and_versioned_without_copying(linked):
    root, repo, rows = linked
    sha = approve(repo, rows)
    blob = subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:knowledge/one.md"])
    approval = json.loads(subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:sources/reviews/one.json"]))
    assert approval["body_sha256"] == hashlib.sha256(blob).hexdigest()
    hits, warnings = sources.search(root, "quartz")
    assert not warnings and hits[0]["revision"] == sha
    assert "/blob/" + sha + "/" in hits[0]["url"]
    (repo / "knowledge/one.md").write_text("# changed without approval")
    assert (
        sources.search(root, "quartz")[0][0]["source_sha256"]
        == hits[0]["source_sha256"]
    )
    commit(repo)
    assert sources.search(root, "quartz")[0] == []
    assert sources.catalog(root)["warnings"]  # fail closed on stale approval


def test_pinned_revision_and_unlink_leave_upstream_alone(linked):
    root, repo, rows = linked
    first = git(repo, "rev-parse", "HEAD")
    sources.link(root, "team", repo, "org/team", first)
    approve(repo, rows)
    assert sources.search(root, "quartz")[0] == []
    sources.unlink(root, "team")
    assert sources.configuration(root) == []
    assert git(repo, "status", "--porcelain") == ""


def test_symlink_blob_cannot_leak_and_no_upstream_code_is_run(linked):
    root, repo, rows = linked
    (repo / "knowledge/one.md").unlink()
    (repo / "knowledge/one.md").symlink_to("/etc/passwd")
    commit(repo)
    assert sources.catalog(root)["sources"] == []
    assert sources.catalog(root)["warnings"]


def test_bad_settings_exclude_team_without_breaking_personal_recall(tmp_path):
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings/sources.yaml").write_text("sources: [bad]")
    assert sources.search(tmp_path, "quartz")[0] == []
    assert sources.catalog(tmp_path)["warnings"]


@pytest.fixture
def unified(tmp_path):
    root = tmp_path / 'personal'
    root.mkdir()
    repo = tmp_path / 'team-knowledge'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'settings').mkdir()
    (repo / 'settings/library.yaml').write_text(yaml.safe_dump({
        'schema_version':1, 'layout':'oks', 'kind':'team', 'repository':'org/team'}))
    files = {
        'wiki/one.md': '---\nid: one\ntitle: Quartz cancellation\ntype: strategy\nhuman_reviewed_at: "2026-11-10T00:00:00Z"\n---\nUse refunds. [[../raw/evidence.md]]',
        'drafts/candidate.md': '---\ntitle: Quartz pending\nstatus: draft\n---\nUnreviewed lesson.',
        'raw/evidence.md': '# Original material\nSource evidence.',
        'skills/quartz/SKILL.md': '---\nname: quartz\n---\nDo not auto execute.',
        'wiki/skill-record.md': '---\ntitle: Quartz skill registry\nskill_id: quartz\nhuman_reviewed_at: "2026-11-10T00:00:00Z"\n---\nSkill registry, not a knowledge instruction.',
    }
    for relative,text in files.items():
        p=repo/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    commit(repo)
    sources.link(root,'team',repo,'org/team')
    return root,repo


def test_standard_buckets_are_federated_without_copying_or_executing(unified):
    root,repo=unified
    data=sources.catalog(root)
    assert not data['warnings']
    entries=data['sources'][0]['entries']
    assert {e['asset_kind'] for e in entries} == {'wiki','drafts','raw','skills'}
    hits,warnings=sources.search(root,'Quartz',type_filter='strategy')
    assert not warnings and [e['title'] for e in hits] == ['Quartz cancellation']
    assert sources.search(root,'Quartz',type_filter='concept')[0] == []
    assert sources.search(root,'Quartz',scope='unrelated')[0] == []
    assert not (root/'wiki').exists() and not (repo/'.oks').exists()
    before=hits[0]['source_sha256']
    (repo/'wiki/one.md').write_text('Uncommitted change')
    assert sources.read(root,'team','wiki/one.md')['source_sha256']==before


def test_team_virtual_files_keep_commit_and_reject_traversal(unified):
    from knowledge_studio.vfs import VfsService,VfsResolver,VfsError
    root,repo=unified
    fs=VfsService(VfsResolver(root))
    assert any(e['uri']=='oks://team/' for e in fs.ls('oks://')['entries'])
    assert fs.ls('oks://team/')['entries'][0]['name']=='team'
    read=fs.read('oks://team/team/wiki/one.md')
    assert read['read_only'] and read['revision']==git(repo,'rev-parse','HEAD')
    assert read['source_sha256']==hashlib.sha256(read['content'].encode()).hexdigest()
    assert fs.tree('oks://team/team/',depth=2)['entries']
    assert fs.find('Original',under='oks://team/team/raw/')['matches']
    assert any(e['uri'].startswith('oks://team/') for e in fs.find('Original',under='oks://')['matches'])
    with pytest.raises(VfsError):fs.read('oks://team/team/../settings/library.yaml')
    with pytest.raises(VfsError):fs.read('oks://team/team/settings/library.yaml')
    (repo/'raw/leak.md').symlink_to('/etc/passwd')
    commit(repo)
    assert sources.catalog(root)['warnings']


def test_cross_library_links_are_resolved_by_namespace(unified):
    root,repo=unified
    entries=sources.catalog(root)['sources'][0]['entries']
    entries.append({'id':'wiki/local.md','path':'wiki/local.md','body':'[[team:team/one]]'})
    edges=sources.relations(entries)
    assert {'a':'wiki/local.md','b':'team:team/one','type':'cites'} in edges
    assert {'a':'team:team/one','b':'team:team/raw/evidence.md','type':'cites'} in edges


def test_migrated_catalog_keeps_candidate_state_and_stale_reviews_closed(linked):
    root,repo,rows=linked
    (repo/'records/catalog').mkdir(parents=True)
    (repo/'drafts').mkdir()
    (repo/'raw/sources').mkdir(parents=True)
    (repo/'knowledge/one.md').rename(repo/'drafts/one.md')
    rows['knowledge'][0]['path']='drafts/one.md'
    (repo/'records/catalog/knowledge.yaml').write_text(yaml.safe_dump(rows))
    (repo/'sources/index.json').rename(repo/'raw/sources/index.json')
    git(repo,'rm','-r','--cached','catalog')
    (repo/'catalog/knowledge.yaml').unlink()
    commit(repo)
    data=sources.catalog(root)
    assert not data['warnings'] and data['sources'][0]['candidate_count']==1
    assert sources.search(root,'quartz')[0]==[]
    assert data['sources'][0]['entries'][0]['id']=='team:team/one'


def test_empty_standard_team_can_be_linked_and_namespace_collisions_stay_separate(tmp_path):
    root=tmp_path/'personal';root.mkdir()
    for name in ('first','second'):
        repo=tmp_path/name;repo.mkdir();git(repo,'init','-q')
        (repo/'wiki').mkdir();(repo/'wiki/.gitkeep').touch()
        commit(repo)
        sources.link(root,name,repo,'org/'+name)
    assert len(sources.catalog(root)['sources'])==2
    assert sources.search(root,'anything')[0]==[]


def test_graph_does_not_treat_code_examples_as_links(unified):
    root,repo=unified
    entries=sources.catalog(root)['sources'][0]['entries']
    entries.append({'id':'wiki/local.md','path':'wiki/local.md','body':'```md\n[[team:team/one]]\n```'})
    assert not any(e['a']=='wiki/local.md' for e in sources.relations(entries))


def test_measured_cli_and_studio_read_compare_committed_bytes_not_worktree(unified):
    from knowledge_studio.vfs_observation import execute, observe_call
    root,repo=unified
    uri='oks://team/team/wiki/one.md'
    expected=sources.read(root,'team','wiki/one.md')['body']
    (repo/'wiki/one.md').write_text('Changed in worktree only')
    value=observe_call(root,'read',uri,lambda service:service.read(uri))
    assert value['content']==expected
    report=execute(root,'compare',uri)
    assert report['trace']['comparison']['equivalent']
    assert report['trace']['revision']==git(repo,'rev-parse','HEAD')
    assert any('Git' in s['name'] for s in report['trace']['spans'])


def test_inspect_reads_committed_readme_without_execution_or_registration(linked):
    from typer.testing import CliRunner
    from knowledge_studio.cli import app
    root, repo = linked[:2]
    (repo / 'README.md').write_text('# Requirements\nGitHub sign-in for private reads.\nNever execute this example: touch SHOULD_NOT_EXIST\n')
    sha = commit(repo)
    (repo / 'README.md').write_text('# Uncommitted instructions')
    before = (root / 'settings/sources.yaml').read_bytes()
    result = CliRunner().invoke(app, ['sources', 'inspect', str(repo)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data['revision'] == sha
    assert 'GitHub sign-in' in data['readme']['text']
    assert 'Uncommitted' not in data['readme']['text']
    assert data['validation'] == 'readme_only'
    assert not (repo / 'SHOULD_NOT_EXIST').exists()
    assert (root / 'settings/sources.yaml').read_bytes() == before


def test_library_readme_is_vfs_reference_not_reviewed_knowledge(unified):
    from knowledge_studio.library_vfs import request
    root, repo = unified
    (repo / 'readme.md').write_text('# Prerequisites\nUniqueLibraryCredentialChecklist')
    sha = commit(repo)
    document = request(root, 'oks://team/team/readme.md', 'read')
    assert document['revision'] == sha
    assert document['asset_kind'] == 'reference'
    assert document['status'] == 'reference'
    assert 'UniqueLibraryCredentialChecklist' in document['content']
    hits, warnings = sources.search(root, 'UniqueLibraryCredentialChecklist')
    assert hits == [] and not warnings
    (repo / 'readme.md').unlink()
    commit(repo)
    assert sources.inspect_library(repo)['status'] == 'missing_readme'
