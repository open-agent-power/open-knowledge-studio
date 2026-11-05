import hashlib
import json
import pytest
from knowledge_studio import evaluation_feedback as feedback, studio_evaluation as ev


@pytest.fixture
def root(tmp_path):
    (tmp_path / "wiki").mkdir()
    for slug in ["yes", "no", "unknown"]:
        (tmp_path / "wiki" / f"{slug}.md").write_text(f"# {slug}\nsource evidence")
    return tmp_path


def observed(root):
    feedback.configure(root, {"values": {"capture_enabled": True}})
    return feedback.capture(
        root, "original query", [{"slug": s} for s in ["yes", "no", "unknown"]]
    )


def test_missing_feedback_and_use_are_not_negative_or_human_gold(root):
    identifier = observed(root)
    feedback.record_use(root, "yes", identifier)
    value = feedback.candidate(root, identifier)
    assert value["review"] is None and len(value["signals"]) == 1
    assert value["adoption"] == "unknown"  # no general adoption claimed for every hit
    with pytest.raises(ValueError, match="No confirmed"):
        feedback.export(root, {"name": "gold"})
    assert "original query" not in json.dumps(feedback.observations(root))


def test_reject_requires_confirmation_and_reason_and_unknown_stays_unlabeled(root):
    identifier = observed(root)
    request = {
        "id": identifier,
        "query": "original query",
        "accept": ["yes"],
        "reject": ["no"],
    }
    with pytest.raises(ValueError, match="confirmation"):
        feedback.review(root, request)
    request["confirm"] = True
    with pytest.raises(ValueError, match="reason"):
        feedback.review(root, request)
    request["reason"] = "Unrelated instruction"
    value = feedback.review(root, request)
    assert set(value["review"]["decisions"]) == {"yes", "no"}
    exported = feedback.export(root, {"name": "My labels", "kind": "preference"})
    pairs = [
        json.loads(line)
        for line in ev.path(root, exported["path"]).read_text().splitlines()
    ]
    assert (
        len(pairs) == 1
        and pairs[0]["chosen"]["slug"] == "yes"
        and pairs[0]["rejected"]["slug"] == "no"
    )
    assert len(pairs[0]["chosen"]["source_sha256"]) == 64
    dataset = feedback.export(root, {"name": "My eval"})
    assert dataset["case_count"] == 1


def test_changed_query_and_source_need_explicit_review(root):
    identifier = observed(root)
    request = {
        "id": identifier,
        "query": "changed query",
        "accept": ["yes"],
        "confirm": True,
    }
    with pytest.raises(ValueError, match="derived query"):
        feedback.review(root, request)
    request["derived_query"] = True
    feedback.review(root, request)
    (root / "wiki/yes.md").write_text("# different version")
    with pytest.raises(ValueError, match="source changed"):
        feedback.export(root, {"name": "stale"})


def test_unbound_use_is_preserved_without_guessing_query(root):
    feedback.record_use(root, "yes")
    values = feedback.candidates(root)["items"]
    assert (
        len(values) == 1 and values[0]["query"] is None and values[0]["review"] is None
    )
    with pytest.raises(ValueError, match="derived query"):
        feedback.review(
            root,
            {
                "id": values[0]["id"],
                "query": "human reconstruction",
                "accept": ["yes"],
                "confirm": True,
            },
        )


def test_review_api_requires_local_edit_and_explicit_origin(root):
    import threading
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from knowledge_studio.mail_web import create_server

    (root / "mail").mkdir()
    identifier = observed(root)
    for editable in [False, True]:
        server = create_server(root, 0, local_edit=editable)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        payload = json.dumps(
            {
                "id": identifier,
                "query": "original query",
                "accept": ["yes"],
                "confirm": True,
                "expected_knowledge_base": str(root),
            }
        ).encode()

        def request(headers):
            return urlopen(
                Request(
                    origin + "/api/evaluation/review",
                    data=payload,
                    headers={"Content-Type": "application/json", **headers},
                ),
                timeout=5,
            )

        try:
            with pytest.raises(HTTPError) as exc:
                request({})
            assert exc.value.code == 403
            if editable:
                with request({"Origin": origin}) as response:
                    assert (
                        json.load(response)["review"]["decisions"]["yes"]["decision"]
                        == "accepted"
                    )
            else:
                with pytest.raises(HTTPError) as exc:
                    request({"Origin": origin})
                assert exc.value.code == 403
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


def test_recall_trace_is_reviewable_and_extended_capture_deduplicates(root):
    from knowledge_studio.vfs_observation import _save

    trace = {
        "id": "trace-one",
        "kind": "recall",
        "at": "2026-11-05T00:00:00Z",
        "query_sha256": hashlib.sha256(b"q").hexdigest(),
        "hits": [{"slug": "yes"}],
    }
    _save(root, trace)
    assert feedback.candidate(root, "trace-one")["review"] is None
    feedback.configure(root, {"values": {"capture_enabled": True}})
    assert (
        feedback.capture(root, "q", [{"slug": "yes"}], {"call_trace": trace})
        == "trace-one"
    )
    assert len(feedback.candidates(root)["items"]) == 1
