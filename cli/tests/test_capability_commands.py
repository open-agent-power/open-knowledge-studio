import pytest

from knowledge_studio import capability_commands


def _command_check(name: str, available: bool) -> dict:
    return {
        "type": "command",
        "name": name,
        "available": available,
        "path": f"/usr/bin/{name}" if available else None,
        "suggestion": None if available else f"Install {name}",
    }


def test_optional_command_failure_does_not_mark_doctor_unhealthy(
    tmp_path, monkeypatch
):
    provider = {
        "id": "yt-dlp",
        "label": "yt-dlp",
        "execution": "managed",
        "requirements": {
            "command": "yt-dlp",
            "optional_commands": ["ffmpeg"],
        },
    }
    availability = {"yt-dlp": True, "ffmpeg": False}
    monkeypatch.setattr(
        capability_commands, "_scan_providers", lambda _root: [provider]
    )
    monkeypatch.setattr(
        capability_commands,
        "_check_command",
        lambda name: _command_check(name, availability[name]),
    )

    result = capability_commands.capability_doctor(tmp_path)

    provider_result = result["providers"][0]
    optional_check = next(
        check for check in provider_result["checks"] if check["name"] == "ffmpeg"
    )
    assert provider_result["status"] == "ready"
    assert provider_result["healthy"] is True
    assert result["overall"] == "healthy"
    assert optional_check["available"] is False
    assert optional_check["required"] is False


def test_required_command_failure_still_marks_doctor_unhealthy(
    tmp_path, monkeypatch
):
    provider = {
        "id": "local-tool",
        "label": "Local Tool",
        "execution": "managed",
        "requirements": {"command": "required-tool"},
    }
    monkeypatch.setattr(
        capability_commands, "_scan_providers", lambda _root: [provider]
    )
    monkeypatch.setattr(
        capability_commands,
        "_check_command",
        lambda name: _command_check(name, False),
    )

    result = capability_commands.capability_doctor(tmp_path)

    provider_result = result["providers"][0]
    assert provider_result["status"] == "unavailable"
    assert provider_result["healthy"] is False
    assert result["overall"] == "issues_found"


def test_catalog_yaml_preserves_scalar_strings_and_yaml_structure(tmp_path):
    path = tmp_path / "provider.yaml"
    path.write_text(
        "id: 001\n"
        "enabled: true\n"
        "validated: 2026-08-06\n"
        "missing: null\n"
        "cost: 0\n"
        "requirements: {}\n"
        'label: \'A "quoted" label\'\n'
        "known_limits: [one, 'two, three']\n"
        "description: |\n  First line.\n  Second line.\n",
        encoding="utf-8",
    )

    assert capability_commands._load_yaml_mapping(path) == {
        "id": "001",
        "enabled": "true",
        "validated": "2026-08-06",
        "missing": "null",
        "cost": "0",
        "requirements": {},
        "label": 'A "quoted" label',
        "known_limits": ["one", "two, three"],
        "description": "First line.\nSecond line.\n",
    }


@pytest.mark.parametrize("text", ["label: [", "- one\n- two\n", ""])
def test_catalog_yaml_skips_invalid_or_non_mapping_documents(tmp_path, text):
    path = tmp_path / "provider.yaml"
    path.write_text(text, encoding="utf-8")

    assert capability_commands._load_yaml_mapping(path) is None


def test_action_metadata_uses_the_same_string_preserving_yaml_loader(tmp_path, monkeypatch):
    (tmp_path / "actions.yaml").write_text(
        "actions:\n  custom.action:\n    label: true\n    description: 2026-08-06\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(capability_commands, "files", lambda _package: tmp_path)

    assert capability_commands._load_actions_metadata() == {
        "custom.action": {"label": "true", "description": "2026-08-06"}
    }
