"""Read-only virtual directories backed by indexed Git blobs, not worktrees."""
from __future__ import annotations

from . import linked_sources


def request(root, uri, action, *, offset=0, limit=20000, depth=3, max_entries=1000,
            query="", max_results=50):
    from .vfs import OksUri, VfsError

    parsed = OksUri.parse(uri)
    data = linked_sources.catalog(root)
    documents, directories = {}, {(): {"uri": "oks://team/", "name": "team", "type": "directory", "read_only": True}}
    for library in data["sources"]:
        prefix = (library["name"],)
        directories[prefix] = {"name": library["name"], "type": "directory",
                               "uri": OksUri("team", prefix).render(), "read_only": True}
        for entry in library["entries"]:
            parts = prefix + tuple(entry["path"].split("/"))
            documents[parts] = entry
            for size in range(2, len(parts)):
                parent = parts[:size]
                directories[parent] = {"name": parent[-1], "type": "directory",
                                       "uri": OksUri("team", parent).render(), "read_only": True}
    current = parsed.parts
    if current not in documents and current not in directories:
        raise VfsError("PATH_NOT_FOUND", "Linked document or directory is unavailable")
    canonical = parsed.render()
    entry = documents.get(current)
    def item(parts, value):
        return {"name": parts[-1], "type": "file", "uri": OksUri("team", parts).render(),
                "read_only": True, "repository": value["repository"], "revision": value["revision"],
                "status": value["status"], "asset_kind": value.get("asset_kind"),
                "source_sha256": value["source_sha256"]}
    if action == "stat":
        return {"uri": canonical, "type": "file" if entry else "directory", "mount": "team",
                "size": len(entry["body"].encode()) if entry else None, "modified_at": None,
                "read_only": True, **(item(current, entry) if entry else {})}
    if action == "read":
        if entry is None:
            raise VfsError("UNSUPPORTED_CONTENT", "Choose a linked file")
        text = entry["body"]
        page = text[offset:offset + limit]
        end = offset + len(page)
        return {**item(current, entry), "content": page, "offset": offset,
                "returned_chars": len(page), "total_chars": len(text),
                "truncated": end < len(text), "next_offset": end if end < len(text) else None}
    if entry is not None:
        raise VfsError("NOT_DIRECTORY", "Choose a linked directory")
    children = {**directories, **{parts:item(parts,e) for parts,e in documents.items()}}
    rows = [value for parts,value in sorted(children.items())
            if parts[:len(current)] == current and 0 < len(parts)-len(current) <= (depth if action == "tree" else 1)]
    if action == "find":
        matches = []
        for parts,e in sorted(documents.items()):
            if parts[:len(current)] != current:
                continue
            path = "/".join(parts)
            index = e["body"].casefold().find(query.casefold())
            if query.casefold() in path.casefold() or index >= 0:
                matches.append({**item(parts,e), "match": "path" if query.casefold() in path.casefold() else "content",
                                "snippet": path if index < 0 else e["body"][max(0,index-80):index+120]})
        return {"uri":canonical,"query":query,"matches":matches[:max_results],
                "truncated":len(matches)>max_results,"skipped_count":0,"warnings":data["warnings"]}
    if action == "overview":
        return {"uri":canonical,"directories":[e for e in rows if e["type"]=="directory"],
                "files":[e for e in rows if e["type"]=="file"],
                "counts":{t:sum(e["type"]==t for e in rows) for t in ("directory","file","special")},"index_uri":None}
    return {"uri":canonical,"entries":rows[:max_entries],"depth":depth,
            "truncated":len(rows)>max_entries,"read_only":True,"warnings":data["warnings"]}
