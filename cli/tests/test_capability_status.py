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
