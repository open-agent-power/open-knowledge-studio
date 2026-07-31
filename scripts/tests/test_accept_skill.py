import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "accept" / "scripts" / "accept.py"
SPEC = importlib.util.spec_from_file_location("oks_accept", SCRIPT)
accept = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = accept
SPEC.loader.exec_module(accept)


def test_accept_skill_has_complete_serial_matrix():
    assert accept.ORDER == ("document", "pdf", "formula", "watch")
    assert set(accept.FIXTURES) == set(accept.ORDER)
    assert "feishu" in accept.SUPPORTED_CAPABILITIES


def test_accept_skill_redacts_sensitive_assignment():
    assert "secret-value" not in accept.redact("token=secret-value")
    assert "private-open-id" not in accept.redact('{"openId": "private-open-id"}')
    assert accept.redact("plain output") == "plain output"


def test_accept_skill_path_guard_rejects_sibling(tmp_path):
    root = tmp_path / "runs"
    child = root / "run-a"
    child.mkdir(parents=True)
    assert accept.is_child(child, root)
    assert not accept.is_child(tmp_path / "other", root)


def test_accept_skill_writes_modular_matrix(tmp_path):
    report = accept.Report("document", tmp_path / "run-document", status="passed", cleanup="removed")
    report.commands.append({"command": ["pipx", "install"], "exit_code": 0, "elapsed_seconds": 1, "output": ""})
    report.commands.append({"command": ["oks", "--version"], "exit_code": 0, "elapsed_seconds": 1, "output": ""})
    report.artifacts["isolated_environment_bytes_after_base_install"] = "123"
    report.artifacts["isolated_environment_bytes_after_capability_install"] = "456"
    accept.write_matrix(tmp_path, [report])
    matrix = (tmp_path / "matrix.md").read_text(encoding="utf-8")
    assert "Core CLI: `passed`" in matrix
    assert "| 456 |" in matrix


def test_accept_skill_parses_local_fixture_overrides(tmp_path):
    fixture = tmp_path / "sample.pdf"
    overrides = accept.parse_fixture_overrides([f"pdf={fixture}"])
    assert overrides == {"pdf": fixture.resolve()}


def test_accept_skill_usage_option_is_not_an_external_timeout():
    assert "timeout" not in accept.EXTERNAL_MARKERS
