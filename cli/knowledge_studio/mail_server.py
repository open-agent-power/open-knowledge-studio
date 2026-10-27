"""Opt-in managed Mail server detached from a terminal or Windows host Job."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import traceback
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import uuid

from knowledge_studio import store


def _paths(root: Path, port: int):
    root = root.expanduser().resolve()
    if not root.is_dir() or not 1 <= port <= 65535:
        raise ValueError("Choose an existing instance and a port between 1 and 65535")
    directory = root / ".oks/mail-web"
    files = {key: directory / f"{port}.{key}" for key in ("json", "stop", "log", "lock")}
    for path in [root / ".oks", directory, *files.values()]:
        if path.is_symlink() or path.is_junction():
            raise ValueError("Mail runtime path cannot be a symlink or junction")
    return root, files


def _record(root, port, files):
    try:
        if files["json"].stat().st_size > 4096:
            raise ValueError("Mail runtime record exceeds size limit")
        value = json.loads(files["json"].read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (not isinstance(value, dict) or value.get("root") != str(root) or value.get("port") != port
            or not re.fullmatch(r"[0-9a-f]{32}", str(value.get("server_id", "")))
            or value.get("mode") not in {"reader", "collaboration"}):
        raise ValueError("Invalid or mismatched Mail runtime record")
    return value


def _probe(port):
    try:
        # Always connect directly to loopback, regardless of proxy environment.
        with build_opener(ProxyHandler({})).open(
                f"http://127.0.0.1:{port}/api/mail/capabilities", timeout=0.5) as response:
            raw = response.read(65537)
        value = json.loads(raw) if len(raw) <= 65536 else None
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, URLError):
        return None


def _occupied(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def server_status(root: Path, port: int = 3182) -> dict:
    """Probe actual HTTP ownership without creating files or trusting a PID."""
    root, files = _paths(root, port)
    record, caps = _record(root, port, files), _probe(port)
    managed = bool(record and caps and caps.get("server_id") == record["server_id"]
                   and os.path.normcase(str(caps.get("knowledge_base"))) == os.path.normcase(str(root))
                   and caps.get("mode") == record["mode"])
    return {"status": "running" if managed else ("unmanaged" if _occupied(port) else "stopped"),
            "url": f"http://127.0.0.1:{port}/", "root": str(root), "port": port,
            "mode": record["mode"] if managed else None,
            "pid": caps.get("server_pid") if managed else None,
            "server_id": record["server_id"] if managed else None}


def _write(files, record):
    store._atomic_write(files["json"], json.dumps(record, ensure_ascii=True) + "\n")


def _remove_owned(root, port, files, server_id):
    current = _record(root, port, files)
    if current and current["server_id"] == server_id:
        files["json"].unlink(missing_ok=True)
        files["stop"].unlink(missing_ok=True)


def _spawn(root, port, mode, server_id, files):
    package_parent = Path(__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONPATH=str(package_parent), OKS_ROOT=str(root), PYTHONDONTWRITEBYTECODE="1")
    executable = sys.executable
    if os.name == "nt" and sys.prefix != sys.base_prefix:
        # CPython's venv redirector creates a new KILL_ON_JOB_CLOSE Job around
        # the real interpreter. Bypass that wrapper, using its own path handoff
        # so getpath still selects this venv's prefix and site-packages.
        executable = sys._base_executable
        if not Path(executable).is_file():
            raise ValueError("The virtual environment's base Python is unavailable")
        env["__PYVENV_LAUNCHER__"] = sys.executable
    command = [executable, "-B", "-X", "utf8", "-m", "knowledge_studio.mail_server",
               "--root", str(root), "--port", str(port), "--mode", mode, "--server-id", server_id]
    if os.name == "nt":
        return _spawn_windows(command, package_parent, env)
    # No inherited terminal or pipes.
    with files["log"].open("ab") as log:
        return subprocess.Popen(command, cwd=package_parent, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, close_fds=True, start_new_session=True)


class _WindowsWorker:
    """Poll the handle of the process WMI just created; never terminate by PID."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes

        self.pid = pid
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._handle = self._kernel.OpenProcess(0x100000 | 0x1000, False, pid)

    def poll(self):
        import ctypes
        from ctypes import wintypes

        if not self._handle:
            return 1  # It may have exited before OpenProcess, still bounded by readiness.
        waited = self._kernel.WaitForSingleObject(self._handle, 0)
        if waited == 258:  # WAIT_TIMEOUT: still running.
            return None
        code = wintypes.DWORD()
        if waited != 0 or not self._kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise OSError("Cannot query the newly launched Mail worker")
        return code.value

    def __del__(self):
        if getattr(self, "_handle", None):
            self._kernel.CloseHandle(self._handle)


