import hashlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def vfs_root(tmp_path: Path) -> Path:
    for relative in (
        "profiles",
        "raw/executions",
        "raw/.logs",
        "wiki/computing/concepts",
        "drafts",
        "mail",
        ".agents/skills/query",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles/team.md").write_text("# Team\n", encoding="utf-8")
    (tmp_path / "wiki/computing/concepts/中文 页面.md").write_text(
        "# 中文页面\n", encoding="utf-8"
    )
    return tmp_path


def test_parse_and_render_canonical_uri(vfs_root):
    from knowledge_studio.vfs import OksUri

    uri = OksUri.parse(
        "oks://wiki/computing/concepts/%E4%B8%AD%E6%96%87%20%E9%A1%B5%E9%9D%A2.md"
    )

    assert uri.scope == "wiki"
    assert uri.parts == ("computing", "concepts", "中文 页面.md")
    assert (
        uri.render()
        == "oks://wiki/computing/concepts/%E4%B8%AD%E6%96%87%20%E9%A1%B5%E9%9D%A2.md"
    )


@pytest.mark.parametrize(
    ("uri", "code"),
    [
        ("http://wiki/example.md", "INVALID_URI"),
        ("oks://settings/recall.yaml", "UNSUPPORTED_SCOPE"),
        ("oks://wiki/../profiles/team.md", "INVALID_URI"),
        ("oks://wiki/%2E%2E/profiles/team.md", "INVALID_URI"),
        ("oks://wiki/a%2Fb.md", "INVALID_URI"),
        ("oks://wiki/a%5Cb.md", "INVALID_URI"),
        ("oks://wiki/a.md?raw=1", "INVALID_URI"),
        ("oks://wiki/a.md#section", "INVALID_URI"),
        ("oks://wiki//", "INVALID_URI"),
    ],
)
def test_invalid_uri_is_rejected(uri, code):
    from knowledge_studio.vfs import OksUri, VfsError

    with pytest.raises(VfsError) as exc:
        OksUri.parse(uri)
    assert exc.value.code == code


def test_resolver_maps_public_mounts_and_trace_alias(vfs_root):
    from knowledge_studio.vfs import VfsResolver

    trace = vfs_root / "raw/executions/run-1/events.jsonl"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("{}\n", encoding="utf-8")
    resolver = VfsResolver(vfs_root)

    assert resolver.resolve("oks://profiles/team.md").path == vfs_root / "profiles/team.md"
    assert resolver.resolve("oks://traces/run-1/events.jsonl").path == trace
    assert resolver.uri_for_path(trace) == "oks://traces/run-1/events.jsonl"


@pytest.mark.parametrize("uri", ["oks://raw/executions/", "oks://raw/.logs/"])
def test_raw_internal_paths_are_not_exposed(vfs_root, uri):
    from knowledge_studio.vfs import VfsError, VfsResolver

    with pytest.raises(VfsError) as exc:
        VfsResolver(vfs_root).resolve(uri)
    assert exc.value.code == "PATH_NOT_EXPOSED"


def test_any_symlink_component_is_rejected(vfs_root):
    from knowledge_studio.vfs import VfsError, VfsResolver

    target = vfs_root / "profiles/team.md"
    link = vfs_root / "wiki/link.md"
    link.symlink_to(target)

    with pytest.raises(VfsError) as exc:
        VfsResolver(vfs_root).resolve("oks://wiki/link.md")
    assert exc.value.code == "SYMLINK_NOT_ALLOWED"


_UNSAFE_PHYSICAL_PATHS = [Path("wiki") / ".." / "settings" / "recall.yaml"]
if os.name != "nt":
    # Windows treats backslashes as native separators, so a physical filename
    # containing one cannot be represented there. URI-level backslashes remain
    # covered by test_invalid_uri_is_rejected on every platform.
    _UNSAFE_PHYSICAL_PATHS.append(Path("wiki") / "unsafe\\name.md")


@pytest.mark.parametrize("path", _UNSAFE_PHYSICAL_PATHS)
def test_uri_for_path_rejects_noncanonical_or_unsafe_paths(vfs_root, path):
    from knowledge_studio.vfs import VfsError, VfsResolver

    with pytest.raises(VfsError) as exc:
        VfsResolver(vfs_root).uri_for_path(path)
    assert exc.value.code == "PATH_NOT_EXPOSED"


def test_uri_for_path_rejects_external_symlink_into_public_mount(vfs_root, tmp_path):
    from knowledge_studio.vfs import VfsError, VfsResolver

    external_link = tmp_path.parent / f"{tmp_path.name}-outside-link.md"
    external_link.symlink_to(vfs_root / "wiki/computing/concepts/中文 页面.md")

    with pytest.raises(VfsError) as exc:
        VfsResolver(vfs_root).uri_for_path(external_link)
    assert exc.value.code == "PATH_NOT_EXPOSED"


def test_ls_and_stat_return_canonical_nodes(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    service = VfsService(VfsResolver(vfs_root))
    listing = service.ls("oks://wiki/computing/concepts/")
    stat = service.stat("oks://profiles/team.md")

    assert listing["entries"] == [
        {
            "name": "中文 页面.md",
            "type": "file",
            "uri": "oks://wiki/computing/concepts/%E4%B8%AD%E6%96%87%20%E9%A1%B5%E9%9D%A2.md",
        }
    ]
    assert stat["type"] == "file"
    assert stat["uri"] == "oks://profiles/team.md"
    assert stat["size"] == (vfs_root / "profiles/team.md").stat().st_size
    assert stat["modified_at"].endswith("+00:00")
    assert stat["mount"] == "profiles"


def test_stat_and_read_accept_uri_without_md_suffix(vfs_root):
    """Canonical URIs should not expose the on-disk ``.md`` format.

    A URI without the suffix must still stat/read the ``.md`` file, while a
    URI *with* the suffix keeps working (backward compatibility)."""
    from knowledge_studio.vfs import VfsResolver, VfsService

    service = VfsService(VfsResolver(vfs_root))

    # Chinese slug without .md suffix resolves to the .md file transparently.
    bare = "oks://wiki/computing/concepts/中文 页面"
    stat = service.stat(bare)
    assert stat["type"] == "file"
    assert stat["size"] == (vfs_root / "wiki/computing/concepts/中文 页面.md").stat().st_size

    # read() also works without the suffix and returns the same content.
    bare_content = service.read(bare)["content"]
    md_content = service.read(bare + ".md")["content"]
    assert bare_content == md_content == "# 中文页面\n"

    # A genuinely missing path (no .md sibling) still raises PATH_NOT_FOUND.
    from knowledge_studio.vfs import VfsError

    with pytest.raises(VfsError) as exc:
        service.stat("oks://wiki/computing/concepts/does-not-exist")
    assert exc.value.code == "PATH_NOT_FOUND"


def test_root_ls_is_synthetic_and_physical_ls_hides_exclusions(vfs_root):
    from knowledge_studio.vfs import MOUNTS, VfsResolver, VfsService

    service = VfsService(VfsResolver(vfs_root))

    assert service.ls("oks://")["entries"] == [
        {"name": scope, "type": "directory", "uri": f"oks://{scope}/"}
        for scope in MOUNTS if scope not in {"goal", "discuss", "skill", "host-skills"}
    ]
    assert service.ls("oks://raw/")["entries"] == []


def test_ls_rejects_files_and_symlink_children(vfs_root):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    service = VfsService(VfsResolver(vfs_root))
    with pytest.raises(VfsError) as exc:
        service.ls("oks://profiles/team.md")
    assert exc.value.code == "NOT_DIRECTORY"

    (vfs_root / "wiki/link.md").symlink_to(vfs_root / "profiles/team.md")
    with pytest.raises(VfsError) as exc:
        service.ls("oks://wiki/")
    assert exc.value.code == "SYMLINK_NOT_ALLOWED"


def test_read_is_utf8_paginated(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    page = vfs_root / "wiki/computing/concepts/long.md"
    page.write_text("中文" * 15_000, encoding="utf-8")
    service = VfsService(VfsResolver(vfs_root))

    first = service.read("oks://wiki/computing/concepts/long.md")
    second = service.read(
        "oks://wiki/computing/concepts/long.md",
        offset=first["next_offset"],
        limit=10_000,
    )

    assert first["returned_chars"] == 20_000
    assert first["truncated"] is True
    assert second["offset"] == 20_000
    assert first["content"] + second["content"] == "中文" * 15_000


@pytest.mark.parametrize("payload", [b"\xff\x00", b"\x00\x01"])
def test_read_rejects_binary(vfs_root, payload):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    binary = vfs_root / "raw/blob.bin"
    binary.write_bytes(payload)
    with pytest.raises(VfsError) as exc:
        VfsService(VfsResolver(vfs_root)).read("oks://raw/blob.bin")
    assert exc.value.code == "UNSUPPORTED_CONTENT"


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 1), (0, 0), (0, 1_000_001)],
)
def test_read_validates_pagination(vfs_root, offset, limit):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    with pytest.raises(VfsError) as exc:
        VfsService(VfsResolver(vfs_root)).read(
            "oks://profiles/team.md", offset=offset, limit=limit
        )
    assert exc.value.code == "INVALID_ARGUMENT"


