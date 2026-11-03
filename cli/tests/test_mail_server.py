"""Managed background Mail lifecycle, independent of the launching process."""
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

import pytest
from typer.testing import CliRunner

from knowledge_studio.cli import app
from knowledge_studio.mail_web import create_server
from knowledge_studio import mail_server


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def instance(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "mail").mkdir()
    yield tmp_path
    # Pytest captures this output unless a test fails. Keep detached-worker
    # diagnostics from this synthetic instance available on CI failures.
    for log in (tmp_path / ".oks" / "mail-web").glob("*.log"):
        print(f"\nDetached Mail log ({log.name}):\n{log.read_text(encoding='utf-8', errors='replace')[-8000:]}")


def test_detached_server_survives_launcher_exit_and_stops(instance):
    port = free_port()
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]),
               PYTHONDONTWRITEBYTECODE="1")
    script = ("import json; from pathlib import Path; from knowledge_studio.mail_server import start_background; "
              f"print(json.dumps(start_background(Path({str(instance)!r}),{port})))")
    try:
        launched = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script],
                                  env=env, capture_output=True, text=True, encoding="utf-8", timeout=25)
        assert launched.returncode == 0, launched.stderr
        result = json.loads(launched.stdout)
        assert result["status"] == "running"
        assert mail_server.server_status(instance, port)["status"] == "running"
        with urlopen(f"http://127.0.0.1:{port}/api/mail/capabilities", timeout=3) as response:
            caps = json.load(response)
        assert caps["read_only"] is True
        assert caps["server_id"] == result["server_id"]
        assert not [p for p in (instance / "mail").rglob("*") if p.is_file()]
        assert mail_server.start_background(instance, port)["reused"] is True
        with pytest.raises(ValueError, match="mode differs"):
            mail_server.start_background(instance, port, mode="collaboration")
    finally:
        mail_server.stop_background(instance, port)
    assert mail_server.server_status(instance, port)["status"] == "stopped"


def test_foreign_foreground_server_is_never_adopted_or_stopped(instance, tmp_path):
    server = create_server(instance, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(ValueError, match="occupied|unmanaged"):
            mail_server.start_background(instance, server.server_port)
        assert mail_server.stop_background(instance, server.server_port)["status"] == "unmanaged"
        assert thread.is_alive()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_loopback_startup_does_not_require_reverse_dns(instance, monkeypatch):
    def unavailable(_host):
        raise RuntimeError("Reverse DNS is unavailable")

    monkeypatch.setattr(socket, "getfqdn", unavailable)
    server = create_server(instance, 0)
    try:
        assert server.server_name == "127.0.0.1"
        assert server.server_port == server.server_address[1]
    finally:
        server.server_close()


def test_other_instance_cannot_reuse_or_stop_owner(instance, tmp_path):
    other = tmp_path / "other"
    (other / "wiki").mkdir(parents=True)
    (other / "mail").mkdir()
    port = free_port()
    try:
        mail_server.start_background(instance, port)
        with pytest.raises(ValueError, match="occupied|unmanaged"):
            mail_server.start_background(other, port)
        assert mail_server.stop_background(other, port)["status"] == "unmanaged"
        # Even a copied PID/token cannot make another instance own this server.
        forged = json.loads((instance / f".oks/mail-web/{port}.json").read_text("utf-8"))
        forged["root"] = str(other.resolve())
        record = other / f".oks/mail-web/{port}.json"
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(forged), encoding="utf-8")
        assert mail_server.stop_background(other, port)["status"] == "unmanaged"
        assert mail_server.server_status(instance, port)["status"] == "running"
    finally:
        mail_server.stop_background(instance, port)


def test_cli_status_and_stop_are_nonblocking(instance):
    runner = CliRunner()
    for action in ["--status", "--stop"]:
        result = runner.invoke(app, ["mail", "serve", action, "--path", str(instance), "--port", str(free_port())])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "stopped"
    invalid = runner.invoke(app, ["mail", "serve", "--background", "--stop", "--path", str(instance)])
    assert invalid.exit_code == 2
    assert not (instance / ".oks").exists()


def test_runtime_state_symlink_cannot_redirect_writes(instance, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = instance / ".oks"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="symlink|junction"):
        mail_server.start_background(instance, free_port())
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(os.name != "nt" or sys.prefix == sys.base_prefix,
                    reason="Windows virtual-environment redirector")