def _spawn_windows(command, cwd, env):
    # WMI creates the process outside the caller's Job chain under the same user.
    # CREATE_BREAKAWAY_FROM_JOB also avoids the provider's own resource Job.
    # Use fixed PowerShell code and a private JSON environment value: paths and
    # environment are never shell code or command-line arguments.
    # Windows executable lookup can otherwise prepend the KB working directory.
    # Search only absolute PATH entries, never an implicitly trusted ./pwsh.exe.
    shell = next((Path(entry) / "pwsh.exe" for entry in os.get_exec_path()
                  if Path(entry).is_absolute() and (Path(entry) / "pwsh.exe").is_file()),
                 Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    script = r"""
$ErrorActionPreference = 'Stop'
$stage = 'configuration'
try {
    $spec = $env:_OKS_MAIL_LAUNCH_SPEC | ConvertFrom-Json
    $stage = 'startup'
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{
        ShowWindow = [uint16]0
        CreateFlags = [uint32]0x01000608
        EnvironmentVariables = [string[]]@($spec.env.PSObject.Properties | ForEach-Object { $_.Name + '=' + [string]$_.Value })
    }
    $stage = 'process_create'
    $created = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = [string]$spec.command
        CurrentDirectory = [string]$spec.cwd
        ProcessStartupInformation = $startup
    }
    @{ code = [int]$created.ReturnValue; pid = [int]$created.ProcessId } | ConvertTo-Json -Compress
} catch {
    # Exception messages/PowerShell diagnostics can contain the launch environment.
    $kind = if ($_.CategoryInfo.Category -eq 'PermissionDenied') { 'access_denied' } else { 'launch_failed' }
    $hresult = $null
    if ([string]$_.FullyQualifiedErrorId -match '^HRESULT (0x[0-9a-fA-F]{8}),') {
        $hresult = $Matches[1]
    }
    @{ error = $kind; stage = $stage; hresult = $hresult } | ConvertTo-Json -Compress
    exit 1
}
"""
    payload = {"command": subprocess.list2cmdline(command), "cwd": str(cwd),
               "env": {**env, "_OKS_MAIL_WMI_STDIO": "1"}}
    try:
        launched = subprocess.run([str(shell), "-NoLogo", "-NoProfile", "-NonInteractive",
                                   "-WindowStyle", "Hidden", "-Command", script],
                                  env={**os.environ, "_OKS_MAIL_LAUNCH_SPEC": json.dumps(payload, ensure_ascii=True)},
                                  capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=15,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Windows WMI launch timed out; foreground serve remains available") from None
    hint = "; foreground serve remains available"
    try:
        result = json.loads(launched.stdout.lstrip("\ufeff"))
        if not isinstance(result, dict):
            raise ValueError("Expected an object")
    except ValueError:
        reason = "could not launch Mail" if launched.returncode else "did not confirm a Mail process"
        raise RuntimeError("Windows WMI " + reason + hint) from None
    if launched.returncode:
        # Only fixed labels and a strictly validated HRESULT may leave this boundary.
        reason = "access denied" if result.get("error") == "access_denied" else "could not launch Mail"
        stage = result.get("stage")
        stages = {"configuration": "launch configuration", "startup": "startup setup",
                  "process_create": "process creation"}
        if isinstance(stage, str) and stage in stages:
            reason += " during " + stages[stage]
        hresult = result.get("hresult")
        if isinstance(hresult, str) and re.fullmatch(r"0x[0-9a-fA-F]{8}", hresult):
            reason += " (" + hresult + ")"
        raise RuntimeError("Windows WMI " + reason + hint)
    code, pid = result.get("code"), result.get("pid")
    if "error" in result or type(code) is not int or not 0 <= code <= 0xFFFFFFFF:
        raise RuntimeError("Windows WMI did not confirm a Mail process" + hint)
    if code:
        reason = {2: "access denied", 3: "insufficient privilege",
                  9: "path not found", 21: "invalid parameter"}.get(code, "process creation failed")
        raise RuntimeError(f"Windows WMI {reason} (return code {code})" + hint)
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
        raise RuntimeError("Windows WMI did not confirm a Mail process" + hint)
    return _WindowsWorker(result["pid"])


def start_background(root: Path, port: int = 3182, *, mode: str = "reader", timeout: float = 10) -> dict:
    from knowledge_studio.mail_setup import validate_root

    if mode not in {"reader", "collaboration"}:
        raise ValueError("Choose reader or collaboration mode")
    root = validate_root(root)
    root, files = _paths(root, port)
    files["json"].parent.mkdir(parents=True, exist_ok=True)
    with store._file_lock(files["lock"]):
        state = server_status(root, port)
        if state["status"] == "running":
            if state["mode"] != mode:
                raise ValueError("Managed server mode differs; stop it before restarting")
            return {**state, "reused": True}
        if state["status"] == "unmanaged":
            raise ValueError("Port occupied by an unmanaged server; choose another port")
        server_id = uuid.uuid4().hex
        record = {"root": str(root), "port": port, "mode": mode, "server_id": server_id, "pid": None}
        files["stop"].unlink(missing_ok=True)
        _write(files, record)
        try:
            child = _spawn(root, port, mode, server_id, files)
        except (OSError, ValueError, RuntimeError):
            _remove_owned(root, port, files, server_id)
            raise
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = server_status(root, port)
            if state["status"] == "running" and state["server_id"] == server_id:
                record["pid"] = state["pid"]
                _write(files, record)
                return {**state, "reused": False}
            if child.poll() is not None:
                break
            time.sleep(0.1)
        store._atomic_write(files["stop"], server_id)
        raise RuntimeError(f"Background Mail did not become ready; inspect {files['log']}")


def stop_background(root: Path, port: int = 3182, *, timeout: float = 10) -> dict:
    root, files = _paths(root, port)
    if not files["json"].exists():
        return server_status(root, port)
    with store._file_lock(files["lock"]):
        state = server_status(root, port)
        if state["status"] != "running":
            if state["status"] == "stopped":
                record = _record(root, port, files)
                if record:
                    _remove_owned(root, port, files, record["server_id"])
            return state
        store._atomic_write(files["stop"], state["server_id"])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _probe(port):
                _remove_owned(root, port, files, state["server_id"])
                return {**state, "status": "stopped", "pid": None}
            time.sleep(0.1)
        raise RuntimeError("Managed Mail server has not stopped; no PID was killed")


def serve_worker(root: Path, port: int, mode: str, server_id: str):
    from knowledge_studio.mail_web import create_server

    root, files = _paths(root, port)
    record = _record(root, port, files)
    if not record or record["server_id"] != server_id:
        raise ValueError("Background launch record is no longer current")
    server = None
    try:
        server = create_server(root, port, mode=mode)
        server.background_id = server_id
        server.background_pid = os.getpid()
        server.timeout = 0.2
        while True:
            current = _record(root, port, files)
            if not current or current["server_id"] != server_id:
                break
            if files["stop"].exists() and files["stop"].read_text(encoding="utf-8") == server_id:
                break
            server.handle_request()
    finally:
        if server:
            server.server_close()
        # Only the controlling CLI writes/removes the shared port record while
        # holding its lock. A late old worker cannot overwrite a new launch.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--mode", choices=["reader", "collaboration"], required=True)
    parser.add_argument("--server-id", required=True)
    args = parser.parse_args()
    if os.environ.get("_OKS_MAIL_WMI_STDIO") == "1":
        _root, files = _paths(args.root, args.port)
        with files["log"].open("a", encoding="utf-8", buffering=1) as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    serve_worker(args.root, args.port, args.mode, args.server_id)
                except Exception:
                    traceback.print_exc()
                    raise SystemExit(1) from None
        return
    serve_worker(args.root, args.port, args.mode, args.server_id)


if __name__ == "__main__":
    main()
