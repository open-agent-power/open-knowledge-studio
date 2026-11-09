"""Atomic snapshot replacement under transient and permanent Windows locks."""
import json
import os
import stat
from threading import Event, Thread
import time

import pytest

from knowledge_studio import store


@pytest.fixture
def write_snapshot():
    return lambda path, value: store._atomic_write(path, json.dumps(value))


@pytest.mark.skipif(os.name != "nt", reason="Windows reader sharing semantics")
@pytest.mark.parametrize("release_on_failure", [True, False])
def test_reader_collision_recovers_or_fails_with_intact_json(tmp_path, monkeypatch, write_snapshot, release_on_failure):
    target = tmp_path / "job.json"
    original, updated = {"status": "queued"}, {"status": "running"}
    write_snapshot(target, original)
    opened, failed, release = Event(), Event(), Event()
    observations = []

    def reader():
        with target.open("rb") as stream:
            observations.append(json.load(stream))
            opened.set()
            assert (failed if release_on_failure else release).wait(5)

    thread = Thread(target=reader)
    thread.start()
    replace = os.replace
    errors = []

    def observed_replace(source, destination):
        try:
            return replace(source, destination)
        except PermissionError as exc:
            errors.append(exc.winerror)
            failed.set()
            raise

    monkeypatch.setattr(os, "replace", observed_replace)
    started = time.monotonic()
    try:
        assert opened.wait(5)
        if release_on_failure:
            write_snapshot(target, updated)
        else:
            with pytest.raises(PermissionError) as exc:
                write_snapshot(target, updated)
            assert exc.value.winerror == 5
        assert errors and set(errors) == {5}
        assert observations == [original]
        assert json.loads(target.read_text()) == (updated if release_on_failure else original)
        assert list(tmp_path.iterdir()) == [target]
    finally:
        release.set()
        failed.set()
        thread.join(5)
    assert not thread.is_alive()
    assert time.monotonic() - started < 2


@pytest.mark.skipif(os.name != "nt", reason="Windows readonly attributes")
def test_persistent_access_denial_preserves_original_and_cleans_temporary(tmp_path, write_snapshot):
    target = tmp_path / "job.json"
    original = {"status": "queued"}
    write_snapshot(target, original)
    target.chmod(stat.S_IREAD)
    started = time.monotonic()
    try:
        with pytest.raises(PermissionError) as exc:
            write_snapshot(target, {"status": "running"})
        assert exc.value.winerror == 5
        assert json.loads(target.read_text()) == original
        assert list(tmp_path.iterdir()) == [target]
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert time.monotonic() - started < 2


def test_other_io_errors_propagate_without_retry(tmp_path, monkeypatch, write_snapshot):
    target = tmp_path / "job.json"
    write_snapshot(target, {"status": "queued"})
    errors = []

    def fail(source, destination):
        error = FileNotFoundError("missing target directory")
        errors.append(error)
        raise error

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(FileNotFoundError) as exc:
        write_snapshot(target, {"status": "running"})
    assert errors == [exc.value]
    assert json.loads(target.read_text()) == {"status": "queued"}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name != "nt", reason="Windows error codes")
def test_simulated_transient_access_denial_retries_then_replaces(tmp_path, monkeypatch, write_snapshot):
    target = tmp_path / "job.json"
    write_snapshot(target, {"status": "queued"})
    replace = os.replace
    attempts = []

    def interrupted(source, destination):
        attempts.append(True)
        if len(attempts) <= 2:
            raise PermissionError(13, "file is being read", None, 5)
        return replace(source, destination)

    monkeypatch.setattr(os, "replace", interrupted)
    write_snapshot(target, {"status": "running"})
    assert len(attempts) == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "running"}
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(os.name != "nt", reason="Windows error codes")
def test_other_windows_permission_errors_are_not_retried(tmp_path, monkeypatch, write_snapshot):
    target = tmp_path / "job.json"
    write_snapshot(target, {"status": "queued"})
    attempts = []

    def fail(source, destination):
        attempts.append(True)
        raise PermissionError(13, "other denial", None, 32)

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(PermissionError) as error:
        write_snapshot(target, {"status": "running"})
    assert error.value.winerror == 32
    assert len(attempts) == 1
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "queued"}
    assert list(tmp_path.iterdir()) == [target]