def test_read_many_preserves_order_and_total_bound(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    first = vfs_root / "wiki/first.md"
    second = vfs_root / "wiki/second.md"
    first.write_text("abcdef", encoding="utf-8")
    second.write_text("uvwxyz", encoding="utf-8")

    result = VfsService(VfsResolver(vfs_root)).read_many(
        ["oks://wiki/first.md", "oks://wiki/second.md"],
        limit=5,
        max_total_chars=8,
    )

    assert [item["uri"] for item in result["items"]] == [
        "oks://wiki/first.md",
        "oks://wiki/second.md",
    ]
    assert [item["content"] for item in result["items"]] == ["abcde", "uvw"]
    assert result["returned_chars"] == 8
    assert result["returned_count"] == 2
    assert result["truncated"] is True


@pytest.mark.parametrize(
    ("uris", "limit", "max_total_chars"),
    [
        ([], 20_000, 10),
        (["oks://profiles/team.md"] * 251, 20_000, 10),
        (["oks://profiles/team.md"], 0, 10),
        (["oks://profiles/team.md"], 20_000, 0),
        (["oks://profiles/team.md"], 20_000, 8 * 1024 * 1024 + 1),
    ],
)
def test_read_many_validates_bounds(vfs_root, uris, limit, max_total_chars):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    with pytest.raises(VfsError) as exc:
        VfsService(VfsResolver(vfs_root)).read_many(
            uris, limit=limit, max_total_chars=max_total_chars
        )
    assert exc.value.code == "INVALID_ARGUMENT"


def test_read_many_fails_closed_on_invalid_uri(vfs_root):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    with pytest.raises(VfsError) as exc:
        VfsService(VfsResolver(vfs_root)).read_many(
            ["oks://profiles/team.md", "oks://wiki/missing.md"]
        )
    assert exc.value.code == "PATH_NOT_FOUND"


def test_tree_honors_depth_and_entry_limit(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    for name in ("a.md", "b.md", "c.md"):
        (vfs_root / "wiki" / name).write_text(name, encoding="utf-8")
    service = VfsService(VfsResolver(vfs_root))

    result = service.tree("oks://wiki/", depth=1, max_entries=2)

    assert len(result["entries"]) == 2
    assert result["truncated"] is True


def test_tree_depth_zero_returns_no_descendants(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    result = VfsService(VfsResolver(vfs_root)).tree("oks://wiki/", depth=0)

    assert result["entries"] == []
    assert result["truncated"] is False


def test_overview_is_mechanical_and_does_not_write_sidecars(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    index = vfs_root / "wiki/INDEX.md"
    index.write_text("# Index\n", encoding="utf-8")
    result = VfsService(VfsResolver(vfs_root)).overview("oks://wiki/")

    assert result["index_uri"] == "oks://wiki/INDEX.md"
    assert result["counts"] == {"directory": 1, "file": 1, "special": 0}
    assert [entry["name"] for entry in result["directories"]] == ["computing"]
    assert [entry["name"] for entry in result["files"]] == ["INDEX.md"]
    assert not (vfs_root / "wiki/.abstract.md").exists()
    assert not (vfs_root / "wiki/.overview.md").exists()


def test_find_is_literal_bounded_and_reports_skips(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    (vfs_root / "wiki/a.md").write_text(
        "Atomic Write prevents corruption", encoding="utf-8"
    )
    (vfs_root / "wiki/b[1].md").write_text("literal brackets", encoding="utf-8")
    (vfs_root / "wiki/blob.bin").write_bytes(b"\xff\x00")
    service = VfsService(VfsResolver(vfs_root))

    result = service.find("atomic write", under="oks://wiki/", max_results=1)

    assert result["matches"][0]["uri"] == "oks://wiki/a.md"
    assert result["matches"][0]["match"] == "content"
    assert len(result["matches"][0]["snippet"]) <= 200
    assert result["skipped_count"] == 1
    assert result["truncated"] is False


def test_find_matches_paths_literally_and_truncates_on_another_match(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    (vfs_root / "wiki/brackets[1].md").write_text("first", encoding="utf-8")
    (vfs_root / "wiki/brackets[2].md").write_text("second", encoding="utf-8")
    result = VfsService(VfsResolver(vfs_root)).find(
        "BRACKETS[", under="oks://wiki/", max_results=1
    )

    assert result["matches"] == [
        {
            "uri": "oks://wiki/brackets%5B1%5D.md",
            "match": "path",
            "snippet": "brackets[1].md",
        }
    ]
    assert result["truncated"] is True


def test_tree_and_find_honor_exclusions_and_reject_symlinks(vfs_root):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    (vfs_root / "raw/executions/hidden.md").write_text(
        "hidden needle", encoding="utf-8"
    )
    (vfs_root / "raw/.logs/hidden.md").write_text("hidden needle", encoding="utf-8")
    service = VfsService(VfsResolver(vfs_root))

    assert service.tree("oks://raw/")["entries"] == []
    assert service.find("hidden needle", under="oks://raw/")["matches"] == []

    (vfs_root / "wiki/link.md").symlink_to(vfs_root / "profiles/team.md")
    for operation in (
        lambda: service.tree("oks://wiki/"),
        lambda: service.find("team", under="oks://wiki/"),
    ):
        with pytest.raises(VfsError) as exc:
            operation()
        assert exc.value.code == "SYMLINK_NOT_ALLOWED"


def test_host_mount_is_not_traversed_by_root_and_explicit_paths_reject_symlinks(vfs_root):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    (vfs_root / ".agents/skills/query").rmdir()
    (vfs_root / ".agents/skills").rmdir()
    (vfs_root / ".agents/skills").symlink_to(
        vfs_root / "missing-skills", target_is_directory=True
    )
    service = VfsService(VfsResolver(vfs_root))

    service.tree("oks://")
    service.find("needle", under="oks://")
    for operation in (
        lambda: service.tree("oks://host-skills/"),
        lambda: service.find("needle", under="oks://host-skills/"),
    ):
        with pytest.raises(VfsError) as exc:
            operation()
        assert exc.value.code == "SYMLINK_NOT_ALLOWED"


def test_find_utf8_content_snippet_is_character_bounded(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    (vfs_root / "wiki/chinese.md").write_text(
        "前" * 120 + "原子写入" + "后" * 120, encoding="utf-8"
    )

    match = VfsService(VfsResolver(vfs_root)).find(
        "原子写入", under="oks://wiki/"
    )["matches"][0]

    assert match["match"] == "content"
    assert "原子写入" in match["snippet"]
    assert len(match["snippet"]) <= 200


@pytest.mark.parametrize(
    ("operation", "kwargs", "code"),
    [
        ("tree", {"uri": "oks://wiki/", "depth": -1}, "INVALID_ARGUMENT"),
        ("tree", {"uri": "oks://wiki/", "depth": 11}, "INVALID_ARGUMENT"),
        (
            "tree",
            {"uri": "oks://wiki/", "max_entries": 0},
            "INVALID_ARGUMENT",
        ),
        (
            "tree",
            {"uri": "oks://wiki/", "max_entries": 10_001},
            "INVALID_ARGUMENT",
        ),
        ("find", {"query": "", "under": "oks://wiki/"}, "INVALID_ARGUMENT"),
        (
            "find",
            {"query": "x", "under": "oks://wiki/", "max_results": 0},
            "INVALID_ARGUMENT",
        ),
        (
            "find",
            {"query": "x", "under": "oks://wiki/", "max_results": 201},
            "INVALID_ARGUMENT",
        ),
    ],
)
def test_browsing_operations_validate_limits(vfs_root, operation, kwargs, code):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    with pytest.raises(VfsError) as exc:
        getattr(VfsService(VfsResolver(vfs_root)), operation)(**kwargs)
    assert exc.value.code == code


@pytest.mark.parametrize("operation", ["tree", "overview"])
def test_directory_browsing_rejects_file_targets(vfs_root, operation):
    from knowledge_studio.vfs import VfsError, VfsResolver, VfsService

    with pytest.raises(VfsError) as exc:
        getattr(VfsService(VfsResolver(vfs_root)), operation)(
            "oks://profiles/team.md"
        )
    assert exc.value.code == "NOT_DIRECTORY"


def _file_snapshot(root: Path) -> dict[str, str]:
    snapshot = {}
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        snapshot[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return snapshot


def test_basic_vfs_operations_do_not_change_files(vfs_root):
    from knowledge_studio.vfs import VfsResolver, VfsService

    service = VfsService(VfsResolver(vfs_root))
    before = _file_snapshot(vfs_root)

    service.ls("oks://wiki/computing/concepts/")
    service.stat("oks://profiles/team.md")
    service.read("oks://profiles/team.md")
    service.read_many(["oks://profiles/team.md"])
    service.tree("oks://wiki/")
    service.overview("oks://wiki/")
    service.find("team", under="oks://profiles/")

    assert _file_snapshot(vfs_root) == before
