from knowledge_studio import capability_commands
from knowledge_studio.capability_commands import _check_provider_health, _provider_status


def test_managed_provider_uses_shared_capability_resolution(monkeypatch):
    monkeypatch.delenv("OKS_DOCUMENT_PYTHON", raising=False)
    monkeypatch.setattr(
        "oks_connector.capability_check.is_capability_available",
        lambda name: (name == "document", "/current/python"),
    )
    provider = {
        "id": "markitdown",
        "execution": "managed",
        "requirements": {
            "python_package": "markitdown",
            "env": ["OKS_DOCUMENT_PYTHON"],
        },
    }

    checks = _check_provider_health(provider)

    assert _provider_status(checks, "markitdown", "managed") == "ready"
    assert not [check for check in checks if check["type"] == "env_var"]
    assert any(
        check["type"] == "python_import" and check["available"] is True
        for check in checks
    )


def test_status_scans_once_and_preserves_catalog_and_doctor_results(tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "provider.yaml").write_text(
        "label: Custom provider\n"
        "provides:\n  custom.action: stable\n"
        "requirements: {}\n"
        "known_limits: [local only]\n"
        "user_impact:\n  disk: 0\n"
        "maturity_by_action:\n  custom.action: experimental\n"
        "platforms: [windows]\n",
        encoding="utf-8",
    )
    browser = tmp_path / "browser"
    browser.mkdir()
    (browser / "provider.yaml").write_text(
        "id: browser\nexecution: external\nprovides:\n  custom.action: experimental\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(capability_commands, "_check_provider_health", lambda _provider: [])
    monkeypatch.setattr(capability_commands, "_load_actions_metadata", lambda: {})
    catalog = capability_commands.capability_list(tmp_path)
    doctor = capability_commands.capability_doctor(tmp_path)
    original_scan = capability_commands._scan_providers
    scans = []

    def scan(root):
        scans.append(root)
        return original_scan(root)

    monkeypatch.setattr(capability_commands, "_scan_providers", scan)

    result = capability_commands.capability_status(tmp_path)

    assert scans == [tmp_path]
    assert result["by_action"] == catalog["by_action"] == {
        "custom.action": ["browser", "custom"]
    }
    assert result["overall"] == doctor["overall"] == "healthy"
    assert result["actions"] == {
        "custom.action": {
            "id": "custom.action", "label": "custom.action", "description": ""
        }
    }
    for provider, health in zip(result["providers"], doctor["providers"]):
        assert provider["id"] == health["id"]
        assert provider["status"] == health["status"]
        assert provider["healthy"] == health["healthy"]
    assert result["providers"][0]["status"] == "blocked"
    assert result["providers"][1] == {
        "id": "custom",
        "label": "Custom provider",
        "execution": "unknown",
        "description": "",
        "status": "ready",
        "healthy": True,
        "capabilities": ["custom.action"],
        "known_limits": ["local only"],
        "user_impact": {"disk": "0"},
        "maturity_by_action": {"custom.action": "experimental"},
        "platforms": ["windows"],
    }
