"""Smoke test: oks_connector core imports cleanly after namespace migration.

extractors/web.py 顶层 import trafilatura（可选依赖），不在此测；各提取器
的第三方依赖应是延迟 import，由具体路由触发。
"""
import subprocess
import sys


def test_core_imports():
    import oks_connector
    import oks_connector.raw_bundle_adapter as rba
    import oks_connector.route
    import oks_connector.validator
    import oks_connector.network
    import oks_connector._shared
    import oks_connector.constants
    assert hasattr(rba, "build_parser")
    assert hasattr(rba, "main")


def test_cli_help_runs():
    proc = subprocess.run(
        [sys.executable, "-m", "oks_connector.raw_bundle_adapter", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage" in proc.stdout.lower()


def test_help_survives_legacy_output_encoding():
    import os

    env = dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="cp1252")
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-m", "oks_connector.raw_bundle_adapter", "--help"],
        capture_output=True, env=env, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("cp1252", errors="replace")
    assert b"usage" in proc.stdout.lower()
    assert b"\\u" in proc.stdout  # nonrepresentable text remains recoverable


def test_direct_adapters_run_without_installed_connector(tmp_path):
    """Extraction venvs need not install OKS or the old standalone distribution."""
    from pathlib import Path
    import os
    import oks_connector

    package = Path(oks_connector.__file__).parent
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    for name in ("raw_bundle_adapter.py", "raw_ingest.py"):
        proc = subprocess.run(
            [sys.executable, "-S", str(package / name), "--help"],
            cwd=tmp_path, env=env, capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr


def test_package_import_does_not_pollute_sys_path():
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; before=list(sys.path); import oks_connector; assert sys.path == before"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_builtin_search_does_not_depend_on_distribution_entrypoints(tmp_path, monkeypatch):
    import importlib.metadata
    from knowledge_studio.search import get_backend

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda **kw: ())
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "example.py").write_text("def unique_refund_handler():\n    return True\n")
    backend = get_backend("code", root=str(tmp_path))
    assert backend.search("unique refund handler")
    # Constructing the optional backend must not download or import a model.
    assert get_backend("embedding", root=str(tmp_path))._model is None


def test_legacy_dispatcher_paths_point_to_bundled_files():
    from oks_connector.raw_ingest import ADAPTER, FORMULA_CANDIDATES

    assert ADAPTER.is_file()
    assert FORMULA_CANDIDATES.is_file()
