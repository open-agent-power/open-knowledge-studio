import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_evidence_rich_handlers_use_explicit_argv_contracts():
    handlers = json.loads((ROOT / "settings" / "handlers.json").read_text(encoding="utf-8"))
    by_name = {item["name"]: item for item in handlers}

    expected = {"oks-video", "oks-audio", "oks-image", "oks-document", "oks-pdf"}
    assert expected <= by_name.keys()

    for name in expected:
        handler = by_name[name]
        assert handler["level"] == 1
        assert handler["json_protocol"] is True
        assert handler["output_contract"] == "raw-multimodal/v0.1"
        assert handler["tool_config"] == "settings/raw-tools.json"
        assert isinstance(handler["check_argv"], list)
        assert handler["check_argv"]
        assert "command_template" not in handler
        assert "command_sequence" not in handler
        assert bool(handler.get("command_argv")) ^ bool(handler.get("command_argv_sequence"))


def test_handler_argv_does_not_restore_runtime_router():
    content = (ROOT / "settings" / "handlers.json").read_text(encoding="utf-8")
    assert "raw_ingest.py" not in content

    handlers = json.loads(content)
    raw_handlers = [item for item in handlers if item.get("output_contract") == "raw-multimodal/v0.1"]
    flattened = json.dumps(raw_handlers, ensure_ascii=False)
    assert "raw_bundle_adapter.py" in flattened
