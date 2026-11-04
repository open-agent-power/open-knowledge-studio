"""Cross-process tests for the Store's read/modify/write locks.

``_file_lock`` coordinates mutations both across processes (an OS file lock) and
inside a single interpreter (a thread lock). The defects these tests pin down
only appear when two *processes* touch the same file, so every writer runs in
its own interpreter: threads of the test process would be serialised by the
thread lock even if the file lock were missing, and the test would then pass
with or without the fix.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from knowledge_studio import store

CLI_DIR = Path(store.__file__).resolve().parents[1]

# Each child waits for one shared wall-clock instant so the mutations overlap
# instead of starting one after another, which would hide the race.
_UPDATE_FIELD_AT = (
    "import pathlib, sys, time\n"
    "from knowledge_studio import store\n"
    "delay = float(sys.argv[1]) - time.time()\n"
    "if delay > 0:\n"
    "    time.sleep(delay)\n"
    "store._update_frontmatter_field(pathlib.Path(sys.argv[2]), sys.argv[3], sys.argv[4])\n"
)

_WRITE_PAGE_AT = (
    "import sys, time\n"
    "from knowledge_studio import store\n"
    "delay = float(sys.argv[1]) - time.time()\n"
    "if delay > 0:\n"
    "    time.sleep(delay)\n"
    "store.write_wiki_page(sys.argv[2], sys.argv[3], area='computing')\n"
)

_REVIEW_AT = (
    "import sys, time\n"
    "from knowledge_studio import store\n"
    "delay = float(sys.argv[1]) - time.time()\n"
    "if delay > 0: time.sleep(delay)\n"
    "try:\n"
    "    (store.promote_draft if sys.argv[2] == 'promote' else store.reject_draft)(sys.argv[3])\n"
    "except ValueError as exc:\n"
    "    print('conflict:', exc)\n"
)


def _spawn(script, *args, root):
    env = dict(os.environ)
    env["OKS_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(CLI_DIR), env.get("PYTHONPATH", "")) if part
    )
    return subprocess.Popen(
        [sys.executable, "-c", script, *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _run_all(procs):
    for proc in procs:
        _out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0, err


def test_concurrent_frontmatter_updates_keep_every_field(tmp_path, monkeypatch):
    """Eight processes set eight different fields on one page.

    ``_update_frontmatter_field`` rewrites the whole file. Without the lock each
    writer loads a pre-race snapshot and writes it back, so whichever field was
    written first is gone — the page keeps a shrinking subset of the fields.
    """
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    page = store.write_wiki_page("concurrent-fields", "body " * 20000, area="computing")
    jobs = [(f"field_{index}", f"value_{index}") for index in range(8)]
    start = time.time() + 4
    procs = [
        _spawn(_UPDATE_FIELD_AT, str(start), str(page), name, value, root=tmp_path)
        for name, value in jobs
    ]
    _run_all(procs)
    meta = store.parse_wiki_file(page)
    assert [name for name, _ in jobs if meta.get(name) is None] == []
    assert all(meta[name] == value for name, value in jobs)


def test_concurrent_writes_keep_every_fingerprint_mapping(tmp_path, monkeypatch):
    """Six processes write six distinct pages at the same instant.

    The fingerprint index is a read/modify/write over one JSON file. Unlocked,
    each writer saves the snapshot it loaded before the others landed, so the
    index keeps fewer mappings than there are pages and the lost pages lose
    duplicate protection permanently.
    """
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    bodies = [f"concurrent body {index} " + "x" * 4000 for index in range(6)]
    start = time.time() + 4
    procs = [
        _spawn(_WRITE_PAGE_AT, str(start), f"concurrent page {index}", body, root=tmp_path)
        for index, body in enumerate(bodies)
    ]
    _run_all(procs)
    index = json.loads(store._fingerprint_index_path().read_text(encoding="utf-8"))
    assert len(index) == len(bodies)
    assert len(set(index.values())) == len(bodies)


def test_concurrent_promote_and_reject_cannot_decide_same_revision_twice(tmp_path, monkeypatch):
    monkeypatch.setenv("OKS_ROOT", str(tmp_path))
    draft = tmp_path / "drafts" / "same-revision.md"
    draft.parent.mkdir()
    original = b"---\ntitle: Same revision\ndraft_type: concept\ndraft_area: computing\n---\n\nKeep exact review evidence.\n"
    draft.write_bytes(original)
    start = time.time() + 3
    procs = [
        _spawn(_REVIEW_AT, str(start), action, "same-revision", root=tmp_path)
        for action in ("promote", "reject")
    ]
    _run_all(procs)

    from knowledge_studio import draft_review
    digest = __import__("hashlib").sha256(original).hexdigest()
    receipt = draft_review.read_receipt(tmp_path, "same-revision", digest)
    assert receipt["decision"] in {"promoted", "rejected"}
    assert draft.read_bytes() == original
    assert draft_review.read_original(tmp_path, receipt) == original
    assert "same-revision" not in {item["slug"] for item in store.list_drafts()}