def test_windows_worker_has_no_venv_wrapper_and_keeps_its_environment(instance, monkeypatch):
    # A venv python.exe redirector creates its own KILL_ON_JOB_CLOSE Job,
    # even when Popen has already requested breakaway from the outer host.
    spawn = mail_server._spawn_windows
    spawned = []

    def capture(command, cwd, env):
        child = spawn(command, cwd, env)
        spawned.append((child, command, {"cwd": cwd, "env": env}))
        return child

    monkeypatch.setattr(mail_server, "_spawn_windows", capture)
    port = free_port()
    try:
        result = mail_server.start_background(instance, port)
        child, command, options = spawned[0]
        assert result["pid"] == child.pid, "The server must be the detached process itself"
        # Probe the exact interpreter/environment selected for the detached worker.
        code = "import json,sys; print(json.dumps([sys.executable,sys.prefix,sys.base_prefix]))"
        probe = subprocess.run([command[0], "-B", "-X", "utf8", "-c", code],
                               cwd=options["cwd"], env=options["env"], capture_output=True,
                               text=True, encoding="utf-8", timeout=10)
        assert probe.returncode == 0, probe.stderr
        assert json.loads(probe.stdout) == [sys.executable, sys.prefix, sys.base_prefix]
        assert child.poll() is None
    finally:
        mail_server.stop_background(instance, port)


@pytest.mark.skipif(os.name != "nt", reason="Windows structured WMI launch")
def test_windows_launch_treats_unicode_and_shell_characters_as_literal_paths(instance):
    root = instance / "共享 空格 ' $(exit 99)"
    for name in ["wiki", "drafts", "mail"]:
        (root / name).mkdir(parents=True, exist_ok=True)
    port = free_port()
    try:
        result = mail_server.start_background(root, port)
        assert result["status"] == "running"
        assert result["root"] == str(root.resolve())
        assert mail_server.start_background(root, port)["reused"] is True
    finally:
        mail_server.stop_background(root, port)
    assert mail_server.server_status(root, port)["status"] == "stopped"


@pytest.mark.skipif(os.name != "nt", reason="Windows Job lifecycle")
@pytest.mark.parametrize("backend", ["direct-control", "wmi"])
def test_server_survives_actual_launcher_job_termination(instance, backend):
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                    ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6),
                    ("memory", ctypes.c_size_t * 4)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    assert job
    limits = Extended()
    limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE, without permission to break away.
    assert kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits))
    port = free_port()
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONDONTWRITEBYTECODE="1")
    direct = ("def direct(command, cwd, env):\n"
              f"    with open({str(instance / f'.oks/mail-web/{port}.log')!r}, 'ab') as log:\n"
              "        return mail_server.subprocess.Popen(command, cwd=cwd, env=env, "
              "stdin=mail_server.subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, "
              "creationflags=mail_server.subprocess.DETACHED_PROCESS|mail_server.subprocess.CREATE_NEW_PROCESS_GROUP)\n"
              "mail_server._spawn_windows=direct\n")
    script = ("import sys,json; from pathlib import Path; from knowledge_studio import mail_server; "
              + (f"exec({direct!r}); " if backend == "direct-control" else "") +
              "sys.stdin.readline(); "
              f"print(json.dumps(mail_server.start_background(Path({str(instance)!r}),{port})),flush=True); "
              "sys.stdin.readline(); print('UNEXPECTED_NORMAL_EXIT',flush=True)")
    # Do not let a traceback fill a pipe while waiting for the readiness line.
    launcher_errors = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    launcher = subprocess.Popen([sys.executable, "-B", "-X", "utf8", "-c", script],
                                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=launcher_errors,
                                text=True, encoding="utf-8")
    try:
        assert kernel.AssignProcessToJobObject(job, int(launcher._handle))
        launcher.stdin.write("start\n")
        launcher.stdin.flush()
        ready = launcher.stdout.readline()
        if not ready:
            launcher.wait(timeout=5)
            launcher_errors.seek(0)
            pytest.fail(f"Mail launcher exited with code {launcher.returncode} before readiness:\n"
                        + launcher_errors.read())
        result = json.loads(ready)
        assert result["status"] == "running"
        assert launcher.poll() is None  # Still blocked on its open stdin pipe.
        kernel.CloseHandle(job)
        job = None
        launcher.wait(timeout=5)
        # Windows can report exit code 0 for Job-close termination. The blocked
        # launcher exited without executing its normal-exit sentinel instead.
        assert "UNEXPECTED_NORMAL_EXIT" not in launcher.stdout.read()
        if backend == "wmi":
            assert mail_server.server_status(instance, port)["status"] == "running"
        else:
            deadline = time.monotonic() + 3
            while mail_server.server_status(instance, port)["status"] != "stopped" and time.monotonic() < deadline:
                time.sleep(0.1)
            assert mail_server.server_status(instance, port)["status"] == "stopped"
    finally:
        if job:
            kernel.CloseHandle(job)
        if launcher.poll() is None:
            launcher.terminate()
            launcher.wait(timeout=5)
        for stream in [launcher.stdin, launcher.stdout, launcher_errors]:
            stream.close()
        mail_server.stop_background(instance, port)


