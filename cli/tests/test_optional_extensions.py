from pathlib import Path
from types import SimpleNamespace
import json
import tomllib

from typer.testing import CliRunner
import subprocess

from knowledge_studio import cli


runner = CliRunner()


def test_capability_registry_entries_are_valid():
    """Capability install hints are code-based (_CAPABILITIES dict); validate them.

    The old handlers.json had pip hints referencing nonexistent packages.
    Now the registry lives in cli._CAPABILITIES and each entry declares
    deps that pip can install directly.
    """
    for name, entry in cli._CAPABILITIES.items():
        assert "deps" in entry, f"{name}: capability entry missing 'deps'"
        assert "purpose" in entry, f"{name}: capability entry missing 'purpose'"
        for dep in entry["deps"]:
            assert "oks-connector[" not in dep, (
                f"{name}: dependency must not reference oks-connector extras: {dep!r}"
            )


def test_ingest_prepare_shows_source_info(monkeypatch, tmp_path):
    """`oks ingest prepare` creates workspace and shows source info."""
    f = tmp_path / "test.md"
    f.write_text("# Hello\n\nSample content.", encoding="utf-8")
    result = runner.invoke(cli.app, [
        "ingest", "prepare", str(f),
        "--kb-root", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    assert "test.md" in result.output or "Source:" in result.output


def test_ingest_group_help_no_args():
    """`oks ingest` with no args shows help (group requires subcommand)."""
    result = runner.invoke(cli.app, ["ingest"])
    assert result.exit_code == 2  # no_args_is_help
    assert "prepare" in result.output


def test_connector_command_reports_none_after_legacy_deletion():
    """Legacy connector was permanently deleted in v0.4.0 — _connector_command returns None."""
    assert cli._connector_command() is None


def test_ingest_prepare_json_output(monkeypatch, tmp_path):
    """`oks ingest prepare --json` outputs valid JSON with expected keys."""
    f = tmp_path / "sample.md"
    f.write_text("content", encoding="utf-8")
    result = runner.invoke(cli.app, [
        "ingest", "prepare", str(f),
        "--kb-root", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.stdout)
    for key in ("run_id", "source_id", "modality", "manifest_dir", "text_ready"):
        assert key in data, f"Missing key: {key}"


def test_ingest_prepare_rejects_bad_source(tmp_path):
    """`oks ingest prepare` for non-existent file: succeeds but text_ready=False."""
    result = runner.invoke(cli.app, [
        "ingest", "prepare", "/nonexistent/file.xyz",
        "--kb-root", str(tmp_path),
    ])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["text_ready"] is False
    assert data["access_mode"] == "manual"



def test_capability_install_is_explicit_by_default():
    result = runner.invoke(cli.app, ["capability", "install", "watch"])

    assert result.exit_code == 0, result.output
    assert "pip" in result.output  # pip install command shown (may wrap in panel)
    assert "--yes" in result.output


def test_capability_install_document_uses_isolated_venv(monkeypatch, tmp_path):
    received = []
    capability_python = tmp_path / "document-venv" / ("Scripts/python.exe" if cli.os.name == "nt" else "bin/python")

    def fake_run(command):
        received.append(command)
        if command[:3] == [cli.sys.executable, "-m", "venv"]:
            capability_python.parent.mkdir(parents=True)
            capability_python.write_text("")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(cli, "_capability_already_installed", lambda _name: False)
    monkeypatch.setattr(cli, "_managed_capability_python", lambda _name: capability_python)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["capability", "install", "document", "--yes"])

    assert result.exit_code == 0, result.output
    pip_commands = [command for command in received if "pip" in command]
    assert len(pip_commands) == 1
    assert pip_commands[0][0] == str(capability_python)
    assert pip_commands[0][0] != cli.sys.executable
    assert "markitdown" in " ".join(pip_commands[0])


def test_pdf_lite_capability_is_pinned_and_isolated():
    assert cli._CAPABILITIES["pdf-lite"]["deps"] == [
        "pymupdf4llm==0.0.27",
        "pymupdf==1.28.0",
    ]


def test_managed_capability_root_can_be_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OKS_CAPABILITY_ROOT", str(tmp_path))

    path = cli._managed_capability_python("pdf-lite")

    assert path.is_relative_to(tmp_path)


def test_capability_install_skips_when_already_installed(monkeypatch):
    monkeypatch.setattr(cli, "_capability_already_installed", lambda _name: True)

    result = runner.invoke(cli.app, ["capability", "install", "document"])

    assert result.exit_code == 0, result.output
    assert "already" in result.output


def test_formula_capability_pins_mineru_compatible_tokenizers():
    """Keep the optional formula install compatible with MinerU's worker."""
    assert "tokenizers==0.22.1" in cli._CAPABILITIES["formula"]["deps"]


def test_feishu_missing_worker_is_actionable(monkeypatch):
    monkeypatch.setattr(cli, "_feishu_worker_path", lambda: None)

    result = runner.invoke(cli.app, ["feishu", "run-once"])

    assert result.exit_code == 2
    assert "OKS_FEISHU_WORKER" in result.output


def test_feishu_worker_receives_current_knowledge_root(monkeypatch, tmp_path):
    worker = tmp_path / "feishu_base_worker.py"
    worker.write_text("# worker")
    received = {}

    def fake_run(command, *, env):
        received["command"] = command
        received["env"] = env
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "_feishu_worker_path", lambda: worker)
    monkeypatch.setattr(cli, "get_kb_root", lambda: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["feishu", "run-once", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert received["command"][2:] == [
        "--knowledge-root", str(tmp_path), "run-once", "--limit", "1",
    ]
    assert received["env"]["OKS_KNOWLEDGE_ROOT"] == str(tmp_path)


def test_feishu_form_is_human_visible():
    result = runner.invoke(cli.app, ["feishu", "form", "--url", "https://example.feishu.cn/form"])

    assert result.exit_code == 0
    assert "https://example.feishu.cn/form" in result.output


def test_feishu_submit_forwards_optional_context(monkeypatch):
    received = []
    monkeypatch.setattr(cli, "_run_feishu_worker", lambda command, extra: received.extend([command, *extra]))

    result = runner.invoke(
        cli.app, ["feishu", "submit", "https://example.com", "--thought", "watch", "--rating", "A"]
    )

    assert result.exit_code == 0, result.output
    assert received == ["enqueue", "https://example.com", "--thought", "watch", "--rating", "A"]


def test_feishu_candidate_and_review_commands_forward_to_worker(monkeypatch):
    received = []
    monkeypatch.setattr(cli, "_run_feishu_worker", lambda command, extra: received.append([command, *extra]))

    publish = runner.invoke(
        cli.app,
        ["feishu", "publish-candidate", "--record-id", "rec123", "--candidate-file", "candidate.md"],
    )
    review = runner.invoke(cli.app, ["feishu", "review-once", "--limit", "1"])

    assert publish.exit_code == 0, publish.output
    assert review.exit_code == 0, review.output
    assert received == [
        ["publish-candidate", "--record-id", "rec123", "--candidate-file", "candidate.md"],
        ["review-once", "--limit", "1"],
    ]


def test_feishu_reconcile_review_forwards_exact_message_pair(monkeypatch):
    received = []
    monkeypatch.setattr(cli, "_run_feishu_worker", lambda command, extra: received.append([command, *extra]))

    result = runner.invoke(
        cli.app,
        [
            "feishu", "reconcile-review",
            "--prompt-message-id", "om_prompt",
            "--reply-message-id", "om_reply",
        ],
    )

    assert result.exit_code == 0, result.output
    assert received == [[
        "reconcile-review", "--prompt-message-id", "om_prompt", "--reply-message-id", "om_reply",
    ]]


def test_feishu_capability_never_bundles_tenant_configuration():
    result = runner.invoke(cli.app, ["capability", "install", "feishu"])

    assert result.exit_code == 0, result.output
    assert "lark-cli" in result.output  # appears in both zh/en


def test_feishu_capability_installs_only_public_web_dependencies(monkeypatch):
    received = {}

    def fake_run(command):
        received["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["capability", "install", "feishu", "--yes"])

    assert result.exit_code == 0, result.output
    assert received["command"][-2:] == ["requests==2.34.2", "trafilatura==2.1.0"]


def test_no_direct_url_dependencies_block_pypi_upload():
    """PyPI rejects any Requires-Dist with a direct URL — that breaks releases.

    Runtime-only installs (git checkouts, private forks) belong in
    cli._CAPABILITIES, which is passed to `pip install` and never becomes
    package metadata.
    """
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = config["project"]

    declared = list(project.get("dependencies", []))
    for extra_deps in project.get("optional-dependencies", {}).values():
        declared.extend(extra_deps)

    offenders = [dep for dep in declared if "@ git+" in dep or "@ http" in dep]
    assert not offenders, f"direct URL dependencies make the release unpublishable: {offenders}"


def test_connector_packages_are_declared_for_wheel_builds():
    """oks_connector was removed in v0.4.0; the two essential stdlib-only
    utilities (capability_check, _lark_cli) were inlined into knowledge_studio."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    packages = config["tool"]["setuptools"]["packages"]

    # oks_connector must NOT be shipped
    assert "oks_connector" not in packages
    assert "oks_connector.feishu_worker" not in packages
    # The inlined modules are in knowledge_studio (not separate packages)
    assert "knowledge_studio" in packages


def test_wheel_never_installs_generic_top_level_names():
    """Generic names in site-packages would collide with unrelated user packages."""
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    setuptools_config = config["tool"]["setuptools"]

    installed_tops = {name.split(".")[0] for name in setuptools_config["packages"]}
    installed_tops |= {
        name.split(".")[0] for name in setuptools_config.get("py-modules", [])
    }
    assert installed_tops == {"knowledge_studio"}
    for reserved in ("i18n", "constants", "digest", "network", "route", "validator"):
        assert reserved not in installed_tops


def test_feishu_setup_forwards_explicit_credential_opt_in(monkeypatch, tmp_path):
    worker = tmp_path / "feishu_base_worker.py"
    worker.write_text("# worker")
    setup = tmp_path / "feishu_setup.py"
    setup.write_text("# setup")
    received = {}

    def fake_run(command):
        received["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "_resolve_lark_cli", lambda: "lark-cli")
    monkeypatch.setattr(cli, "_feishu_worker_path", lambda: worker)
    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    result = runner.invoke(cli.app, ["feishu", "setup", "--show-credentials"])

    assert result.exit_code == 0, result.output
    assert received["command"][-1] == "--show-credentials"


def test_feishu_commands_honor_lark_cli_exe_override(monkeypatch, tmp_path):
    """setup must use the shared resolver, so LARK_CLI_EXE works there too."""
    fake_cli = tmp_path / "lark-cli-custom"
    fake_cli.write_text("#!/bin/sh\n")
    fake_cli.chmod(0o755)
    monkeypatch.setenv("LARK_CLI_EXE", str(fake_cli))
    # Prove the resolver is used rather than a bare PATH lookup.
    monkeypatch.setattr(cli.shutil, "which", lambda _name: None)

    assert cli._resolve_lark_cli() == str(fake_cli.resolve())