@pytest.mark.skipif(os.name != "nt", reason="Windows WMI bridge")
@pytest.mark.parametrize("failure", ["timeout", "denied", "malformed"])
def test_wmi_launch_failure_is_clear_and_does_not_echo_environment(instance, monkeypatch, failure):
    from types import SimpleNamespace
    monkeypatch.setenv("OKS_TEST_SECRET", "must-not-appear-in-errors")

    def run(command, **options):
        payload = json.loads(options["env"]["_OKS_MAIL_LAUNCH_SPEC"])
        assert payload["env"]["OKS_TEST_SECRET"] == "must-not-appear-in-errors"
        assert "must-not-appear-in-errors" not in " ".join(command)
        assert "-WindowStyle" in command and "Hidden" in command
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 15, stderr="must-not-appear-in-errors")
        return SimpleNamespace(returncode=0 if failure == "malformed" else 1,
                               stdout="not json", stderr="must-not-appear-in-errors")

    monkeypatch.setattr(mail_server.subprocess, "run", run)
    with pytest.raises(RuntimeError) as error:
        mail_server.start_background(instance, free_port())
    assert "foreground serve remains available" in str(error.value)
    assert "must-not-appear-in-errors" not in str(error.value)
    assert not list((instance / ".oks/mail-web").glob("*.json"))


@pytest.mark.skipif(os.name != "nt", reason="Windows executable search")
def test_wmi_bridge_does_not_execute_a_shell_from_the_knowledge_directory(instance, monkeypatch):
    from types import SimpleNamespace
    (instance / "pwsh.exe").write_text("untrusted KB file", encoding="utf-8")
    monkeypatch.chdir(instance)
    monkeypatch.setenv("PATH", ".")

    def run(command, **options):
        assert Path(command[0]).is_absolute()
        assert Path(command[0]).parent != instance
        return SimpleNamespace(returncode=0, stdout='{"code":0,"pid":1234}', stderr="")

    monkeypatch.setattr(mail_server.subprocess, "run", run)
    monkeypatch.setattr(mail_server, "_WindowsWorker", lambda pid: pid)
    assert mail_server._spawn_windows([sys.executable], instance, dict(os.environ)) == 1234


@pytest.mark.skipif(os.name != "nt", reason="Windows WMI bridge")
@pytest.mark.parametrize(("reply", "returncode", "expected"), [
    ({"error": "access_denied", "stage": "process_create", "hresult": "0x80041003"}, 1,
     "access denied during process creation (0x80041003)"),
    ({"code": 2, "pid": 0}, 0, "access denied (return code 2)"),
    ({"code": 3, "pid": 0}, 0, "insufficient privilege (return code 3)"),
    ({"code": 9, "pid": 0}, 0, "path not found (return code 9)"),
    ({"code": 21, "pid": 0}, 0, "invalid parameter (return code 21)"),
    ({"code": 8, "pid": 0}, 0, "process creation failed (return code 8)"),
])
def test_wmi_structured_failure_preserves_reason_without_environment(instance, monkeypatch, reply, returncode, expected):
    from types import SimpleNamespace
    secret = "must-not-appear-in-errors"
    reply = {**reply, "message": secret, "environment": {"secret": secret}}
    monkeypatch.setattr(mail_server.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=returncode, stdout=json.dumps(reply), stderr=secret))
    with pytest.raises(RuntimeError, match=re.escape(expected)) as error:
        mail_server.start_background(instance, free_port())
    assert secret not in str(error.value)
    assert "foreground serve remains available" in str(error.value)
    assert not list((instance / ".oks/mail-web").glob("*.json"))


@pytest.mark.skipif(os.name != "nt", reason="Windows WMI bridge")
@pytest.mark.parametrize(("reply", "returncode"), [
    (None, 0), ([], 0), ("secret", 0), ({}, 0),
    ({"code": False, "pid": 1234}, 0),
    ({"code": 0, "pid": True}, 0),
    ({"code": 0, "pid": 0}, 0),
    ({"code": "secret", "pid": 1234}, 0),
    ({"code": -1, "pid": 1234}, 0),
    ({"code": 0, "pid": 0x100000000}, 0),
    ({"error": "secret", "code": 0, "pid": 1234}, 0),
    ({"code": 0, "pid": 1234}, 1),
    ({"error": "secret", "stage": "secret", "hresult": "secret"}, 1),
    ({"error": "access_denied", "stage": ["secret"], "hresult": "secret"}, 1),
])
def test_wmi_invalid_reply_is_sanitized_and_never_adopted(instance, monkeypatch, reply, returncode):
    from types import SimpleNamespace
    monkeypatch.setattr(mail_server.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=returncode, stdout=json.dumps(reply), stderr="secret"))
    monkeypatch.setattr(mail_server, "_WindowsWorker", lambda pid: pytest.fail("Invalid reply adopted"))
    with pytest.raises(RuntimeError) as error:
        mail_server._spawn_windows([sys.executable], instance, dict(os.environ))
    assert "secret" not in str(error.value)
    assert "foreground serve remains available" in str(error.value)
